"""Search API – guest-limited full-text search with URL detection."""

import re
import uuid

from fastapi import APIRouter, Cookie, Query, Response

from . import searchdb
from .auth import get_current_user

router = APIRouter()

# Simple regex: has a "." but no spaces → treat as URL
_URL_PATTERN = re.compile(r"^[^\s]+\.[^\s]+$")

GUEST_SEARCH_LIMIT = 4


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
        return {"results": [], "total": 0, "page": 1, "limit_reached": False}

    # Resolve logged-in user
    user = get_current_user(session_token)
    is_guest = user is None

    # URL detection – if it looks like a URL, redirect
    if _URL_PATTERN.match(query):
        url = query if query.startswith(("http://", "https://")) else f"https://{query}"
        return {"redirect": url}

    # Guest rate-limiting
    if is_guest:
        count = int(guest_searches or "0")
        if count >= GUEST_SEARCH_LIMIT:
            return {
                "results": [],
                "total": 0,
                "page": 1,
                "limit_reached": True,
                "message": "Please log in for unlimited searches",
            }
        # Increment counter
        count += 1
        if not guest_id:
            guest_id = uuid.uuid4().hex
            response.set_cookie(key="guest_id", value=guest_id, httponly=True, samesite="lax", max_age=86400, path="/")
        response.set_cookie(
            key="guest_searches", value=str(count), httponly=False, samesite="lax", max_age=86400, path="/"
        )

    # Perform search
    data = searchdb.search(query, page=page)
    data["limit_reached"] = False
    return data
