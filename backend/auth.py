"""Authentication module – signup, login, logout, password reset, sessions."""

import hashlib
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel

from . import emailer

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "users.db")

router = APIRouter()

RESET_TOKEN_TTL_MINUTES = 30
FORGOT_COOLDOWN_SECONDS = 60

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_forgot_last_request: dict[str, float] = {}


# ── Database helpers ────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create users, sessions & password-reset tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT    PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            created_at TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT    PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            created_at TEXT    NOT NULL,
            expires_at TEXT    NOT NULL,
            used_at    TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_password_resets_user
            ON password_resets(user_id);
        """
    )
    conn.close()


# ── Validation helpers ──────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_email(email: str) -> str:
    """Normalise and validate an email address."""
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")
    return email


def _validate_password(password: str) -> None:
    """Enforce the same bcrypt-safe rules on signup and password reset."""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password is too long (maximum 72 characters)")


def _hash_password(password: str) -> str:
    try:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()
    except ValueError:
        raise HTTPException(status_code=400, detail="Password is too long (maximum 72 characters)")


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode())
    except (ValueError, TypeError):
        return False


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Dependency: current user (returns email or None) ────────────────────────

def get_current_user(session_token: str | None = Cookie(default=None)) -> str | None:
    """Return the email of the logged-in user, or None."""
    if not session_token:
        return None
    conn = _get_db()
    row = conn.execute(
        """
        SELECT u.email
          FROM sessions s
          JOIN users u ON u.id = s.user_id
         WHERE s.token = ?
        """,
        (session_token,),
    ).fetchone()
    conn.close()
    return row["email"] if row else None


def require_user(user: str | None = Depends(get_current_user)) -> str:
    """Dependency that raises 401 when no valid session exists."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ── Request / Response models ───────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/api/signup")
def signup(body: AuthRequest):
    email = _validate_email(body.email)
    _validate_password(body.password)

    password_hash = _hash_password(body.password)
    now = _now().isoformat()

    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    conn.close()
    return {"message": "Account created"}


@router.post("/api/login")
def login(
    body: AuthRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
):
    email = body.email.strip().lower()
    password = body.password

    conn = _get_db()
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    if row is None or not _verify_password(password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = secrets.token_hex(32)
    now = _now().isoformat()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, row["id"], now),
    )
    conn.commit()
    conn.close()

    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 24 * 30,  # 30 days
        path="/",
    )

    # Send the sign-in alert after the response; failures never block login.
    background.add_task(
        emailer.send_login_notice,
        email,
        _now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        request.client.host if request.client else "unknown",
        request.headers.get("user-agent", "Unknown device"),
    )

    return {"email": email}


@router.post("/api/logout")
def logout(response: Response, session_token: str | None = Cookie(default=None)):
    if session_token:
        conn = _get_db()
        conn.execute("DELETE FROM sessions WHERE token = ?", (session_token,))
        conn.commit()
        conn.close()
    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out"}


@router.get("/api/me")
def me(user: str = Depends(require_user)):
    return {"email": user}


@router.post("/api/forgot-password")
def forgot_password(body: ForgotPasswordRequest, background: BackgroundTasks):
    """Email a password-reset link. Always returns the same message."""
    generic = {
        "message": (
            "If an account with that email exists, a password reset link "
            "has been sent. Check your inbox and spam folder."
        )
    }

    email = body.email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return generic

    # Light throttle: at most one reset email per address per minute.
    now_mono = time.monotonic()
    last_request = _forgot_last_request.get(email)
    if last_request is not None and now_mono - last_request < FORGOT_COOLDOWN_SECONDS:
        return generic

    conn = _get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        conn.close()
        return generic

    _forgot_last_request[email] = now_mono

    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)

    # Invalidate previous reset links for this account and clear expired ones.
    conn.execute(
        "DELETE FROM password_resets WHERE user_id = ? OR expires_at < ?",
        (row["id"], now.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO password_resets (token_hash, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (_hash_reset_token(token), row["id"], now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()

    reset_url = f"{emailer.app_base_url()}/reset-password.html?token={token}"
    background.add_task(
        emailer.send_password_reset,
        email,
        reset_url,
        RESET_TOKEN_TTL_MINUTES,
    )
    return generic


@router.post("/api/reset-password")
def reset_password(body: ResetPasswordRequest):
    """Consume a reset token and set a new password."""
    _validate_password(body.new_password)

    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")

    token_hash = _hash_reset_token(token)
    conn = _get_db()
    row = conn.execute(
        """
        SELECT pr.user_id, pr.expires_at, u.email
          FROM password_resets pr
          JOIN users u ON u.id = pr.user_id
         WHERE pr.token_hash = ? AND pr.used_at IS NULL
        """,
        (token_hash,),
    ).fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")

    try:
        expired = datetime.fromisoformat(row["expires_at"]) <= _now()
    except ValueError:
        expired = True

    if expired:
        conn.execute("DELETE FROM password_resets WHERE token_hash = ?", (token_hash,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")

    password_hash = _hash_password(body.new_password)
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, row["user_id"]),
    )
    # A reset link is single-use; also sign the user out everywhere.
    conn.execute("DELETE FROM password_resets WHERE user_id = ?", (row["user_id"],))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
    conn.commit()
    conn.close()

    return {
        "message": "Password updated. You can now sign in with your new password.",
        "email": row["email"],
    }
