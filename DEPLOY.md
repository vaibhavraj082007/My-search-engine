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

## 7. Operations

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
