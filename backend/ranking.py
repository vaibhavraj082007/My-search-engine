"""Click-popularity ranking – normalisation, decay, and result ordering.

The provider order is the fallback. Result stats are loaded by ``clicks.py``
and passed in here, which keeps this module pure and easy to test.
"""

import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ── Tunable ranking configuration ───────────────────────────────────────────
CLICK_HALF_LIFE_DAYS = max(
    0.1, float(os.getenv("CLICK_HALF_LIFE_DAYS", "30"))
)

# Expected click-through rate by displayed position. A click at a lower
# position is worth more because it had less natural exposure. The weight is
# capped so a very low position cannot dominate the ranking.
POSITION_CTR = {
    1: 1.00,
    2: 0.88,
    3: 0.77,
    4: 0.67,
    5: 0.58,
    6: 0.50,
    7: 0.43,
    8: 0.37,
    9: 0.32,
    10: 0.28,
}
POSITION_CTR_FALLBACK = 0.20
MAX_POSITION_WEIGHT = max(1.0, float(os.getenv("MAX_POSITION_WEIGHT", "5")))

# Bayesian-style smoothing: (weighted_clicks + a*prior) / (impressions + b).
# A brand-new result with one click cannot outrank a result with many clicks.
PRIOR_CLICKS = max(0.0, float(os.getenv("RANK_PRIOR_CLICKS", "1")))
PRIOR_CLICK_RATE = max(
    0.0, min(1.0, float(os.getenv("RANK_PRIOR_CLICK_RATE", "0.05")))
)
PRIOR_IMPRESSIONS = max(
    0.0, float(os.getenv("RANK_PRIOR_IMPRESSIONS", "10"))
)

# Tiny boost for URLs that are popular across all queries but have no
# query-specific data yet.
GLOBAL_BOOST_WEIGHT = max(
    0.0, float(os.getenv("RANK_GLOBAL_BOOST_WEIGHT", "0.002"))
)
GLOBAL_BOOST_REFERENCE_CLICKS = max(
    1.0, float(os.getenv("RANK_GLOBAL_BOOST_REFERENCE_CLICKS", "100"))
)

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "mkt_tok",
    "yclid",
    "_hsenc",
    "_hsmi",
    "vero_id",
    "wickedid",
}
_TRACKING_PREFIXES = ("utm_",)


def normalize_query(query: str) -> str:
    """Canonical query key: NFKC, casefold, punctuation-free, single-spaced.

    "NMIMS", "nmims", and "N.M.I.M.S" all become "nmims".
    """
    text = unicodedata.normalize("NFKC", query or "").casefold()
    text = "".join(
        ch for ch in text if not unicodedata.category(ch).startswith("P")
    )
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url: str) -> str:
    """Canonical URL key, used only for learning and comparison.

    Lowercases the host, drops "www.", tracking parameters, fragments, default
    ports, and trailing slashes, sorts the remaining query, and maps http/https
    to one key. The original URL is still the one users open.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"}:
        return ""

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""

    try:
        port = parts.port
    except ValueError:
        port = None
    default_port = 443 if parts.scheme.lower() == "https" else 80
    netloc = f"[{host}]" if ":" in host else host
    if port and port != default_port:
        netloc = f"{netloc}:{port}"

    path = (parts.path or "").rstrip("/")

    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key in _TRACKING_PARAMS:
            continue
        if any(lower_key.startswith(prefix) for prefix in _TRACKING_PREFIXES):
            continue
        query_pairs.append((key, value))
    query_pairs.sort(key=lambda pair: (pair[0], pair[1]))

    return urlunsplit(
        ("https", netloc, path, urlencode(query_pairs, doseq=False), "")
    )


def _parse_when(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decay_factor(last_seen, now: datetime | None = None) -> float:
    """Exponential decay for a half-life of CLICK_HALF_LIFE_DAYS."""
    seen = _parse_when(last_seen)
    if seen is None:
        return 1.0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    days = max(0.0, (current - seen).total_seconds() / 86400.0)
    return math.pow(0.5, days / CLICK_HALF_LIFE_DAYS)


def position_weight(position: int) -> float:
    """Relative value of a click at ``position`` (1-based), capped."""
    try:
        pos = max(1, int(position))
    except (TypeError, ValueError):
        pos = 1
    expected = POSITION_CTR.get(pos, POSITION_CTR_FALLBACK)
    if expected <= 0:
        expected = POSITION_CTR_FALLBACK
    return min(MAX_POSITION_WEIGHT, POSITION_CTR[1] / expected)


def popularity_score(stats: dict | None, now: datetime | None = None) -> float:
    """Smoothed, position-corrected, time-decayed popularity for one result."""
    if not stats:
        return 0.0

    clicks = int(stats.get("clicks") or 0)
    impressions = max(0.0, float(stats.get("impressions") or 0.0))
    anchor = stats.get("last_decayed_at") or stats.get("last_clicked_at")

    # ``decayed_clicks`` is already position-weighted and is kept decayed to
    # ``last_decayed_at``. Older rows and hand-built stats may only have the
    # cumulative column, so fall back to decaying that from the last click.
    weighted = float(stats.get("decayed_clicks") or 0.0)
    if weighted <= 0:
        weighted = float(stats.get("position_weighted_clicks") or 0.0)
    if weighted > 0:
        weighted *= decay_factor(anchor, now)

    score = 0.0
    if clicks > 0 and weighted > 0:
        score = (
            weighted + PRIOR_CLICKS * PRIOR_CLICK_RATE
        ) / (impressions + PRIOR_IMPRESSIONS)

    # A global boost only applies when this query has never seen the URL.
    if not stats.get("_has_query_stats"):
        global_clicks = max(0.0, float(stats.get("global_clicks") or 0.0))
        if global_clicks > 0:
            score += GLOBAL_BOOST_WEIGHT * min(
                1.0,
                math.log1p(global_clicks)
                / math.log1p(GLOBAL_BOOST_REFERENCE_CLICKS),
            )

    return score


def rank_items(
    items: list[dict],
    stats_by_url: dict[str, dict] | None,
    kind: str,
    token_factory=None,
) -> list[dict]:
    """Return a ranked copy of ``items`` with debug/ranking metadata."""
    if not isinstance(items, list):
        return []
    stats_by_url = stats_by_url or {}
    scored = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        key = normalize_url(url)
        stats = stats_by_url.get(key) if key else None
        score = popularity_score(stats)
        enriched = dict(item)
        enriched["popularity_score"] = round(score, 6)
        enriched["click_count"] = int(stats.get("clicks") or 0) if stats else 0
        enriched["rank_source"] = (
            "clicks" if enriched["click_count"] > 0 else "default"
        )
        scored.append((score, index, enriched))

    # Python's sort is stable; the original provider index is the fallback
    # for cold-start results and ties.
    scored.sort(key=lambda row: (-row[0], row[1]))

    ranked = []
    for position, (_, _, item) in enumerate(scored, start=1):
        item["click_position"] = position
        if token_factory and item.get("url"):
            item["click_token"] = token_factory(kind, item["url"], position)
        ranked.append(item)
    return ranked


def rank_payload(
    payload: dict,
    query: str,
    stats_by_kind: dict[str, dict[str, dict]] | None = None,
    token_factory=None,
) -> dict:
    """Rank web, video, and news results without mutating the cached payload."""
    if not payload:
        return payload

    stats_by_kind = stats_by_kind or {}
    ranked = dict(payload)

    ranked["results"] = rank_items(
        payload.get("results") or [],
        stats_by_kind.get("web"),
        "web",
        token_factory,
    )
    if "videos" in payload:
        ranked["videos"] = rank_items(
            payload.get("videos") or [],
            stats_by_kind.get("video"),
            "video",
            token_factory,
        )
    if "news" in payload:
        ranked["news"] = rank_items(
            payload.get("news") or [],
            stats_by_kind.get("news"),
            "news",
            token_factory,
        )

    # The answer and Wikipedia cards are tracked separately. Their clicks use
    # a different stats namespace, so they can never outrank web links.
    for kind, key in (("answer", "answer"), ("wiki", "wikipedia")):
        item = payload.get(key)
        if isinstance(item, dict):
            enriched = dict(item)
            enriched["click_position"] = 1
            if token_factory and enriched.get("url"):
                enriched["click_token"] = token_factory(kind, enriched["url"], 1)
            ranked[key] = enriched

    return ranked


def config_snapshot() -> dict:
    """Small diagnostic view for the protected ranking debug endpoint."""
    return {
        "click_half_life_days": CLICK_HALF_LIFE_DAYS,
        "position_ctr": dict(POSITION_CTR),
        "position_ctr_fallback": POSITION_CTR_FALLBACK,
        "max_position_weight": MAX_POSITION_WEIGHT,
        "prior_clicks": PRIOR_CLICKS,
        "prior_click_rate": PRIOR_CLICK_RATE,
        "prior_impressions": PRIOR_IMPRESSIONS,
        "global_boost_weight": GLOBAL_BOOST_WEIGHT,
        "global_boost_reference_clicks": GLOBAL_BOOST_REFERENCE_CLICKS,
    }
