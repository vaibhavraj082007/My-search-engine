"""Feedback collection – stores submissions and emails them to the site owner."""

import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from . import emailer

logger = logging.getLogger("8search.feedback")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "feedback.db")

router = APIRouter()

MAX_NAME = 100
MAX_EMAIL = 254
MAX_MESSAGE = 4000
MIN_MESSAGE = 3
COOLDOWN_SECONDS = 30

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Per-IP cooldown so one visitor can't flood the owner's inbox. The global
# API limiter (120/min) still applies on top of this.
_last_submission: dict[str, float] = {}
_cooldown_lock = threading.Lock()


# ── Database helpers ────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create the feedback table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            email      TEXT,
            message    TEXT NOT NULL,
            ip         TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_created
            ON feedback(created_at);
        """
    )
    conn.close()


# ── Request helpers ─────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    message: str = ""


def _client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _cooldown_remaining(ip: str) -> int:
    """Record a submission and return seconds to wait (0 when allowed)."""
    now = time.monotonic()
    with _cooldown_lock:
        last = _last_submission.get(ip)
        if last is not None and now - last < COOLDOWN_SECONDS:
            return int(COOLDOWN_SECONDS - (now - last)) + 1

        _last_submission[ip] = now

        # Keep the in-memory map from growing forever.
        if len(_last_submission) > 5000:
            cutoff = now - COOLDOWN_SECONDS
            for key, seen in list(_last_submission.items()):
                if seen < cutoff:
                    del _last_submission[key]
    return 0


# ── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/api/feedback")
def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    background: BackgroundTasks,
):
    """Store a feedback message and email it to the site owner."""
    name = (body.name or "").strip()
    email = (body.email or "").strip()
    message = (body.message or "").strip()

    if len(name) > MAX_NAME:
        raise HTTPException(status_code=422, detail=f"Name must be {MAX_NAME} characters or fewer")

    if email:
        if len(email) > MAX_EMAIL or not _EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Please enter a valid email address")

    if len(message) < MIN_MESSAGE:
        raise HTTPException(status_code=422, detail="Please write a message before submitting")

    if len(message) > MAX_MESSAGE:
        raise HTTPException(
            status_code=422,
            detail=f"Message must be {MAX_MESSAGE} characters or fewer",
        )

    ip = _client_ip(request)
    retry_after = _cooldown_remaining(ip)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {retry_after} seconds before sending more feedback.",
        )

    user_agent = (request.headers.get("user-agent") or "Unknown device")[:500]
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    conn = _get_db()
    cursor = conn.execute(
        """
        INSERT INTO feedback (name, email, message, ip, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name or None, email or None, message, ip, user_agent, created_at),
    )
    feedback_id = cursor.lastrowid
    conn.commit()
    conn.close()

    logger.info("Stored feedback #%s from %s", feedback_id, ip)

    # Email the owner after the response; delivery failures never block the
    # visitor's success message (the submission is already stored above).
    email_ready = emailer.is_configured()
    background.add_task(
        emailer.send_feedback_notice,
        feedback_id,
        name,
        email,
        message,
        created_at,
        ip,
        user_agent,
    )

    return {
        "message": (
            "Thanks for your feedback! It has been sent."
            if email_ready
            else "Thanks for your feedback! It has been saved."
        )
    }
