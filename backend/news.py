"""Trending News: real feed ingestion, snapshots, API and 6-hour scheduler."""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import feedparser
import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from .news_ranking import (
    dedupe_items,
    items_from_feed,
    normalize_url,
    select_trending,
)
from .news_sources import (
    CATEGORIES,
    FEEDS,
    GNEWS_CATEGORIES,
    GNEWS_ENDPOINT,
    GNEWS_WEIGHT,
    FeedSource,
)

logger = logging.getLogger("8search.news")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

router = APIRouter()

DB_PATH = os.getenv(
    "NEWS_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "news.db"),
)
NEWS_REFRESH_HOURS = max(1.0, float(os.getenv("NEWS_REFRESH_HOURS", "6")))
NEWS_COUNT = max(25, int(os.getenv("NEWS_COUNT", "25")))
NEWS_MAX_AGE_HOURS = max(1, int(os.getenv("NEWS_MAX_AGE_HOURS", "48")))
NEWS_RELAX_HOURS = max(NEWS_MAX_AGE_HOURS, 72)
FEED_TIMEOUT = max(1.0, float(os.getenv("NEWS_FEED_TIMEOUT", "6")))
MAX_FEED_BYTES = 5 * 1024 * 1024

_refresh_lock = asyncio.Lock()
_background_tasks: set[asyncio.Task] = set()
_scheduler_task: asyncio.Task | None = None


def _contact_email() -> str:
    return (
        os.getenv("NEWS_CONTACT_EMAIL", "").strip()
        or os.getenv("FEEDBACK_EMAIL", "").strip()
        or "news@8search.local"
    )


def _user_agent() -> str:
    return f"8search-news/1.0 (+mailto:{_contact_email()})"


def _admin_token() -> str:
    return os.getenv("NEWS_ADMIN_TOKEN", "").strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _get_db() -> sqlite3.Connection:
    _ensure_parent(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS news_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            url_norm      TEXT UNIQUE NOT NULL,
            title         TEXT NOT NULL,
            summary       TEXT NOT NULL DEFAULT '',
            image_url     TEXT NOT NULL DEFAULT '',
            source        TEXT NOT NULL,
            category      TEXT NOT NULL,
            published_at  TEXT NOT NULL,
            fetched_at    TEXT NOT NULL,
            cluster_id    TEXT NOT NULL DEFAULT '',
            score         REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS news_items_published
            ON news_items(published_at DESC);
        CREATE INDEX IF NOT EXISTS news_items_category
            ON news_items(category, published_at DESC);

        CREATE TABLE IF NOT EXISTS news_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    TEXT NOT NULL,
            item_ids_json TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


# ── Feed fetching ────────────────────────────────────────────────────────────

def _parse_feed_bytes(content: bytes):
    return feedparser.parse(content)


async def fetch_feed(client: httpx.AsyncClient, feed: FeedSource, now: datetime):
    """Fetch and parse one feed. Raises on HTTP/parse failure."""
    response = await client.get(
        feed.url,
        headers={
            "User-Agent": _user_agent(),
            "Accept": "application/rss+xml, application/atom+xml, application/xml, "
                      "text/xml;q=0.9, */*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8",
        },
        timeout=FEED_TIMEOUT,
    )
    response.raise_for_status()
    if len(response.content) > MAX_FEED_BYTES:
        raise ValueError(f"feed larger than {MAX_FEED_BYTES} bytes")
    parsed = await asyncio.to_thread(_parse_feed_bytes, response.content)
    entries = getattr(parsed, "entries", None) or []
    if not entries and getattr(parsed, "bozo", False):
        raise ValueError("feed did not contain usable entries")
    items = items_from_feed(parsed, feed, now=now, max_age_hours=NEWS_RELAX_HOURS)
    return items


async def fetch_gnews(client: httpx.AsyncClient, now: datetime) -> list[dict]:
    """Optional licensed API. Returns [] without a key or on any failure."""
    key = (os.getenv("GNEWS_API_KEY") or os.getenv("NEWSAPI_KEY") or "").strip()
    if not key:
        return []
    items: list[dict] = []
    for api_category, feed_category in GNEWS_CATEGORIES:
        try:
            response = await client.get(
                GNEWS_ENDPOINT,
                params={
                    "category": api_category,
                    "lang": "en",
                    "max": 10,
                    "apikey": key,
                },
                timeout=FEED_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            for article in payload.get("articles") or []:
                title = (article.get("title") or "").strip()
                url = normalize_url(article.get("url") or "")
                if not title or not url:
                    continue
                published = _parse_iso(article.get("publishedAt")) or now
                if published < now - timedelta(hours=NEWS_RELAX_HOURS):
                    continue
                items.append(
                    {
                        "url": url,
                        "url_norm": url,
                        "title": title[:300],
                        "summary": (article.get("description") or "").strip()[:400],
                        "image_url": article.get("image") or "",
                        "source": ((article.get("source") or {}).get("name") or "GNEWS")[:80],
                        "source_weight": GNEWS_WEIGHT,
                        "category": feed_category,
                        "published_at": published,
                        "fetched_at": now,
                    }
                )
        except Exception as exc:
            logger.warning("GNews category %s failed: %s", api_category, exc)
    return items


async def collect_items(now: datetime | None = None, feeds=None) -> tuple[list[dict], dict]:
    """Fetch all configured feeds concurrently, never letting one break another."""
    now = now or _now()
    feeds = list(FEEDS if feeds is None else feeds)
    items: list[dict] = []
    failures: list[str] = []
    ok_feeds = 0

    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    timeout = httpx.Timeout(FEED_TIMEOUT)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        limits=limits,
        headers={"User-Agent": _user_agent()},
    ) as client:
        tasks = [asyncio.create_task(fetch_feed(client, feed, now)) for feed in feeds]
        if (os.getenv("GNEWS_API_KEY") or os.getenv("NEWSAPI_KEY")):
            tasks.append(asyncio.create_task(fetch_gnews(client, now)))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for source, result in zip(feeds + ([FeedSource("GNEWS", "", "world")] if len(results) > len(feeds) else []), results):
        if isinstance(result, Exception):
            failures.append(f"{source.name}: {type(result).__name__}: {result}")
            logger.warning("news feed failed (%s): %s", source.name, result)
        else:
            ok_feeds += 1
            items.extend(result)

    stats = {
        "feeds_total": len(feeds),
        "feeds_ok": ok_feeds,
        "failures": failures,
        "raw_items": len(items),
    }
    return items, stats


# ── Snapshot storage ─────────────────────────────────────────────────────────

def _latest_snapshot(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, created_at, item_ids_json FROM news_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _snapshot_rows(conn: sqlite3.Connection, snapshot: sqlite3.Row) -> list[sqlite3.Row]:
    try:
        ids = [int(value) for value in json.loads(snapshot["item_ids_json"] or "[]")]
    except Exception:
        return []
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM news_items WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def _serialize_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "image_url": row["image_url"],
        "source": row["source"],
        "category": row["category"],
        "published_at": row["published_at"],
        "url": row["url_norm"],
    }


def get_snapshot(category: str = "all", limit: int = NEWS_COUNT) -> dict:
    conn = _get_db()
    try:
        snapshot = _latest_snapshot(conn)
        if snapshot is None:
            return {
                "snapshot_id": None,
                "updated_at": None,
                "next_refresh_at": None,
                "items": [],
            }
        rows = _snapshot_rows(conn, snapshot)
        if category != "all":
            rows = [row for row in rows if row["category"] == category]
        rows = rows[:limit]
        created = _parse_iso(snapshot["created_at"]) or _now()
        return {
            "snapshot_id": snapshot["id"],
            "updated_at": snapshot["created_at"],
            "next_refresh_at": _iso(created + timedelta(hours=NEWS_REFRESH_HOURS)),
            "items": [_serialize_row(row) for row in rows],
        }
    finally:
        conn.close()


def get_item(item_id: int) -> dict | None:
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM news_items WHERE id = ?", (item_id,)).fetchone()
        return _serialize_row(row) if row else None
    finally:
        conn.close()


def snapshot_age_hours() -> float | None:
    conn = _get_db()
    try:
        snapshot = _latest_snapshot(conn)
        if snapshot is None:
            return None
        created = _parse_iso(snapshot["created_at"])
        if created is None:
            return None
        return max(0.0, (_now() - created).total_seconds() / 3600)
    finally:
        conn.close()


def needs_refresh() -> bool:
    age = snapshot_age_hours()
    return age is None or age >= NEWS_REFRESH_HOURS


def _previous_urls() -> set[str]:
    conn = _get_db()
    try:
        snapshot = _latest_snapshot(conn)
        if snapshot is None:
            return set()
        return {row["url_norm"] for row in _snapshot_rows(conn, snapshot)}
    finally:
        conn.close()


def _store_snapshot(items: list[dict], now: datetime) -> int:
    conn = _get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ids: list[int] = []
        for item in items:
            conn.execute(
                """
                INSERT INTO news_items
                    (url_norm, title, summary, image_url, source, category,
                     published_at, fetched_at, cluster_id, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_norm) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    image_url = excluded.image_url,
                    source = excluded.source,
                    category = excluded.category,
                    published_at = excluded.published_at,
                    fetched_at = excluded.fetched_at,
                    cluster_id = excluded.cluster_id,
                    score = excluded.score
                """,
                (
                    item["url_norm"],
                    item["title"],
                    item.get("summary") or "",
                    item.get("image_url") or "",
                    item.get("source") or "",
                    item.get("category") or "world",
                    _iso(item.get("published_at") or now),
                    _iso(now),
                    item.get("cluster_id") or "",
                    float(item.get("score") or 0),
                ),
            )
            row = conn.execute(
                "SELECT id FROM news_items WHERE url_norm = ?", (item["url_norm"],)
            ).fetchone()
            if row:
                ids.append(row["id"])
        if len(ids) < 10:
            conn.rollback()
            raise ValueError("not enough usable items to replace the snapshot")
        cursor = conn.execute(
            "INSERT INTO news_snapshots (created_at, item_ids_json) VALUES (?, ?)",
            (_iso(now), json.dumps(ids)),
        )
        snapshot_id = cursor.lastrowid
        cutoff = _iso(now - timedelta(days=7))
        conn.execute("DELETE FROM news_items WHERE published_at < ?", (cutoff,))
        conn.execute(
            """
            DELETE FROM news_snapshots
            WHERE id NOT IN (
                SELECT id FROM news_snapshots ORDER BY id DESC LIMIT 30
            )
            """
        )
        conn.commit()
        return int(snapshot_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Refresh orchestration ────────────────────────────────────────────────────

def _file_lock():
    """Cross-process refresh lock so multiple workers cannot refresh together."""
    try:
        import fcntl
    except Exception:
        return None
    _ensure_parent(DB_PATH)
    path = DB_PATH + ".lock"
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_file_lock(handle) -> None:
    if handle is None:
        return
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    finally:
        try:
            handle.close()
        except Exception:
            pass


def _rank_for_snapshot(items: list[dict], now: datetime, previous: set[str]) -> list[dict]:
    primary = [
        item for item in items
        if (item.get("published_at") or now) >= now - timedelta(hours=NEWS_MAX_AGE_HOURS)
    ]
    selected = select_trending(
        primary,
        count=NEWS_COUNT,
        previous_urls=previous,
        now=now,
        max_age_hours=NEWS_MAX_AGE_HOURS,
    )
    if len(selected) < NEWS_COUNT:
        selected = select_trending(
            items,
            count=NEWS_COUNT,
            previous_urls=previous,
            now=now,
            max_age_hours=NEWS_RELAX_HOURS,
        )
    return selected


async def refresh_news(force: bool = False) -> dict:
    """Fetch, rank and atomically replace the snapshot. Keep old data on failure."""
    if _refresh_lock.locked():
        return {"status": "skipped", "reason": "refresh already running"}
    async with _refresh_lock:
        lock_handle = _file_lock()
        if lock_handle is None:
            return {"status": "skipped", "reason": "another worker is refreshing"}
        try:
            now = _now()
            raw_items, stats = await collect_items(now=now)
            items = dedupe_items(raw_items)
            if len(items) < 10:
                message = f"only {len(items)} valid items; keeping the previous snapshot"
                logger.error("news refresh failed: %s", message)
                return {"status": "failed", "items": len(items), "message": message, **stats}

            previous = _previous_urls()
            selected = _rank_for_snapshot(items, now, previous)
            if len(selected) < 10:
                message = f"only {len(selected)} selected items; keeping the previous snapshot"
                logger.error("news refresh failed: %s", message)
                return {"status": "failed", "items": len(selected), "message": message, **stats}

            snapshot_id = _store_snapshot(selected, now)
            logger.info(
                "news refreshed: snapshot=%s items=%s feeds_ok=%s/%s",
                snapshot_id,
                len(selected),
                stats.get("feeds_ok"),
                stats.get("feeds_total"),
            )
            return {
                "status": "ok",
                "snapshot_id": snapshot_id,
                "items": len(selected),
                "updated_at": _iso(now),
                **stats,
            }
        except Exception as exc:
            logger.exception("news refresh failed")
            return {"status": "failed", "message": str(exc)}
        finally:
            _release_file_lock(lock_handle)


def _track(task: asyncio.Task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def ensure_fresh_async() -> None:
    """Stale-while-revalidate: serve the old snapshot while this runs."""
    if not needs_refresh() or _refresh_lock.locked():
        return
    task = asyncio.create_task(refresh_news())
    _track(task)


async def _scheduler_loop() -> None:
    # Startup refresh is triggered immediately, then the loop checks every
    # five minutes. A successful snapshot only refreshes when six hours old.
    while True:
        try:
            if needs_refresh():
                await refresh_news()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("news scheduler iteration failed")
        await asyncio.sleep(300)


def start_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _scheduler_task = asyncio.create_task(_scheduler_loop())


async def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
    for task in list(_background_tasks):
        task.cancel()
    _background_tasks.clear()


# ── API ──────────────────────────────────────────────────────────────────────

def _etag(payload: dict, category: str, limit: int) -> str:
    raw = json.dumps(
        {
            "id": payload.get("snapshot_id"),
            "updated": payload.get("updated_at"),
            "category": category,
            "limit": limit,
            "ids": [item["id"] for item in payload.get("items", [])],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return '"' + hashlib.sha256(raw.encode("utf-8")).hexdigest() + '"'


@router.get("/api/news")
async def news_feed(
    request: Request,
    category: str = Query("all"),
    limit: int = Query(NEWS_COUNT, ge=1, le=50),
):
    category = (category or "all").lower()
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail="category must be one of: " + ", ".join(CATEGORIES),
        )
    payload = get_snapshot(category, limit)
    if payload.get("updated_at") is None:
        ensure_fresh_async()
    elif needs_refresh():
        ensure_fresh_async()

    etag = _etag(payload, category, limit)
    if request.headers.get("if-none-match", "").strip() == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=300",
            },
        )

    body = {
        "updated_at": payload.get("updated_at"),
        "next_refresh_at": payload.get("next_refresh_at"),
        "items": payload.get("items", []),
    }
    if not body["items"]:
        body["message"] = "News is temporarily unavailable. Please try again later."
    return JSONResponse(
        body,
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=300",
            "X-News-Updated": str(payload.get("updated_at") or ""),
        },
    )


@router.get("/api/news/{item_id}")
async def news_item(item_id: int):
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News story not found")
    return item


@router.post("/api/news/refresh")
async def refresh_endpoint(
    x_news_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    expected = _admin_token()
    supplied = (x_news_token or "").strip()
    if not supplied and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = value.strip()
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")

    result = await refresh_news(force=True)
    return result
