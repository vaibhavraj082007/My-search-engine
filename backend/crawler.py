#!/usr/bin/env python3
"""
CLI web crawler – crawls a website and indexes pages into the search database.

Usage:
    python3 -m backend.crawler <start_url> [--max-pages 50] [--delay 1.0]
"""

import argparse
import sys
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

# Allow running as `python3 crawler.py` or `python3 -m backend.crawler`
try:
    from . import searchdb
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from backend import searchdb


USER_AGENT = "8searchBot/1.0"


def _robots_allowed(base_url: str, url: str) -> bool:
    """Check robots.txt for the target domain."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception:
        return True  # If we can't read robots.txt, allow
    return rp.can_fetch(USER_AGENT, url)


def _extract_text(html: str) -> tuple[str | None, str | None, list[str]]:
    """Parse HTML → (title, text_content, list_of_links)."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style elements
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    # Get visible text
    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = " ".join(text.split())

    # Extract links
    links = []
    for a in soup.find_all("a", href=True):
        links.append(a["href"])

    return title, text, links


def crawl(start_url: str, max_pages: int = 50, delay: float = 1.0) -> None:
    """Crawl starting from start_url, indexing up to max_pages."""
    searchdb.init_db()

    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc

    visited: set[str] = set()
    queue: list[str] = [start_url]
    indexed = 0

    print(f"🕷  Starting crawl at {start_url}")
    print(f"   Domain: {base_domain} | Max pages: {max_pages} | Delay: {delay}s")
    print()

    with httpx.Client(
        follow_redirects=True,
        timeout=15.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        while queue and indexed < max_pages:
            url = queue.pop(0)

            # Normalize
            url = url.split("#")[0]  # remove fragment
            if url in visited:
                continue
            visited.add(url)

            # Same domain only
            parsed = urlparse(url)
            if parsed.netloc != base_domain:
                continue

            # Check robots.txt
            if not _robots_allowed(start_url, url):
                print(f"  ⛔ Blocked by robots.txt: {url}")
                continue

            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    print(f"  ⚠  {resp.status_code} {url}")
                    continue
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    continue
            except Exception as e:
                print(f"  ❌ Error fetching {url}: {e}")
                continue

            title, text_content, links = _extract_text(resp.text)

            if text_content and len(text_content) > 50:
                searchdb.insert_page(url, title, text_content)
                indexed += 1
                print(f"  ✅ [{indexed}/{max_pages}] {title or '(no title)'} — {url}")
            else:
                print(f"  ⏭  Skipped (too little content): {url}")

            # Enqueue discovered links
            for href in links:
                abs_url = urljoin(url, href)
                abs_parsed = urlparse(abs_url)
                # Same domain, http(s) only
                if abs_parsed.netloc == base_domain and abs_parsed.scheme in ("http", "https"):
                    clean = abs_url.split("#")[0]
                    if clean not in visited:
                        queue.append(clean)

            if delay > 0:
                time.sleep(delay)

    print()
    print(f"✨ Crawl complete. Indexed {indexed} pages.")


def main():
    parser = argparse.ArgumentParser(description="Crawl a website and index pages for 8search.")
    parser.add_argument("url", help="Start URL to crawl")
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum pages to crawl (default: 50)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds (default: 1.0)")
    args = parser.parse_args()

    crawl(args.url, max_pages=args.max_pages, delay=args.delay)


if __name__ == "__main__":
    main()
