#!/usr/bin/env python3
"""Simple asynchronous load test for the 8search API.

Examples:
    python scripts/load_test.py
    python scripts/load_test.py --requests 5000 --concurrency 200
    python scripts/load_test.py --url http://staging.example.com --query fastapi

For accurate results, start the target with RATE_LIMIT_PER_MINUTE=0. Otherwise
the per-IP limiter will intentionally return 429s.
"""

import argparse
import asyncio
import time

import httpx


def percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(len(sorted_values) * fraction))
    return sorted_values[index]


async def run_request(
    client: httpx.AsyncClient,
    query: str,
    latencies: list[float],
    errors: list[str],
) -> None:
    started = time.perf_counter()
    try:
        response = await client.get("/api/search", params={"q": query})
        if response.status_code == 200:
            latencies.append(time.perf_counter() - started)
        else:
            errors.append(str(response.status_code))
    except Exception as exc:
        errors.append(type(exc).__name__)


async def worker(
    client: httpx.AsyncClient,
    query: str,
    count: int,
    latencies: list[float],
    errors: list[str],
) -> None:
    for _ in range(count):
        await run_request(client, query, latencies, errors)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load test the 8search search API")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--query", default="python fastapi")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        raise SystemExit("--requests and --concurrency must be positive")

    latencies: list[float] = []
    errors: list[str] = []

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    async with httpx.AsyncClient(
        base_url=args.url,
        timeout=60.0,
        limits=limits,
    ) as client:
        # Warm the cache so the test measures serving capacity, not first-call cost.
        await client.get("/api/search", params={"q": args.query})

        started = time.perf_counter()
        tasks = []
        base, remainder = divmod(args.requests, args.concurrency)
        for index in range(args.concurrency):
            count = base + (1 if index < remainder else 0)
            if count:
                tasks.append(
                    asyncio.create_task(
                        worker(client, args.query, count, latencies, errors)
                    )
                )
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - started

    latencies.sort()
    served = len(latencies)
    throughput = served / elapsed if elapsed else 0.0

    print(f"Target       : {args.url}")
    print(f"Query        : {args.query!r}")
    print(f"Requests     : {args.requests} at concurrency {args.concurrency}")
    print(f"Duration     : {elapsed:.2f}s")
    print(f"Throughput   : {throughput:.1f} req/s")
    print(f"Successful   : {served}")
    print(f"Errors       : {len(errors)}")
    if errors:
        counts: dict[str, int] = {}
        for error in errors:
            counts[error] = counts.get(error, 0) + 1
        print(f"Error mix    : {counts}")
    if latencies:
        print(f"p50 latency  : {percentile(latencies, 0.50) * 1000:.1f} ms")
        print(f"p95 latency  : {percentile(latencies, 0.95) * 1000:.1f} ms")
        print(f"p99 latency  : {percentile(latencies, 0.99) * 1000:.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
