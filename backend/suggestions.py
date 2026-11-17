"""Search suggestions for the browser address bar and the in-page dropdown.

Sources, in order:
  * aggregate popular queries (no user ids, no IPs, PII filtered)
  * title prefix matches from the optional local crawl index
  * Wikipedia's OpenSearch API as a fast last resort

Everything is cached briefly in memory so a keystroke never waits on a slow
upstream twice.
"""

import asyncio
import os
import re
import sqlite3
import time
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from . import searchdb
from .answers import get_http_client

router = APIRouter()

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "suggest.db")
MAX_SUGGESTIONS = 8
CACHE_TTL = 180
WIKI_TIMEOUT = max(
    0.15, float(os.getenv("SUGGEST_WIKI_TIMEOUT", "0.75"))
)

_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE = re.compile(r"(?:\+?\d[\s().-]*){7,}")
_ALNUM = re.compile(r"[A-Za-z0-9]")

_cache: dict[str, tuple[float, list[dict]]] = {}
_recent: dict[str, float] = {}


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS query_stats (
            query_norm TEXT PRIMARY KEY,
            query_text TEXT NOT NULL,
            count      INTEGER NOT NULL DEFAULT 0,
            last_seen  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS query_stats_count
            ON query_stats(count DESC);
        """
    )
    conn.close()


def clean_query(value: str | None) -> str:
    """Normalise a suggestion query and reject obvious personal data."""
    text = _CONTROL.sub(" ", value or "")
    text = _WHITESPACE.sub(" ", text).strip()
    if not 1 <= len(text) <= 120:
        return ""
    if not _ALNUM.search(text):
        return ""
    if "://" in text or text.startswith(("javascript:", "data:")):
        return ""
    if _EMAIL.search(text) or _PHONE.search(text):
        return ""
    return text


def _norm(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()


def _user_agent() -> str:
    contact = (
        os.getenv("SUGGEST_CONTACT_EMAIL", "").strip()
        or os.getenv("NEWS_CONTACT_EMAIL", "").strip()
        or os.getenv("FEEDBACK_EMAIL", "").strip()
        or "suggest@8search.local"
    )
    return f"8search-suggestions/1.0 (+mailto:{contact})"


def record_query(value: str) -> None:
    """Aggregate a successful search query. Never raises into the request."""
    text = clean_query(value)
    if not text:
        return
    norm = _norm(text)
    now_mono = time.monotonic()
    last = _recent.get(norm)
    if last is not None and now_mono - last < 20:
        return
    _recent[norm] = now_mono
    if len(_recent) > 5000:
        cutoff = now_mono - 120
        for key, stamp in list(_recent.items()):
            if stamp < cutoff:
                _recent.pop(key, None)
    try:
        conn = _get_db()
        conn.execute(
            """
            INSERT INTO query_stats (query_norm, query_text, count, last_seen)
            VALUES (?, ?, 1, datetime('now'))
            ON CONFLICT(query_norm) DO UPDATE SET
                count = count + 1,
                query_text = excluded.query_text,
                last_seen = excluded.last_seen
            """,
            (norm, text),
        )
        conn.commit()
        conn.close()
    except Exception:
        # Suggestions are an enhancement; a locked database must never break
        # a search.
        return


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def popular_suggestions(value: str, limit: int) -> list[dict]:
    prefix = _escape_like(_norm(value)) + "%"
    contains = "%" + _escape_like(_norm(value)) + "%"
    try:
        conn = _get_db()
        rows = conn.execute(
            """
            SELECT query_text, count
            FROM query_stats
            WHERE query_norm LIKE ? ESCAPE '\\'
            ORDER BY count DESC, last_seen DESC
            LIMIT ?
            """,
            (prefix, max(limit * 2, 12)),
        ).fetchall()
        if len(rows) < limit:
            seen = {row["query_text"].casefold() for row in rows}
            extra = conn.execute(
                """
                SELECT query_text, count
                FROM query_stats
                WHERE query_norm LIKE ? ESCAPE '\\'
                ORDER BY count DESC, last_seen DESC
                LIMIT ?
                """,
                (contains, max(limit * 3, 20)),
            ).fetchall()
            for row in extra:
                if row["query_text"].casefold() not in seen:
                    rows.append(row)
                    seen.add(row["query_text"].casefold())
                if len(rows) >= limit:
                    break
        conn.close()
    except Exception:
        return []
    return [{"text": row["query_text"], "kind": "popular"} for row in rows[:limit]]


def local_index_suggestions(value: str, limit: int) -> list[dict]:
    """Prefix matches from the optional local full-text index."""
    prefix = _escape_like(_norm(value)) + "%"
    try:
        if not os.path.exists(searchdb.DB_PATH):
            return []
        conn = sqlite3.connect(searchdb.DB_PATH, timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT title FROM pages
            WHERE title IS NOT NULL AND title <> ''
              AND lower(title) LIKE ? ESCAPE '\\'
            ORDER BY length(title) ASC
            LIMIT ?
            """,
            (prefix, max(limit * 3, 20)),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        title = _WHITESPACE.sub(" ", row["title"] or "").strip()[:120]
        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        out.append({"text": title, "kind": "local"})
        if len(out) >= limit:
            break
    return out


async def wikipedia_suggestions(value: str, limit: int) -> list[dict]:
    try:
        client = await get_http_client()
        response = await asyncio.wait_for(
            client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": value,
                    "limit": limit,
                    "namespace": 0,
                    "format": "json",
                    "origin": "*",
                },
                headers={"Accept": "application/json", "User-Agent": _user_agent()},
            ),
            timeout=WIKI_TIMEOUT,
        )
        if response.status_code != 200:
            return []
        data = response.json()
        titles = data[1] if isinstance(data, list) and len(data) > 1 else []
        out = []
        for title in titles:
            if not isinstance(title, str):
                continue
            title = _WHITESPACE.sub(" ", title).strip()[:120]
            if title:
                out.append({"text": title, "kind": "web"})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _merge(groups: list[list[dict]], limit: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for entry in group:
            text = entry.get("text", "")
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(entry)
            if len(out) >= limit:
                return out
    return out


async def suggest(value: str, limit: int = MAX_SUGGESTIONS) -> list[dict]:
    text = clean_query(value)
    if not text:
        return []
    # Include the requested size so a small limit never gets a longer cached
    # list (and vice versa) on a hit.
    key = f"{limit}:{_norm(text)}"
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    popular, local = await asyncio.gather(
        asyncio.to_thread(popular_suggestions, text, limit),
        asyncio.to_thread(local_index_suggestions, text, limit),
    )
    merged = _merge([popular, local], limit)
    if len(merged) < limit:
        merged = _merge(
            [merged, await wikipedia_suggestions(text, limit)],
            limit,
        )

    if len(_cache) > 1024:
        cutoff = now - CACHE_TTL
        for old_key, (stamp, _) in list(_cache.items()):
            if stamp < cutoff:
                _cache.pop(old_key, None)
    _cache[key] = (now, merged)
    return merged


@router.get("/api/suggest")
async def suggestions(
    q: str = Query("", max_length=500),
    format: str = Query("opensearch"),
    limit: int = Query(MAX_SUGGESTIONS, ge=1, le=MAX_SUGGESTIONS),
):
    """OpenSearch suggestions JSON, plus a richer shape for the page UI."""
    items = await suggest(q, limit)
    if format == "rich":
        return JSONResponse(
            {
                "q": q,
                "suggestions": items,
                "wikipedia_search": "https://en.wikipedia.org/w/index.php?search="
                + quote(clean_query(q)),
            },
            headers={"Cache-Control": "public, max-age=60"},
        )
    return JSONResponse(
        [q, [item["text"] for item in items]],
        media_type="application/x-suggestions+json",
        headers={"Cache-Control": "public, max-age=60"},
    )
