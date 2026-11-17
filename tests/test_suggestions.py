"""OpenSearch suggestions, rich in-page suggestions and privacy filters."""

import asyncio
import random
import string
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import suggestions


@pytest.fixture
def suggest_db(tmp_path, monkeypatch):
    monkeypatch.setattr(suggestions, "DB_PATH", str(tmp_path / "suggest.db"))
    suggestions._cache.clear()
    suggestions._recent.clear()
    suggestions.init_db()
    yield


@pytest.fixture
def suggest_client(suggest_db, monkeypatch):
    async def fake_suggest(value: str, limit: int = suggestions.MAX_SUGGESTIONS):
        return [
            {"text": value, "kind": "popular"},
            {"text": value + " news", "kind": "web"},
        ]

    monkeypatch.setattr(suggestions, "suggest", fake_suggest)
    app = FastAPI()
    app.include_router(suggestions.router)
    with TestClient(app) as client:
        yield client


def test_opensearch_json_shape_by_default(suggest_client):
    response = suggest_client.get("/api/suggest", params={"q": "nvidia"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-suggestions+json"
    )
    assert response.json() == ["nvidia", ["nvidia", "nvidia news"]]


def test_rich_format_includes_kinds_and_search_link(suggest_client):
    response = suggest_client.get(
        "/api/suggest", params={"q": "nvidia", "format": "rich"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["q"] == "nvidia"
    assert data["suggestions"][0] == {"text": "nvidia", "kind": "popular"}
    assert data["wikipedia_search"].startswith(
        "https://en.wikipedia.org/w/index.php?search="
    )


def test_suggestion_limit_is_bounded(suggest_client):
    assert suggest_client.get(
        "/api/suggest", params={"q": "x", "limit": 9}
    ).status_code == 422


def test_suggestions_never_set_guest_quota_cookies(suggest_client):
    response = suggest_client.get(
        "/api/suggest",
        params={"q": "quota check"},
        cookies={"guest_searches": "4"},
    )
    assert response.status_code == 200
    assert "guest_searches" not in response.cookies


def test_clean_query_rejects_personal_data_and_unsafe_text():
    assert suggestions.clean_query("safe search query") == "safe search query"
    assert suggestions.clean_query("person@example.com") == ""
    assert suggestions.clean_query("+1 (555) 123-4567") == ""
    assert suggestions.clean_query("javascript:alert(1)") == ""
    assert suggestions.clean_query("data:text/html,hi") == ""
    assert suggestions.clean_query("a" * 121) == ""


def _unique_letters(prefix: str) -> str:
    # Avoid long digit runs: clean_query intentionally rejects phone-like text.
    return prefix + "".join(random.choices(string.ascii_lowercase, k=16))


def test_popular_queries_are_aggregated_without_identifiers(suggest_db):
    query = _unique_letters("SuggestTest")
    suggestions.record_query(query)

    results = suggestions.popular_suggestions(query[:12], 8)
    assert any(item["text"] == query for item in results)
    assert all(item["kind"] == "popular" for item in results)


def test_cached_suggestions_respect_the_requested_limit(suggest_db, monkeypatch):
    text = _unique_letters("size")

    def fake_popular(value: str, limit: int):
        return [
            {"text": f"{value} result {index}", "kind": "popular"}
            for index in range(limit)
        ]

    monkeypatch.setattr(suggestions, "popular_suggestions", fake_popular)
    monkeypatch.setattr(suggestions, "local_index_suggestions", lambda value, limit: [])
    monkeypatch.setattr(suggestions, "wikipedia_suggestions", lambda value, limit: [])

    async def run():
        full = await suggestions.suggest(text, 8)
        small = await suggestions.suggest(text, 2)
        return full, small

    full, small = asyncio.run(run())
    assert len(full) == 8
    assert len(small) == 2


def test_cached_suggestions_finish_well_under_100ms(suggest_db, monkeypatch):
    text = _unique_letters("cache")

    def fake_popular(value: str, limit: int):
        return [{"text": f"{value} result {index}", "kind": "popular"} for index in range(8)]

    wiki_calls: list[str] = []

    async def fake_wiki(value: str, limit: int):
        wiki_calls.append(value)
        return []

    monkeypatch.setattr(suggestions, "popular_suggestions", fake_popular)
    monkeypatch.setattr(suggestions, "local_index_suggestions", lambda value, limit: [])
    monkeypatch.setattr(suggestions, "wikipedia_suggestions", fake_wiki)

    async def run():
        first = await suggestions.suggest(text)
        started = time.perf_counter()
        second = await suggestions.suggest(text)
        return first, second, time.perf_counter() - started

    first, second, elapsed = asyncio.run(run())

    assert first == second
    assert len(first) == 8
    assert wiki_calls == []
    assert elapsed < 0.1
