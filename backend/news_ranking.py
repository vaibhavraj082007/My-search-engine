"""Cleaning, de-duplication, clustering and trending ranking for real news.

The ranking is intentionally explainable:
  * recency decays with a 12-hour half-life
  * a story covered by more distinct outlets gets a strong boost
  * reputable sources keep a modest weight
  * a small novelty bonus makes the next six-hour snapshot visibly fresh

No article bodies are stored. Only the feed-provided headline, summary, image,
publisher, category and canonical article URL survive this module.
"""

import calendar
import hashlib
import html
import math
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .news_sources import CATEGORIES

_WHITESPACE = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_IMAGE_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "has", "have", "he", "her", "his", "how", "in", "into", "is",
    "it", "its", "may", "more", "new", "not", "of", "on", "or", "our",
    "over", "said", "says", "she", "that", "the", "their", "them", "there",
    "these", "they", "this", "to", "was", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "you", "your", "after", "before",
    "about", "amid", "against", "could", "would", "should", "than", "then",
}
_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "igshid", "mc_cid", "mc_eid", "mkt_tok",
    "cmpid", "ocid", "ref", "referrer", "source", "spm", "yclid",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "ns_", "at_")


def clean_text(value, limit: int | None = None) -> str:
    """Strip tags/entities, collapse whitespace and optionally truncate."""
    if not value:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        try:
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def truncate_summary(value: str, limit: int = 400) -> str:
    """Trim to a sentence boundary when possible, otherwise a word boundary."""
    text = clean_text(value)
    if len(text) <= limit:
        return text
    window = text[:limit].rstrip()
    sentence = _SENTENCE_END.split(window)
    if len(sentence) > 1:
        candidate = " ".join(sentence[:-1]).strip()
        if len(candidate) >= 80:
            return candidate
    if " " in window:
        window = window.rsplit(" ", 1)[0]
    return window.rstrip(" ,;:-") + "…"


def normalize_url(value: str) -> str:
    """Canonical http(s) URL with fragments and tracking parameters removed."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    try:
        parts = urlsplit(raw)
    except Exception:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host
    if port and port not in (80, 443):
        netloc += f":{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in _TRACKING_PARAMS or lowered.startswith(_TRACKING_PREFIXES):
            continue
        query.append((key, item))
    query.sort()
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def _entry_value(entry, key: str):
    if hasattr(entry, "get"):
        return entry.get(key)
    try:
        return entry[key]
    except Exception:
        return None


def _published_at(entry, now: datetime) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = _entry_value(entry, key)
        if value:
            try:
                stamp = calendar.timegm(value)
                return datetime.fromtimestamp(stamp, tz=timezone.utc)
            except Exception:
                pass
    raw = (
        _entry_value(entry, "published")
        or _entry_value(entry, "updated")
        or _entry_value(entry, "created")
    )
    if raw:
        try:
            text = str(raw).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            try:
                from email.utils import parsedate_to_datetime

                parsed = parsedate_to_datetime(str(raw))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except Exception:
                pass
    return None


def _first_image(entry, summary_html: str) -> str:
    candidates: list[str] = []

    for key in ("media_content", "media_thumbnail"):
        value = _entry_value(entry, key) or []
        if isinstance(value, dict):
            value = [value]
        if isinstance(value, list):
            for media in value:
                if isinstance(media, dict):
                    if media.get("url"):
                        candidates.append(str(media["url"]))
                    elif media.get("href"):
                        candidates.append(str(media["href"]))

    image = _entry_value(entry, "image")
    if isinstance(image, dict):
        candidates.extend(str(image.get(key) or "") for key in ("href", "url"))

    for key in ("links", "enclosures"):
        value = _entry_value(entry, key) or []
        if isinstance(value, dict):
            value = [value]
        if isinstance(value, list):
            for link in value:
                if not isinstance(link, dict):
                    continue
                href = link.get("href") or link.get("url") or ""
                media_type = (link.get("type") or "").lower()
                if href and (media_type.startswith("image/") or key == "enclosures"):
                    candidates.append(str(href))

    if summary_html:
        match = _IMAGE_SRC.search(summary_html)
        if match:
            candidates.append(html.unescape(match.group(1)))

    for candidate in candidates:
        candidate = candidate.strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        parts = urlsplit(candidate)
        if parts.scheme in {"http", "https"} and parts.netloc:
            return candidate
    return ""


def items_from_feed(parsed, feed, now: datetime | None = None, max_age_hours: int = 72) -> list[dict]:
    """Convert one parsed feed into clean, age-bounded items."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    items: list[dict] = []
    entries = getattr(parsed, "entries", None) or []
    for entry in entries:
        title = clean_text(_entry_value(entry, "title"), limit=300)
        link = _entry_value(entry, "link") or ""
        if not title or not link:
            continue
        url_norm = normalize_url(str(link))
        if not url_norm:
            continue
        published = _published_at(entry, now)
        if published is None:
            # Undated items could be old. Showing them as fresh would fake
            # recency, so they are dropped.
            continue
        if published > now + timedelta(hours=6):
            published = now
        if published < cutoff:
            continue

        raw_summary = (
            _entry_value(entry, "summary")
            or _entry_value(entry, "description")
            or ""
        )
        content = _entry_value(entry, "content")
        if not raw_summary and isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                raw_summary = first.get("value") or ""
        summary = truncate_summary(str(raw_summary), 400)
        image = _first_image(entry, str(raw_summary))
        category = feed.category if feed.category in CATEGORIES else "world"
        items.append(
            {
                "url": url_norm,
                "url_norm": url_norm,
                "title": title,
                "summary": summary,
                "image_url": image,
                "source": feed.name,
                "source_weight": float(feed.weight),
                "category": category,
                "published_at": published,
                "fetched_at": now,
            }
        )
    return items


def dedupe_items(items: list[dict]) -> list[dict]:
    """Keep the richest item for each canonical URL."""
    best: dict[str, dict] = {}
    for item in items:
        key = item.get("url_norm") or normalize_url(item.get("url", ""))
        if not key:
            continue
        item["url_norm"] = key
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        current_key = (
            1 if current.get("image_url") else 0,
            len(current.get("summary") or ""),
            current.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
        )
        item_key = (
            1 if item.get("image_url") else 0,
            len(item.get("summary") or ""),
            item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
        )
        if item_key > current_key:
            best[key] = item
    return list(best.values())


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.casefold())
    return {word for word in words if len(word) > 1 and word not in _STOPWORDS}


def _comparable_title(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.casefold()))


def _same_story(first: dict, second: dict) -> bool:
    a = first.get("_title_norm") or _comparable_title(first.get("title", ""))
    b = second.get("_title_norm") or _comparable_title(second.get("title", ""))
    if not a or not b:
        return False
    if a == b:
        return True
    tokens_a = first.get("_tokens") or _title_tokens(first.get("title", ""))
    tokens_b = second.get("_tokens") or _title_tokens(second.get("title", ""))
    if len(tokens_a) < 2 or len(tokens_b) < 2:
        return False
    ratio = SequenceMatcher(None, a, b).ratio()
    shared = tokens_a & tokens_b
    jaccard = len(shared) / max(1, len(tokens_a | tokens_b))
    if ratio >= 0.68:
        return True
    if ratio >= 0.52 and jaccard >= 0.52 and len(shared) >= 2:
        return True
    return jaccard >= 0.78 and len(shared) >= 3


def cluster_items(items: list[dict], now: datetime | None = None) -> list[dict]:
    """Group near-duplicate stories and choose one representative per cluster."""
    now = now or datetime.now(timezone.utc)
    ordered = sorted(
        items,
        key=lambda item: item.get("published_at") or now,
        reverse=True,
    )
    clusters: list[dict] = []
    for item in ordered:
        item["_title_norm"] = _comparable_title(item.get("title", ""))
        item["_tokens"] = _title_tokens(item.get("title", ""))
        match = None
        for cluster in clusters:
            if _same_story(item, cluster["representative"]):
                match = cluster
                break
        if match is None:
            clusters.append({"items": [item], "representative": item})
        else:
            match["items"].append(item)

    out = []
    for cluster in clusters:
        members = cluster["items"]
        representative = max(
            members,
            key=lambda item: (
                1 if item.get("image_url") else 0,
                float(item.get("source_weight") or 0),
                item.get("published_at") or now,
                len(item.get("summary") or ""),
            ),
        )
        distinct_sources = len({(item.get("source") or "").casefold() for item in members})
        age_hours = max(
            0.0,
            (now - (representative.get("published_at") or now)).total_seconds() / 3600,
        )
        recency = 0.5 ** (age_hours / 12.0)
        coverage = math.log2(1 + distinct_sources)
        score = (
            3.2 * recency
            + 2.6 * coverage
            + 0.5 * float(representative.get("source_weight") or 0)
            + (0.2 if representative.get("image_url") else 0.0)
        )
        cluster_id = hashlib.sha1(
            (representative.get("_title_norm") or representative.get("title", "")).encode("utf-8")
        ).hexdigest()[:16]
        representative = dict(representative)
        representative.update(
            {
                "cluster_id": cluster_id,
                "cluster_size": len(members),
                "distinct_sources": distinct_sources,
                "score": round(score, 6),
                "members": members,
            }
        )
        out.append(representative)
    return out


def select_trending(
    items: list[dict],
    count: int = 25,
    previous_urls: set[str] | None = None,
    now: datetime | None = None,
    max_age_hours: int = 72,
) -> list[dict]:
    """Pick a diverse top-N with a hard three-stories-per-source cap."""
    now = now or datetime.now(timezone.utc)
    previous_urls = previous_urls or set()
    cutoff = now - timedelta(hours=max_age_hours)
    fresh = [
        item for item in items
        if (item.get("published_at") or now) >= cutoff
    ]
    if not fresh:
        return []

    count = max(1, int(count))
    clusters = cluster_items(dedupe_items(fresh), now=now)
    for item in clusters:
        item["_novelty"] = 0.10 if item.get("url_norm") not in previous_urls else 0.0
    clusters.sort(
        key=lambda item: (
            float(item.get("score") or 0) + item.get("_novelty", 0.0),
            item.get("published_at") or now,
        ),
        reverse=True,
    )

    selected: list[dict] = []
    source_counts: dict[str, int] = {}
    selected_urls: set[str] = set()

    def take(item: dict) -> bool:
        if not item or item.get("url_norm") in selected_urls:
            return False
        source = (item.get("source") or "").casefold()
        if source_counts.get(source, 0) >= 3:
            return False
        selected.append(item)
        selected_urls.add(item.get("url_norm"))
        source_counts[source] = source_counts.get(source, 0) + 1
        return True

    # The single best story is the large hero card.
    if clusters:
        take(clusters[0])

    # First pass: one story per category, repeatedly, so the feed does not
    # collapse into a single topic.
    while len(selected) < count:
        added = False
        for category in CATEGORIES:
            if category == "all":
                continue
            candidate = next(
                (
                    item for item in clusters
                    if item.get("category") == category
                    and item.get("url_norm") not in selected_urls
                    and source_counts.get((item.get("source") or "").casefold(), 0) < 3
                ),
                None,
            )
            if candidate and take(candidate):
                added = True
                if len(selected) >= count:
                    break
        if not added:
            break

    # Fill any remaining slots in pure score order (still respecting the cap).
    if len(selected) < count:
        for item in clusters:
            take(item)
            if len(selected) >= count:
                break

    # Strip private ranking helpers before the items reach storage/API.
    for item in selected:
        item.pop("_title_norm", None)
        item.pop("_tokens", None)
        item.pop("_novelty", None)
        item.pop("members", None)
    return selected
