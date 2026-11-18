# Deploying 8search with HTTPS

This guide covers the production Docker stack in `docker-compose.prod.yml`:
Caddy terminates TLS, FastAPI runs on the private Docker network, and Redis
provides shared caches and rate limits. The same steps work with Nginx if you
already run one.

## 1. Point the domain at the server

Create an `A`/`AAAA` DNS record for the hostname you will use, for example
`search.example.com`. Ports **80** and **443** must be reachable so Caddy can
obtain a Let's Encrypt certificate.

## 2. Configure the environment

```bash
cp .env.production.example .env
```

Edit `.env` and set at least:

| Variable | Why |
| --- | --- |
| `APP_BASE_URL` | Exact public origin used in emails, OpenSearch and the manifest. No trailing slash. |
| `SITE_ADDRESS` | Domain Caddy serves. Use `localhost` only for an internal test. |
| `ACME_EMAIL` | Let's Encrypt registration address. |
| `TRUST_PROXY=1` | Honour `X-Forwarded-Proto`/`X-Forwarded-Host`/`X-Forwarded-For` from Caddy. |
| `FORCE_HTTPS=1` | Adds HSTS and treats proxied requests as HTTPS. |
| `COOKIE_SECURE=1` | Marks session and guest cookies `Secure`. |
| `ALLOWED_ORIGINS` | Exact HTTPS origin; do not use `*` with credentials. |
| `NEWS_ADMIN_TOKEN` | Protects `POST /api/news/refresh`. Generate a long random value. |
| `NEWS_CONTACT_EMAIL` | Contact address sent to publishers in the feed User-Agent. |
| `CLICK_TOKEN_SECRET` | Same long random value on every app replica. |

Generate secrets without leaving them in shell history:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Never expose the app's port 8000 directly. The production Compose file only
publishes Caddy's ports 80/443.

## 3. Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Watch the first news refresh and certificate issuance:

```bash
docker compose -f docker-compose.prod.yml logs -f web caddy
```

The news scheduler runs on startup, then checks every five minutes and replaces
the snapshot once it is six hours old. Existing snapshots keep being served
while a refresh runs.

## 4. Verify HTTPS, proxy headers and security headers

```bash
curl -I https://search.example.com/health
curl -I https://search.example.com/search?q=test
curl https://search.example.com/api/news | head
curl -s https://search.example.com/opensearch.xml | head
```

Expected:

- `200` from `/health`, with `Strict-Transport-Security` when HTTPS is active.
- `/search` returns `text/html`; the result page contains `noindex`.
- `/api/news` returns a JSON snapshot with real publisher links, or a clear
  empty message while the first refresh is still running.
- `/opensearch.xml` and `/manifest.webmanifest` use `https://search.example.com`.

Cookies should include `Secure; HttpOnly; SameSite=Lax`:

```bash
curl -I -X POST https://search.example.com/api/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}'
```

### News refresh

```bash
curl -X POST https://search.example.com/api/news/refresh \
  -H "Authorization: Bearer $NEWS_ADMIN_TOKEN"
```

Without a valid token the endpoint returns `403`. The same refresh runs
automatically every six hours.

### Feed health

Run this on the host or inside the container to validate every configured
publisher feed without writing the news database:

```bash
docker compose -f docker-compose.prod.yml exec web python scripts/check_news.py
```

It exits non-zero if fewer than 25 ranked stories are available.

## 5. Make 8search the browser default

Open `https://search.example.com/set-default`. It includes per-browser steps
for Chrome, Brave, Edge, Firefox and Safari, plus the OpenSearch URL template:

```
https://search.example.com/search?q=%s
```

Browsers that support OpenSearch can discover `/opensearch.xml` from the
homepage automatically. Safari does not allow arbitrary third-party search
engines in its own address bar; the page explains the homepage / Add to Home
Screen alternatives.

## 6. Nginx alternative

If Caddy is not an option, terminate TLS with Nginx and keep the app bound to
the private network. A minimal `server` block:

```nginx
server {
    listen 80;
    server_name search.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name search.example.com;

    ssl_certificate     /etc/letsencrypt/live/search.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/search.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host  $host;
        proxy_read_timeout 60s;
    }
}
```

Keep `TRUST_PROXY=1`, `FORCE_HTTPS=1` and `COOKIE_SECURE=1` set. Restrict
`FORWARDED_ALLOW_IPS` to the proxy address when it is not a Docker network.
Obtain certificates with Certbot or your existing ACME client.

## 7. Data durability and backups

All durable state lives in SQLite databases in `data/` (bind-mounted at
`/app/data`): accounts and sessions, click statistics, feedback, suggestion
counts and the news snapshot. The account, click, feedback, suggestion and
search databases run in WAL mode with `synchronous=FULL` and a 15-second busy
timeout, so a committed write survives a process crash or power loss on the
host. The news snapshot uses `synchronous=NORMAL` because it is replaceable
content that is refreshed every six hours.

### Automatic backups

The `backup` service in `docker-compose.prod.yml` writes a verified snapshot
every six hours (`BACKUP_INTERVAL_SECONDS`, default `21600`) to `backups/`.
Each snapshot uses SQLite's online backup API, so it is consistent even while
the app is serving traffic. A snapshot is published only after every database
passes `PRAGMA integrity_check` and has a SHA-256 checksum recorded in
`manifest.json`. Snapshots older than `BACKUP_KEEP_DAYS` (default 30) are
pruned, but the newest snapshot is always kept.

```bash
docker compose -f docker-compose.prod.yml logs -f backup
ls -lh backups/
cat backups/<timestamp>/manifest.json
```

### Manual backup and integrity check

```bash
# Write and verify a snapshot now (works while the app is running).
docker compose -f docker-compose.prod.yml exec web \
  python scripts/backup_data.py

# Verify the live databases without writing a snapshot.
docker compose -f docker-compose.prod.yml exec web \
  python scripts/backup_data.py --check-only
```

On a host without Docker, run the same commands from the repository root with
`DATA_DIR=/path/to/data BACKUP_DIR=/path/to/backups`.

### Restore

Restoring replaces live data. The tool first checks the manifest and every
checksum, then writes a safety backup of the current data before copying
anything.

```bash
# 1. Stop writes.
docker compose -f docker-compose.prod.yml stop web

# 2. Restore a verified snapshot.
docker compose -f docker-compose.prod.yml run --rm \
  -e DATA_DIR=/app/data -e BACKUP_DIR=/app/backups \
  web python scripts/restore_data.py /app/backups/<timestamp> --yes

# 3. Start the app and check health.
docker compose -f docker-compose.prod.yml start web
curl -fsS https://search.example.com/health
```

### Copy backups off the server

A backup on the same disk does not survive disk or host loss. Copy `backups/`
to object storage or another machine after each snapshot, for example:

```bash
# Run from cron on the host, once per hour.
rclone sync /srv/8search/backups remote:8search-backups
```

Use versioning or object-lock on the remote bucket so a compromised host cannot
delete the remote copies. Test a restore from the offsite copy before launch,
and again at least once a month. Also copy `data/.click_secret` (included in
each snapshot): losing it invalidates outstanding click tokens, and changing it
should be treated as a key rotation.

### Monitoring and alerts

- Point an uptime monitor at `/health` (liveness) and `/ready` (readiness) from
  outside the host, and alert after two consecutive failures.
- Alert on disk usage above 80%, on a missing backup for more than 12 hours,
  and on any `integrity_check` result other than `ok`.
- Container logs use the `json-file` driver capped at 10 MB × 5 files per
  service, so a log flood cannot fill the disk.
- `restart: unless-stopped` plus the Compose health checks restart a crashed or
  hung web process automatically. `stop_grace_period: 40s` lets in-flight
  requests finish on deploy.
- Keep the host clock synced (NTP). Session expiry and click decay rely on it.

### Capacity for 50,000 users over 50 days

50,000 users over 50 days is about 1,000 users per day and roughly 0.01 average
requests per second. The real risks are launch-day bursts and shared NAT, not
steady-state throughput:

- `RATE_LIMIT_PER_MINUTE=600` and `SUGGEST_RATE_LIMIT_PER_MINUTE=1200` are
  per-IP budgets sized for offices, campuses and mobile carriers that put many
  users behind one address. Increase them only together with monitoring.
- `WEB_CONCURRENCY=4` handles ordinary traffic on a 2 vCPU / 4 GB host. Redis
  keeps caches and rate-limit counters shared across workers.
- SQLite in WAL mode handles this write volume comfortably on one host. Do not
  run multiple app containers against the same `data/` directory. To scale
  horizontally, move sessions and clicks to PostgreSQL first; see
  [SCALING.md](SCALING.md).
- Run the load test against staging before launch:
  `python scripts/load_test.py --url http://127.0.0.1:8000 --requests 2000 --concurrency 100`.
- Keep at least 20% free disk space. A full disk is the most common way a
  SQLite-backed service stops accepting writes.

### Deploy and upgrade checklist

1. Confirm the latest backup is present and its manifest says `ok`.
2. `docker compose -f docker-compose.prod.yml up -d --build`
3. Watch `web` become healthy, then run the checks in section 4.
4. Search once, open a result, and confirm news still loads.
5. If anything is wrong: stop `web`, restore the previous snapshot, start `web`.

## 8. Operations

- **Back up `/app/data`** (`data/` on the host): users, sessions, feedback,
  clicks, suggestions and the news snapshot all live there.
- **Restart** with `docker compose -f docker-compose.prod.yml restart web`.
- **Scale** app replicas only after moving users/sessions/clicks to shared
  storage and setting the same `CLICK_TOKEN_SECRET` everywhere. See
  [SCALING.md](SCALING.md).
- **Rate limits**: `RATE_LIMIT_PER_MINUTE` applies to API requests, while
  `SUGGEST_RATE_LIMIT_PER_MINUTE` keeps the autocomplete endpoint responsive.
  Neither suggestions nor news consume the guest search quota.
- **Guest quota**: `GUEST_SEARCH_LIMIT` defaults to 4. Changing it affects new
  guest cookies; existing guests keep their current count.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Certificate not issued | DNS points at the server and ports 80/443 are open. |
| Redirect loop | `TRUST_PROXY=1` is set and the proxy sends `X-Forwarded-Proto: https`. |
| Cookies not persisted | `APP_BASE_URL` matches the browser origin and `COOKIE_SECURE=1` is only used over HTTPS. |
| News is empty | Check `docker compose logs web` for feed failures, then run `scripts/check_news.py`. |
| `403` from `/api/news/refresh` | `NEWS_ADMIN_TOKEN` is set and the request sends the same Bearer token. |
| `502` from search | Third-party providers are slow or blocked; check outbound HTTPS access. |
