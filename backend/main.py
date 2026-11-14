"""8search API – main FastAPI application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, feedback, searchdb
from .answers import close_http_client
from .cache import cache
from .ratelimit import limiter
from .search_api import router as search_router
from .weather_api import router as weather_router

STATIC_CACHE_EXTENSIONS = {
    ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".map",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases and shared runtime resources on startup."""
    auth.init_db()
    feedback.init_db()
    searchdb.init_db()
    await cache.start()
    limiter.redis = cache.redis
    try:
        yield
    finally:
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

    if path.startswith("/api/") or path in {"/health", "/ready"}:
        response.headers["Cache-Control"] = "no-store"
    elif extension in STATIC_CACHE_EXTENSIONS:
        if "v=" in request.url.query:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
    else:
        response.headers["Cache-Control"] = "no-cache"

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
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
        if not await limiter.allow(f"api:{_client_ip(request)}"):
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
app.include_router(feedback.router)
app.include_router(search_router)
app.include_router(weather_router)

# Mount frontend static files – served at "/" with html=True so
# index.html is served for the root path and other .html files
# are served by their path.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
