/*
 * Campus Swap service worker.
 *
 * Scope is deliberately narrow: this is a marketplace with live listings,
 * messages, and payment state, so we never want someone to see stale data
 * while thinking it's current. We only cache the static "app shell" (CSS,
 * icons, manifest) for speed and a basic offline fallback - never HTML
 * pages, and never anything from a POST/PUT/DELETE request.
 */

const CACHE_NAME = "campus-swap-shell-v1";

const APP_SHELL = [
  "/static/css/style.css",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
  "/static/img/favicon.svg",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Never intercept anything but simple GETs - forms, checkout, and API
  // calls must always go straight to the network.
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  // Only handle our own static app-shell files. Everything else (every
  // HTML page, every dynamic route) always goes to the network, so users
  // never see stale listings, prices, or messages.
  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request)
          .then((response) => {
            if (response && response.status === 200) {
              const copy = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => cached);
        return cached || networkFetch;
      })
    );
  }
  // Non-static GETs (dashboard, marketplace, etc.) are left alone entirely
  // and go straight to the network with the browser's normal behaviour.
});
