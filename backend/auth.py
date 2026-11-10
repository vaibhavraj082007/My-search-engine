"""Authentication module – signup, login, logout, session management."""

import os
import secrets
import sqlite3
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "users.db")

router = APIRouter()


# ── Database helpers ────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create users & sessions tables if they don't exist."""
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
        """
    )
    conn.close()


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


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/api/signup")
def signup(body: AuthRequest):
    email = body.email.strip().lower()
    password = body.password

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="Email already registered")
    conn.close()
    return {"message": "Account created"}


@router.post("/api/login")
def login(body: AuthRequest, response: Response):
    email = body.email.strip().lower()
    password = body.password

    conn = _get_db()
    row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, row["id"], now))
    conn.commit()
    conn.close()

    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
        path="/",
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
