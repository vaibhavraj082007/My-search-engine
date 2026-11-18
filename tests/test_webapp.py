"""Browser-facing search-engine routes: /search, OpenSearch, manifest, set-default."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import webapp

ROOT = Path(__file__).resolve().parents[1]
OS_NS = "{http://a9.com/-/spec/opensearch/1.1/}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://search.example")
    app = FastAPI()
    app.include_router(webapp.router)
    with TestClient(app) as test_client:
        yield test_client


def test_search_page_has_escaped_metadata_and_noindex(client):
    query = '<script>alert("x")</script> 😀 café'
    response = client.get("/search", params={"q": query, "tab": "images"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    body = response.text
    assert "<title>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; 😀 café – 8search</title>" in body
    assert '<meta name="robots" content="noindex">' in body
    assert 'data-search-query="&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; 😀 café"' in body
    assert 'data-search-tab="images"' in body
    assert '<meta name="description" content="Search results for “&lt;script&gt;' in body
    assert 'on 8search — answers, links, videos and news.">' in body


def test_search_page_truncates_query_to_500_characters(client):
    query = "x" * 600
    response = client.get("/search", params={"q": query})
    assert response.status_code == 200
    assert "x" * 500 in response.text
    assert "x" * 501 not in response.text


def test_empty_search_page_serves_the_app(client):
    response = client.get("/search")
    assert response.status_code == 200
    assert "<title>8search</title>" in response.text


def test_home_redirects_legacy_query_to_canonical_search_url(client):
    response = client.get(
        "/", params={"q": "hello world", "tab": "ai", "page": "2"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.path == "/search"
    params = parse_qs(parsed.query)
    assert params["q"] == ["hello world"]
    assert params["tab"] == ["ai"]
    assert params["page"] == ["2"]


def test_home_redirect_drops_invalid_tab_and_encodes_query(client):
    response = client.get(
        "/", params={"q": "<script>&x", "tab": "javascript:"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert "tab=" not in location
    assert "<script>" not in location
    assert location.startswith("/search?q=%3Cscript%3E%26x")


def test_opensearch_descriptor_is_discoverable(client):
    response = client.get("/opensearch.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/opensearchdescription+xml"
    )

    root = ET.fromstring(response.text)
    assert root.tag == OS_NS + "OpenSearchDescription"
    assert root.findtext(OS_NS + "ShortName") == "8search"
    templates = [
        node.attrib["template"] for node in root.findall(OS_NS + "Url")
    ]
    assert "https://search.example/search?q={searchTerms}" in templates
    assert "https://search.example/api/suggest?q={searchTerms}" in templates
    assert "https://search.example/" in root.findtext(
        "{http://www.mozilla.org/2006/browser/search/}SearchForm"
    )


def test_manifest_contains_search_url_and_icons(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    data = json.loads(response.text)
    assert data["id"] == "/"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"
    assert data["display"] == "standalone"
    assert data["search_url"] == "https://search.example/search?q={searchTerms}"
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"32x32", "64x64", "180x180", "192x192", "512x512"} <= sizes
    maskable = [icon for icon in data["icons"] if "maskable" in icon.get("purpose", "")]
    assert maskable


def test_install_page_explains_every_platform(client):
    response = client.get("/install")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    for text in ("iPhone", "iPad", "Android", "Windows", "macOS", "Add to Home Screen"):
        assert text in body
    assert 'id="installAppBtn"' in body
    assert "/manifest.webmanifest" in body
    assert "/pwa.js" in body


def test_app_shell_files_are_present_and_keep_accounts_out_of_cache():
    service_worker = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
    offline = (ROOT / "frontend/offline.html").read_text(encoding="utf-8")
    install = (ROOT / "frontend/install.html").read_text(encoding="utf-8")
    assert 'url.pathname.startsWith("/api/")' in service_worker
    assert 'request.mode === "navigate"' in service_worker
    assert "offline.html" in service_worker
    assert "You’re offline." in offline
    assert "/install" in install


def test_history_ui_is_available_from_the_search_bar_and_backed_by_the_api():
    index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "frontend/app.js").read_text(encoding="utf-8")

    assert 'id="historyDialog"' in index
    assert 'id="historyList"' in index
    assert 'id="historyEmpty"' in index
    assert 'id="historyClear"' in index
    assert 'id="historyClearConfirm"' in index
    assert 'aria-labelledby="historyTitle"' in index

    assert 'id="historyBtn"' in app_js
    assert "/api/history?limit=5" in app_js
    assert "View all history" in app_js
    assert "function openHistory()" in app_js
    assert "function clearAllHistory()" in app_js
    assert "method: 'DELETE'" in app_js


def test_set_default_page_replaces_placeholders(client):
    response = client.get("/set-default")
    assert response.status_code == 200
    body = response.text
    assert "__BASE_URL__" not in body
    assert "__SEARCH_URL__" not in body
    assert "https://search.example/search?q=%s" in body
    for browser in ("Chrome", "Brave", "Edge", "Firefox", "Safari"):
        assert browser in body


def test_forwarded_headers_are_trusted_only_when_enabled(monkeypatch):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    app = FastAPI()
    app.include_router(webapp.router)

    with TestClient(app, base_url="http://internal:8000") as proxied:
        monkeypatch.setenv("TRUST_PROXY", "0")
        ignored = proxied.get(
            "/manifest.webmanifest",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "search.example",
            },
        )
        assert json.loads(ignored.text)["search_url"].startswith("http://internal")

        monkeypatch.setenv("TRUST_PROXY", "1")
        trusted = proxied.get(
            "/manifest.webmanifest",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "search.example",
            },
        )
        assert json.loads(trusted.text)["search_url"].startswith(
            "https://search.example"
        )


def test_safe_internal_path_rejects_external_and_control_characters():
    assert webapp.safe_internal_path("/search?q=x") == "/search?q=x"
    for value in (
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/search\nSet-Cookie: x=1",
        "search",
    ):
        assert webapp.safe_internal_path(value) == "/"


def test_favicon_and_app_icons_exist():
    for relative in (
        "frontend/favicon.ico",
        "frontend/assets/favicon-16.png",
        "frontend/assets/favicon-32.png",
        "frontend/assets/icon-64.png",
        "frontend/assets/apple-touch-icon.png",
    ):
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.stat().st_size > 0, relative


def test_index_and_auth_pages_discover_opensearch_and_icons():
    for relative in ("frontend/index.html", "frontend/login.html", "frontend/signup.html"):
        body = (ROOT / relative).read_text(encoding="utf-8")
        assert "/opensearch.xml" in body
        assert "/favicon.ico" in body
        assert "/manifest.webmanifest" in body


def test_information_pages_are_served_with_the_shared_footer(client):
    for path, title in (
        ("/about", "About – 8search"),
        ("/privacy", "Privacy – 8search"),
        ("/terms", "Terms – 8search"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        body = response.text
        assert title in body
        assert 'class="footer-links"' in body
        for href in ("/about", "/privacy", "/terms", "/set-default", "/install"):
            assert f'href="{href}"' in body


def test_landing_page_has_tagline_footer_and_no_third_party_brand():
    body = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'id="landingTagline"' in body
    assert "Search ranked by what people actually click." in body
    assert 'id="askAiFab"' in body
    assert "Ask 8search AI" in body
    assert "gemini" not in body.lower()
    for href in ("/about", "/privacy", "/terms", "/set-default", "/install"):
        assert f'href="{href}"' in body
    assert "© 2026 8search" in body


def test_landing_page_has_trending_peek_and_ai_fab():
    body = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'id="trendingPeek"' in body
    assert 'href="#trendingNews"' in body
    assert 'id="askAiFab"' in body
    assert "defer" in body


def test_download_installer_all_platforms(client):
    for platform in ("mac", "android", "windows", "ios"):
        res_get = client.get(f"/download/{platform}")
        assert res_get.status_code == 200
        assert "content-disposition" in res_get.headers
        assert "attachment" in res_get.headers["content-disposition"]
        assert len(res_get.content) > 0

        res_head = client.head(f"/download/{platform}")
        assert res_head.status_code == 200
        assert "content-disposition" in res_head.headers


def test_top_bar_has_date_clock_and_responsive_download(client):
    body = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'id="topDate"' in body
    assert 'id="istClock"' in body
    assert 'class="download-btn-label"' in body
    assert 'class="dl-full"' in body
    assert 'id="bgToggleBtn"' in body

