#!/usr/bin/env python3
"""Check the configured publisher feeds without touching the news database.

Usage:
    python scripts/check_news.py
    python scripts/check_news.py --json
    python scripts/check_news.py --max-feeds 10

Exit code 0 means at least ``--min-items`` clean, recent stories were parsed
and enough of them survived ranking for a full 25-story snapshot.
"""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import news  # noqa: E402
from backend.news_ranking import dedupe_items  # noqa: E402
from backend.news_sources import FEEDS  # noqa: E402


async def run(max_feeds: int | None, min_items: int) -> int:
    feeds = FEEDS[:max_feeds] if max_feeds else FEEDS
    now = datetime.now(timezone.utc)
    raw_items, stats = await news.collect_items(now=now, feeds=feeds)
    clean = dedupe_items(raw_items)
    selected = news._rank_for_snapshot(clean, now, set())

    categories = Counter(item["category"] for item in selected)
    sources = Counter(item["source"] for item in selected)
    payload = {
        "checked_at": now.isoformat(),
        "feeds_checked": len(feeds),
        "feeds_ok": stats["feeds_ok"],
        "feeds_failed": len(stats["failures"]),
        "raw_items": stats["raw_items"],
        "clean_unique_items": len(clean),
        "selected_for_snapshot": len(selected),
        "categories": dict(categories),
        "sources": dict(sources.most_common(10)),
        "failures": stats["failures"],
    }

    if "--json" in sys.argv:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Feeds checked:          {payload['feeds_checked']}")
        print(f"Feeds responding:       {payload['feeds_ok']}")
        print(f"Feeds failed:           {payload['feeds_failed']}")
        print(f"Raw stories:            {payload['raw_items']}")
        print(f"Unique clean stories:   {payload['clean_unique_items']}")
        print(f"Selected for snapshot:  {payload['selected_for_snapshot']}")
        print(f"Categories:             {json.dumps(payload['categories'])}")
        if payload["failures"]:
            print("\nFeed failures:")
            for failure in payload["failures"]:
                print(f"  - {failure}")

    if len(selected) < min_items:
        print(
            f"\nERROR: only {len(selected)} ranked stories; "
            f"need at least {min_items}.",
            file=sys.stderr,
        )
        return 1
    if stats["feeds_ok"] == 0:
        print("\nERROR: no feed responded.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-feeds",
        type=int,
        default=None,
        help="Only check the first N configured feeds (useful for a smoke test).",
    )
    parser.add_argument(
        "--min-items",
        type=int,
        default=25,
        help="Minimum number of ranked stories required (default: 25).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()
    return asyncio.run(run(args.max_feeds, args.min_items))


if __name__ == "__main__":
    raise SystemExit(main())
