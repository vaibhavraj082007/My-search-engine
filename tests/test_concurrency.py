"""Concurrency and multi-user stress tests.

Simulates multiple simultaneous users querying, clicking, logging in,
recording history, and downloading platform installers at the same time to
verify zero database locks (OperationalError: database is locked) and zero 500s.
"""

import concurrent.futures
import os
import uuid
import pytest
from fastapi.testclient import TestClient

from backend import auth, clicks, feedback, history, main, search_api, suggestions
from backend.main import app


@pytest.fixture(autouse=True)
def init_all_databases():
    """Ensure all databases and tables are initialized and clean."""
    auth.init_db()
    history.init_db()
    feedback.init_db()
    clicks.init_db()
    suggestions.init_db()


def test_concurrent_signups_and_logins():
    """20 users concurrently sign up, sign in, check /api/me and write search history."""
    client = TestClient(app)

    def user_flow(index: int):
        user_email = f"concurrent_user_{index}_{uuid.uuid4().hex[:6]}@example.com"
        password = "ValidPassword123!"

        # 1. Sign up
        signup_res = client.post(
            "/api/signup",
            json={"email": user_email, "password": password},
        )
        assert signup_res.status_code == 200, signup_res.text

        # 2. Log in
        login_client = TestClient(app)
        login_res = login_client.post(
            "/api/login",
            json={"email": user_email, "password": password},
        )
        assert login_res.status_code == 200, login_res.text
        assert "session_token" in login_res.cookies

        # 3. /api/me check
        me_res = login_client.get("/api/me")
        assert me_res.status_code == 200
        assert me_res.json()["email"] == user_email

        # 4. Record search history
        for q_idx in range(3):
            history.record_search(user_email, f"query {index} {q_idx}", "web")

        entries, total = history.fetch_history(user_email, limit=10)
        assert total == 3
        assert len(entries) == 3

        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(user_flow, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            assert f.result() is True


def test_concurrent_searches_and_clicks(monkeypatch):
    """30 simultaneous search and click operations."""
    async def fake_collect(query: str, page: int) -> dict:
        return {
            "results": [
                {"url": f"https://example.com/{query}/{i}", "title": f"Result {i}", "snippet": "Test"}
                for i in range(5)
            ],
            "news": [],
            "answer": None,
            "wikipedia": None,
            "videos": [],
            "total": 5,
            "page": 1,
            "per_page": 10,
            "has_more": False,
            "max_page": 10,
            "limit_reached": False,
        }

    monkeypatch.setattr(search_api, "_collect_payload_limited", fake_collect)

    def search_flow(index: int):
        client = TestClient(app)
        q = f"concurrent test query {index % 5}"
        res = client.get(f"/api/search?q={q}")
        assert res.status_code == 200, res.text
        data = res.json()
        assert len(data.get("results", [])) == 5

        # Record a suggestion
        suggestions.record_query(q)

        # Trigger click
        item = data["results"][0]
        token = item.get("click_token")
        if token:
            click_res = client.post(
                "/api/click",
                json={
                    "query": q,
                    "url": item["url"],
                    "title": item["title"],
                    "position": item.get("click_position", 1),
                    "kind": item.get("click_kind", "web"),
                    "token": token,
                },
                cookies={"guest_id": f"guest-{index}"},
            )
            assert click_res.status_code == 204, click_res.text
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(search_flow, i) for i in range(30)]
        for f in concurrent.futures.as_completed(futures):
            assert f.result() is True


def test_concurrent_platform_downloads():
    """Concurrent requests downloading macOS, Windows, Android, and iOS installers."""
    platforms = ["mac", "windows", "android", "ios", "dmg", "exe", "apk", "mobileconfig"]

    def download_flow(platform: str):
        client = TestClient(app)
        # Test GET
        get_res = client.get(f"/download/{platform}")
        assert get_res.status_code == 200, f"GET failed for {platform}"
        assert len(get_res.content) > 1000, f"Empty download for {platform}"

        # Test HEAD
        head_res = client.head(f"/download/{platform}")
        assert head_res.status_code == 200, f"HEAD failed for {platform}"
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(download_flow, p) for p in platforms * 3]
        for f in concurrent.futures.as_completed(futures):
            assert f.result() is True


def test_concurrent_feedback_submissions(monkeypatch):
    """Concurrent feedback submissions from distinct IPs."""
    monkeypatch.setenv("TRUST_PROXY", "1")

    def feedback_flow(index: int):
        client = TestClient(app)
        res = client.post(
            "/api/feedback",
            headers={"x-forwarded-for": f"198.51.100.{index}"},
            json={
                "name": f"User {index}",
                "email": f"user{index}@example.com",
                "message": f"This is test feedback message {index} for concurrency verification.",
            },
        )
        assert res.status_code == 200, res.text
        assert "received" in res.json()["message"]
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(feedback_flow, i) for i in range(15)]
        for f in concurrent.futures.as_completed(futures):
            assert f.result() is True
