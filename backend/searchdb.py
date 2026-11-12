"""Search database – FTS5 full-text index over crawled pages."""

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "search.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create pages table and FTS5 virtual table."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            url        TEXT    UNIQUE NOT NULL,
            title      TEXT,
            content    TEXT,
            crawled_at TEXT    NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            title,
            content,
            content=pages,
            content_rowid=id
        );

        -- Triggers to keep FTS in sync with pages table
        CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
            INSERT INTO pages_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        """
    )
    conn.close()


def insert_page(url: str, title: str | None, content: str | None) -> None:
    """Upsert a crawled page into the index."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    # Try insert, on conflict update
    conn.execute(
        """
        INSERT INTO pages (url, title, content, crawled_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title      = excluded.title,
            content    = excluded.content,
            crawled_at = excluded.crawled_at
        """,
        (url, title, content, now),
    )
    conn.commit()
    conn.close()


def search(query: str, page: int = 1, per_page: int = 10) -> dict:
    """
    Search the FTS index.

    Returns: {results: [{url, title, snippet}], total: int, page: int}
    """
    conn = _get_db()
    offset = (page - 1) * per_page

    # Count total matches
    total_row = conn.execute(
        "SELECT count(*) AS cnt FROM pages_fts WHERE pages_fts MATCH ?",
        (query,),
    ).fetchone()
    total = total_row["cnt"] if total_row else 0

    # Fetch page of results with snippets
    rows = conn.execute(
        """
        SELECT
            p.url,
            p.title,
            snippet(pages_fts, 1, '<b>', '</b>', '…', 40) AS snippet
        FROM pages_fts
        JOIN pages p ON p.id = pages_fts.rowid
        WHERE pages_fts MATCH ?
        ORDER BY rank
        LIMIT ? OFFSET ?
        """,
        (query, per_page, offset),
    ).fetchall()
    conn.close()

    results = [{"url": r["url"], "title": r["title"], "snippet": r["snippet"]} for r in rows]
    return {"results": results, "total": total, "page": page}


def get_stats() -> dict:
    """Return total number of indexed pages."""
    conn = _get_db()
    row = conn.execute("SELECT count(*) AS cnt FROM pages").fetchone()
    conn.close()
    return {"total_pages": row["cnt"] if row else 0}
