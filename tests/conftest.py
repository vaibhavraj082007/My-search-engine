"""Shared pytest fixtures for the click-popularity tests."""

import os
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import clicks, search_api  # noqa: E402
from backend.cache import cache  # noqa: E402

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


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
