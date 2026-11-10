#!/usr/bin/env python3
"""
Import all camera sources (or a single one by name).

Usage:
    python3 -m backend.import_all            # run all importers
    python3 -m backend.import_all finland     # run just one
"""

import sys
import os

try:
    from . import camdb
    from .importers import otcm, finland, newzealand, hongkong
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from backend import camdb
    from backend.importers import otcm, finland, newzealand, hongkong

ALL_IMPORTERS = [otcm, finland, newzealand, hongkong]


def main():
    camdb.init_db()

    # Optional: run a single source
    target = sys.argv[1].lower().strip() if len(sys.argv) > 1 else None

    importers_to_run = ALL_IMPORTERS
    if target:
        importers_to_run = [m for m in ALL_IMPORTERS if m.NAME == target]
        if not importers_to_run:
            available = ", ".join(m.NAME for m in ALL_IMPORTERS)
            print(f"❌ Unknown source: '{target}'")
            print(f"   Available: {available}")
            sys.exit(1)

    summary = []
    total = 0

    for importer in importers_to_run:
        try:
            count = importer.run()
            summary.append((importer.NAME, count, "✅"))
            total += count
        except Exception as e:
            summary.append((importer.NAME, 0, f"❌ {e}"))

    # Print summary table
    print()
    print("━" * 50)
    print(f"  {'Source':<20} {'Imported':>10}  Status")
    print("─" * 50)
    for name, count, status in summary:
        print(f"  {name:<20} {count:>10}  {status}")
    print("─" * 50)
    print(f"  {'TOTAL':<20} {total:>10}")
    print("━" * 50)


if __name__ == "__main__":
    main()
