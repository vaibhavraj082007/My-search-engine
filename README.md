<p align="center">
  <img src="frontend/assets/logo.png" alt="8search logo" width="260" />
</p>

<h1 align="center">8search</h1>

<p align="center">
  <b>A next-generation search engine with a live interactive satellite globe.</b><br/>
  Search the web like Google · Explore the Earth like Google Earth.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Leaflet-globe-199900?logo=leaflet&logoColor=white" alt="Leaflet" />
  <img src="https://img.shields.io/badge/licence-MIT-green" alt="MIT Licence" />
</p>

---

## 🌍 What is 8search?

**8search** is a full-featured web search engine inspired by Google and Chrome, combined with a stunning **live interactive satellite globe** right below the search bar.

### 🔎 Search — Unlimited, Fast, Yours

- Type any query and get results instantly — just like Google.
- Type a URL (like `example.com`) and navigate directly — just like Chrome's address bar.
- **Every user gets 4 free searches without signing in.**
- After 4 searches → a friendly prompt asks the user to **log in or create a free account**.
- Once logged in → **unlimited searches, forever, no limits.**
- **Click-popularity ranking:** links people open most for a query rise to the top, with position-bias correction and time decay.
- Powered by your own crawler and full-text search index — you control what's indexed.

### 🌐 The Globe — Interactive 3D Earth

Right below the search bar sits a **3D satellite globe** that users can spin and zoom:
- **3D Globe / Flat map** toggle
- **Satellite / Street imagery** toggle
- **Live USGS Earthquake overlay** showing recent seismic activity
- **Current Location Weather**: quick shortcut on the homepage shows the live forecast for your current location.

---

## ✨ Feature Overview

| Feature | Guest (no login) | Logged-in User |
| --- | :---: | :---: |
| Web search | ✅ 4 searches | ✅ **Unlimited** |
| Click-popularity ranking (learns from result clicks) | ✅ | ✅ |
| URL navigation (like Chrome) | ✅ | ✅ |
| Interactive satellite globe | ✅ | ✅ |
| Current location live weather | ✅ | ✅ |
| Earthquake overlay (USGS) | ✅ | ✅ |
| Globe/Flat & Map/Satellite toggle | ✅ | ✅ |
| Search history & preferences | ❌ | ✅ |
| In-app Lens camera (QR, text, homework, translate) | ✅ | ✅ |

---

## 🖼️ How It Looks

```
┌─────────────────────────────────────────────────────────┐
│  🔍  [  Search the web or type a URL...            ]    │
│       ──────────────────────────────────────────         │
│                                                         │
│               ┌──────────────────────┐                  │
│              /    🌐 SATELLITE GLOBE   \                │
│             /   Spin and zoom the 3D    \               │
│            |    Earth with satellite &   |              │
│            |    earthquake layers        |              │
│             \                          /               │
│              \                        /                │
│               └──────────────────────┘                  │
│                                                         │
│  [ 🌐 Globe/Flat ]  [ 🗺️ Map/Satellite ]  [ 🔴 Quakes ]│
└─────────────────────────────────────────────────────────┘
```

---

## 🏗️ Architecture

```
8search/
├── frontend/                    # The browser app
│   ├── index.html               # Main page: search bar + globe
│   ├── style.css                # Colours, layout, dark theme
│   ├── app.js                   # Search logic, login state, UTC clock
│   ├── map.js                   # Globe, map layers, current weather panel
│   ├── lens.js                  # In-app camera, QR scanning, OCR, Lens panel
│   ├── vendor/jsQR.js           # Local QR fallback decoder
│   ├── login.html               # Login page
│   └── signup.html              # Sign-up page
│
├── backend/                     # Python FastAPI server
│   ├── main.py                  # App entry point, routes, CORS, static files
│   ├── auth.py                  # User accounts (salted password hashing)
│   ├── search_api.py            # Search endpoint (full-text search)
│   ├── ranking.py               # Click normalisation, decay, position bias, ordering
│   ├── clicks.py                # Click storage, HMAC tokens, anti-abuse, /api/click
│   ├── searchdb.py              # Search index database
│   ├── crawler.py               # Web crawler (respects robots.txt)
│   ├── lens.py                  # /api/solve (SymPy) and /api/translate
│   └── data/                    # (legacy location; runtime data lives in ../data)
│
├── data/                        # Auto-created: users, search, feedback, clicks SQLite DBs
├── tests/                       # pytest suite for ranking and click anti-abuse
├── scripts/seed_clicks.py       # Demo click data for the ranking
├── requirements.txt             # Python dependencies
├── requirements-dev.txt         # Test dependencies (pytest)
└── README.md                    # ← You are here
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** — check with `python3 --version`
- **Terminal** (macOS: Cmd+Space → "Terminal")

### 1. Clone & Enter the Project

```bash
cd ~/Desktop/8search
```

### 2. Create a Virtual Environment & Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # Do this every time you open a new terminal
pip install -r requirements.txt
```

### 3. Start the Server

Run this from the **project root** (not from inside `backend/`):

```bash
uvicorn backend.main:app --reload
```

### 4. Open in Your Browser

👉 **http://localhost:8000**

That's it. Search, spin the globe, and explore the Earth.

---

## 🔍 How Search Works

8search is an **answer-first search page**. For each query it builds:

1. **Quick answer / meaning** — a short overview with a **Show more** expander.
   Single words use a Wiktionary definition; topics use Wikipedia.
2. **Wikipedia card** — the matching article, with a direct link.
3. **Videos** — YouTube results with thumbnails, duration, and channel.
4. **Web links** — DuckDuckGo results, supplemented by Bing's RSS endpoint
   when a provider is rate-limited.
5. **In the news** — recent articles and images when available.

Every enrichment is fetched independently, so a missing Wikipedia article or
video section never breaks the rest of the page. Providers are raced against a
short time window, so one slow source cannot hold up the page.

Repeat searches are served from a 5-minute server cache and the browser's
session cache. Going back to an earlier query is instant (typically 20–60 ms
with no network call). A **cold** live-web search still takes roughly a second
because the third-party providers must be queried; no search engine can return
fresh live-web results in literal milliseconds.

### Indexing Pages (optional local index)

8search also ships with its own crawler and FTS5 index. You can add pages:

```bash
python crawler.py https://en.wikipedia.org/wiki/Mumbai
```

After crawling, matching pages are merged into web results.

### Search Behaviour

| Input | What happens |
| --- | --- |
| `example.com` | Navigates directly (like Chrome) |
| `dark web` | Answer + Wikipedia + videos + web links |
| `serendipity` | Dictionary meaning + Wikipedia + videos + links |
| Any query after 4 searches (guest) | Prompts to log in |
| Any query after login | Unlimited results |

### Rate Limiting (Guest vs Logged-in)

- **Guests:** 4 searches per session. After that, a non-intrusive banner asks them to sign in.
- **Logged-in users:** Unlimited searches. No caps. No throttle. No ads. Ever.
- **High-traffic protection:** per-IP API limiting, shared caching, and bounded
  upstream concurrency keep the site responsive under load. See
  [SCALING.md](SCALING.md) for the production path to 500k users.

---

## 🔥 Click-Popularity Ranking

8search learns from the results people actually open. For each query it keeps
aggregate click statistics per URL and uses them to re-order the merged result
list. A result with real clicks moves above results nobody clicks; results with
no data keep the search provider's original order, so a brand-new query behaves
exactly as before.

### How it works

1. **Normalise.** Queries are lowercased, Unicode-normalised, punctuation-free,
   and whitespace-collapsed (`NMIMS`, `nmims`, and `N.M.I.M.S` share one key).
   URLs are lowercased, stripped of `www.`, tracking parameters, fragments, and
   trailing slashes, with `http`/`https` unified.
2. **Count impressions.** Every `/api/search` response records one impression
   per returned web, video, and news URL. Writes are buffered and flushed in
   batches, never on the request path.
3. **Accept only real clicks.** Each result carries a short-lived HMAC token
   binding the query, URL, kind, and displayed position. `POST /api/click`
   rejects missing/expired/forged tokens, and a URL that was not shown cannot be
   clicked. Web, video, news, Wikipedia, and quick-answer clicks use separate
   stats namespaces, so the always-on answer cards cannot boost web links.
4. **Correct for position bias.** A click at position 8 is worth more than a
   click at position 1 because top slots get accidental clicks. The weight is
   `expected_ctr(1) / expected_ctr(position)`, capped at about 5×.
5. **Decay and smooth.** Clicks decay exponentially with a 30-day half-life.
   The score is `(decayed_weighted_clicks + prior_clicks * prior_rate) /
   (impressions + prior_impressions)`, so one lucky click cannot beat a result
   with many clicks.
6. **Re-rank after the cache.** The five-minute cache stores the raw provider
   payload, never the ranked order. Ranking runs on every request, so a click
   changes the next search immediately. Ties and cold-start results fall back
   to the provider order.

A small global URL boost helps a generally popular result beat an unknown one
when the query itself has no data for either. All constants are in
`backend/ranking.py` and can be overridden with environment variables.

### Privacy and anti-abuse

- Only salted one-way hashes of IP addresses, user agents, sessions, and (for
  logged-in users) account identifiers are stored. Raw IPs are never written.
- A session can count the same query + URL at most once per hour.
- Per-IP and per-session click rate limits sit on top of the global API limiter.
- Known crawler/bot user agents are ignored.
- Click history is never exposed to other users. `/api/popular` returns only
  aggregate counts; `/api/ranking/debug` requires `RANKING_DEBUG_TOKEN`.

### Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/search?q=...` | GET | Adds `rank_source`, `click_count`, `popularity_score`, `click_position`, and `click_token` to results |
| `/api/click` | POST | Record a clicked result; returns `204` immediately and writes in a background task |
| `/api/popular?q=...` | GET | Top clicked URLs for a query (`kind=web\|video\|news\|answer\|wiki`) |
| `/api/ranking/debug?q=...&token=...` | GET | Protected config + click stats for debugging |

### Demo data

Use the seed script to make the effect visible while developing:

```bash
python scripts/seed_clicks.py --query nmims \
  --click https://www.nmims.edu/ \
  --click https://en.wikipedia.org/wiki/Narsee_Monjee_Institute_of_Management_Studies

python scripts/seed_clicks.py --query nmims --show
```

### Tests

```bash
pip install -r requirements-dev.txt
./venv/bin/pytest -q
```

### Ranking configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLICKS_DB_PATH` | `data/clicks.db` | Click SQLite database |
| `CLICK_TOKEN_SECRET` | generated in `data/.click_secret` | HMAC key; set the same value on every replica |
| `CLICK_SECRET_PATH` | `data/.click_secret` | Where the generated HMAC key is stored when the secret is not set |
| `CLICK_TOKEN_TTL_SECONDS` | `21600` | Signed click-token lifetime |
| `CLICK_DEDUPE_SECONDS` | `3600` | Same session/query/URL dedupe window |
| `CLICK_RATE_PER_MINUTE` | `60` | Per-IP click reports per minute |
| `CLICK_SESSION_RATE_PER_MINUTE` | `20` | Per-session click reports per minute |
| `CLICK_HALF_LIFE_DAYS` | `30` | Exponential click decay |
| `MAX_POSITION_WEIGHT` | `5` | Cap on position-bias correction |
| `RANK_PRIOR_CLICKS` | `1` | Smoothing prior clicks |
| `RANK_PRIOR_CLICK_RATE` | `0.05` | Smoothing prior click rate |
| `RANK_PRIOR_IMPRESSIONS` | `10` | Smoothing prior impressions |
| `RANK_GLOBAL_BOOST_WEIGHT` | `0.002` | Boost for globally popular URLs with no query data |
| `RANK_GLOBAL_BOOST_REFERENCE_CLICKS` | `100` | Global click count that earns the full boost |
| `CLICK_RETENTION_DAYS` | `90` | Raw click-event retention |
| `CLICK_CLEANUP_INTERVAL_SECONDS` | `21600` | Decay/prune job cadence |
| `IMPRESSION_FLUSH_SECONDS` | `5` | Impression batch flush interval |
| `IMPRESSION_BATCH_SIZE` | `200` | Buffered impression keys that trigger an early flush |
| `RANKING_DEBUG` | `0` | Set `1` to log rank details |
| `RANKING_DEBUG_TOKEN` | unset | Enables `/api/ranking/debug` |

---

## 📷 8search Lens — In-App Visual Search

The camera button next to the search bar opens a **Lens-style camera inside
8search**. Nothing is redirected to Google Lens, and the photo stays in the
browser; only the text you choose to solve or translate is sent to the server.

| In the camera | What happens |
| --- | --- |
| **QR codes & barcodes** | Detected automatically, with the result shown in the panel. URLs get an **Open link** button; Wi-Fi codes show the network and password (with copy); contact cards and plain text can be copied. |
| **Text** | OCR reads the photo, then you can **copy**, **listen** (speech synthesis), search the text on 8search, or **translate** it. |
| **Homework / math** | Equations are solved with **SymPy** and shown with the detected expression and step-by-step working. Supports linear equations, quadratics, equation systems separated by `;` or new lines, percentages (`15% of 80`), derivatives, and integrals. |
| **Translation** | Choose from 29 languages. The recognized text is translated by `/api/translate` and can be copied or read aloud. |
| **Photos** | **Retake** or **New scan** returns to the live camera. Upload a photo as a fallback when camera access is blocked. |

### Camera details

- Live preview uses `getUserMedia`; the rear camera is preferred and a **switch
  camera** button flips between front and rear. Flashlight is shown when the
  device supports it.
- QR detection uses the browser's native `BarcodeDetector` when available and
  falls back to the local `frontend/vendor/jsQR.js`, so QR scanning works in
  Chrome, Edge, and Safari-style browsers. jsQR 1.4.0 is vendored under the
  Apache-2.0 licence (see `frontend/vendor/README.md`).
- Text recognition uses **Tesseract.js 5.1.1**, loaded from jsDelivr on first
  use. The first OCR run therefore needs an internet connection; afterwards the
  worker is reused for the rest of the session.
- Photos are downscaled before OCR to keep recognition fast. Capture, OCR, and
  QR decoding all happen locally.
- The URL/Wi-Fi/contact parsing and clipboard actions are implemented in
  `frontend/lens.js`; math and translation are the only server calls.

> **Requirements:** camera access needs **HTTPS** (or `localhost`). On a phone,
> open the site over HTTPS or via your computer's local address with a trusted
> certificate; browsers block `getUserMedia` on plain HTTP origins.
>
> **Scope:** this is an in-app approximation of Lens — QR, OCR, homework, and
> translation. It does not use Google's proprietary visual product database, so
> recognizing an object from the image alone (without readable text) is not
> included.

---

## 🌐 The Globe — Interactive Satellite Map

The satellite globe is the centrepiece of 8search. It sits directly below the search bar.

### Controls

| Control | Action |
| --- | --- |
| 🖱️ Drag | Spin the globe |
| 🔄 Scroll | Zoom in / out |
| `Globe / Flat` button | Toggle 3D globe or flat map |
| `Map / Satellite` button | Toggle street map or satellite imagery |
| `Earthquakes` button | Show last 24 hours of M2.5+ earthquakes (USGS) |

---

## 👤 User Accounts

| Feature | Details |
| --- | --- |
| Sign up / sign in | Email + password (8+ characters) |
| Password storage | bcrypt hash only (never plain text) |
| Password reset | Single-use emailed link, valid for 30 minutes |
| Signup welcome | Account-ready email after the first signup |
| Login alerts | Formal security email after every successful sign-in |
| Sign-out notice | Confirmation email after signing out |
| Help path | Every security email includes an "if this wasn't you" link that opens an email to `FEEDBACK_EMAIL` |
| Feedback | Form at the bottom of the site emails submissions to the owner |
| Data location | Local SQLite in `data/` |
| Session | HttpOnly cookie (30 days) |

### ✉️ Email setup (welcome, sign-in, sign-out, reset & feedback)

Copy `backend/.env.example` to `backend/.env` and fill in your SMTP details:

| Variable | Example | Notes |
| --- | --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` | Your provider's SMTP server |
| `SMTP_PORT` | `587` | `465` with `SMTP_SECURITY=ssl` |
| `SMTP_USER` | `you@gmail.com` | SMTP login |
| `SMTP_PASSWORD` | app password | For Gmail, create an App Password |
| `SMTP_FROM` | `"8search <you@gmail.com>"` | Sender shown in the email |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl`, or `none` |
| `APP_BASE_URL` | `http://localhost:8000` | Used to build reset links |
| `FEEDBACK_EMAIL` | `you@gmail.com` | Inbox that receives feedback submissions |

> `SMTP_USER` must be the Google account that created the App Password. `FEEDBACK_EMAIL` can be a different address if you want feedback delivered somewhere else.

> **Local development:** if SMTP is not configured, every email — including the password-reset link — is printed to the server console. Password resets still work end-to-end.

> **Feedback:** submissions from the form at the bottom of the homepage are saved to `data/feedback.db` and emailed to `FEEDBACK_EMAIL`. Each IP address has a 30-second cooldown.

> **Account emails:** signup, sign-in, and sign-out notices include the time, IP address, device, and a support link; sign-in alerts also include a password-reset link. Emails are sent after the response, so an SMTP outage never blocks signup, login, logout, or feedback.

Accounts unlock **unlimited searches** and will power future features like search history, bookmarks, and personalized globe settings.

---

## 🛠️ API Reference

While the server is running, visit **http://localhost:8000/docs** for the full interactive Swagger UI.

Key endpoints:

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/search?q=...` | GET | Answer-first web search (cached, rate-limited, click-ranked) |
| `/api/click` | POST | Record a clicked result (HMAC token, background write, `204`) |
| `/api/popular?q=...` | GET | Top clicked URLs for a query |
| `/api/ranking/debug?q=...&token=...` | GET | Protected ranking diagnostics |
| `/api/solve` | POST | Solve math/equations from recognized text (SymPy, with steps) |
| `/api/translate` | POST | Translate recognized text into a chosen language |
| `/api/signup` | POST | Create account |
| `/api/login` | POST | Log in (sends a sign-in alert email) |
| `/api/logout` | POST | Log out |
| `/api/me` | GET | Current user info |
| `/api/forgot-password` | POST | Email a password-reset link |
| `/api/reset-password` | POST | Set a new password with a reset token |
| `/api/feedback` | POST | Store feedback and email it to `FEEDBACK_EMAIL` |
| `/health` | GET | Liveness probe for load balancers |
| `/ready` | GET | Readiness probe (reports cache backend) |

---

## 🐛 Troubleshooting

| Problem | Solution |
| --- | --- |
| `command not found: python3` | Install Python 3.9+ from [python.org](https://www.python.org/downloads/) |
| `No module named fastapi` | Activate the venv: `source venv/bin/activate` |
| Blank globe | Open browser console (Cmd+Option+J) and check for errors |
| Camera button shows "Camera unavailable" | Allow camera access for the site, or upload a photo instead. `getUserMedia` requires HTTPS or `localhost`. |
| OCR does not start | Tesseract.js is loaded from jsDelivr on first use — check the internet connection and any content blockers. |
| Math answer says "No solvable math expression" | Keep the equation in the frame and avoid glare; retake the photo or type it into the search bar. |

---

## ⚠️ Before Going Public

> [!IMPORTANT]
> The current setup is designed for **local development and learning**. Before deploying to real users:

- **Database:** SQLite is fine for one host. Move users/sessions/reset tokens and the click store to Postgres before running multiple app replicas.
- **Click ranking:** set `CLICK_TOKEN_SECRET` to the same value on every replica and move click events/stats to shared storage. See [SCALING.md](SCALING.md).
- **Search provider:** DuckDuckGo/Bing HTML and RSS endpoints are demo-grade. Use a paid search API with an SLA for real traffic.
- **YouTube:** scraping results pages will be blocked at scale. Use the YouTube Data API.
- **Map tiles:** OpenStreetMap and Esri tiles have usage limits. Switch to a commercial tile provider for heavy traffic.
- **Authentication:** Add HTTPS, rate-limit failed logins, and consider OAuth for production.
- **Crawler:** Maintain the 1-second delay and always respect `robots.txt`.

See **[SCALING.md](SCALING.md)** for the full production architecture, sizing
math, environment variables, and load-test instructions.

---

## 🗺️ Roadmap

- [x] Full-text web search with own crawler
- [x] 4-search guest limit → login for unlimited
- [x] Interactive satellite globe below search bar
- [x] Earthquake overlay (USGS)
- [x] In-app Lens camera: QR, OCR, homework solving, translation
- [x] User accounts with secure password hashing
- [x] Click-popularity ranking (Google-style learning from result clicks)
- [ ] Search suggestions / autocomplete
- [ ] Search history for logged-in users
- [ ] Bookmarked locations on the globe
- [ ] Dark / light theme toggle
- [ ] Mobile-responsive globe
- [ ] Air quality index overlay

---

## 📄 Licence

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <b>8search</b> — Search the web. Explore the world. 🌍
</p>
