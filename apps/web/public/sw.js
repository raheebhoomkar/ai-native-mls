// Caches the app shell (index.html and its built files) so the app opens without a
// connection and can say it is offline. API responses are never cached: listings and
// permissions must always come from the server.
const CACHE = "mls-shell-v1";

async function cacheShell() {
  const cache = await caches.open(CACHE);
  const response = await fetch("./", { cache: "no-store" });
  if (!response.ok) return;
  const html = await response.clone().text();
  const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map(
    (m) => m[1],
  );
  await cache.put("./", response);
  await cache.addAll(assets);
}

self.addEventListener("install", (event) => {
  event.waitUntil(cacheShell().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (event.request.mode === "navigate") {
    // Network first, so a new release shows at once; the cached shell only when offline.
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          if (response.ok)
            void caches.open(CACHE).then((c) => c.put("./", copy));
          return response;
        })
        .catch(() => caches.match("./")),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    // Built files have a content hash in their name, so a cached copy is never stale.
    event.respondWith(
      caches.match(event.request).then(
        (hit) =>
          hit ??
          fetch(event.request).then((response) => {
            const copy = response.clone();
            if (response.ok)
              void caches.open(CACHE).then((c) => c.put(event.request, copy));
            return response;
          }),
      ),
    );
  }
});
