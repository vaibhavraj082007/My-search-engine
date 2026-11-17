"""Trending News ingestion, ranking, snapshots and API behaviour."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import random
import string

import feedparser
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import news
from backend.news_ranking import cluster_items, items_from_feed, normalize_url, select_trending
from backend.news_sources import FeedSource

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def make_item(
    index: int,
    category: str = "world",
    source: str | None = None,
    title: str | None = None,
    age_minutes: int = 0,
) -> dict:
    return {
        "url": f"https://publisher{index % 12}.example/story-{index}",
        "url_norm": f"https://publisher{index % 12}.example/story-{index}",
        "title": title or " ".join(
            "".join(random.choices(string.ascii_lowercase, k=10))
            for _ in range(4)
        ),
        "summary": f"Summary {index}",
        "image_url": "",
        "source": source or f"Publisher {index % 10}",
        "source_weight": 0.8,
        "category": category,
        "published_at": NOW - timedelta(minutes=age_minutes),
        "fetched_at": NOW,
    }


@pytest.fixture
def news_client(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "DB_PATH", str(tmp_path / "news.db"))
    monkeypatch.setattr(news, "ensure_fresh_async", lambda: None)
    news.init_db()
    app = FastAPI()
    app.include_router(news.router)
    with TestClient(app) as client:
        yield client


def _store(items: list[dict], when: datetime = NOW) -> int:
    return news._store_snapshot(items, when)


def test_news_count_target_is_at_least_25():
    assert 25 <= news.NEWS_COUNT <= 50


def test_select_trending_returns_25_diverse_unique_stories():
    categories = ["india", "world", "technology", "business", "science", "sports"]
    items = [
        make_item(
            index,
            category=categories[index % len(categories)],
            source=f"Publisher {index % 12}",
            age_minutes=index * 7,
        )
        for index in range(48)
    ]

    selected = select_trending(items, count=25, now=NOW, max_age_hours=48)

    assert len(selected) == 25
    urls = [item["url_norm"] for item in selected]
    assert len(urls) == len(set(urls))
    assert len({item["category"] for item in selected}) >= 5

    source_counts: dict[str, int] = {}
    for item in selected:
        source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1
        assert "_title_norm" not in item
        assert "_tokens" not in item
        assert "_novelty" not in item
    assert max(source_counts.values()) <= 3


def test_cluster_items_merges_the_same_story_from_multiple_outlets():
    items = [
        make_item(
            0,
            source="BBC News",
            title="Massive storm hits the southern coast tonight",
            age_minutes=5,
        ),
        make_item(
            1,
            source="The Guardian",
            title="Massive storm hits southern coast tonight",
            age_minutes=8,
        ),
        make_item(
            2,
            source="Al Jazeera",
            title="Massive storm hits the southern coast tonight",
            age_minutes=10,
        ),
        make_item(3, source="NPR", title="A completely different science report"),
    ]

    clusters = cluster_items(items, now=NOW)
    storm = [item for item in clusters if "storm" in item["title"]]
    assert len(storm) == 1
    assert storm[0]["distinct_sources"] == 3
    assert storm[0]["cluster_size"] == 3


def test_items_from_feed_cleans_html_and_drops_unsafe_or_undated_entries():
    fresh = format_datetime(NOW - timedelta(hours=1))
    old = format_datetime(NOW - timedelta(days=10))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <title>Example publisher</title>
      <item>
        <title>Test &amp; story</title>
        <link>https://example.com/a?utm_source=newsletter&amp;id=1</link>
        <description><![CDATA[<p>Hello <b>world</b></p><img src="https://example.com/i.jpg">]]></description>
        <pubDate>{fresh}</pubDate>
      </item>
      <item>
        <title>No date</title>
        <link>https://example.com/no-date</link>
      </item>
      <item>
        <title>Unsafe scheme</title>
        <link>javascript:alert(1)</link>
        <pubDate>{fresh}</pubDate>
      </item>
      <item>
        <title>Too old</title>
        <link>https://example.com/old</link>
        <pubDate>{old}</pubDate>
      </item>
    </channel></rss>"""
    parsed = feedparser.parse(xml)
    source = FeedSource("Example publisher", "https://example.com/feed", "world", 0.9)

    items = items_from_feed(parsed, source, now=NOW, max_age_hours=48)

    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Test & story"
    assert item["summary"] == "Hello world"
    assert item["url_norm"] == "https://example.com/a?id=1"
    assert item["image_url"] == "https://example.com/i.jpg"
    assert item["source"] == "Example publisher"


def test_normalize_url_rejects_unsafe_schemes_and_strips_tracking():
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("ftp://example.com/file") == ""
    assert (
        normalize_url("https://Example.com/a/?utm_source=x&b=2&a=1#frag")
        == "https://example.com/a?a=1&b=2"
    )


def test_snapshot_api_returns_25_items_and_filters_categories(news_client):
    items = [
        make_item(
            index,
            category="technology" if index % 3 == 0 else "world",
            age_minutes=index,
        )
        for index in range(36)
    ]
    _store(items)

    response = news_client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 25
    assert data["updated_at"]
    assert data["next_refresh_at"]
    assert all(item["url"].startswith("https://") for item in data["items"])

    tech = news_client.get("/api/news", params={"category": "technology", "limit": 5})
    assert tech.status_code == 200
    tech_items = tech.json()["items"]
    assert 1 <= len(tech_items) <= 5
    assert all(item["category"] == "technology" for item in tech_items)

    assert news_client.get("/api/news", params={"category": "fashion"}).status_code == 400


def test_news_api_etag_and_304(news_client):
    _store([make_item(index) for index in range(30)])

    first = news_client.get("/api/news")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag

    cached = news_client.get("/api/news", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == etag


def test_empty_news_api_returns_a_clear_message_not_fake_stories(news_client):
    response = news_client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["updated_at"] is None
    assert "unavailable" in data["message"].lower()


def test_stale_snapshot_triggers_background_revalidation(monkeypatch, news_client):
    calls: list[str] = []
    monkeypatch.setattr(news, "ensure_fresh_async", lambda: calls.append("refresh"))

    _store([make_item(index) for index in range(30)])
    news_client.get("/api/news")
    assert calls == []

    old = news._now() - timedelta(hours=news.NEWS_REFRESH_HOURS + 1)
    conn = news._get_db()
    conn.execute(
        "UPDATE news_snapshots SET created_at = ?",
        (old.isoformat(),),
    )
    conn.commit()
    conn.close()
    assert news.needs_refresh() is True

    news_client.get("/api/news")
    assert calls == ["refresh"]


def test_store_snapshot_keeps_the_previous_snapshot_on_a_thin_refresh(news_client):
    _store([make_item(index) for index in range(30)])
    assert len(news.get_snapshot("all", 50)["items"]) == 30

    # A refresh with fewer than the promised 25 stories must never replace a
    # good snapshot (and must never become the public news feed).
    with pytest.raises(ValueError):
        _store([make_item(index) for index in range(12)])

    assert len(news.get_snapshot("all", 50)["items"]) == 30


def test_refresh_endpoint_requires_the_configured_token(news_client, monkeypatch):
    monkeypatch.delenv("NEWS_ADMIN_TOKEN", raising=False)
    assert news_client.post("/api/news/refresh").status_code == 403

    monkeypatch.setenv("NEWS_ADMIN_TOKEN", "news-secret")
    assert news_client.post("/api/news/refresh").status_code == 403
    assert (
        news_client.post(
            "/api/news/refresh", headers={"X-News-Token": "wrong"}
        ).status_code == 403
    )

    async def fake_refresh(force: bool = False) -> dict:
        assert force is True
        return {"status": "ok", "items": 25}

    monkeypatch.setattr(news, "refresh_news", fake_refresh)

    allowed = news_client.post(
        "/api/news/refresh", headers={"Authorization": "Bearer news-secret"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "ok"


def test_news_api_does_not_consume_guest_quota(news_client):
    _store([make_item(index) for index in range(30)])
    response = news_client.get(
        "/api/news",
        cookies={"guest_searches": "999"},
    )
    assert response.status_code == 200
    assert "guest_searches" not in response.cookies


def test_news_limit_is_capped_at_50(news_client):
    assert news_client.get("/api/news", params={"limit": 51}).status_code == 422
