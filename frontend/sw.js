/* 8search app shell.
 *
 * The service worker exists for installability and to keep a usable offline
 * page. It deliberately never caches API responses, account pages or search
 * results: those must always come from the server.
 */
const CACHE = "8search-shell-v20261118-9";
const OFFLINE_URL = "/offline.html";
const PRECACHE = [
  OFFLINE_URL,
  "/assets/icon-192.png",
  "/assets/icon-512.png",
  "/assets/apple-touch-icon.png",
  "/favicon.ico",
];
const STATIC_ASSET = /\.(?:css|js|mjs|png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf|otf|map)$/i;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname === "/health" ||
    url.pathname === "/ready" ||
    url.pathname === "/sw.js"
  ) {
    return;
  }

  if (request.mode === "navigate") {
    // Do not let the browser's HTTP cache make a failed network look online.
    // Dynamic pages must come from the server; when they cannot, show the
    // purpose-built offline page instead of a half-working cached shell.
    const networkRequest = new Request(request.url, {
      cache: "reload",
      credentials: request.credentials,
      mode: "same-origin",
      redirect: "follow",
    });
    event.respondWith(
      fetch(networkRequest).catch(async () => {
        const cache = await caches.open(CACHE);
        return (await cache.match(OFFLINE_URL)) || Response.error();
      })
    );
    return;
  }

  if (!STATIC_ASSET.test(url.pathname)) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      } catch (error) {
        return Response.error();
      }
    })()
  );
});
