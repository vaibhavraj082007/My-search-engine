"""8search API – main FastAPI application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import auth, searchdb
from .search_api import router as search_router
from .weather_api import router as weather_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all databases on startup."""
    auth.init_db()
    searchdb.init_db()
    yield


app = FastAPI(title="8search API", lifespan=lifespan)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router)
app.include_router(search_router)
app.include_router(weather_router)

# Mount frontend static files – served at "/" with html=True so
# index.html is served for the root path and other .html files
# are served by their path.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
