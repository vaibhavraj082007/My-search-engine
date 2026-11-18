"""Private, per-account search history.

History belongs to a signed-in account and is stored in the same SQLite
database as accounts and sessions.  Guests are never recorded and can never
read history: every query in this module is scoped by the authenticated
user's email address.  A user's own repeated query updates its position in
the list instead of creating duplicate rows, which keeps the list useful and
the table small for long-lived accounts.
"""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from . import auth

router = APIRouter()

MAX_HISTORY_QUERY = 500
MAX_PAGE_SIZE = 100
VALID_TABS = {"web", "ai", "images", "code"}


class HistoryEntry(BaseModel):
    query: str
    tab: str = "web"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tab(tab: str | None) -> str:
    return tab if tab in VALID_TABS else "web"


def init_db() -> None:
    """Create the history table without touching existing account data."""
    conn = auth._get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email  TEXT    NOT NULL,
                query_key   TEXT    NOT NULL,
                query       TEXT    NOT NULL,
                tab         TEXT    NOT NULL DEFAULT 'web',
                searched_at TEXT    NOT NULL,
                UNIQUE (user_email, query_key)
            );
            CREATE INDEX IF NOT EXISTS idx_search_history_user
                ON search_history(user_email, searched_at DESC, id DESC);
            """
        )
        conn.commit()
    finally:
        conn.close()


def record_search(user_email: str, query: str, tab: str = "web") -> None:
    """Insert or refresh one private history entry.

    Older clients and cached searches may record the same query more than
    once; the UNIQUE constraint makes that harmless.  The newest search moves
    to the top of the list.
    """
    if not user_email:
        return
    cleaned = (query or "").strip()[:MAX_HISTORY_QUERY]
    if not cleaned:
        return
    safe_tab = _normalize_tab(tab)
    query_key = cleaned.casefold()

    conn = auth._get_db()
    try:
        conn.execute(
            """
            INSERT INTO search_history (user_email, query_key, query, tab, searched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_email, query_key) DO UPDATE SET
                query = excluded.query,
                tab = excluded.tab,
                searched_at = excluded.searched_at
            """,
            (user_email, query_key, cleaned, safe_tab, _now()),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_history(
    user_email: str,
    limit: int = 5,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return one page of history and the total number of saved queries."""
    if not user_email:
        return [], 0

    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    offset = max(0, int(offset))

    conn = auth._get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM search_history WHERE user_email = ?",
            (user_email,),
        ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT query, tab, searched_at
              FROM search_history
             WHERE user_email = ?
             ORDER BY searched_at DESC, id DESC
             LIMIT ? OFFSET ?
            """,
            (user_email, limit, offset),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "query": row["query"],
            "tab": row["tab"],
            "searched_at": row["searched_at"],
        }
        for row in rows
    ], int(total)


def clear_history(user_email: str) -> None:
    if not user_email:
        return
    conn = auth._get_db()
    try:
        conn.execute("DELETE FROM search_history WHERE user_email = ?", (user_email,))
        conn.commit()
    finally:
        conn.close()


def _page_payload(user_email: str, limit: int, offset: int) -> dict:
    items, total = fetch_history(user_email, limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.get("/api/history")
def get_history(
    limit: int = Query(5, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0, le=1_000_000),
    user: str = Depends(auth.require_user),
):
    """List only the signed-in user's history, newest first."""
    return _page_payload(user, limit, offset)


@router.post("/api/history", status_code=204)
def post_history(
    entry: HistoryEntry,
    user: str = Depends(auth.require_user),
):
    """Record a search made from a locally cached result page.

    The search endpoints record ordinary requests themselves.  This endpoint
    covers the browser's in-tab result cache and is idempotent by design.
    """
    record_search(user, entry.query, entry.tab)
    return Response(status_code=204)


@router.delete("/api/history", status_code=204)
def delete_history(user: str = Depends(auth.require_user)):
    """Delete every history entry owned by the signed-in account."""
    clear_history(user)
    return Response(status_code=204)
