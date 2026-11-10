#!/usr/bin/env python3
"""
CLI healthcheck – test all camera URLs and mark their status.

Usage:
    python3 -m backend.healthcheck
"""

import asyncio
import sys
import os

import httpx

try:
    from . import camdb
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from backend import camdb


MAX_CONCURRENCY = 20


async def check_camera(
    client: httpx.AsyncClient,
    cam: dict,
    semaphore: asyncio.Semaphore,
    results: dict,
) -> None:
    """HEAD-request a single camera URL and update its status."""
    async with semaphore:
        cam_id = cam["id"]
        url = cam["url"]
        try:
            resp = await client.head(url, follow_redirects=True)
            if resp.status_code == 200:
                camdb.mark_status(cam_id, "working")
                results["working"] += 1
            else:
                camdb.mark_status(cam_id, "dead")
                results["dead"] += 1
        except Exception:
            camdb.mark_status(cam_id, "dead")
            results["dead"] += 1


async def run_healthcheck() -> None:
    """Check all non-dead cameras concurrently."""
    camdb.init_db()
    cameras = camdb.get_all_cameras(exclude_dead=True)
    total = len(cameras)

    if total == 0:
        print("No cameras to check.")
        return

    print(f"🏥 Health-checking {total} cameras (concurrency={MAX_CONCURRENCY})…")
    print()

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results = {"working": 0, "dead": 0}

    async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "8search-healthcheck/1.0"}) as client:
        tasks = [check_camera(client, cam, semaphore, results) for cam in cameras]

        done_count = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done_count += 1
            if done_count % 50 == 0 or done_count == total:
                pct = (done_count / total) * 100
                print(f"  [{done_count}/{total}] {pct:.0f}% — ✅ {results['working']} working, ❌ {results['dead']} dead")

    print()
    print("━" * 40)
    print(f"  ✅ Working: {results['working']}")
    print(f"  ❌ Dead:    {results['dead']}")
    print(f"  📊 Total:   {total}")
    print("━" * 40)


def main():
    asyncio.run(run_healthcheck())


if __name__ == "__main__":
    main()
