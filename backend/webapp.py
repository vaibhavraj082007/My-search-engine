"""Browser-facing pages: /search, OpenSearch, set-default and auth aliases.

The application is a static vanilla-JS frontend, but browser search engines
need stable URLs and server-rendered metadata. These routes live in front of
the trailing StaticFiles mount in main.py.
"""

import html
import os
import re
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree as ET

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

router = APIRouter()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
INDEX_FILE = os.path.join(FRONTEND_DIR, "index.html")
SET_DEFAULT_FILE = os.path.join(FRONTEND_DIR, "set-default.html")
INSTALL_FILE = os.path.join(FRONTEND_DIR, "install.html")
ABOUT_FILE = os.path.join(FRONTEND_DIR, "about.html")
PRIVACY_FILE = os.path.join(FRONTEND_DIR, "privacy.html")
TERMS_FILE = os.path.join(FRONTEND_DIR, "terms.html")
MAX_QUERY_LENGTH = 500
VALID_TABS = {"web", "ai", "images", "code"}

_TITLE_RE = re.compile(r"<title>.*?</title>", re.I | re.S)
_DESCRIPTION_RE = re.compile(
    r'<meta\s+name=["\']description["\'][^>]*>', re.I
)


def _load_page(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def base_url(request: Request) -> str:
    """Return the public base URL, honouring APP_BASE_URL and proxies."""
    configured = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return configured

    forwarded_proto = ""
    forwarded_host = ""
    if os.getenv("TRUST_PROXY", "0") == "1":
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        forwarded_host = request.headers.get("x-forwarded-host", "")

    scheme = (forwarded_proto.split(",")[0].strip() or request.url.scheme or "http").lower()
    if scheme not in {"http", "https"}:
        scheme = "http"
    host = (
        forwarded_host.split(",")[0].strip()
        or request.headers.get("host", "")
        or request.url.netloc
    )
    return f"{scheme}://{host}".rstrip("/")


def safe_internal_path(value: str | None, fallback: str = "/") -> str:
    """Only allow same-site absolute paths (no protocol-relative URLs)."""
    if not value:
        return fallback
    value = value.strip()
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    if "\\" in value or any(ord(ch) < 32 for ch in value):
        return fallback
    return value


def search_url(query: str, tab: str = "web", page: int | None = None) -> str:
    """Build a canonical, safely encoded /search URL."""
    params = {"q": (query or "").strip()[:MAX_QUERY_LENGTH]}
    if tab in VALID_TABS and tab != "web":
        params["tab"] = tab
    if page and page > 1:
        params["page"] = str(page)
    return "/search?" + urlencode(params)


def _clean_query(value: str | None) -> str:
    return (value or "").strip()[:MAX_QUERY_LENGTH]


def _clean_tab(value: str | None) -> str:
    return value if value in VALID_TABS else "web"


def _search_page_html(query: str, tab: str) -> str:
    template = _load_page(INDEX_FILE)
    safe_query = html.escape(query, quote=True)
    title = html.escape(f"{query} – 8search", quote=True)
    description = html.escape(
        f"Search results for “{query}” on 8search — answers, links, videos and news.",
        quote=True,
    )
    extras = (
        f'<meta name="description" content="{description}">\n'
        '  <meta name="robots" content="noindex">'
    )
    if _TITLE_RE.search(template):
        template = _TITLE_RE.sub(f"<title>{title}</title>", template, count=1)
    else:
        template = template.replace("</head>", f"<title>{title}</title>\n</head>", 1)
    if _DESCRIPTION_RE.search(template):
        template = _DESCRIPTION_RE.sub(extras, template, count=1)
    else:
        template = template.replace("</head>", f"  {extras}\n</head>", 1)

    # The frontend reads q/tab from the URL, but this data attribute also lets
    # a cached page (or a no-JS browser) know which tab was requested.
    template = template.replace(
        '<body class="landing-page">',
        f'<body class="landing-page" data-search-query="{safe_query}" data-search-tab="{tab}">',
        1,
    )
    return template


@router.get("/", include_in_schema=False)
async def home(request: Request, q: str = Query("", max_length=2000)):
    """Serve the homepage, and redirect the old /?q= form to /search."""
    query = _clean_query(q)
    if query:
        tab = _clean_tab(request.query_params.get("tab") or request.query_params.get("mode"))
        page = request.query_params.get("page")
        url = search_url(query, tab)
        if page and page.isdigit() and int(page) > 1:
            url += "&page=" + str(int(page))
        return RedirectResponse(url, status_code=307)
    return FileResponse(INDEX_FILE, media_type="text/html")


@router.get("/search", include_in_schema=False)
async def search_page(
    q: str = Query("", max_length=2000),
    tab: str | None = Query(None),
    mode: str | None = Query(None),
):
    query = _clean_query(q)
    if not query:
        return FileResponse(INDEX_FILE, media_type="text/html")
    return HTMLResponse(_search_page_html(query, _clean_tab(tab or mode)))


@router.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"), media_type="text/html")


@router.get("/signup", include_in_schema=False)
async def signup_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "signup.html"), media_type="text/html")


@router.get("/forgot-password", include_in_schema=False)
async def forgot_password_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "forgot-password.html"), media_type="text/html")


@router.get("/reset-password", include_in_schema=False)
async def reset_password_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "reset-password.html"), media_type="text/html")


@router.get("/opensearch.xml", include_in_schema=False)
async def opensearch(request: Request):
    root = base_url(request)
    ET.register_namespace("", "http://a9.com/-/spec/opensearch/1.1/")
    ET.register_namespace("moz", "http://www.mozilla.org/2006/browser/search/")
    OS = "{http://a9.com/-/spec/opensearch/1.1/}"
    MOZ = "{http://www.mozilla.org/2006/browser/search/}"

    description = ET.Element(OS + "OpenSearchDescription")
    ET.SubElement(description, OS + "ShortName").text = "8search"
    ET.SubElement(description, OS + "Description").text = (
        "8search – answer-first search with a live satellite globe"
    )
    ET.SubElement(description, OS + "InputEncoding").text = "UTF-8"
    ET.SubElement(description, OS + "OutputEncoding").text = "UTF-8"

    for size, path in (("16x16", "/assets/favicon-16.png"), ("64x64", "/assets/icon-64.png")):
        image = ET.SubElement(description, OS + "Image", {"width": size.split("x")[0],
                                                          "height": size.split("x")[1],
                                                          "type": "image/png"})
        image.text = root + path

    ET.SubElement(
        description,
        OS + "Url",
        {
            "type": "text/html",
            "method": "get",
            "template": root + "/search?q={searchTerms}",
        },
    )
    ET.SubElement(
        description,
        OS + "Url",
        {
            "type": "application/x-suggestions+json",
            "method": "get",
            "template": root + "/api/suggest?q={searchTerms}",
        },
    )
    ET.SubElement(description, MOZ + "SearchForm").text = root + "/"

    xml = ET.tostring(description, encoding="unicode")
    body = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml
    return Response(
        body,
        media_type="application/opensearchdescription+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest(request: Request):
    import json

    root = base_url(request)
    payload = {
        "id": "/",
        "name": "8search – answer-first search",
        "short_name": "8search",
        "description": "Answer-first search with a live satellite globe.",
        "lang": "en",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "any",
        "background_color": "#f5f2ec",
        "theme_color": "#f5f2ec",
        "categories": ["search", "news", "utilities"],
        "icons": [
            {"src": "/assets/favicon-32.png", "sizes": "32x32", "type": "image/png"},
            {"src": "/assets/icon-64.png", "sizes": "64x64", "type": "image/png"},
            {"src": "/assets/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
            {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
        "prefer_related_applications": False,
        "search_url": root + "/search?q={searchTerms}",
    }
    return Response(
        json.dumps(payload, separators=(",", ":")),
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/set-default", include_in_schema=False)
async def set_default(request: Request):
    template = _load_page(SET_DEFAULT_FILE)
    root = html.escape(base_url(request), quote=True)
    template = template.replace("__BASE_URL__", root)
    template = template.replace("__QUERY_TEMPLATE__", root + "/search?q=%s")
    template = template.replace("__SEARCH_URL__", root + "/search?q=%s")
    return HTMLResponse(template)


@router.get("/install", include_in_schema=False)
async def install_page():
    return FileResponse(INSTALL_FILE, media_type="text/html")


@router.get("/about", include_in_schema=False)
async def about_page():
    return FileResponse(ABOUT_FILE, media_type="text/html")


@router.get("/privacy", include_in_schema=False)
async def privacy_page():
    return FileResponse(PRIVACY_FILE, media_type="text/html")


@router.get("/terms", include_in_schema=False)
async def terms_page():
    return FileResponse(TERMS_FILE, media_type="text/html")


@router.api_route("/download/{platform}", methods=["GET", "HEAD"], include_in_schema=False)
async def download_installer(platform: str):
    """Direct, forced attachment download for native installers."""
    platform = platform.lower().strip()
    downloads_map = {
        "mac": ("8search.dmg", "application/x-apple-diskimage"),
        "dmg": ("8search.dmg", "application/x-apple-diskimage"),
        "android": ("8search.apk", "application/vnd.android.package-archive"),
        "apk": ("8search.apk", "application/vnd.android.package-archive"),
        "windows": ("8search-Setup.exe", "application/x-msdownload"),
        "exe": ("8search-Setup.exe", "application/x-msdownload"),
        "ios": ("8search.mobileconfig", "application/x-apple-aspen-config"),
        "mobileconfig": ("8search.mobileconfig", "application/x-apple-aspen-config"),
    }
    if platform not in downloads_map:
        raise HTTPException(status_code=404, detail="Platform installer not found")

    filename, media_type = downloads_map[platform]
    filepath = os.path.join(FRONTEND_DIR, "downloads", filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Installer file missing")

    # For iOS .mobileconfig, Apple Safari requires application/x-apple-aspen-config
    # with inline disposition so iOS triggers the system prompt:
    # "This website is trying to download a configuration profile. Do you want to allow this? Allow"
    if platform in ("ios", "mobileconfig"):
        return FileResponse(
            filepath,
            filename=filename,
            media_type="application/x-apple-aspen-config",
            headers={
                "Content-Type": "application/x-apple-aspen-config",
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "public, max-age=3600",
            },
        )

    return FileResponse(
        filepath,
        filename=filename,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        },
    )

