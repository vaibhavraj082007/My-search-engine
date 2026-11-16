#!/usr/bin/env python3
"""Seed click-popularity data for a demo query.

This is a local demo helper; it writes directly to ``data/clicks.db`` and does
not call the HTTP API. For a realistic demo, pass URLs that actually appear in
the search results you are testing.

Examples:
    # Seed 20 fake clicks for three URLs (position 5, capped by the ranker)
    python scripts/seed_clicks.py --query nmims \
        --click https://www.nmims.edu/ --click https://en.wikipedia.org/wiki/NMIMS

    # Give one URL 40 clicks and another 8
    python scripts/seed_clicks.py --query "python fastapi" \
        --click "https://fastapi.tiangolo.com/ = 40" \
        --click "https://www.python.org/ = 8"

    # Inspect and reset
    python scripts/seed_clicks.py --query nmims --show
    python scripts/seed_clicks.py --query nmims --reset

The ``URL = COUNT`` form is convenient when a shell URL contains ``=``.
"""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend import clicks  # noqa: E402
from backend.ranking import normalize_query, normalize_url  # noqa: E402

DEFAULT_URLS = [
    "https://www.nmims.edu/",
    "https://en.wikipedia.org/wiki/Narsee_Monjee_Institute_of_Management_Studies",
    "https://www.shiksha.com/college/nmims-mumbai-narsee-monjee-institute-of-management-studies-357",
]


def parse_click(value: str) -> tuple[str, int]:
    """Parse ``URL`` or ``URL = COUNT`` into (url, count)."""
    raw = value.strip()
    url = raw
    count = 20
    if "=" in raw:
        candidate_url, count_text = raw.rsplit("=", 1)
        try:
            count = int(count_text.strip())
            url = candidate_url.strip()
        except ValueError:
            # The "=" belongs to the URL's query string, not a click count.
            count = 20
    if not url.startswith(("http://", "https://")):
        raise argparse.ArgumentTypeError(
            f"click URL must start with http:// or https://: {url!r}"
        )
    if count < 1:
        raise argparse.ArgumentTypeError("click count must be positive")
    return url, count


def reset_query(query: str) -> None:
    query_norm = normalize_query(query)
    if not query_norm:
        return
    conn = clicks._get_db()
    try:
        conn.execute(
            "DELETE FROM result_stats WHERE query_norm = ?", (query_norm,)
        )
        conn.execute(
            "DELETE FROM click_events WHERE query_norm = ?", (query_norm,)
        )
        conn.commit()
    finally:
        conn.close()


def seed(query: str, entries: list[tuple[str, int]], position: int) -> int:
    query_norm = normalize_query(query)
    query_key = clicks._stats_query_key(query_norm, "web")
    now = datetime.now(timezone.utc)
    created_at = clicks._iso(now)
    added = 0

    for url, count in entries:
        url_norm = normalize_url(url)
        if not url_norm:
            print(f"skip invalid URL: {url}")
            continue
        for _ in range(count):
            session_hash = clicks._hash_value(
                "seed:" + uuid.uuid4().hex
            )
            recorded = clicks._record_click(
                query_key,
                url_norm,
                url_norm,
                position,
                session_hash,
                None,
                clicks._hash_value("ip:seed"),
                clicks._hash_value("ua:seed"),
                "web",
                created_at,
            )
            if recorded:
                added += 1

    return added


def show(query: str) -> None:
    rows = clicks.popular(query, "web", limit=50)
    if not rows:
        print("No clicks recorded for this query yet.")
        return
    print(f"Top clicked web results for {query!r}:")
    for rank, row in enumerate(rows, start=1):
        print(
            f"  {rank:>2}. {row['clicks']:>4} clicks  "
            f"score={row['popularity_score']:.4f}  {row['url']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed demo click data for 8search popularity ranking"
    )
    parser.add_argument("--query", default="nmims", help="demo query")
    parser.add_argument(
        "--click",
        action="append",
        type=parse_click,
        default=[],
        metavar="URL[=COUNT]",
        help="URL to seed; repeat for multiple URLs (default count 20)",
    )
    parser.add_argument(
        "--position",
        type=int,
        default=5,
        help="displayed position to simulate (default 5)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="override clicks.db path (default data/clicks.db)",
    )
    parser.add_argument(
        "--reset", action="store_true", help="clear this query before seeding"
    )
    parser.add_argument(
        "--show", action="store_true", help="show current top clicked URLs"
    )
    args = parser.parse_args()

    query = args.query.strip()
    if not query:
        raise SystemExit("--query cannot be empty")

    if args.db:
        clicks.DB_PATH = os.path.abspath(args.db)
    clicks.init_db()

    if args.reset:
        reset_query(query)
        print(f"Reset click data for {query!r}.")

    entries = args.click or [(url, 20) for url in DEFAULT_URLS]
    if args.click or not args.show:
        added = seed(query, entries, max(1, args.position))
        print(f"Added {added} demo clicks for {query!r} at position {args.position}.")
        print("Restart is not required; the next search re-ranks from this DB.")

    if args.show or args.click:
        print()
        show(query)


if __name__ == "__main__":
    main()
