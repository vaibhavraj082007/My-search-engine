"""Click storage, token, dedupe, and cleanup tests."""

import time
from datetime import datetime, timedelta, timezone

import pytest

from backend import clicks, ranking


def _record(
    query: str,
    url: str,
    kind: str = "web",
    session: str = "session-1",
    position: int = 1,
    title: str = "Result",
    created_at: str | None = None,
) -> bool:
    query_norm = ranking.normalize_query(query)
    return clicks._record_click(
        clicks._stats_query_key(query_norm, kind),
        ranking.normalize_url(url),
        title,
        position,
        clicks._hash_value("session:" + session),
        None,
        clicks._hash_value("ip:127.0.0.1"),
        clicks._hash_value("ua:test"),
        kind,
        created_at or clicks._iso(),
    )


def test_token_binds_query_url_kind_and_position(click_store):
    token = clicks.make_click_token(
        "NMIMS", "https://www.example.com/a?utm_source=x", "web", 5
    )
    assert clicks.verify_click_token(
        token, "nmims", "http://example.com/a/", "web", 5
    )
    assert not clicks.verify_click_token(
        token, "different query", "https://example.com/a", "web", 5
    )
    assert not clicks.verify_click_token(
        token, "nmims", "https://example.com/other", "web", 5
    )
    assert not clicks.verify_click_token(
        token, "nmims", "https://example.com/a", "video", 5
    )
    assert not clicks.verify_click_token(
        token, "nmims", "https://example.com/a", "web", 4
    )


def test_token_expires(click_store):
    token = clicks.make_click_token("q", "https://example.com", "web", 1)
    assert clicks.verify_click_token(
        token,
        "q",
        "https://example.com",
        "web",
        1,
        now=time.time() + clicks.CLICK_TOKEN_TTL_SECONDS + 5,
    ) is False


def test_dedupe_limits_same_session_to_one_click_per_hour(click_store):
    url = "https://dedupe.example/result"
    assert _record("dedupe query", url, session="same") is True
    assert _record("dedupe query", url, session="same") is False

    stats = clicks.fetch_stats(
        "dedupe query", {"web": [{"url": url}]}
    )
    row = stats["web"][ranking.normalize_url(url)]
    assert row["clicks"] == 1


def test_impressions_are_batched_and_fetched_per_kind(click_store):
    query = "batched impressions"
    clicks.record_impressions(
        query, [{"url": "https://web.example/a", "title": "Web"}], "web"
    )
    clicks.record_impressions(
        query, [{"url": "https://video.example/a", "title": "Video"}], "video"
    )
    clicks.flush_impressions()

    stats = clicks.fetch_stats(
        query,
        {
            "web": [{"url": "https://web.example/a"}],
            "video": [{"url": "https://video.example/a"}],
            "news": [{"url": "https://news.example/a"}],
        },
    )
    assert stats["web"][ranking.normalize_url("https://web.example/a")][
        "impressions"
    ] == 1
    assert stats["video"][ranking.normalize_url("https://video.example/a")][
        "impressions"
    ] == 1
    assert stats["news"][ranking.normalize_url("https://news.example/a")][
        "impressions"
    ] == 0


def test_answer_clicks_do_not_boost_web_stats(click_store):
    query = "separate kinds"
    url = "https://en.wikipedia.org/wiki/Example"
    assert _record(query, url, kind="answer", session="answer-session") is True

    stats = clicks.fetch_stats(
        query, {"web": [{"url": url}], "answer": [{"url": url}]}
    )
    assert stats["web"][ranking.normalize_url(url)]["clicks"] == 0
    assert stats["answer"][ranking.normalize_url(url)]["clicks"] == 1


def test_cleanup_deletes_old_events_and_decays_stats(click_store):
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    old_event = clicks._iso(now - timedelta(days=120))
    recent_event = clicks._iso(now - timedelta(days=2))
    old_clicked = clicks._iso(now - timedelta(days=100))
    old_decayed = clicks._iso(now - timedelta(days=30))

    conn = clicks._get_db()
    try:
        conn.execute(
            """
            INSERT INTO click_events (
                query_norm, url_norm, title, position, session_id,
                user_id, ip_hash, user_agent_hash, created_at
            )
            VALUES ('cleanup', 'https://old.example/a', 'Old', 1, 's1',
                    NULL, 'ip', 'ua', ?)
            """,
            (old_event,),
        )
        conn.execute(
            """
            INSERT INTO click_events (
                query_norm, url_norm, title, position, session_id,
                user_id, ip_hash, user_agent_hash, created_at
            )
            VALUES ('cleanup', 'https://recent.example/a', 'Recent', 1, 's2',
                    NULL, 'ip', 'ua', ?)
            """,
            (recent_event,),
        )
        conn.execute(
            """
            INSERT INTO result_stats (
                query_norm, url_norm, title, impressions, clicks,
                decayed_clicks, position_weighted_clicks,
                last_clicked_at, last_shown_at, last_decayed_at
            )
            VALUES ('cleanup', 'https://old.example/a', 'Old', 0, 1,
                    0.8, 0.8, ?, ?, ?)
            """,
            (old_clicked, old_clicked, old_decayed),
        )
        conn.execute(
            """
            INSERT INTO result_stats (
                query_norm, url_norm, title, impressions, clicks,
                decayed_clicks, position_weighted_clicks,
                last_clicked_at, last_shown_at, last_decayed_at
            )
            VALUES ('cleanup', 'https://shown.example/a', 'Shown', 3, 0,
                    0, 0, NULL, ?, NULL)
            """,
            (old_clicked,),
        )
        conn.commit()
    finally:
        conn.close()

    result = clicks.cleanup(now=now)

    assert result["click_events_deleted"] == 1
    assert result["stats_pruned"] == 1

    conn = clicks._get_db()
    try:
        events = conn.execute(
            "SELECT url_norm FROM click_events ORDER BY url_norm"
        ).fetchall()
        stats = conn.execute(
            """
            SELECT decayed_clicks FROM result_stats
             WHERE query_norm = 'cleanup' AND url_norm = 'https://old.example/a'
            """
        ).fetchone()
    finally:
        conn.close()

    assert [row["url_norm"] for row in events] == ["https://recent.example/a"]
    assert stats["decayed_clicks"] == pytest.approx(0.4, rel=0.01)
