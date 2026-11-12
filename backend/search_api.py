"""Search API – real web search, answers, videos, and news.

Designed for high request volume:
  * async I/O with one pooled HTTP client per worker
  * shared TTL cache + single-flight so popular queries hit upstream once
  * bounded upstream concurrency and per-request timeouts
  * HTML/RSS fallbacks when a provider is rate-limited
"""

import asyncio
import os
import re
import traceback
import uuid
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from . import searchdb
from .answers import (
    build_answer,
    get_http_client,
    get_instant_answer,
    get_videos,
    get_wikipedia,
    get_wiktionary,
)
from .auth import get_current_user
from .cache import cache

router = APIRouter()

# Simple regex: has a "." but no spaces → treat as URL
_URL_PATTERN = re.compile(r"^[^\s]+\.[^\s]+$")
_WHITESPACE = re.compile(r"\s+")

GUEST_SEARCH_LIMIT = 4

SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "300"))
SEARCH_CONCURRENCY = int(os.getenv("SEARCH_CONCURRENCY", "64"))
SEARCH_QUEUE_TIMEOUT = float(os.getenv("SEARCH_QUEUE_TIMEOUT", "5"))
SEARCH_TIMEOUT = float(os.getenv("SEARCH_TIMEOUT", "7"))
NEWS_TIMEOUT = float(os.getenv("NEWS_TIMEOUT", "6"))
META_TIMEOUT = float(os.getenv("META_TIMEOUT", "5"))
ANSWER_SOURCE_TIMEOUT = float(os.getenv("ANSWER_SOURCE_TIMEOUT", "4"))
VIDEO_TIMEOUT = float(os.getenv("VIDEO_TIMEOUT", "6"))
DDGS_CONCURRENCY = max(1, int(os.getenv("DDGS_CONCURRENCY", "6")))
DDGS_TIMEOUT = float(os.getenv("DDGS_TIMEOUT", "4"))
DISABLE_LOCAL_INDEX = os.getenv("DISABLE_LOCAL_INDEX", "0") == "1"

_search_semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)
_ddgs_semaphore = asyncio.Semaphore(DDGS_CONCURRENCY)

_HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _get_ddgs():
    """Return a DDGS instance using the best available package."""
    try:
        from ddgs import DDGS
        return DDGS()
    except Exception:
        from duckduckgo_search import DDGS
        return DDGS()


async def _run_ddgs(fn, *args):
    """Run a blocking DDGS call with a hard thread/concurrency bound.

    DDGS has no async API and no server-side timeout. Without these guards a
    burst of unique queries would exhaust the default thread pool and make
    every search wait on the slowest scrape.
    """
    try:
        async with _ddgs_semaphore:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), DDGS_TIMEOUT)
    except Exception:
        return []


# ── Web search ───────────────────────────────────────────────────────────

def _ddgs_web_search(query: str, max_results: int = 15, page: int = 1) -> list[dict]:
    """Fetch web results through the ddgs library (blocking, run in a thread)."""
    try:
        results = []
        with _get_ddgs() as ddgs:
            for r in ddgs.text(query, max_results=max_results, page=page):
                results.append({
                    "url":     r.get("href", ""),
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    except Exception:
        # DDGS raises on rate limits and empty result sets; this is expected
        # under load and already handled by the caller's fallbacks.
        return []


async def _html_web_search(query: str, max_results: int = 15) -> list[dict]:
    """Fallback: parse DuckDuckGo's lightweight HTML result page."""
    try:
        from bs4 import BeautifulSoup

        client = await get_http_client()
        response = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=10.0,
        )
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for block in soup.select(".result"):
            link = block.select_one(".result__a")
            if not link:
                continue
            href = link.get("href") or ""
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
            if not href.startswith("http"):
                continue
            snippet = block.select_one(".result__snippet")
            results.append({
                "url":     href,
                "title":   link.get_text(" ", strip=True),
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception:
        # DDGS raises on rate limits and empty result sets; this is expected
        # under load and already handled by the caller's fallbacks.
        return []


async def _bing_rss_web_search(query: str, max_results: int = 10, page: int = 1) -> list[dict]:
    """Fallback/supplement using Bing's RSS endpoint (stable, no JS)."""
    try:
        client = await get_http_client()
        response = await client.get(
            "https://www.bing.com/search",
            params={
                "q": query,
                "format": "rss",
                "cc": "us",
                "setlang": "en",
                "first": (page - 1) * 10 + 1,
            },
            timeout=10.0,
        )
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        results = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            if title and link.startswith("http"):
                results.append({
                    "url": link,
                    "title": title,
                    "snippet": description,
                })
            if len(results) >= max_results:
                break
        return results
    except Exception:
        # DDGS raises on rate limits and empty result sets; this is expected
        # under load and already handled by the caller's fallbacks.
        return []


def _merge_results(primary: list[dict], extra: list[dict], limit: int) -> list[dict]:
    merged = list(primary)
    seen = {_normalize_url(item.get("url", "")) for item in merged}
    for item in extra:
        key = _normalize_url(item.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


async def _web_search(query: str, max_results: int = 15, page: int = 1) -> list[dict]:
    """Web results with complementary fallbacks when a provider is limited."""
    results = await _run_ddgs(_ddgs_web_search, query, max_results, page)

    if len(results) < 5:
        extra = await _bing_rss_web_search(query, max_results, page)
        results = _merge_results(results, extra, max_results)

    if not results:
        results = await _html_web_search(query, max_results)

    return results[:max_results]


# ── News search ──────────────────────────────────────────────────────────

def _news_search_ddgs(query: str, max_results: int = 6) -> list[dict]:
    """Fetch recent news results with images (blocking, run in a thread)."""
    try:
        results = []
        with _get_ddgs() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "url":    r.get("url", ""),
                    "title":  r.get("title", ""),
                    "source": r.get("source", ""),
                    "date":   r.get("date", ""),
                    "image":  r.get("image", ""),
                    "body":   r.get("body", ""),
                })
        return results
    except Exception:
        # DDGS raises on rate limits and empty result sets; this is expected
        # under load and already handled by the caller's fallbacks.
        return []


def _unwrap_bing_link(url: str) -> str:
    if "bing.com/news/apiclick" in url:
        values = parse_qs(urlparse(url).query).get("url")
        if values:
            return values[0]
    return url


async def _bing_rss_news_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        client = await get_http_client()
        response = await client.get(
            "https://www.bing.com/news/search",
            params={"q": query, "format": "rss", "cc": "us", "setlang": "en"},
            timeout=10.0,
        )
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        results = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = _unwrap_bing_link((item.findtext("link") or "").strip())
            description = (item.findtext("description") or "").strip()

            date = ""
            raw_date = (item.findtext("pubDate") or "").strip()
            if raw_date:
                try:
                    date = parsedate_to_datetime(raw_date).isoformat()
                except Exception:
                    date = raw_date

            results.append({
                "url":    link,
                "title":  title,
                "source": (item.findtext("Source") or "").strip(),
                "date":   date,
                "image":  (item.findtext("Image") or "").strip(),
                "body":   description,
            })
            if len(results) >= max_results:
                break
        return results
    except Exception:
        # DDGS raises on rate limits and empty result sets; this is expected
        # under load and already handled by the caller's fallbacks.
        return []


async def _news_search(query: str, max_results: int = 6) -> list[dict]:
    results = await _run_ddgs(_news_search_ddgs, query, max_results)
    if len(results) < 3:
        extra = await _bing_rss_news_search(query, max_results)
        results = _merge_results(results, extra, max_results)
    return results[:max_results]


# ── Enrichment ───────────────────────────────────────────────────────────

async def _answer_meta(query: str):
    """Fetch Wikipedia, Wiktionary, and Instant Answer data independently.

    The Instant Answer endpoint is the least reliable of the three. Giving each
    source its own timeout means a slow fallback cannot discard a valid
    Wikipedia article or dictionary definition.
    """
    async def safe(coro, seconds: float = ANSWER_SOURCE_TIMEOUT):
        try:
            return await asyncio.wait_for(coro, timeout=seconds)
        except Exception:
            return None

    wiki, wiktionary, instant = await asyncio.gather(
        safe(get_wikipedia(query)),
        safe(get_wiktionary(query)),
        safe(get_instant_answer(query)),
    )
    return (
        wiki if isinstance(wiki, dict) else None,
        wiktionary if isinstance(wiktionary, dict) else None,
        instant if isinstance(instant, dict) else None,
    )


def _normalize_url(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/").lower()


def _clean_web_results(
    web_results: list[dict],
    wikipedia: dict | None,
    videos: list[dict],
) -> list[dict]:
    """Drop duplicates already shown in the answer, wiki, or video blocks."""
    wiki_key = _normalize_url(wikipedia["url"]) if wikipedia else ""
    video_keys = {_normalize_url(video["url"]) for video in videos}

    cleaned = []
    seen = set()
    for result in web_results:
        url = result.get("url") or ""
        key = _normalize_url(url)
        if not key or key in seen:
            continue
        if wiki_key and key == wiki_key:
            continue
        if key in video_keys:
            continue
        host = (urlparse(url).hostname or "").lower()
        if videos and (host.endswith("youtube.com") or host == "youtu.be"):
            continue
        seen.add(key)
        cleaned.append(result)
    return cleaned


async def _with_timeout(task: asyncio.Task, default, seconds: float):
    """Await a task but fall back to a default instead of failing the search."""
    try:
        return await asyncio.wait_for(task, timeout=seconds)
    except Exception:
        return default


async def _collect_payload(query: str, page: int) -> dict:
    web_task = asyncio.create_task(_web_search(query, 15, page))
    news_task = asyncio.create_task(_news_search(query, 6))
    meta_task = asyncio.create_task(_answer_meta(query))
    videos_task = asyncio.create_task(get_videos(query, 4))

    # Each source has its own budget. A slow or broken provider returns an
    # empty section instead of taking down the whole result page.
    web_results, news_results, meta, videos = await asyncio.gather(
        _with_timeout(web_task, [], SEARCH_TIMEOUT),
        _with_timeout(news_task, [], NEWS_TIMEOUT),
        _with_timeout(meta_task, (None, None, None), META_TIMEOUT),
        _with_timeout(videos_task, [], VIDEO_TIMEOUT),
    )

    wikipedia, wiktionary, instant = meta
    answer = build_answer(query, wikipedia, wiktionary, instant)
    web_results = _clean_web_results(web_results, wikipedia, videos)

    # Merge local index (bonus results)
    if not DISABLE_LOCAL_INDEX:
        try:
            local_data = await asyncio.to_thread(searchdb.search, query, page)
            seen_urls = {_normalize_url(r["url"]) for r in web_results}
            for local_result in local_data.get("results", []):
                key = _normalize_url(local_result["url"])
                if key and key not in seen_urls:
                    web_results.append(local_result)
                    seen_urls.add(key)
        except Exception:
            pass

    return {
        "results": web_results,
        "news":    news_results,
        "answer":  answer,
        "wikipedia": wikipedia,
        "videos":  videos,
        "total":   len(web_results),
        "page":    page,
        "limit_reached": False,
    }


async def _collect_payload_limited(query: str, page: int) -> dict:
    try:
        await asyncio.wait_for(_search_semaphore.acquire(), timeout=SEARCH_QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="Search is busy right now. Please try again in a moment.",
        )
    try:
        return await _collect_payload(query, page)
    finally:
        _search_semaphore.release()


def _has_content(payload: dict) -> bool:
    # Don't cache video-only or empty partial responses. They usually mean an
    # upstream was rate-limited, and caching them would keep the page thin for
    # every user until the TTL expires.
    return bool(
        payload.get("results")
        or payload.get("news")
        or payload.get("answer")
        or payload.get("wikipedia")
    )


def _cache_key(query: str, page: int) -> str:
    normalized = _WHITESPACE.sub(" ", query).strip().casefold()
    return f"8s:search:v1:{page}:{normalized}"


# ── Route ────────────────────────────────────────────────────────────────

@router.get("/api/search")
async def search(
    response: Response,
    q: str = Query("", min_length=0, max_length=400),
    page: int = Query(1, ge=1, le=10),
    session_token: str | None = Cookie(default=None),
    guest_id: str | None = Cookie(default=None),
    guest_searches: str | None = Cookie(default=None),
):
    query = q.strip()
    if not query:
        return {
            "results": [], "news": [], "answer": None, "wikipedia": None,
            "videos": [], "total": 0, "page": 1, "limit_reached": False,
        }

    user = await run_in_threadpool(get_current_user, session_token)
    is_guest = user is None

    # URL detection – navigate directly
    if _URL_PATTERN.match(query):
        url = query if query.startswith(("http://", "https://")) else f"https://{query}"
        return {"redirect": url}

    # Guest rate-limiting
    if is_guest:
        count = int(guest_searches or "0")
        if count >= GUEST_SEARCH_LIMIT:
            return {
                "results": [], "news": [], "answer": None, "wikipedia": None,
                "videos": [], "total": 0, "page": 1,
                "limit_reached": True,
                "message": "Please sign in for unlimited searches",
            }
        count += 1
        if not guest_id:
            guest_id = uuid.uuid4().hex
            response.set_cookie(key="guest_id", value=guest_id,
                                httponly=True, samesite="lax", max_age=86400, path="/")
        response.set_cookie(key="guest_searches", value=str(count),
                            httponly=False, samesite="lax", max_age=86400, path="/")

    try:
        payload, cache_hit = await cache.get_or_set(
            _cache_key(query, page),
            lambda: _collect_payload_limited(query, page),
            ttl=SEARCH_CACHE_TTL,
            should_cache=_has_content,
        )
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail="Search is temporarily unavailable. Please try again.",
        )

    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return payload
