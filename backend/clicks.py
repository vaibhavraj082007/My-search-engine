"""Click logging, anti-abuse, and click-popularity lookups.

The browser reports clicks on results that 8search actually showed. Each
result carries a short-lived HMAC token binding the query, URL, kind, and
position, so a direct API call cannot invent a click for an unseen URL.
Only salted hashes of IP addresses and user agents are stored.

Writes are buffered and serialised: impressions share one batched write,
clicks are inserted in a background task, and the ranking lookup uses one SQL
query for the whole page.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    HTTPException,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import auth
from .ranking import (
    config_snapshot,
    decay_factor,
    normalize_query,
    normalize_url,
    popularity_score,
    position_weight,
)
from .ratelimit import RateLimiter

logger = logging.getLogger("8search.clicks")
ranking_logger = logging.getLogger("8search.ranking")

DB_PATH = os.getenv(
    "CLICKS_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "clicks.db"),
)
CLICK_TOKEN_SECRET = os.getenv("CLICK_TOKEN_SECRET", "").strip()

CLICK_TOKEN_TTL_SECONDS = max(
    60, int(os.getenv("CLICK_TOKEN_TTL_SECONDS", str(6 * 60 * 60)))
)
DEDUPE_WINDOW_SECONDS = max(0, int(os.getenv("CLICK_DEDUPE_SECONDS", "3600")))
RETENTION_DAYS = max(1, int(os.getenv("CLICK_RETENTION_DAYS", "90")))
IMPRESSION_FLUSH_SECONDS = max(
    1, int(os.getenv("IMPRESSION_FLUSH_SECONDS", "5"))
)
IMPRESSION_BATCH_SIZE = max(
    1, int(os.getenv("IMPRESSION_BATCH_SIZE", "200"))
)
CLEANUP_INTERVAL_SECONDS = max(
    60, int(os.getenv("CLICK_CLEANUP_INTERVAL_SECONDS", str(6 * 60 * 60)))
)

KINDS = ("web", "video", "news", "answer", "wiki")

router = APIRouter()

# Click endpoints have their own limits on top of the global API limiter.
click_ip_limiter = RateLimiter(
    int(os.getenv("CLICK_RATE_PER_MINUTE", "60"))
)
click_session_limiter = RateLimiter(
    int(os.getenv("CLICK_SESSION_RATE_PER_MINUTE", "20"))
)

_BOT_RE = re.compile(
    r"(bot|crawler|spider|slurp|scrape|headless|phantomjs|"
    r"curl/|wget/|python-requests|python-httpx|httpx/|aiohttp|"
    r"go-http-client|java/|okhttp|libwww|httpclient|"
    r"facebookexternalhit|bingpreview|pinterest|"
    r"lighthouse|pingdom|uptime|monitor|"
    r"semrush|ahrefs|mj12|dotbot|petalbot|gptbot|claudebot|"
    r"bytespider|ccbot)",
    re.IGNORECASE,
)

# ── Database ────────────────────────────────────────────────────────────────

_write_lock = threading.Lock()
_impression_lock = threading.Lock()
_impression_buffer: dict[tuple[str, str], tuple[int, str, str]] = {}
_last_flush = time.monotonic()

_secret_lock = threading.Lock()
_secret_cache: bytes | None = None


def _get_db() -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(DB_PATH))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    columns = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    """Create the click store and its indexes (idempotent)."""
    conn = _get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS click_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                query_norm     TEXT    NOT NULL,
                url_norm       TEXT    NOT NULL,
                title          TEXT,
                position       INTEGER NOT NULL DEFAULT 0,
                session_id     TEXT    NOT NULL,
                user_id        TEXT,
                ip_hash        TEXT,
                user_agent_hash TEXT,
                created_at     TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_click_events_dedupe
                ON click_events(session_id, query_norm, url_norm, created_at);
            CREATE INDEX IF NOT EXISTS idx_click_events_created
                ON click_events(created_at);

            CREATE TABLE IF NOT EXISTS result_stats (
                query_norm              TEXT    NOT NULL,
                url_norm                TEXT    NOT NULL,
                title                   TEXT,
                impressions             INTEGER NOT NULL DEFAULT 0,
                clicks                  INTEGER NOT NULL DEFAULT 0,
                decayed_clicks          REAL    NOT NULL DEFAULT 0,
                position_weighted_clicks REAL   NOT NULL DEFAULT 0,
                last_clicked_at         TEXT,
                last_shown_at           TEXT,
                last_decayed_at         TEXT,
                PRIMARY KEY (query_norm, url_norm)
            );

            CREATE INDEX IF NOT EXISTS idx_result_stats_rank
                ON result_stats(query_norm, position_weighted_clicks DESC);
            CREATE INDEX IF NOT EXISTS idx_result_stats_clicks
                ON result_stats(query_norm, clicks DESC);

            CREATE TABLE IF NOT EXISTS global_url_stats (
                url_norm        TEXT PRIMARY KEY,
                total_clicks    INTEGER NOT NULL DEFAULT 0,
                last_clicked_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_global_url_clicks
                ON global_url_stats(total_clicks DESC);
            """
        )
        # Small forward migration for databases created by older builds.
        _ensure_column(conn, "result_stats", "last_decayed_at", "TEXT")
        conn.commit()
    finally:
        conn.close()


# ── Secrets and hashing ─────────────────────────────────────────────────────

def _secret_path() -> str:
    return os.getenv(
        "CLICK_SECRET_PATH",
        os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), ".click_secret"),
    )


def _secret() -> bytes:
    """Return the token/HMAC secret, creating a local one when unset.

    ``CLICK_TOKEN_SECRET`` is preferred in production so every replica shares
    the same key. Local development persists a random key in ``data/`` so
    restarting the server does not invalidate tokens already in a browser.
    """
    global _secret_cache
    if CLICK_TOKEN_SECRET:
        return CLICK_TOKEN_SECRET.encode("utf-8")

    with _secret_lock:
        if _secret_cache is not None:
            return _secret_cache

        path = _secret_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(secrets.token_hex(32))
        except FileExistsError:
            pass

        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError:
            value = ""

        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

        if len(value) < 32:
            value = secrets.token_hex(32)
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(value)
            except OSError:
                pass

        _secret_cache = value.encode("utf-8")
        return _secret_cache


def _hash_value(value: str) -> str:
    """Salted, one-way hash used for IP, session, user, and UA identifiers."""
    return hmac.new(
        _secret(), (value or "").encode("utf-8", "replace"), hashlib.sha256
    ).hexdigest()


def _stats_query_key(query_norm: str, kind: str) -> str:
    """Namespaced stats key so answer/wiki clicks cannot boost web results."""
    if kind == "web":
        return query_norm
    return f"@{kind}:{query_norm}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime | None = None) -> str:
    return (when or _now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ── Signed click tokens ─────────────────────────────────────────────────────

def _sign(message: str) -> str:
    try:
        digest = hmac.new(
            _secret(), message.encode("utf-8"), hashlib.sha256
        ).digest()
    except Exception:
        logger.exception("could not sign click token")
        return ""
    # 18 bytes is comfortably collision-resistant and keeps tokens short.
    return base64.urlsafe_b64encode(digest[:18]).decode("ascii").rstrip("=")


def make_click_token(
    query: str, url: str, kind: str, position: int
) -> str:
    """Create a short-lived token for one rendered result."""
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        return ""
    query_norm = normalize_query(query)
    url_norm = normalize_url(url)
    if not query_norm or not url_norm:
        return ""
    try:
        pos = max(0, int(position))
    except (TypeError, ValueError):
        pos = 0
    issued = int(time.time())
    message = (
        f"{issued}\n{_stats_query_key(query_norm, kind)}\n{url_norm}\n{pos}"
    )
    signature = _sign(message)
    if not signature:
        return ""
    return f"{issued}.{signature}"


def verify_click_token(
    token: str,
    query: str,
    url: str,
    kind: str,
    position: int,
    now: float | None = None,
) -> bool:
    """Check that a click token is authentic and still within its TTL."""
    kind = (kind or "").strip().lower()
    if not token or kind not in KINDS:
        return False
    try:
        issued_raw, supplied = token.split(".", 1)
        issued = int(issued_raw)
    except (TypeError, ValueError):
        return False

    current = float(now if now is not None else time.time())
    if issued > current + 120 or current - issued > CLICK_TOKEN_TTL_SECONDS:
        return False

    query_norm = normalize_query(query)
    url_norm = normalize_url(url)
    if not query_norm or not url_norm:
        return False
    try:
        pos = max(0, int(position))
    except (TypeError, ValueError):
        pos = 0
    message = (
        f"{issued}\n{_stats_query_key(query_norm, kind)}\n{url_norm}\n{pos}"
    )
    signature = _sign(message)
    if not signature:
        return False
    try:
        return hmac.compare_digest(
            supplied.encode("utf-8"), signature.encode("ascii")
        )
    except (UnicodeError, TypeError):
        return False


# ── Batching helpers ────────────────────────────────────────────────────────

def record_impressions(query: str, items: list[dict], kind: str = "web") -> None:
    """Buffer one impression per rendered URL.

    Called after the response is built. The buffer is flushed every few
    seconds or when it grows, so a burst of searches becomes one SQLite
    transaction instead of one write per result.
    """
    query_norm = normalize_query(query)
    if not query_norm or not items or kind not in KINDS:
        return

    query_key = _stats_query_key(query_norm, kind)
    shown_at = _iso()
    should_flush = False

    with _impression_lock:
        for item in items:
            if not isinstance(item, dict):
                continue
            url_norm = normalize_url(item.get("url") or "")
            if not url_norm:
                continue
            key = (query_key, url_norm)
            count, title, _ = _impression_buffer.get(
                key, (0, "", shown_at)
            )
            title = (item.get("title") or title or "")[:300]
            _impression_buffer[key] = (count + 1, title, shown_at)

        if (
            len(_impression_buffer) >= IMPRESSION_BATCH_SIZE
            or time.monotonic() - _last_flush >= IMPRESSION_FLUSH_SECONDS
        ):
            should_flush = True

    if should_flush:
        flush_impressions()


def record_page_impressions(query: str, payload: dict) -> None:
    """Record web, video, and news impressions for one search response."""
    record_impressions(query, payload.get("results") or [], "web")
    record_impressions(query, payload.get("videos") or [], "video")
    record_impressions(query, payload.get("news") or [], "news")


def _merge_impressions(
    batch: dict[tuple[str, str], tuple[int, str, str]]
) -> None:
    with _impression_lock:
        for key, (count, title, shown_at) in batch.items():
            old_count, old_title, old_shown = _impression_buffer.get(
                key, (0, "", shown_at)
            )
            _impression_buffer[key] = (
                old_count + count,
                title or old_title,
                max(old_shown, shown_at),
            )


def flush_impressions() -> None:
    """Write buffered impressions in one transaction."""
    global _impression_buffer, _last_flush

    with _impression_lock:
        if not _impression_buffer:
            _last_flush = time.monotonic()
            return
        batch = _impression_buffer
        _impression_buffer = {}
        _last_flush = time.monotonic()

    rows = [
        (query_key, url_norm, title, count, shown_at)
        for (query_key, url_norm), (count, title, shown_at) in batch.items()
    ]

    conn = None
    try:
        with _write_lock:
            conn = _get_db()
            conn.executemany(
                """
                INSERT INTO result_stats (
                    query_norm, url_norm, title, impressions, clicks,
                    decayed_clicks, position_weighted_clicks,
                    last_clicked_at, last_shown_at, last_decayed_at
                )
                VALUES (?, ?, ?, ?, 0, 0, 0, NULL, ?, NULL)
                ON CONFLICT(query_norm, url_norm) DO UPDATE SET
                    impressions = result_stats.impressions
                                  + excluded.impressions,
                    title = CASE
                        WHEN result_stats.title IS NULL
                          OR result_stats.title = ''
                        THEN excluded.title
                        ELSE result_stats.title
                    END,
                    last_shown_at = excluded.last_shown_at
                """,
                rows,
            )
            conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        _merge_impressions(batch)
        logger.exception("could not flush click impressions")
    finally:
        if conn is not None:
            conn.close()


# ── Click recording ─────────────────────────────────────────────────────────

def _record_click(
    query_key: str,
    url_norm: str,
    title: str,
    position: int,
    session_hash: str,
    user_id: str | None,
    ip_hash: str,
    ua_hash: str,
    kind: str,
    created_at: str,
) -> bool:
    """Insert one click and update the aggregate stats.

    Runs in a background task. Dedupe is enforced here so even concurrent
    reports of the same click cannot double-count it.
    """
    cutoff = _iso(_now() - timedelta(seconds=DEDUPE_WINDOW_SECONDS))
    conn = None
    recorded = False
    try:
        with _write_lock:
            conn = _get_db()
            conn.execute("BEGIN IMMEDIATE")

            duplicate = conn.execute(
                """
                SELECT 1
                  FROM click_events
                 WHERE session_id = ?
                   AND query_norm = ?
                   AND url_norm = ?
                   AND created_at >= ?
                 LIMIT 1
                """,
                (session_hash, query_key, url_norm, cutoff),
            ).fetchone()
            if duplicate is not None:
                conn.rollback()
                return False

            conn.execute(
                """
                INSERT INTO click_events (
                    query_norm, url_norm, title, position, session_id,
                    user_id, ip_hash, user_agent_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_key,
                    url_norm,
                    title,
                    position,
                    session_hash,
                    user_id,
                    ip_hash,
                    ua_hash,
                    created_at,
                ),
            )

            conn.execute(
                """
                INSERT INTO result_stats (
                    query_norm, url_norm, title, impressions, clicks,
                    decayed_clicks, position_weighted_clicks,
                    last_clicked_at, last_shown_at, last_decayed_at
                )
                VALUES (?, ?, ?, 0, 0, 0, 0, NULL, NULL, NULL)
                ON CONFLICT(query_norm, url_norm) DO NOTHING
                """,
                (query_key, url_norm, title),
            )

            row = conn.execute(
                """
                SELECT decayed_clicks, last_clicked_at, last_decayed_at
                  FROM result_stats
                 WHERE query_norm = ? AND url_norm = ?
                """,
                (query_key, url_norm),
            ).fetchone()

            now = _now()
            anchor = None
            old_decayed = 0.0
            if row is not None:
                old_decayed = float(row["decayed_clicks"] or 0.0)
                anchor = _parse_iso(
                    row["last_decayed_at"] or row["last_clicked_at"]
                )

            decayed = old_decayed * decay_factor(anchor, now)
            decayed += position_weight(position)
            now_iso = _iso(now)

            conn.execute(
                """
                UPDATE result_stats
                   SET title = CASE
                           WHEN ? IS NULL OR ? = '' THEN title
                           ELSE ?
                       END,
                       clicks = clicks + 1,
                       decayed_clicks = ?,
                       position_weighted_clicks =
                           position_weighted_clicks + ?,
                       last_clicked_at = ?,
                       last_decayed_at = ?
                 WHERE query_norm = ? AND url_norm = ?
                """,
                (
                    title,
                    title,
                    title,
                    decayed,
                    position_weight(position),
                    now_iso,
                    now_iso,
                    query_key,
                    url_norm,
                ),
            )

            conn.execute(
                """
                INSERT INTO global_url_stats (
                    url_norm, total_clicks, last_clicked_at
                )
                VALUES (?, 1, ?)
                ON CONFLICT(url_norm) DO UPDATE SET
                    total_clicks = global_url_stats.total_clicks + 1,
                    last_clicked_at = excluded.last_clicked_at
                """,
                (url_norm, now_iso),
            )
            conn.commit()
            recorded = True
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception("could not record click")
    finally:
        if conn is not None:
            conn.close()
    return recorded


# ── Ranking lookups ─────────────────────────────────────────────────────────

def fetch_stats(
    query: str, items_by_kind: dict[str, list[dict]]
) -> dict[str, dict[str, dict]]:
    """Load stats for every rendered URL in one SQL query.

    Returns ``{kind: {url_norm: stats}}``. Missing rows are simply absent,
    which the ranking module treats as cold start (provider order).
    """
    query_norm = normalize_query(query)
    result = {kind: {} for kind in items_by_kind}
    if not query_norm:
        return result

    inputs: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for kind, items in items_by_kind.items():
        if kind not in KINDS:
            continue
        query_key = _stats_query_key(query_norm, kind)
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url_norm = normalize_url(item.get("url") or "")
            if not url_norm:
                continue
            row_key = (kind, query_key, url_norm)
            if row_key in seen:
                continue
            seen.add(row_key)
            inputs.append(row_key)

    if not inputs:
        return result

    values = ",".join("(?,?,?)" for _ in inputs)
    params: list[str] = []
    for kind, query_key, url_norm in inputs:
        params.extend((kind, query_key, url_norm))

    sql = f"""
        WITH input(kind, query_norm, url_norm) AS (VALUES {values})
        SELECT input.kind AS kind,
               input.url_norm AS url_norm,
               rs.query_norm IS NOT NULL AS has_query_stats,
               rs.title AS title,
               COALESCE(rs.impressions, 0) AS impressions,
               COALESCE(rs.clicks, 0) AS clicks,
               COALESCE(rs.decayed_clicks, 0) AS decayed_clicks,
               COALESCE(rs.position_weighted_clicks, 0)
                   AS position_weighted_clicks,
               rs.last_clicked_at AS last_clicked_at,
               rs.last_decayed_at AS last_decayed_at,
               rs.last_shown_at AS last_shown_at,
               COALESCE(gs.total_clicks, 0) AS global_clicks,
               gs.last_clicked_at AS global_last_clicked_at
          FROM input
          LEFT JOIN result_stats rs
            ON rs.query_norm = input.query_norm
           AND rs.url_norm = input.url_norm
          LEFT JOIN global_url_stats gs
            ON gs.url_norm = input.url_norm
    """

    conn = None
    try:
        conn = _get_db()
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        logger.exception("could not load click stats")
        return result
    finally:
        if conn is not None:
            conn.close()

    for row in rows:
        stats = dict(row)
        stats["_has_query_stats"] = bool(stats.pop("has_query_stats"))
        result.setdefault(row["kind"], {})[row["url_norm"]] = stats
    return result


def popular(query: str, kind: str = "web", limit: int = 20) -> list[dict]:
    """Return the most-clicked URLs for one query."""
    query_norm = normalize_query(query)
    kind = (kind or "web").strip().lower()
    if not query_norm or kind not in KINDS:
        return []

    query_key = _stats_query_key(query_norm, kind)
    conn = None
    try:
        conn = _get_db()
        rows = conn.execute(
            """
            SELECT url_norm, title, impressions, clicks, decayed_clicks,
                   position_weighted_clicks, last_clicked_at,
                   last_shown_at, last_decayed_at
              FROM result_stats
             WHERE query_norm = ? AND clicks > 0
             ORDER BY clicks DESC, decayed_clicks DESC
             LIMIT ?
            """,
            (query_key, max(1, min(100, int(limit)))),
        ).fetchall()
    except Exception:
        logger.exception("could not load popular results")
        return []
    finally:
        if conn is not None:
            conn.close()

    now = _now()
    output = []
    for row in rows:
        stats = dict(row)
        stats["_has_query_stats"] = True
        output.append({
            "url": stats["url_norm"],
            "title": stats.get("title") or "",
            "clicks": int(stats.get("clicks") or 0),
            "impressions": int(stats.get("impressions") or 0),
            "popularity_score": round(popularity_score(stats, now), 6),
            "last_clicked_at": stats.get("last_clicked_at"),
        })
    return output


# ── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup(now: datetime | None = None) -> dict:
    """Decay aggregate stats and delete click events past retention."""
    flush_impressions()
    current = now or _now()
    cutoff = _iso(current - timedelta(days=RETENTION_DAYS))

    conn = None
    deleted_events = 0
    pruned_stats = 0
    decayed_rows = 0
    try:
        with _write_lock:
            conn = _get_db()
            conn.execute("BEGIN IMMEDIATE")

            rows = conn.execute(
                """
                SELECT query_norm, url_norm, decayed_clicks,
                       last_clicked_at, last_decayed_at
                  FROM result_stats
                 WHERE decayed_clicks > 0
                """
            ).fetchall()
            updates = []
            for row in rows:
                anchor = _parse_iso(
                    row["last_decayed_at"] or row["last_clicked_at"]
                )
                value = float(row["decayed_clicks"] or 0.0)
                value *= decay_factor(anchor, current)
                updates.append(
                    (value, _iso(current), row["query_norm"], row["url_norm"])
                )
            if updates:
                conn.executemany(
                    """
                    UPDATE result_stats
                       SET decayed_clicks = ?, last_decayed_at = ?
                     WHERE query_norm = ? AND url_norm = ?
                    """,
                    updates,
                )
            decayed_rows = len(updates)

            deleted_events = conn.execute(
                "DELETE FROM click_events WHERE created_at < ?", (cutoff,)
            ).rowcount
            pruned_stats = conn.execute(
                """
                DELETE FROM result_stats
                 WHERE clicks = 0
                   AND (last_shown_at IS NULL OR last_shown_at < ?)
                """,
                (cutoff,),
            ).rowcount
            conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception("click cleanup failed")
    finally:
        if conn is not None:
            conn.close()

    return {
        "click_events_deleted": int(deleted_events or 0),
        "stats_decayed": decayed_rows,
        "stats_pruned": int(pruned_stats or 0),
    }


async def _maintenance_loop() -> None:
    last_cleanup = time.monotonic()
    while True:
        await asyncio.sleep(IMPRESSION_FLUSH_SECONDS)
        try:
            await asyncio.to_thread(flush_impressions)
            if time.monotonic() - last_cleanup >= CLEANUP_INTERVAL_SECONDS:
                result = await asyncio.to_thread(cleanup)
                logger.info("click cleanup: %s", result)
                last_cleanup = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("click maintenance failed")


def start_maintenance() -> asyncio.Task:
    """Start the impression flusher and periodic cleanup task."""
    return asyncio.create_task(
        _maintenance_loop(), name="8search-click-maintenance"
    )


# ── HTTP helpers ────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _session_key(
    request: Request,
    session_token: str | None,
    guest_id: str | None,
) -> str:
    if session_token:
        return "user:" + session_token
    if guest_id:
        return "guest:" + guest_id
    # No cookie yet: fall back to the network/device pair so dedupe still
    # works for clients that block cookies.
    return "anon:" + _client_ip(request) + "|" + (
        request.headers.get("user-agent") or ""
    )


def _is_bot(user_agent: str) -> bool:
    return bool(user_agent and _BOT_RE.search(user_agent))


def log_ranking(query: str, payload: dict) -> None:
    """Optional one-line-per-result diagnosic, enabled by RANKING_DEBUG=1."""
    if os.getenv("RANKING_DEBUG", "0") != "1":
        return
    for position, item in enumerate(payload.get("results") or [], start=1):
        if not isinstance(item, dict):
            continue
        ranking_logger.info(
            "rank query=%r position=%d score=%.6f clicks=%d source=%s url=%s",
            query,
            position,
            float(item.get("popularity_score") or 0.0),
            int(item.get("click_count") or 0),
            item.get("rank_source") or "default",
            item.get("url") or "",
        )


# ── Request models and routes ───────────────────────────────────────────────

class ClickRequest(BaseModel):
    query: str = Field(default="", max_length=400)
    url: str = Field(default="", max_length=4096)
    title: str = Field(default="", max_length=500)
    position: int = Field(default=0, ge=0, le=100)
    kind: str = Field(default="web", max_length=20)
    token: str = Field(default="", max_length=512)


@router.post("/api/click", status_code=204, response_class=Response)
async def click(
    body: ClickRequest,
    request: Request,
    background: BackgroundTasks,
    session_token: str | None = Cookie(default=None),
    guest_id: str | None = Cookie(default=None),
):
    """Accept a result click and store it after the response is sent.

    The endpoint never touches guest-search cookies, so clicking results does
    not consume the four-search guest allowance.
    """
    kind = (body.kind or "web").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="Unsupported click kind")

    query = body.query.strip()
    url = body.url.strip()
    if not query or not url:
        raise HTTPException(status_code=400, detail="Invalid click")

    user_agent = request.headers.get("user-agent") or ""
    if _is_bot(user_agent):
        return Response(status_code=204)

    if not verify_click_token(
        body.token, query, url, kind, body.position
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired click token",
        )

    ip_hash = _hash_value("ip:" + _client_ip(request))
    session_hash = _hash_value(
        "session:" + _session_key(request, session_token, guest_id)
    )

    if not await click_ip_limiter.allow(f"click:ip:{ip_hash}"):
        raise HTTPException(
            status_code=429, detail="Too many clicks. Please slow down."
        )
    if not await click_session_limiter.allow(
        f"click:session:{session_hash}"
    ):
        raise HTTPException(
            status_code=429, detail="Too many clicks. Please slow down."
        )

    user_id = None
    if session_token:
        try:
            email = await run_in_threadpool(auth.get_current_user, session_token)
            if email:
                user_id = _hash_value("user:" + email)
        except Exception:
            user_id = None

    query_norm = normalize_query(query)
    background.add_task(
        _record_click,
        _stats_query_key(query_norm, kind),
        normalize_url(url),
        (body.title or "").strip()[:300],
        int(body.position),
        session_hash,
        user_id,
        ip_hash,
        _hash_value("ua:" + user_agent),
        kind,
        _iso(),
    )
    return Response(status_code=204)


@router.get("/api/popular")
def popular_endpoint(
    q: str = Query("", min_length=0, max_length=400),
    kind: str = Query("web", max_length=20),
    limit: int = Query(20, ge=1, le=100),
):
    """Top clicked URLs for one query (debugging + future Trending UI)."""
    query = q.strip()
    kind = (kind or "web").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="Unsupported click kind")
    if not query:
        return {
            "query": "", "query_norm": "", "kind": kind, "results": [],
        }
    return {
        "query": query,
        "query_norm": normalize_query(query),
        "kind": kind,
        "results": popular(query, kind, limit),
    }


@router.get("/api/ranking/debug")
def ranking_debug(
    request: Request,
    q: str = Query("", min_length=0, max_length=400),
    kind: str = Query("web", max_length=20),
    limit: int = Query(20, ge=1, le=100),
    token: str = Query("", max_length=256),
):
    """Protected view of why a result ranks where it does."""
    expected = os.getenv("RANKING_DEBUG_TOKEN", "").strip()
    supplied = token or request.headers.get("x-ranking-token", "")
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        authorized = hmac.compare_digest(
            supplied.encode("utf-8"), expected.encode("utf-8")
        )
    except (UnicodeError, TypeError):
        authorized = False
    if not authorized:
        raise HTTPException(status_code=404, detail="Not found")

    query = q.strip()
    kind = (kind or "web").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="Unsupported click kind")

    return {
        "query": query,
        "query_norm": normalize_query(query),
        "kind": kind,
        "config": config_snapshot(),
        "token_ttl_seconds": CLICK_TOKEN_TTL_SECONDS,
        "dedupe_window_seconds": DEDUPE_WINDOW_SECONDS,
        "popular": popular(query, kind, limit) if query else [],
    }


def reset_runtime_state() -> None:
    """Clear in-process buffers (used by tests and after a DB switch)."""
    global _secret_cache, _last_flush
    with _impression_lock:
        _impression_buffer.clear()
        _last_flush = time.monotonic()
    with _secret_lock:
        _secret_cache = None
    click_ip_limiter._hits.clear()
    click_session_limiter._hits.clear()
