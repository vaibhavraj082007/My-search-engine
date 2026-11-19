"""Shared pytest fixtures for the click-popularity tests."""

import os
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import (  # noqa: E402
    auth,
    clicks,
    feedback,
    history,
    news,
    search_api,
    searchdb,
    suggestions,
)
from backend.cache import cache  # noqa: E402

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep every test away from the real ``data/`` databases.

    Search requests record suggestions in a background task, sign-in writes
    sessions and history, and the full-app tests exercise every router.  If a
    single module keeps pointing at ``data/``, a test run silently pollutes
    live accounts, history and ranking data.  Redirect every database for
    every test, then initialize the schemas the app expects.
    """
    data_dir = tmp_path / "isolated-data"
    data_dir.mkdir()
    for module, filename in (
        (auth, "users.db"),
        (clicks, "clicks.db"),
        (feedback, "feedback.db"),
        (news, "news.db"),
        (searchdb, "search.db"),
        (suggestions, "suggest.db"),
    ):
        monkeypatch.setattr(module, "DB_PATH", str(data_dir / filename))

    auth.init_db()
    history.init_db()
    feedback.init_db()
    news.init_db()
    searchdb.init_db()
    suggestions.init_db()
    clicks.reset_runtime_state()
    clicks.init_db()

    cache._memory.clear()
    suggestions._cache.clear()
    suggestions._recent.clear()
    feedback._last_submission.clear()
    auth._forgot_last_request.clear()

    yield

    clicks.reset_runtime_state()


@pytest.fixture
def click_store(tmp_path, monkeypatch):
    """Point the click module at a throwaway database for each test."""
    db_path = tmp_path / "clicks.db"
    monkeypatch.setattr(clicks, "DB_PATH", str(db_path))
    monkeypatch.setattr(clicks, "CLICK_TOKEN_SECRET", "test-click-secret")
    clicks.reset_runtime_state()
    clicks.init_db()
    try:
        yield clicks
    finally:
        clicks.reset_runtime_state()


def build_payload(query: str) -> dict:
    """Five deterministic web results whose URLs are unique per query."""
    slug = uuid.uuid5(uuid.NAMESPACE_URL, query).hex[:12]
    titles = ["One", "Two", "Three", "Four", "Five"]
    results = [
        {
            "url": f"https://{slug}-{index}.example/result",
            "title": title,
            "snippet": f"Snippet for {title}",
        }
        for index, title in enumerate(titles, start=1)
    ]
    return {
        "results": results,
        "news": [],
        "answer": None,
        "wikipedia": None,
        "videos": [],
        "total": len(results),
        "page": 1,
        "per_page": 10,
        "has_more": False,
        "max_page": 10,
        "limit_reached": False,
    }


@pytest.fixture
def client(click_store, monkeypatch):
    """Small app with only the search and click routes (no network calls)."""
    cache._memory.clear()

    async def fake_collect(query: str, page: int) -> dict:
        return build_payload(query)

    monkeypatch.setattr(
        search_api, "_collect_payload_limited", fake_collect
    )

    app = FastAPI()
    app.include_router(search_api.router)
    app.include_router(clicks.router)
    with TestClient(app) as test_client:
        yield test_client


def search(client: TestClient, query: str):
    return client.get("/api/search", params={"q": query})


def click_result(
    client: TestClient,
    query: str,
    item: dict,
    session: str = "session-1",
    user_agent: str = BROWSER_UA,
    kind: str | None = None,
):
    client.cookies.set("guest_id", session)
    return client.post(
        "/api/click",
        headers={"user-agent": user_agent},
        json={
            "query": query,
            "url": item["url"],
            "title": item.get("title", ""),
            "position": item.get("click_position", 0),
            "kind": kind or item.get("click_kind", "web"),
            "token": item.get("click_token", ""),
        },
    )
