"""Answer helpers for search results.

Provides the "quick answer" content shown above regular links:
  * Wikipedia summary for the query (article + link)
  * Wiktionary definition for single-word queries
  * DuckDuckGo Instant Answer as a last resort
  * YouTube videos for the query

Every helper fails soft: on any network/parse error it returns None/[] so a
search never breaks just because one enrichment source is unavailable.

All network calls share one pooled AsyncClient, which is important under load.
"""

import asyncio
import html
import json
import os
import re
import traceback
from urllib.parse import quote

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKTIONARY_SUMMARY = "https://en.wiktionary.org/api/rest_v1/page/definition/"
DUCKDUCKGO_IA = "https://api.duckduckgo.com/"
YOUTUBE_SEARCH = "https://www.youtube.com/results"

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "8"))
HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "200"))
DDGS_VIDEO_CONCURRENCY = max(1, int(os.getenv("DDGS_VIDEO_CONCURRENCY", "3")))
DDGS_VIDEO_TIMEOUT = float(os.getenv("DDGS_VIDEO_TIMEOUT", "4"))

_SINGLE_WORD = re.compile(r"^[A-Za-z][A-Za-z'’\-]*$")
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_YT_DATA = (
    re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S),
    re.compile(r'ytInitialData"\]\s*=\s*(\{.*?\});', re.S),
)

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()
_ddgs_video_limiter = asyncio.Semaphore(DDGS_VIDEO_CONCURRENCY)


async def get_http_client() -> httpx.AsyncClient:
    """One pooled client per worker process (reuses TCP connections)."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                limits=httpx.Limits(
                    max_connections=HTTP_MAX_CONNECTIONS,
                    max_keepalive_connections=max(20, HTTP_MAX_CONNECTIONS // 4),
                ),
            )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _clean_html(value: str) -> str:
    """Strip tags/entities from API-provided markup and collapse whitespace."""
    text = _HTML_TAG.sub(" ", value or "")
    text = html.unescape(text)
    text = text.replace("\u200b", "")
    text = _WHITESPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return text.strip().strip('"')


def _trim(text: str, limit: int) -> str:
    """Trim at a sentence boundary without cutting a word in half."""
    text = _WHITESPACE.sub(" ", text or "").strip()
    if len(text) <= limit:
        return text

    cut = text[:limit]
    for marker in (". ", "! ", "? "):
        at = cut.rfind(marker)
        if at > limit * 0.55:
            return cut[: at + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


# ── Wikipedia ────────────────────────────────────────────────────────────

async def _wiki_summary(client: httpx.AsyncClient, title: str) -> dict | None:
    slug = quote(title.replace(" ", "_"), safe="()_,'’-")
    try:
        response = await client.get(WIKI_SUMMARY + slug)
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None

    if data.get("type") in {"disambiguation", "no-extract"}:
        return None

    extract = _clean_html(data.get("extract") or "")
    if len(extract) < 40:
        return None

    desktop = ((data.get("content_urls") or {}).get("desktop") or {})
    url = desktop.get("page") or ""
    if not url:
        return None

    return {
        "title": _clean_html(data.get("title") or title),
        "extract": _trim(extract, 1500),
        "url": url,
        "thumbnail": ((data.get("thumbnail") or {}).get("source") or ""),
        "description": _clean_html(data.get("description") or ""),
    }


async def _wiki_search_titles(client: httpx.AsyncClient, query: str) -> list[str]:
    try:
        response = await client.get(
            WIKI_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 3,
            },
        )
        rows = ((response.json().get("query") or {}).get("search") or [])
        return [row["title"] for row in rows if row.get("title")]
    except Exception:
        return []


async def get_wikipedia(query: str) -> dict | None:
    """Return the best matching Wikipedia article summary, if one exists."""
    try:
        client = await get_http_client()
        direct = await _wiki_summary(client, query)
        if direct:
            return direct

        for title in await _wiki_search_titles(client, query):
            summary = await _wiki_summary(client, title)
            if summary:
                return summary
    except Exception:
        traceback.print_exc()
    return None


# ── Wiktionary (single words) ────────────────────────────────────────────

async def get_wiktionary(query: str) -> dict | None:
    """Return a dictionary definition for a single English word."""
    query = query.strip()
    if not _SINGLE_WORD.match(query):
        return None

    word = query.lower()
    try:
        client = await get_http_client()
        response = await client.get(WIKTIONARY_SUMMARY + quote(word, safe="'-"))
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None

    for entry in data.get("en") or []:
        for definition in entry.get("definitions") or []:
            text = _clean_html(definition.get("definition") or "")
            if len(text) < 15:
                continue
            # Ignore cross-reference-only senses such as "Alternative form of …".
            if text.lower().startswith(("alternative form of", "alternative spelling of")):
                continue
            return {
                "text": text,
                "part_of_speech": _clean_html(entry.get("partOfSpeech") or ""),
                "url": f"https://en.wiktionary.org/wiki/{quote(word)}",
            }
    return None


# ── DuckDuckGo Instant Answer fallback ───────────────────────────────────

async def get_instant_answer(query: str) -> dict | None:
    try:
        client = await get_http_client()
        response = await client.get(
            DUCKDUCKGO_IA,
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "no_redirect": 1,
                "skip_disambig": 1,
            },
        )
        data = response.json()
    except Exception:
        return None

    text = _clean_html(data.get("AbstractText") or data.get("Definition") or "")
    if len(text) < 40:
        return None

    source = _clean_html(
        data.get("AbstractSource") or data.get("DefinitionSource") or "DuckDuckGo"
    )
    url = data.get("AbstractURL") or ""
    if not url and "wiktionary" in source.lower():
        url = f"https://en.wiktionary.org/wiki/{quote(query.strip())}"

    return {
        "title": _clean_html(data.get("Heading") or query.strip().title()),
        "text": _trim(text, 800),
        "source": source,
        "url": url,
    }


# ── Answer selection ─────────────────────────────────────────────────────

def build_answer(
    query: str,
    wikipedia: dict | None,
    wiktionary: dict | None,
    instant: dict | None,
) -> dict | None:
    """Choose the most useful short answer for the query."""
    if wiktionary:
        return {
            "title": query.strip().title(),
            "text": wiktionary["text"],
            "source": "Wiktionary",
            "url": wiktionary["url"],
            "kind": "definition",
            "part_of_speech": wiktionary.get("part_of_speech") or "",
        }

    if wikipedia:
        return {
            "title": wikipedia["title"],
            "text": wikipedia["extract"],
            "source": "Wikipedia",
            "url": wikipedia["url"],
            "kind": "overview",
            "part_of_speech": "",
        }

    if instant:
        return {
            "title": instant["title"],
            "text": instant["text"],
            "source": instant["source"],
            "url": instant.get("url") or "",
            "kind": "overview",
            "part_of_speech": "",
        }

    return None


# ── YouTube videos ───────────────────────────────────────────────────────

def _runs_text(runs) -> str:
    if not runs:
        return ""
    return _clean_html("".join(part.get("text", "") for part in runs if isinstance(part, dict)))


def _collect_video_renderers(node, output: list) -> None:
    if isinstance(node, dict):
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict):
            output.append(renderer)
        for value in node.values():
            _collect_video_renderers(value, output)
    elif isinstance(node, list):
        for value in node:
            _collect_video_renderers(value, output)


async def _youtube_videos(query: str, max_results: int) -> list[dict]:
    client = await get_http_client()
    response = await client.get(
        YOUTUBE_SEARCH,
        params={"search_query": query, "hl": "en"},
        timeout=12.0,
    )
    if response.status_code != 200:
        return []

    match = None
    for pattern in _YT_DATA:
        match = pattern.search(response.text)
        if match:
            break
    if not match:
        return []

    data = json.loads(match.group(1))
    renderers: list = []
    _collect_video_renderers(data, renderers)

    videos: list[dict] = []
    seen: set[str] = set()
    for renderer in renderers:
        video_id = renderer.get("videoId") or ""
        title = _runs_text((renderer.get("title") or {}).get("runs"))
        if not video_id or not title or video_id in seen:
            continue
        seen.add(video_id)

        videos.append(
            {
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "duration": ((renderer.get("lengthText") or {}).get("simpleText") or ""),
                "channel": _runs_text((renderer.get("ownerText") or {}).get("runs")),
                "published": ((renderer.get("publishedTimeText") or {}).get("simpleText") or ""),
            }
        )
        if len(videos) >= max_results:
            break
    return videos


def _ddgs_videos_sync(query: str, max_results: int) -> list[dict]:
    """Fallback video search when YouTube's page layout changes."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            rows = list(ddgs.videos(query, max_results=max_results * 3))
    except Exception:
        return []

    videos: list[dict] = []
    for row in rows:
        url = row.get("content") or row.get("url") or ""
        if "youtube.com" not in url and "youtu.be" not in url:
            continue
        images = row.get("images") or {}
        thumb = row.get("thumbnail") or images.get("medium") or images.get("small") or ""
        videos.append(
            {
                "title": _clean_html(row.get("title") or ""),
                "url": url,
                "thumbnail": thumb,
                "duration": row.get("duration") or "",
                "channel": _clean_html(row.get("publisher") or row.get("uploader") or "YouTube"),
                "published": row.get("published") or "",
            }
        )
        if len(videos) >= max_results:
            break
    return videos


async def get_videos(query: str, max_results: int = 4) -> list[dict]:
    """Return YouTube videos for the query, with a DDGS fallback."""
    try:
        videos = await _youtube_videos(query, max_results)
        if videos:
            return videos
    except Exception:
        traceback.print_exc()

    # Bound the blocking fallback so unique-query bursts cannot exhaust threads.
    try:
        async with _ddgs_video_limiter:
            return await asyncio.wait_for(
                asyncio.to_thread(_ddgs_videos_sync, query, max_results),
                timeout=DDGS_VIDEO_TIMEOUT,
            )
    except Exception:
        return []
