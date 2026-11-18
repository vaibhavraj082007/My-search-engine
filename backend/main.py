"""8search API – main FastAPI application."""

import asyncio
import mimetypes
import os
import shutil
import sqlite3
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, clicks, feedback, history, news, searchdb, suggestions
from .answers import close_http_client
from .cache import cache
from .lens import router as lens_router
from .ratelimit import RateLimiter, limiter
from .search_api import router as search_router
from .webapp import router as webapp_router

# Register custom MIME types for platform installers
mimetypes.add_type("application/x-apple-diskimage", ".dmg")
mimetypes.add_type("application/vnd.android.package-archive", ".apk")
mimetypes.add_type("application/x-msdownload", ".exe")
mimetypes.add_type("application/x-apple-aspen-config", ".mobileconfig")

STATIC_CACHE_EXTENSIONS = {
    ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".map",
    ".webmanifest", ".dmg", ".apk", ".exe", ".mobileconfig",
}

SUGGEST_RATE_LIMIT_PER_MINUTE = int(os.getenv("SUGGEST_RATE_LIMIT_PER_MINUTE", "600"))
suggest_limiter = RateLimiter(limit=SUGGEST_RATE_LIMIT_PER_MINUTE)


def _seed_data_if_empty():
    """Seed data volume on first boot and sync seed users."""
    seed_dir = os.path.join(os.path.dirname(__file__), "..", "data_seed")
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    if os.path.isdir(seed_dir) and os.path.isdir(data_dir):
        for fname in os.listdir(seed_dir):
            if fname.endswith((".shm", ".wal", ".lock")):
                continue
            src = os.path.join(seed_dir, fname)
            dst = os.path.join(data_dir, fname)
            if not os.path.exists(dst) and os.path.isfile(src):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass
        # Sync users from seed into data/users.db so account updates take effect
        seed_users_db = os.path.join(seed_dir, "users.db")
        target_users_db = os.path.join(data_dir, "users.db")
        if os.path.isfile(seed_users_db) and os.path.isfile(target_users_db):
            s_conn = None
            t_conn = None
            try:
                s_conn = sqlite3.connect(seed_users_db, timeout=15)
                t_conn = sqlite3.connect(target_users_db, timeout=15)
                t_conn.execute("PRAGMA journal_mode=WAL")
                t_conn.execute("PRAGMA synchronous=NORMAL")
                t_conn.execute("PRAGMA busy_timeout=15000")
                s_cur = s_conn.cursor()
                t_cur = t_conn.cursor()
                s_cur.execute("SELECT email, password_hash, created_at FROM users")
                for email, pwd_hash, created_at in s_cur.fetchall():
                    t_cur.execute(
                        "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash",
                        (email, pwd_hash, created_at),
                    )
                t_conn.commit()
            except Exception:
                pass
            finally:
                if s_conn is not None:
                    s_conn.close()
                if t_conn is not None:
                    t_conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases and shared runtime resources on startup."""
    _seed_data_if_empty()
    auth.init_db()
    history.init_db()
    feedback.init_db()
    searchdb.init_db()
    clicks.init_db()
    suggestions.init_db()
    news.init_db()
    await cache.start()
    limiter.redis = cache.redis
    suggest_limiter.redis = cache.redis
    clicks.click_ip_limiter.redis = cache.redis
    clicks.click_session_limiter.redis = cache.redis
    maintenance_task = clicks.start_maintenance()
    news.start_scheduler()
    try:
        yield
    finally:
        maintenance_task.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance_task
        await news.stop_scheduler()
        clicks.flush_impressions()
        await cache.close()
        await close_http_client()


app = FastAPI(title="8search API", lifespan=lifespan)

# Compress JSON and text assets (helps a lot on slower connections).
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS for development; restrict in production with ALLOWED_ORIGINS.
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def response_headers(request: Request, call_next):
    """Set safe caching for hashed assets and no-store for dynamic responses."""
    response = await call_next(request)
    path = request.url.path
    extension = os.path.splitext(path)[1].lower()

    if path.startswith("/api/"):
        # News and suggestions deliberately set their own public cache headers.
        if not response.headers.get("cache-control"):
            response.headers["Cache-Control"] = "no-store"
    elif path in {"/health", "/ready"}:
        response.headers["Cache-Control"] = "no-store"
    elif path == "/sw.js":
        # Service worker updates must be checked on every visit.
        response.headers["Cache-Control"] = "no-cache"
    elif extension in STATIC_CACHE_EXTENSIONS:
        if "v=" in request.url.query:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
    else:
        response.headers["Cache-Control"] = "no-cache"

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    proto = request.url.scheme
    if os.getenv("TRUST_PROXY", "0") == "1":
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or proto
    if proto == "https" or os.getenv("FORCE_HTTPS", "0") == "1":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


def _client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_api(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        path = request.url.path
        is_suggest = path == "/api/suggest"
        limiter_to_use = suggest_limiter if is_suggest else limiter
        bucket = "suggest" if is_suggest else "api"
        if not await limiter_to_use.allow(f"{bucket}:{_client_ip(request)}"):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down and try again shortly."},
            )
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {
        "status": "ready",
        "cache": "redis" if cache.redis is not None else "memory",
    }


# Include API routers
app.include_router(auth.router)
app.include_router(history.router)
app.include_router(clicks.router)
app.include_router(feedback.router)
app.include_router(lens_router)
app.include_router(search_router)
app.include_router(suggestions.router)
app.include_router(news.router)
app.include_router(webapp_router)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# Mount frontend static files – served at "/" with html=True so
# index.html is served for the root path and other .html files
# are served by their path. Browser-facing routes above must stay
# registered before this mount.
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
