# Scaling 8search

## Short answer

No single server process can hold 500,000 *simultaneous* users. Reaching that
number is an infrastructure and budget decision, not a code toggle. This repo
now has the application-side pieces needed to scale horizontally and to degrade
safely when traffic exceeds capacity:

- async search pipeline with one pooled HTTP client per worker
- shared TTL cache with single-flight (popular queries hit upstream once)
- Redis support for cache and rate limits across workers and replicas
- bounded upstream concurrency, request timeouts, and 429 responses instead of
  crashing when demand is too high
- gzip compression and long-lived caching for versioned static assets
- Docker image and Compose stack (app + Redis)

## Current request path

```
Browser
  │
  ├── static HTML/CSS/JS ──► CDN in production (long cache for ?v= assets)
  │
  └── /api/search ──► load balancer
                        │
                        ├── app replica 1 ─┐
                        ├── app replica 2 ─┼──► Redis (cache + rate limits)
                        └── app replica N ─┘
                                              │
                                              ├── Wikipedia / Wiktionary
                                              ├── YouTube
                                              └── search provider
```

## What the code already protects against

- **Traffic spikes:** `RATE_LIMIT_PER_MINUTE` returns HTTP 429 per client IP
  before work starts.
- **Cache stampedes:** concurrent requests for the same query share a single
  upstream computation.
- **Pagination:** each upstream result page is cached separately and sliced from
  one de-duplicated pool, so page N never repeats page N-1's URLs. Page 2+ skips
  the news/Wikipedia/video enrichment work, and pagination does not consume
  guest search quota.
- **Slow providers:** every source has its own timeout (`SEARCH_TIMEOUT`,
  `NEWS_TIMEOUT`, `META_TIMEOUT`, `VIDEO_TIMEOUT`). A slow provider is skipped
  and the rest of the page still renders with partial results.
- **Blocking scrapers:** DDGS runs in bounded threads (`DDGS_CONCURRENCY`) with
  a hard timeout, so a burst of unique queries cannot exhaust the thread pool.
- **Provider overload:** only `SEARCH_CONCURRENCY` upstream searches run at a
  time per worker. Others wait up to `SEARCH_QUEUE_TIMEOUT`, then get 503.
- **Provider failures:** Wikipedia, Wiktionary, YouTube, DuckDuckGo, and Bing
  are independent. A missing section does not break the page.
- **Static asset load:** versioned assets are cached for a year; HTML is
  revalidated. Gzip is enabled.

## Sizing math (important)

500,000 concurrent *users* is not 500,000 requests per second. If 10% of them
search once per minute, that is ~833 searches/second. With a 90% cache hit rate,
the origin only handles ~83 upstream searches/second. Use real numbers from
your analytics and a load test before buying infrastructure.

As a starting point for 1,000 search requests/second:

| Component | Starting point |
|---|---|
| App replicas | 4–8 × 2 vCPU, 2–4 GB RAM |
| Redis | 1–2 GB, `allkeys-lru` |
| Postgres | Managed instance with connection pooling |
| CDN | Static frontend + TLS |
| Load balancer | HTTP/2, health checks on `/health` |
| Search API | Paid plan sized for cache misses |

Autoscale on CPU and request latency, not raw request count.

## What must change before a real 500k-user launch

1. **Database:** `data/users.db` is SQLite. It is fine for local development and
   a single host, but it cannot be shared safely across replicas. Move users,
   sessions, and reset tokens to Postgres (or another managed database) and put
   connection pooling in front of it. This is the main remaining app change.
2. **Search provider:** DuckDuckGo/Bing HTML and RSS endpoints are convenient
   for a demo but are not licensed, SLA-backed, high-volume APIs. Use a paid
   provider (Brave Search API, Bing Web Search, Google Programmable Search,
   SerpAPI, etc.) and put its key in the environment.
3. **YouTube:** scraping YouTube's results page will be blocked at scale. Use
   the YouTube Data API (quota-managed) or a video search provider.
4. **Email:** login alerts and reset emails run as in-process background tasks.
   Move them to a queue/worker (Celery, RQ, SQS, Cloud Tasks) so SMTP outages
   and retries never touch web workers.
5. **Sessions:** cookie sessions are stateless from the app's perspective, but
   they still require the shared database above. Consider short-lived signed
   tokens plus a Redis session store if you need instant revocation.
6. **Observability:** add structured logs, request IDs, metrics (cache hit rate,
   p95 latency, 429/503 counts), and alerts. The `/health` and `/ready`
   endpoints are ready for load balancers.
7. **Load test:** run k6, Locust, or `scripts/load_test.py` against a staging
   environment that mirrors production. Tune `SEARCH_CONCURRENCY`,
   `RATE_LIMIT_PER_MINUTE`, worker count, and cache TTL from the results.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WEB_CONCURRENCY` | `4` (Docker) | Uvicorn worker processes |
| `REDIS_URL` | unset | Shared cache + rate limits; required for multiple replicas |
| `SEARCH_CACHE_TTL` | `300` | Seconds to cache a search payload |
| `RESULTS_PER_PAGE` | `10` | Results shown per page (capped at 10) |
| `MAX_SEARCH_PAGE` | `10` | Last page users can open |
| `UPSTREAM_RESULTS_PER_PAGE` | `15` | Max results pulled from each upstream page |
| `WEB_CHUNK_CACHE_TTL` | `900` | Seconds an upstream result chunk stays cached |
| `WEB_CHUNK_EMPTY_CACHE_TTL` | `30` | Seconds an empty/failed upstream chunk is negatively cached |
| `SEARCH_EMPTY_CACHE_TTL` | `30` | Seconds an empty result page is negatively cached |
| `CACHE_MAX_ITEMS` | `5000` | In-memory cache entries per worker |
| `SEARCH_CONCURRENCY` | `64` | Concurrent upstream searches per worker |
| `SEARCH_QUEUE_TIMEOUT` | `5` | Seconds to wait for an upstream slot |
| `SEARCH_TIMEOUT` | `15` | Web-search budget per request |
| `NEWS_TIMEOUT` | `6` | News budget per request |
| `META_TIMEOUT` | `5` | Wikipedia/Wiktionary/answer budget |
| `ANSWER_SOURCE_TIMEOUT` | `4` | Per-source budget inside the answer block |
| `VIDEO_TIMEOUT` | `6` | Video budget per request |
| `DDGS_CONCURRENCY` | `6` | Blocking DDGS scrapes allowed at once per worker |
| `DDGS_TIMEOUT` | `4` | Hard timeout for a blocking DDGS scrape |
| `DDGS_RETRY_DELAY` | `0.4` | Seconds to wait before retrying a short DDGS page |
| `UPSTREAM_MIN_RESULTS` | `5` | Retry DDGS when a page returns fewer results than this |
| `DDGS_VIDEO_CONCURRENCY` | `3` | Blocking video fallbacks allowed at once |
| `DDGS_VIDEO_TIMEOUT` | `4` | Hard timeout for a video fallback |
| `RATE_LIMIT_PER_MINUTE` | `120` | Per-IP API requests per minute (`0` disables) |
| `TRUST_PROXY` | `0` | Set `1` behind a trusted load balancer |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |
| `DISABLE_LOCAL_INDEX` | `0` | Set `1` to skip the local SQLite FTS index |
| `HTTP_MAX_CONNECTIONS` | `200` | Pooled outbound connections per worker |

## Run the scaled stack locally

```bash
docker compose up --build
# open http://localhost:8000
```

Redis is optional for a single process:

```bash
uvicorn backend.main:app --reload
```

## Load test

```bash
# start the app first, ideally with RATE_LIMIT_PER_MINUTE=0 for the test
python scripts/load_test.py --url http://127.0.0.1:8000 --requests 2000 --concurrency 100
```

The script reports throughput, p50/p95/p99 latency, and error counts. Run it
against staging, not production.
