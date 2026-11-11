"""Search API – real web search + news, like Google/Brave."""

import re
import uuid
import traceback

from fastapi import APIRouter, Cookie, Query, Response

from . import searchdb
from .auth import get_current_user

router = APIRouter()

# Simple regex: has a "." but no spaces → treat as URL
_URL_PATTERN = re.compile(r"^[^\s]+\.[^\s]+$")

GUEST_SEARCH_LIMIT = 4


def _get_ddgs():
    """Return a DDGS instance using the best available package."""
    try:
        from ddgs import DDGS
        return DDGS()
    except Exception:
        from duckduckgo_search import DDGS
        return DDGS()


def _web_search(query: str, max_results: int = 15) -> list[dict]:
    """Fetch real web search results."""
    try:
        results = []
        with _get_ddgs() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "url":     r.get("href", ""),
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    except Exception:
        traceback.print_exc()
        return []


def _news_search(query: str, max_results: int = 8) -> list[dict]:
    """Fetch recent news results with images."""
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
        traceback.print_exc()
        return []


@router.get("/api/search")
def search(
    response: Response,
    q: str = Query("", min_length=0),
    page: int = Query(1, ge=1),
    session_token: str | None = Cookie(default=None),
    guest_id: str | None = Cookie(default=None),
    guest_searches: str | None = Cookie(default=None),
):
    query = q.strip()
    if not query:
        return {"results": [], "news": [], "total": 0, "page": 1, "limit_reached": False}

    user = get_current_user(session_token)
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
                "results": [], "news": [], "total": 0, "page": 1,
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

    # Fetch web + news in parallel
    web_results = _web_search(query, max_results=15)
    news_results = _news_search(query, max_results=6)

    # Merge local index (bonus results)
    try:
        local_data = searchdb.search(query, page=page)
        seen_urls = {r["url"] for r in web_results}
        for lr in local_data.get("results", []):
            if lr["url"] not in seen_urls:
                web_results.append(lr)
                seen_urls.add(lr["url"])
    except Exception:
        pass

    return {
        "results": web_results,
        "news":    news_results,
        "total":   len(web_results),
        "page":    page,
        "limit_reached": False,
    }
