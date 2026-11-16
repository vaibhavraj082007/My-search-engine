"""Pure ranking tests: normalisation, decay, position bias, and ordering."""

from datetime import datetime, timedelta, timezone

import pytest

from backend import ranking


def _stats(
    *,
    clicks_count=0,
    impressions=0,
    decayed=None,
    weighted=None,
    last_clicked=None,
    has_query_stats=True,
    global_clicks=0,
):
    stats = {
        "clicks": clicks_count,
        "impressions": impressions,
        "decayed_clicks": (
            float(decayed)
            if decayed is not None
            else float(weighted or 0.0)
        ),
        "position_weighted_clicks": float(weighted or 0.0),
        "last_clicked_at": last_clicked,
        "last_decayed_at": last_clicked,
        "_has_query_stats": has_query_stats,
        "global_clicks": global_clicks,
    }
    return stats


def test_normalize_query_variants():
    expected = "nmims"
    for value in ("NMIMS", "nmims", " N.M.I.M.S ", "N.M.I.M.S"):
        assert ranking.normalize_query(value) == expected


def test_normalize_query_collapses_whitespace_and_unicode():
    assert ranking.normalize_query("  Caffè   Latte  ") == "caffè latte"
    assert ranking.normalize_query("Ｆｕｌｌ－Ｗｉｄｔｈ") == "fullwidth"


def test_normalize_url_canonicalises_tracking_and_scheme():
    raw = (
        "HTTP://WWW.Example.com:80/Path/?utm_source=newsletter"
        "&b=2&a=1#section"
    )
    assert ranking.normalize_url(raw) == "https://example.com/Path?a=1&b=2"
    assert (
        ranking.normalize_url("https://example.com/")
        == ranking.normalize_url("http://www.example.com")
    )


def test_normalize_url_keeps_non_tracking_query_and_path():
    assert (
        ranking.normalize_url("https://example.com/search?q=hello")
        == "https://example.com/search?q=hello"
    )


def test_decay_halves_every_half_life():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert ranking.decay_factor(now - timedelta(days=30), now) == pytest.approx(0.5)
    assert ranking.decay_factor(now - timedelta(days=60), now) == pytest.approx(0.25)
    assert ranking.decay_factor(None, now) == 1.0


def test_position_weight_rewards_lower_positions_and_is_capped():
    assert ranking.position_weight(1) == pytest.approx(1.0)
    assert ranking.position_weight(8) > ranking.position_weight(1)
    assert ranking.position_weight(100) == pytest.approx(ranking.MAX_POSITION_WEIGHT)


def test_smoothing_stops_one_click_beating_many():
    one_click = _stats(
        clicks_count=1,
        impressions=1,
        weighted=ranking.position_weight(8),
    )
    many_clicks = _stats(
        clicks_count=50,
        impressions=100,
        weighted=50.0,
    )
    assert ranking.popularity_score(one_click) < ranking.popularity_score(many_clicks)


def test_cold_start_preserves_provider_order():
    items = [
        {"url": "https://a.example/one"},
        {"url": "https://b.example/two"},
        {"url": "https://c.example/three"},
    ]
    ranked = ranking.rank_items(items, {}, "web")
    assert [item["url"] for item in ranked] == [item["url"] for item in items]
    assert [item["click_position"] for item in ranked] == [1, 2, 3]
    assert all(item["rank_source"] == "default" for item in ranked)


def test_most_clicked_result_is_first():
    items = [
        {"url": "https://a.example/one"},
        {"url": "https://b.example/two"},
        {"url": "https://c.example/three"},
    ]
    stats = {
        ranking.normalize_url("https://b.example/two"): _stats(
            clicks_count=5, impressions=20, weighted=5.0
        ),
        ranking.normalize_url("https://c.example/three"): _stats(
            clicks_count=2, impressions=20, weighted=2.0
        ),
    }
    ranked = ranking.rank_items(items, stats, "web")
    assert [item["url"] for item in ranked] == [
        "https://b.example/two",
        "https://c.example/three",
        "https://a.example/one",
    ]
    assert [item["rank_source"] for item in ranked] == [
        "clicks", "clicks", "default"
    ]


def test_global_boost_only_applies_without_query_stats():
    global_only = _stats(has_query_stats=False, global_clicks=1000)
    no_data = None
    assert ranking.popularity_score(global_only) > ranking.popularity_score(no_data)
    assert ranking.popularity_score(global_only) <= ranking.GLOBAL_BOOST_WEIGHT

    seen_but_never_clicked = _stats(has_query_stats=True, global_clicks=1000)
    assert ranking.popularity_score(seen_but_never_clicked) == 0.0


def test_rank_payload_ranks_videos_and_news_too():
    payload = {
        "results": [],
        "videos": [
            {"url": "https://video.example/one"},
            {"url": "https://video.example/two"},
        ],
        "news": [
            {"url": "https://news.example/one"},
            {"url": "https://news.example/two"},
        ],
    }
    stats = {
        "video": {
            ranking.normalize_url("https://video.example/two"): _stats(
                clicks_count=3, impressions=5, weighted=3.0
            )
        },
        "news": {
            ranking.normalize_url("https://news.example/two"): _stats(
                clicks_count=2, impressions=5, weighted=2.0
            )
        },
    }
    ranked = ranking.rank_payload(payload, "anything", stats)
    assert ranked["videos"][0]["url"] == "https://video.example/two"
    assert ranked["news"][0]["url"] == "https://news.example/two"


def test_rank_payload_does_not_mutate_cached_payload():
    payload = {
        "results": [
            {"url": "https://a.example/one", "title": "One"},
            {"url": "https://b.example/two", "title": "Two"},
        ],
        "videos": [],
        "news": [],
        "answer": None,
        "wikipedia": None,
    }
    original = [dict(item) for item in payload["results"]]
    stats = {
        "web": {
            ranking.normalize_url("https://b.example/two"): _stats(
                clicks_count=1, impressions=1, weighted=2.0
            )
        }
    }
    ranked = ranking.rank_payload(
        payload,
        "query",
        stats,
        token_factory=lambda kind, url, position: "token",
    )
    assert [item["url"] for item in ranked["results"]] == [
        "https://b.example/two",
        "https://a.example/one",
    ]
    assert payload["results"] == original
    assert "click_token" not in payload["results"][0]
    assert ranked["results"][0]["click_token"] == "token"
