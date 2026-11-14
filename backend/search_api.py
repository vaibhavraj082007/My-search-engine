"""Search API – real web search, answers, videos, and news.

Designed for high request volume:
  * async I/O with one pooled HTTP client per worker
  * shared TTL cache + single-flight so popular queries hit upstream once
  * bounded upstream concurrency and per-request timeouts
  * HTML/RSS fallbacks when a provider is rate-limited
"""

import asyncio
import html
import os
import re
import traceback
import uuid
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, unquote, urlparse

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

RESULTS_PER_PAGE = max(1, min(10, int(os.getenv("RESULTS_PER_PAGE", "10"))))
MAX_SEARCH_PAGE = max(1, int(os.getenv("MAX_SEARCH_PAGE", "10")))
UPSTREAM_RESULTS_PER_PAGE = max(
    RESULTS_PER_PAGE, int(os.getenv("UPSTREAM_RESULTS_PER_PAGE", "15"))
)
WEB_CHUNK_CACHE_TTL = int(os.getenv("WEB_CHUNK_CACHE_TTL", "900"))
WEB_CHUNK_EMPTY_CACHE_TTL = int(os.getenv("WEB_CHUNK_EMPTY_CACHE_TTL", "30"))
SEARCH_EMPTY_CACHE_TTL = int(os.getenv("SEARCH_EMPTY_CACHE_TTL", "30"))

SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "300"))
SEARCH_CONCURRENCY = int(os.getenv("SEARCH_CONCURRENCY", "64"))
SEARCH_QUEUE_TIMEOUT = float(os.getenv("SEARCH_QUEUE_TIMEOUT", "5"))
SEARCH_TIMEOUT = float(os.getenv("SEARCH_TIMEOUT", "15"))
NEWS_TIMEOUT = float(os.getenv("NEWS_TIMEOUT", "6"))
META_TIMEOUT = float(os.getenv("META_TIMEOUT", "5"))
ANSWER_SOURCE_TIMEOUT = float(os.getenv("ANSWER_SOURCE_TIMEOUT", "4"))
VIDEO_TIMEOUT = float(os.getenv("VIDEO_TIMEOUT", "6"))
DDGS_CONCURRENCY = max(1, int(os.getenv("DDGS_CONCURRENCY", "6")))
DDGS_TIMEOUT = float(os.getenv("DDGS_TIMEOUT", "4"))
DDGS_IMAGE_TIMEOUT = float(os.getenv("DDGS_IMAGE_TIMEOUT", "8"))
DDGS_RETRY_DELAY = float(os.getenv("DDGS_RETRY_DELAY", "0.4"))
IMAGE_RESULTS_PER_PAGE = max(12, min(48, int(os.getenv("IMAGE_RESULTS_PER_PAGE", "30"))))
IMAGE_CACHE_TTL = int(os.getenv("IMAGE_CACHE_TTL", "900"))
UPSTREAM_MIN_RESULTS = max(1, int(os.getenv("UPSTREAM_MIN_RESULTS", "5")))
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


async def _run_ddgs(fn, *args, timeout: float | None = None):
    """Run a blocking DDGS call with a hard thread/concurrency bound.

    DDGS has no async API and no server-side timeout. Without these guards a
    burst of unique queries would exhaust the default thread pool and make
    every search wait on the slowest scrape.
    """
    try:
        async with _ddgs_semaphore:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args), timeout or DDGS_TIMEOUT
            )
    except Exception:
        return []


# ── Web search ───────────────────────────────────────────────────────────

def _ddgs_web_search(
    query: str, max_results: int = 15, page: int = 1, backend: str = "auto"
) -> list[dict]:
    """Fetch web results through the ddgs library (blocking, run in a thread)."""
    try:
        results = []
        with _get_ddgs() as ddgs:
            for r in ddgs.text(
                query, max_results=max_results, page=page, backend=backend
            ):
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


# ── Image search ─────────────────────────────────────────────────────────

def _ddgs_image_search(
    query: str, max_results: int = 30, page: int = 1
) -> list[dict]:
    """Fetch image results through the ddgs library (blocking)."""
    try:
        results = []
        with _get_ddgs() as ddgs:
            for r in ddgs.images(
                query, max_results=max_results, page=page, safesearch="moderate"
            ):
                image = (r.get("image") or "").strip()
                if not image:
                    continue
                results.append({
                    "image":     image,
                    "thumbnail": (r.get("thumbnail") or image).strip(),
                    "title":     (r.get("title") or "").strip(),
                    "url":       (r.get("url") or "").strip(),
                    "width":     r.get("width") or "",
                    "height":    r.get("height") or "",
                })
        return results
    except Exception:
        # Rate limits and empty result sets are expected under load.
        return []


async def _collect_images(query: str, page: int) -> dict:
    images = await _run_ddgs(
        _ddgs_image_search,
        query,
        IMAGE_RESULTS_PER_PAGE,
        page,
        timeout=DDGS_IMAGE_TIMEOUT,
    )
    return {
        "images":   images,
        "query":    query,
        "page":     page,
        "per_page": IMAGE_RESULTS_PER_PAGE,
        "has_more": len(images) >= IMAGE_RESULTS_PER_PAGE,
    }


async def _html_web_search(query: str, max_results: int = 15, page: int = 1) -> list[dict]:
    """Fallback: parse DuckDuckGo's lightweight HTML result page."""
    try:
        from bs4 import BeautifulSoup

        client = await get_http_client()
        response = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "s": (page - 1) * 10},
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


def _is_usable_result_url(url: str) -> bool:
    """Reject ad/tracking redirects that providers sometimes return as hits."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host.endswith("bing.com") and parsed.path.startswith(("/aclick", "/ck/a")):
        return False
    if host.endswith("duckduckgo.com") and parsed.path.startswith("/y.js"):
        return False
    return True


def _dedupe_results(results: list[dict]) -> list[dict]:
    """Keep the first usable occurrence of each URL, preserving order."""
    pool, seen = [], set()
    for result in results:
        url = result.get("url", "")
        if not _is_usable_result_url(url):
            continue
        key = _normalize_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        pool.append(result)
    return pool


async def _fetch_web_chunk(query: str, upstream_page: int) -> list[dict]:
    """Fetch one upstream page and merge independent providers.

    Three independent sources are queried in parallel: the ddgs "auto" pool,
    Bing RSS, and Yahoo. No single provider is dependable under load, but their
    union almost always fills a page. Results are de-duplicated here, which is
    what makes page slices stable and non-repeating. Everything is cached, so
    the extra breadth costs one set of calls per query/page per cache window
    rather than one per user request.
    """
    limit = UPSTREAM_RESULTS_PER_PAGE * 2
    ddgs_results, bing_results, yahoo_results = await asyncio.gather(
        _run_ddgs(_ddgs_web_search, query, UPSTREAM_RESULTS_PER_PAGE, upstream_page),
        _bing_rss_web_search(query, UPSTREAM_RESULTS_PER_PAGE, upstream_page),
        _run_ddgs(
            _ddgs_web_search,
            query,
            UPSTREAM_RESULTS_PER_PAGE,
            upstream_page,
            "yahoo",
        ),
    )

    merged = _merge_results(ddgs_results, bing_results, limit)
    merged = _merge_results(merged, yahoo_results, limit)

    # DDG intermittently returns an empty/short page when it is throttling.
    # One short retry recovers most of those pages; the retry is cached with
    # the chunk, so the extra upstream call happens only on a cache miss.
    if len(merged) < UPSTREAM_MIN_RESULTS:
        await asyncio.sleep(DDGS_RETRY_DELAY)
        retry = await _run_ddgs(
            _ddgs_web_search, query, UPSTREAM_RESULTS_PER_PAGE, upstream_page
        )
        merged = _merge_results(merged, retry, limit)

    if not merged:
        merged = await _html_web_search(
            query, UPSTREAM_RESULTS_PER_PAGE, upstream_page
        )

    return _dedupe_results(merged)


async def _web_chunk(query: str, upstream_page: int) -> list[dict]:
    """Cache one upstream page. Concurrent misses share one fetch."""
    results, _ = await cache.get_or_set(
        _web_chunk_key(query, upstream_page),
        lambda: _fetch_web_chunk(query, upstream_page),
        ttl=WEB_CHUNK_CACHE_TTL,
        should_cache=lambda value: bool(value),
        negative_ttl=WEB_CHUNK_EMPTY_CACHE_TTL,
    )
    return results or []


async def _choose_page_chunk(query: str, page: int, seen_keys: set[str]) -> int:
    """Pick the upstream page that supplies a result page.

    Upstream pages are flaky: a page can come back empty, or repeat URLs that
    earlier result pages already showed. Walking one page forward (and skipping
    chunks already used by another result page) keeps pagination useful without
    ever reusing a chunk. ``seen_keys`` is the set of URLs that earlier pages
    already displayed.
    """
    used = set()
    for other_page in range(1, MAX_SEARCH_PAGE + 1):
        if other_page == page:
            continue
        mapped = await cache.get(_page_chunk_key(query, other_page))
        if isinstance(mapped, int) and mapped > 0:
            used.add(mapped)

    last_candidate = min(MAX_SEARCH_PAGE + 1, page + 1)
    for candidate in range(page, last_candidate + 1):
        if candidate in used:
            continue
        chunk = await _web_chunk(query, candidate)
        if any(
            _normalize_url(item.get("url", "")) not in seen_keys
            for item in chunk
        ):
            return candidate
    return 0


async def _wiki_search_page(query: str, page: int, max_results: int = 10) -> list[dict]:
    """Paginated Wikipedia search used to fill pages when web search throttles."""
    try:
        client = await get_http_client()
        response = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "sroffset": (page - 1) * max_results,
                "format": "json",
                "formatversion": "2",
                "srprop": "snippet",
            },
            timeout=8.0,
        )
        if response.status_code != 200:
            return []

        items = response.json().get("query", {}).get("search", [])
        results = []
        for item in items:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            snippet = html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet") or ""))
            results.append({
                "url": "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                "title": title,
                "snippet": snippet,
                "source": "Wikipedia",
            })
        return results
    except Exception:
        return []


async def _wiki_chunk(query: str, page: int) -> list[dict]:
    results, _ = await cache.get_or_set(
        _wiki_chunk_key(query, page),
        lambda: _wiki_search_page(query, page, RESULTS_PER_PAGE),
        ttl=WEB_CHUNK_CACHE_TTL,
        should_cache=lambda value: bool(value),
        negative_ttl=WEB_CHUNK_EMPTY_CACHE_TTL,
    )
    return results or []


async def _web_results_page(query: str, page: int) -> tuple[list[dict], int, bool]:
    """Build one page, guaranteed not to repeat URLs from earlier pages.

    Each result page is backed by one upstream page (or the next healthy one
    when a provider throttles). Every page is filtered against the URLs used by
    all earlier result pages, so page N never repeats page N-1.
    """
    seen_keys = set()
    for other_page in range(1, MAX_SEARCH_PAGE + 1):
        if other_page == page:
            continue
        mapped = await cache.get(_page_chunk_key(query, other_page))
        if isinstance(mapped, int):
            chunk_number = mapped if mapped > 0 else 0
        elif other_page < page:
            # The earlier page has not been opened yet, but its natural
            # upstream chunk may already be cached by another request.
            chunk_number = other_page
        else:
            chunk_number = 0

        if chunk_number:
            cached = await cache.get(_web_chunk_key(query, chunk_number))
            for item in cached or []:
                url = item.get("url", "")
                if _is_usable_result_url(url):
                    seen_keys.add(_normalize_url(url))

        # Wiki fallback can fill a page even when its web chunk is empty, so
        # always replay it for earlier pages (mapped chunk 0 included).
        wiki_cached = await cache.get(_wiki_chunk_key(query, other_page))
        for item in wiki_cached or []:
            url = item.get("url", "")
            if _is_usable_result_url(url):
                seen_keys.add(_normalize_url(url))

    chunk_number, _ = await cache.get_or_set(
        _page_chunk_key(query, page),
        lambda: _choose_page_chunk(query, page, seen_keys),
        ttl=WEB_CHUNK_CACHE_TTL,
        should_cache=lambda value: bool(value),
        negative_ttl=WEB_CHUNK_EMPTY_CACHE_TTL,
    )
    current = await _web_chunk(query, chunk_number) if chunk_number else []

    page_results = [
        item for item in _dedupe_results(current)
        if _normalize_url(item.get("url", "")) not in seen_keys
    ][:RESULTS_PER_PAGE]

    # Web providers are the first choice, but they throttle aggressively.
    # Top up a thin page with paginated Wikipedia matches instead of returning
    # an empty page or repeating links from an earlier page.
    if len(page_results) < RESULTS_PER_PAGE:
        page_keys = {_normalize_url(item.get("url", "")) for item in page_results}
        for item in await _wiki_chunk(query, page):
            url = item.get("url", "")
            key = _normalize_url(url)
            if (
                not _is_usable_result_url(url)
                or key in seen_keys
                or key in page_keys
            ):
                continue
            page_keys.add(key)
            page_results.append(item)
            if len(page_results) >= RESULTS_PER_PAGE:
                break

    total = max(len(seen_keys) + len(page_results), (page - 1) * RESULTS_PER_PAGE + len(page_results))
    has_more = page < MAX_SEARCH_PAGE and bool(page_results)
    return page_results, total, has_more


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
        if not _is_usable_result_url(url):
            continue
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
    first_page = page == 1

    web_task = asyncio.create_task(_web_results_page(query, page))

    # Answers, news, videos, and Wikipedia are identical on every page and
    # cost several upstream calls. Fetch them only for page 1 so paging stays
    # cheap when a lot of users are browsing at once.
    news_task = meta_task = videos_task = None
    if first_page:
        news_task = asyncio.create_task(_news_search(query, 6))
        meta_task = asyncio.create_task(_answer_meta(query))
        videos_task = asyncio.create_task(get_videos(query, 4))

    # Each source has its own budget. A slow or broken provider returns an
    # empty section instead of taking down the whole result page.
    web_results, pool_size, has_more = await _with_timeout(
        web_task, ([], 0, False), SEARCH_TIMEOUT
    )

    if first_page:
        news_results, meta, videos = await asyncio.gather(
            _with_timeout(news_task, [], NEWS_TIMEOUT),
            _with_timeout(meta_task, (None, None, None), META_TIMEOUT),
            _with_timeout(videos_task, [], VIDEO_TIMEOUT),
        )
    else:
        news_results, meta, videos = [], (None, None, None), []

    wikipedia, wiktionary, instant = meta
    answer = build_answer(query, wikipedia, wiktionary, instant) if first_page else None
    web_results = _clean_web_results(web_results, wikipedia, videos)

    # Fill a short page from the local index. It is page-aware (LIMIT/OFFSET),
    # so it never turns into duplicate results across pages.
    if not DISABLE_LOCAL_INDEX and len(web_results) < RESULTS_PER_PAGE:
        try:
            local_data = await asyncio.to_thread(
                searchdb.search, query, page, RESULTS_PER_PAGE
            )
            seen_urls = {_normalize_url(r["url"]) for r in web_results}
            for local_result in local_data.get("results", []):
                if len(web_results) >= RESULTS_PER_PAGE:
                    break
                if not _is_usable_result_url(local_result["url"]):
                    continue
                key = _normalize_url(local_result["url"])
                if key and key not in seen_urls:
                    web_results.append(local_result)
                    seen_urls.add(key)
        except Exception:
            pass

    total = max(pool_size, (page - 1) * RESULTS_PER_PAGE + len(web_results))

    return {
        "results": web_results,
        "news":    news_results,
        "answer":  answer,
        "wikipedia": wikipedia,
        "videos":  videos,
        "total":   total,
        "page":    page,
        "per_page": RESULTS_PER_PAGE,
        "has_more": bool(has_more),
        "max_page": MAX_SEARCH_PAGE,
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


def _normalize_query(query: str) -> str:
    return _WHITESPACE.sub(" ", query).strip().casefold()


def _cache_key(query: str, page: int) -> str:
    return f"8s:search:v2:{page}:{RESULTS_PER_PAGE}:{_normalize_query(query)}"


def _web_chunk_key(query: str, upstream_page: int) -> str:
    return (
        f"8s:web:v2:{UPSTREAM_RESULTS_PER_PAGE}:{upstream_page}:"
        f"{_normalize_query(query)}"
    )


def _page_chunk_key(query: str, page: int) -> str:
    return f"8s:pagechunk:v1:{page}:{_normalize_query(query)}"


def _wiki_chunk_key(query: str, page: int) -> str:
    return f"8s:wiki:v1:{page}:{_normalize_query(query)}"


# ── Route ────────────────────────────────────────────────────────────────

@router.get("/api/search")
async def search(
    response: Response,
    q: str = Query("", min_length=0, max_length=400),
    page: int = Query(1, ge=1, le=MAX_SEARCH_PAGE),
    session_token: str | None = Cookie(default=None),
    guest_id: str | None = Cookie(default=None),
    guest_searches: str | None = Cookie(default=None),
):
    query = q.strip()
    if not query:
        return {
            "results": [], "news": [], "answer": None, "wikipedia": None,
            "videos": [], "total": 0, "page": 1, "per_page": RESULTS_PER_PAGE,
            "has_more": False, "max_page": MAX_SEARCH_PAGE, "limit_reached": False,
        }

    user = await run_in_threadpool(get_current_user, session_token)
    is_guest = user is None

    # URL detection – navigate directly
    if _URL_PATTERN.match(query):
        url = query if query.startswith(("http://", "https://")) else f"https://{query}"
        return {"redirect": url}

    # Guest rate-limiting. Only a brand-new search (page 1) consumes quota;
    # paging through results the guest already unlocked must stay free.
    if is_guest:
        if not guest_id:
            guest_id = uuid.uuid4().hex
            response.set_cookie(key="guest_id", value=guest_id,
                                httponly=True, samesite="lax", max_age=86400, path="/")

        if page == 1:
            count = int(guest_searches or "0")
            if count >= GUEST_SEARCH_LIMIT:
                return {
                    "results": [], "news": [], "answer": None, "wikipedia": None,
                    "videos": [], "total": 0, "page": 1,
                    "limit_reached": True,
                    "message": "Please sign in for unlimited searches",
                }
            response.set_cookie(key="guest_searches", value=str(count + 1),
                                httponly=False, samesite="lax", max_age=86400, path="/")

    try:
        payload, cache_hit = await cache.get_or_set(
            _cache_key(query, page),
            lambda: _collect_payload_limited(query, page),
            ttl=SEARCH_CACHE_TTL,
            should_cache=_has_content,
            negative_ttl=SEARCH_EMPTY_CACHE_TTL,
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


@router.get("/api/images")
async def image_search(
    response: Response,
    q: str = Query("", min_length=0, max_length=400),
    page: int = Query(1, ge=1, le=5),
):
    """Image results for the Images tab. Cached and bounded like web search."""
    query = q.strip()
    if not query:
        return {
            "images": [], "query": "", "page": 1,
            "per_page": IMAGE_RESULTS_PER_PAGE, "has_more": False,
        }

    try:
        payload, cache_hit = await cache.get_or_set(
            f"8s:images:v1:{page}:{IMAGE_RESULTS_PER_PAGE}:{_normalize_query(query)}",
            lambda: _collect_images(query, page),
            ttl=IMAGE_CACHE_TTL,
            should_cache=lambda p: bool(p.get("images")),
            negative_ttl=SEARCH_EMPTY_CACHE_TTL,
        )
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail="Image search is temporarily unavailable. Please try again.",
        )

    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return payload
