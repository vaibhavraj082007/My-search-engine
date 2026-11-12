<p align="center">
  <img src="frontend/assets/logo.png" alt="8search logo" width="120" />
</p>

<h1 align="center">8search</h1>

<p align="center">
  <b>A next-generation search engine with a live interactive satellite globe.</b><br/>
  Search the web like Google · Explore the Earth like Google Earth · See live weather anywhere with one click.
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
- Powered by your own crawler and full-text search index — you control what's indexed.

### 🌐 The Globe — Click Anywhere on Earth

Right below the search bar sits a **3D satellite globe** that users can spin, zoom, and click:

| Click anywhere on the globe and instantly see: |
| --- |
| 🌡️ **Live Temperature** — current reading at that exact spot |
| 🌤️ **Weather Condition** — clear, cloudy, rain, snow, storm, etc. |
| 💨 **Wind Speed & Direction** — with an animated arrow showing wind flow |
| 🌧️ **Rain / Precipitation** — current and forecasted |
| ☁️ **Cloud Cover** — percentage of sky covered |
| 🕐 **Live Local Time** — the real-time clock of the clicked location |
| 📅 **16-Day Forecast** — daily highs, lows, and conditions (days 10–16 dimmed as estimates) |

All weather data is **live** from [Open-Meteo](https://open-meteo.com/) — free, no API key needed.

### 📹 Bonus: Live Public Cameras

Green dots on the globe mark **public traffic cameras** from government agencies around the world. Click a dot to see:
- The live camera feed (photo or video stream)
- The camera's owner and credit
- Full weather details for that camera's location

Currently ships with importers for **4 sources** (~8,800+ cameras across the USA, Finland, New Zealand, and Hong Kong), with a simple recipe to add dozens more.

---

## ✨ Feature Overview

| Feature | Guest (no login) | Logged-in User |
| --- | :---: | :---: |
| Web search | ✅ 4 searches | ✅ **Unlimited** |
| URL navigation (like Chrome) | ✅ | ✅ |
| Interactive satellite globe | ✅ | ✅ |
| Click-anywhere live weather | ✅ | ✅ |
| Live local time of any place | ✅ | ✅ |
| Wind speed & direction | ✅ | ✅ |
| 16-day forecast | ✅ | ✅ |
| Live public camera feeds | ✅ | ✅ |
| Earthquake overlay (USGS) | ✅ | ✅ |
| Globe/Flat & Map/Satellite toggle | ✅ | ✅ |
| Search history & preferences | ❌ | ✅ |

---

## 🖼️ How It Looks

```
┌─────────────────────────────────────────────────────────┐
│  🔍  [  Search the web or type a URL...            ]    │
│       ──────────────────────────────────────────         │
│                                                         │
│               ┌──────────────────────┐                  │
│              /    🌐 SATELLITE GLOBE   \                │
│             /   ● ● ●  (camera dots)    \               │
│            |    Click anywhere for live   |              │
│            |    weather, temp, wind &     |              │
│             \   local time of that spot  /              │
│              \                          /               │
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
│   ├── map.js                   # Globe, camera dots, weather panel, click handler
│   ├── login.html               # Login page
│   └── signup.html              # Sign-up page
│
├── backend/                     # Python FastAPI server
│   ├── main.py                  # App entry point, routes, CORS, static files
│   ├── auth.py                  # User accounts (salted password hashing)
│   ├── search_api.py            # Search endpoint (full-text search)
│   ├── searchdb.py              # Search index database
│   ├── crawler.py               # Web crawler (respects robots.txt)
│   ├── weather_api.py           # Weather proxy (Open-Meteo, 15-min cache)
│   ├── cameras_api.py           # "Which cameras are on screen?" endpoint
│   ├── camdb.py                 # Camera database schema & validation
│   ├── healthcheck.py           # Marks dead cameras so they hide from the globe
│   ├── import_all.py            # Runs all camera importers
│   ├── importers/               # One file per camera source
│   │   ├── otcm.py              # OpenTrafficCamMap — ~7,000 US cameras
│   │   ├── finland.py           # Fintraffic — ~470 cameras
│   │   ├── newzealand.py        # NZTA — ~320 cameras
│   │   └── hongkong.py          # HK Transport Dept — ~1,000 cameras
│   └── data/                    # Auto-created: SQLite databases
│
├── requirements.txt             # Python dependencies
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

That's it. Search, spin the globe, click anywhere for live weather.

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
video section never breaks the rest of the page.

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

## 🌐 The Globe — Live Weather on Click

The satellite globe is the centrepiece of 8search. It sits directly below the search bar.

### Controls

| Control | Action |
| --- | --- |
| 🖱️ Drag | Spin the globe |
| 🔄 Scroll | Zoom in / out |
| 👆 Click empty ground | Weather panel for that location |
| 👆 Click a green dot | Camera feed + weather for that spot |
| `Globe / Flat` button | Toggle 3D globe or flat map |
| `Map / Satellite` button | Toggle street map or satellite imagery |
| `Earthquakes` button | Show last 24 hours of M2.5+ earthquakes (USGS) |

### What the Weather Panel Shows

When you click **any point** on the globe:

| Data | Source | Update Frequency |
| --- | --- | --- |
| Temperature (°C/°F) | Open-Meteo | Live (cached 15 min) |
| Weather condition | Open-Meteo | Live |
| Wind speed (km/h) | Open-Meteo | Live |
| Wind direction (arrow) | Open-Meteo | Live |
| Rain / precipitation | Open-Meteo | Live |
| Cloud cover (%) | Open-Meteo | Live |
| **Live local time** | Calculated from longitude | **Real-time (ticking clock)** |
| 16-day forecast | Open-Meteo | Daily |

> **Note:** Days 10–16 in the forecast are dimmed because long-range predictions are rough estimates. No free weather service forecasts beyond 16 days reliably.

---

## 📹 Public Cameras

Green dots on the globe represent **public traffic cameras** published by government agencies.

| Source | Region | ~Cameras | Type | Licence |
| --- | --- | --- | --- | --- |
| OpenTrafficCamMap | 10 US states | 7,000 | Photos + video | MIT |
| Fintraffic | Finland | 470 | Photos (10-min refresh) | CC BY 4.0 |
| NZTA | New Zealand | 320 | Photos | NZTA Data Licence |
| HK Transport Dept | Hong Kong | 1,000 | Photos | data.gov.hk terms |

### Adding More Camera Sources

The system is designed to grow. Dozens more sources are available (see section below):

1. Copy `backend/importers/finland.py` → `backend/importers/yourplace.py`
2. Change `NAME`, `URL`, the `parse` function, and `credit` text
3. Add it to `backend/import_all.py`
4. Run `python3 import_all.py yourplace && python3 healthcheck.py`

### Available Sources to Add

From the [OSIRIS project](https://github.com/simplifaisoul/osiris) (MIT licence):

> Alberta · Arizona · Austria · Australia · Basque Country · Bulgaria · Czechia · Delaware · Edmonton · Florida · France · Georgia (US) · Germany · Greece · Idaho · Indiana · Iceland · Italy · Japan · Lithuania · Louisiana · Macedonia · Maryland · Michigan · Netherlands · Nevada · North Carolina · Ontario · Oregon · Poland · Romania · Serbia · Slovakia · South Carolina · Spain · Sweden · Switzerland · Taiwan · Texas · Thailand · Turkey · Utah · Virginia · Quebec

Also: **Windy Webcams**, **Singapore LTA DataMall**, **Transport for NSW**, **TfL London**.

### Camera Healthcheck

```bash
python3 healthcheck.py
```

Visits every camera URL and marks dead ones so they disappear from the globe. Run after importing, then schedule nightly:

```bash
# Add to crontab -e (replace YOURNAME):
0 3 * * * cd /Users/YOURNAME/8search/backend && /Users/YOURNAME/8search/venv/bin/python healthcheck.py >> health.log 2>&1
```

---

## 👤 User Accounts

| Feature | Details |
| --- | --- |
| Sign up / sign in | Email + password (8+ characters) |
| Password storage | bcrypt hash only (never plain text) |
| Password reset | Single-use emailed link, valid for 30 minutes |
| Login alerts | Email sent after every successful sign-in |
| Data location | Local SQLite in `data/` |
| Session | HttpOnly cookie (30 days) |

### ✉️ Email setup (password reset & login alerts)

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

> **Local development:** if SMTP is not configured, every email — including the password-reset link — is printed to the server console. Password resets still work end-to-end.

Accounts unlock **unlimited searches** and will power future features like search history, bookmarks, and personalized globe settings.

---

## 🛠️ API Reference

While the server is running, visit **http://localhost:8000/docs** for the full interactive Swagger UI.

Key endpoints:

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/search?q=...` | GET | Answer-first web search (cached, rate-limited) |
| `/api/cameras?bounds=...` | GET | Cameras within map bounds |
| `/api/weather?lat=...&lon=...` | GET | Live weather for coordinates |
| `/api/stats` | GET | Camera count per source |
| `/api/signup` | POST | Create account |
| `/api/login` | POST | Log in (sends a sign-in alert email) |
| `/api/logout` | POST | Log out |
| `/api/me` | GET | Current user info |
| `/api/forgot-password` | POST | Email a password-reset link |
| `/api/reset-password` | POST | Set a new password with a reset token |
| `/health` | GET | Liveness probe for load balancers |
| `/ready` | GET | Readiness probe (reports cache backend) |

---

## 🐛 Troubleshooting

| Problem | Solution |
| --- | --- |
| `command not found: python3` | Install Python 3.9+ from [python.org](https://www.python.org/downloads/) |
| `No module named fastapi` | Activate the venv: `source venv/bin/activate` |
| Blank globe | Open browser console (Cmd+Option+J) and check for errors |
| Globe shows but no camera dots | Run `python3 import_all.py`, reload. Check `/api/stats` |
| Camera shows broken image | Camera is offline. Run `python3 healthcheck.py` |
| No cluster numbers on circles | Font CDN was blocked. Dots still work |
| `502` on weather | Open-Meteo is temporarily unreachable |
| Camera images blocked (HTTPS) | A page on `https://` can't load `http://` images. Prefer HTTPS cameras |

---

## ⚠️ Before Going Public

> [!IMPORTANT]
> The current setup is designed for **local development and learning**. Before deploying to real users:

- **Database:** SQLite is fine for one host. Move users/sessions/reset tokens to Postgres before running multiple app replicas.
- **Search provider:** DuckDuckGo/Bing HTML and RSS endpoints are demo-grade. Use a paid search API with an SLA for real traffic.
- **YouTube:** scraping results pages will be blocked at scale. Use the YouTube Data API.
- **Map tiles:** OpenStreetMap and Esri tiles have usage limits. Switch to a commercial tile provider for heavy traffic.
- **Weather API:** Open-Meteo is free for **non-commercial use only**. Review their [terms](https://open-meteo.com/en/terms).
- **Camera licences:** Keep each source's credit visible. The panel already shows per-camera credits.
- **Authentication:** Add HTTPS, rate-limit failed logins, and consider OAuth for production.
- **Crawler:** Maintain the 1-second delay and always respect `robots.txt`.

See **[SCALING.md](SCALING.md)** for the full production architecture, sizing
math, environment variables, and load-test instructions.

---

## 🗺️ Roadmap

- [x] Full-text web search with own crawler
- [x] 4-search guest limit → login for unlimited
- [x] Interactive satellite globe below search bar
- [x] Click-anywhere live weather (temp, wind, rain, clouds)
- [x] Live local time of clicked location
- [x] 16-day forecast
- [x] Public camera feeds on the globe
- [x] Earthquake overlay (USGS)
- [x] User accounts with secure password hashing
- [ ] Search suggestions / autocomplete
- [ ] Search history for logged-in users
- [ ] Bookmarked locations on the globe
- [ ] Dark / light theme toggle
- [ ] Mobile-responsive globe
- [ ] More camera sources (50+ countries)
- [ ] Air quality index overlay
- [ ] Sunrise / sunset times in weather panel

---

## 📄 Licence

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <b>8search</b> — Search the web. Explore the world. See live weather anywhere. 🌍
</p>
