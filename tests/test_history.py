"""Private per-account search history: storage, API and search recording."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import auth, history, search_api
from conftest import search

ALICE = "alice@example.com"
BOB = "bob@example.com"


@pytest.fixture
def accounts_db(tmp_path, monkeypatch):
    """A throwaway account database containing both users and history."""
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "users.db"))
    auth.init_db()
    history.init_db()
    return auth.DB_PATH


def _seed_user(email: str, token: str) -> None:
    """Create a user + session directly so tests focus on history, not bcrypt."""
    conn = auth._get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, "test-only", datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, cursor.lastrowid, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _client(token: str | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(history.router)
    client = TestClient(app)
    if token:
        client.cookies.set("session_token", token)
    return client


def _fresh_query(label: str) -> str:
    return f"{label} {uuid.uuid4().hex[:10]}"


def test_guests_cannot_read_write_or_clear_history(accounts_db):
    guest = _client()

    assert guest.get("/api/history").status_code == 401
    assert guest.post("/api/history", json={"query": "private"}).status_code == 401
    assert guest.delete("/api/history").status_code == 401


def test_guest_session_check_is_a_normal_response_not_an_error(accounts_db):
    """The homepage checks /api/me for every visitor.

    A 401 here would be logged as a browser console error on every guest
    visit, so guests get a 200 with a null email instead.
    """
    app = FastAPI()
    app.include_router(auth.router)
    guest = TestClient(app)

    response = guest.get("/api/me")
    assert response.status_code == 200
    assert response.json() == {"email": None}


def test_history_is_private_to_each_account(accounts_db):
    _seed_user(ALICE, "alice-token")
    _seed_user(BOB, "bob-token")
    alice = _client("alice-token")
    bob = _client("bob-token")

    assert alice.post("/api/history", json={"query": "alice cats", "tab": "web"}).status_code == 204
    assert alice.post("/api/history", json={"query": "alice dogs", "tab": "images"}).status_code == 204

    alice_data = alice.get("/api/history").json()
    assert [item["query"] for item in alice_data["items"]] == ["alice dogs", "alice cats"]
    assert alice_data["items"][0]["tab"] == "images"
    assert alice_data["total"] == 2

    bob_data = bob.get("/api/history").json()
    assert bob_data["items"] == []
    assert bob_data["total"] == 0


def test_repeated_search_moves_to_top_without_duplicates(accounts_db):
    _seed_user(ALICE, "alice-token")
    alice = _client("alice-token")

    alice.post("/api/history", json={"query": "Cats", "tab": "web"})
    alice.post("/api/history", json={"query": "dogs", "tab": "web"})
    alice.post("/api/history", json={"query": "CATS", "tab": "images"})

    data = alice.get("/api/history").json()
    assert data["total"] == 2
    assert [item["query"] for item in data["items"]] == ["CATS", "dogs"]
    assert data["items"][0]["tab"] == "images"


def test_history_paginates_newest_first(accounts_db):
    _seed_user(ALICE, "alice-token")
    alice = _client("alice-token")

    for index in range(12):
        alice.post("/api/history", json={"query": "search %02d" % index})

    first = alice.get("/api/history", params={"limit": 5, "offset": 0}).json()
    assert first["total"] == 12
    assert len(first["items"]) == 5
    assert first["has_more"] is True
    assert first["items"][0]["query"] == "search 11"

    second = alice.get("/api/history", params={"limit": 5, "offset": 5}).json()
    assert len(second["items"]) == 5
    assert second["has_more"] is True

    last = alice.get("/api/history", params={"limit": 5, "offset": 10}).json()
    assert len(last["items"]) == 2
    assert last["has_more"] is False
    assert last["items"][-1]["query"] == "search 00"


def test_clear_history_only_affects_the_signed_in_account(accounts_db):
    _seed_user(ALICE, "alice-token")
    _seed_user(BOB, "bob-token")
    alice = _client("alice-token")
    bob = _client("bob-token")

    alice.post("/api/history", json={"query": "alice secret"})
    bob.post("/api/history", json={"query": "bob secret"})

    assert alice.delete("/api/history").status_code == 204
    assert alice.get("/api/history").json()["items"] == []
    assert [item["query"] for item in bob.get("/api/history").json()["items"]] == ["bob secret"]


def test_signed_in_page_one_searches_are_recorded(client, accounts_db, monkeypatch):
    _seed_user(ALICE, "alice-token")
    client.cookies.set("session_token", "alice-token")

    real_record = history.record_search
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        return real_record(*args, **kwargs)

    monkeypatch.setattr(history, "record_search", spy)

    query = _fresh_query("history web")
    assert search(client, query).status_code == 200
    assert calls == [(ALICE, query, "web")]

    # Paging must not create another history update.
    assert client.get("/api/search", params={"q": query, "page": 2}).status_code == 200
    assert len(calls) == 1

    # A different tab is still a first-page search and updates the saved tab.
    assert client.get("/api/search", params={"q": query, "page": 1, "tab": "ai"}).status_code == 200
    assert calls[-1] == (ALICE, query, "ai")

    async def fake_images(image_query: str, page: int) -> dict:
        return {
            "images": [{"url": "https://example.com/image.jpg", "title": image_query}],
            "query": image_query,
            "page": page,
            "per_page": 30,
            "has_more": False,
        }

    monkeypatch.setattr(search_api, "_collect_images", fake_images)
    image_query = _fresh_query("history images")
    assert client.get("/api/images", params={"q": image_query}).status_code == 200
    assert calls[-1] == (ALICE, image_query, "images")

    saved, total = history.fetch_history(ALICE)
    assert total == 2
    assert {item["query"] for item in saved} == {query, image_query}


def test_guest_searches_are_never_recorded(client, accounts_db, monkeypatch):
    _seed_user(ALICE, "alice-token")
    monkeypatch.setattr(search_api, "get_current_user", lambda token: None)

    query = _fresh_query("guest history")
    assert search(client, query).status_code == 200

    saved, total = history.fetch_history(ALICE)
    assert saved == []
    assert total == 0


def test_history_failure_never_breaks_a_search(client, accounts_db, monkeypatch):
    _seed_user(ALICE, "alice-token")
    client.cookies.set("session_token", "alice-token")

    def broken(*args, **kwargs):
        raise RuntimeError("history database unavailable")

    monkeypatch.setattr(history, "record_search", broken)
    response = search(client, _fresh_query("resilient"))
    assert response.status_code == 200
    assert response.json()["results"]
