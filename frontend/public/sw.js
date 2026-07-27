// Minimal service worker — enables PWA installability (Add to Home Screen).
// Network-first passthrough; no aggressive caching so the app always stays fresh.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // Pass through to the network. A fetch handler is required for install prompts.
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
