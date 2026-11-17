"""End-to-end search + click + re-rank flow."""

import uuid

from backend import clicks, search_api
from conftest import build_payload, click_result, search


def _fresh_query(label: str) -> str:
    return f"{label} {uuid.uuid4().hex[:10]}"


def test_cold_search_keeps_provider_order_and_has_tokens(client):
    query = _fresh_query("cold")
    response = search(client, query)
    assert response.status_code == 200
    data = response.json()

    assert [item["title"] for item in data["results"]] == [
        "One", "Two", "Three", "Four", "Five"
    ]
    assert all(item["rank_source"] == "default" for item in data["results"])
    assert all(item["click_count"] == 0 for item in data["results"])
    assert all(item["popularity_score"] == 0 for item in data["results"])
    assert all(item.get("click_token") for item in data["results"])
    assert response.headers.get("x-ranked") is None


def test_click_reranks_result_five_on_the_next_cached_search(client):
    query = _fresh_query("rerank")
    first = search(client, query).json()
    target = first["results"][4]

    clicks.flush_impressions()
    for session in ("guest-a", "guest-b", "guest-c"):
        assert click_result(client, query, target, session).status_code == 204

    second_response = search(client, query)
    assert second_response.status_code == 200
    assert second_response.headers["x-cache"] == "HIT"
    assert second_response.headers.get("x-ranked") == "clicks"

    second = second_response.json()
    assert second["results"][0]["url"] == target["url"]
    assert second["results"][0]["click_count"] == 3
    assert second["results"][0]["rank_source"] == "clicks"
    assert second["results"][0]["click_position"] == 1

    # Everything with no clicks keeps the provider order behind it.
    assert [item["title"] for item in second["results"][1:]] == [
        "One", "Two", "Three", "Four"
    ]


def test_dedupe_accepts_report_but_counts_one_click(client):
    query = _fresh_query("dedupe")
    first = search(client, query).json()
    target = first["results"][2]

    assert click_result(client, query, target, "same-guest").status_code == 204
    assert click_result(client, query, target, "same-guest").status_code == 204

    clicks.flush_impressions()
    stats = clicks.fetch_stats(
        query, {"web": [{"url": target["url"]}]}
    )
    row = stats["web"][clicks.normalize_url(target["url"])]
    assert row["clicks"] == 1


def test_api_rejects_fake_and_missing_tokens(client):
    query = _fresh_query("fake")
    first = search(client, query).json()
    target = first["results"][0]

    fake = click_result(
        client,
        query,
        {
            "url": "https://attacker.example/never-shown",
            "title": "Fake",
            "click_position": target["click_position"],
            "click_token": target["click_token"],
        },
        "fake-session",
    )
    assert fake.status_code == 400

    missing = client.post(
        "/api/click",
        headers={"user-agent": "Mozilla/5.0 Chrome/122"},
        json={
            "query": query,
            "url": target["url"],
            "title": target["title"],
            "position": target["click_position"],
            "kind": "web",
        },
    )
    assert missing.status_code == 400

    clicks.flush_impressions()
    stats = clicks.fetch_stats(
        query, {"web": [{"url": target["url"]}]}
    )
    row = stats["web"][clicks.normalize_url(target["url"])]
    assert row["clicks"] == 0


def test_bot_user_agent_is_ignored(client):
    query = _fresh_query("bot")
    first = search(client, query).json()
    target = first["results"][1]

    response = click_result(
        client,
        query,
        target,
        "bot-session",
        user_agent="Googlebot/2.1 (+http://www.google.com/bot.html)",
    )
    assert response.status_code == 204

    clicks.flush_impressions()
    stats = clicks.fetch_stats(
        query, {"web": [{"url": target["url"]}]}
    )
    row = stats["web"][clicks.normalize_url(target["url"])]
    assert row["clicks"] == 0


def test_click_does_not_consume_guest_search_quota(client):
    query = _fresh_query("quota")
    first = search(client, query).json()
    assert not first.get("limit_reached")
    target = first["results"][0]

    response = click_result(client, query, target, "quota-guest")
    assert response.status_code == 204
    assert "guest_searches" not in response.cookies

    # The first search used one of the four guest searches; the click must
    # leave exactly three more searches available.
    for _ in range(3):
        assert not search(client, query).json().get("limit_reached")
    assert search(client, query).json().get("limit_reached") is True


def test_guest_search_limit_is_configurable(client, monkeypatch):
    monkeypatch.setenv("GUEST_SEARCH_LIMIT", "1")
    client.cookies.set("guest_searches", "1")

    response = search(client, _fresh_query("envlimit"))
    data = response.json()
    assert data["limit_reached"] is True
    assert data["login_url"].startswith("/login?next=")
    assert "guest_searches" not in response.cookies


def test_image_search_shares_the_guest_quota(client, monkeypatch):
    async def fake_images(query: str, page: int) -> dict:
        return {
            "images": [{"url": "https://example.com/image.jpg", "title": query}],
            "query": query,
            "page": page,
            "per_page": 30,
            "has_more": False,
        }

    monkeypatch.setattr(search_api, "_collect_images", fake_images)

    client.cookies.set("guest_searches", "4")
    blocked = client.get("/api/images", params={"q": "cats"}).json()
    assert blocked["limit_reached"] is True
    assert blocked["login_url"].startswith("/login?next=")
    assert "%2Fsearch%3Fq%3Dcats" in blocked["login_url"]

    client.cookies.set("guest_searches", "3")
    allowed = client.get("/api/images", params={"q": "dogs"})
    assert allowed.status_code == 200
    assert not allowed.json().get("limit_reached")
    assert allowed.cookies["guest_searches"] == "4"


def test_popular_endpoint_returns_clicked_url(client):
    query = _fresh_query("popular")
    first = search(client, query).json()
    target = first["results"][3]
    assert click_result(client, query, target, "popular-guest").status_code == 204

    response = client.get("/api/popular", params={"q": query})
    assert response.status_code == 200
    data = response.json()
    assert data["query_norm"] == clicks.normalize_query(query)
    assert data["results"][0]["url"] == clicks.normalize_url(target["url"])
    assert data["results"][0]["clicks"] == 1


def test_ranking_debug_endpoint_is_protected(client, monkeypatch):
    monkeypatch.setenv("RANKING_DEBUG_TOKEN", "debug-secret")
    query = _fresh_query("debug")
    search(client, query)

    assert client.get("/api/ranking/debug", params={"q": query}).status_code == 404
    denied = client.get(
        "/api/ranking/debug", params={"q": query, "token": "wrong"}
    )
    assert denied.status_code == 404

    allowed = client.get(
        "/api/ranking/debug", params={"q": query, "token": "debug-secret"}
    )
    assert allowed.status_code == 200
    data = allowed.json()
    assert data["query_norm"] == clicks.normalize_query(query)
    assert "click_half_life_days" in data["config"]
    assert "token_ttl_seconds" in data
