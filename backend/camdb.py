"""Camera database – store and query traffic/weather cameras worldwide."""

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cameras.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create the cameras table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cameras (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            source     TEXT    NOT NULL,
            ext_id     TEXT    NOT NULL,
            name       TEXT,
            lat        REAL    NOT NULL,
            lon        REAL    NOT NULL,
            url        TEXT    NOT NULL,
            type       TEXT    DEFAULT 'image',
            credit     TEXT,
            status     TEXT    DEFAULT 'unknown',
            checked_at TEXT,
            UNIQUE(source, ext_id)
        );

        CREATE INDEX IF NOT EXISTS idx_cameras_bounds ON cameras(lat, lon);
        CREATE INDEX IF NOT EXISTS idx_cameras_source ON cameras(source);
        """
    )
    conn.close()


def insert_camera(
    source: str,
    ext_id: str,
    name: str | None,
    lat: float,
    lon: float,
    url: str,
    cam_type: str = "image",
    credit: str | None = None,
) -> bool:
    """
    Insert or update a camera. Returns True if inserted, False if skipped.

    Validates:
    - lat/lon must not both be 0
    - lat/lon must not be None
    - url must start with http
    """
    # Validation
    if lat is None or lon is None:
        return False
    if lat == 0.0 and lon == 0.0:
        return False
    if not url or not url.startswith("http"):
        return False
    if not ext_id:
        return False

    conn = _get_db()
    try:
        conn.execute(
            """
            INSERT INTO cameras (source, ext_id, name, lat, lon, url, type, credit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, ext_id) DO UPDATE SET
                name   = excluded.name,
                lat    = excluded.lat,
                lon    = excluded.lon,
                url    = excluded.url,
                type   = excluded.type,
                credit = excluded.credit
            """,
            (source, str(ext_id), name, lat, lon, url, cam_type, credit),
        )
        conn.commit()
        inserted = True
    except Exception:
        inserted = False
    finally:
        conn.close()
    return inserted


def get_cameras_in_bounds(
    north: float, south: float, east: float, west: float
) -> list[dict]:
    """
    Return cameras within the given bounding box.

    Handles antimeridian crossing (west > east means the box wraps around ±180°).
    """
    conn = _get_db()

    if west <= east:
        # Normal bounding box
        rows = conn.execute(
            """
            SELECT id, source, ext_id, name, lat, lon, url, type, credit, status
            FROM cameras
            WHERE lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
            """,
            (south, north, west, east),
        ).fetchall()
    else:
        # Antimeridian crossing: lon >= west OR lon <= east
        rows = conn.execute(
            """
            SELECT id, source, ext_id, name, lat, lon, url, type, credit, status
            FROM cameras
            WHERE lat BETWEEN ? AND ?
              AND (lon >= ? OR lon <= ?)
            """,
            (south, north, west, east),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> list[dict]:
    """Return camera count per source."""
    conn = _get_db()
    rows = conn.execute(
        """
        SELECT source, count(*) AS count
        FROM cameras
        GROUP BY source
        ORDER BY count DESC
        """
    ).fetchall()
    conn.close()
    return [{"source": r["source"], "count": r["count"]} for r in rows]


def get_all_cameras(exclude_dead: bool = True) -> list[dict]:
    """Return all cameras, optionally excluding dead ones."""
    conn = _get_db()
    if exclude_dead:
        rows = conn.execute(
            "SELECT id, url, status FROM cameras WHERE status != 'dead'"
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, url, status FROM cameras").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_status(camera_id: int, status: str) -> None:
    """Update a camera's status and checked_at timestamp."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        "UPDATE cameras SET status = ?, checked_at = ? WHERE id = ?",
        (status, now, camera_id),
    )
    conn.commit()
    conn.close()
