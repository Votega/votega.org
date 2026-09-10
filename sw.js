/*
 * Vote GA service worker — Phase 0 (offline + installability).
 *
 * Scope: served from the site root ("/") so it controls every page.
 *
 * Caching strategy:
 *   - Precache a small, always-safe core (app shell CSS/JS, icons, offline page).
 *   - Navigations (HTML pages): network-first, falling back to the cached copy,
 *     then to /offline.html. This is what makes a sample ballot you have already
 *     viewed available with no signal — the page is saved on first visit and
 *     served from cache when the network is gone.
 *   - Same-origin static assets (css/js/img/fonts): stale-while-revalidate, so
 *     the app opens instantly and refreshes assets quietly in the background.
 *   - Cross-origin requests (CDN, fonts, analytics) are left to the network and
 *     never cached here, to keep the cache same-origin and predictable.
 *
 * Bump CACHE_VERSION whenever the precache list or strategy changes; the old
 * caches are deleted on activate.
 */

const CACHE_VERSION = 'votega-v1';
const PRECACHE = `${CACHE_VERSION}-precache`;
const RUNTIME = `${CACHE_VERSION}-runtime`;

// Only list files that are guaranteed to exist, so install never fails.
const PRECACHE_URLS = [
  '/',
  '/offline.html',
  '/manifest.json',
  '/assets/css/beautifuljekyll.css',
  '/assets/css/bootstrap-social.css',
  '/assets/js/beautifuljekyll.js',
  '/assets/img/pwa/icon-192.png',
  '/assets/img/pwa/icon-512.png',
  '/assets/img/pwa/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(PRECACHE).then((cache) =>
      // allSettled so a single missing asset can't abort the whole install.
      Promise.allSettled(
        PRECACHE_URLS.map((url) =>
          cache.add(new Request(url, { cache: 'reload' }))
        )
      )
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== PRECACHE && key !== RUNTIME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

function isSameOrigin(url) {
  return new URL(url, self.location.href).origin === self.location.origin;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET; let the browser deal with POST/PUT/etc.
  if (request.method !== 'GET') return;

  // Page navigations: network-first with cache + offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(RUNTIME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() =>
          caches.match(request).then(
            (cached) => cached || caches.match('/offline.html')
          )
        )
    );
    return;
  }

  // Same-origin static assets: stale-while-revalidate.
  if (isSameOrigin(request.url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response && response.status === 200) {
              const copy = response.clone();
              caches.open(RUNTIME).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
  // Cross-origin: fall through to the network (default behavior).
});

/*
 * --- Phase 1 stubs (push notifications) -------------------------------------
 * Intentionally inert in Phase 0. Wiring these up requires an opt-in flow, a
 * VAPID key pair, and a tiny server-side sender (e.g. a scheduled GitHub Action
 * posting to the Web Push API). Left here as a documented home for that work.
 *
 * self.addEventListener('push', (event) => {
 *   const data = event.data ? event.data.json() : {};
 *   event.waitUntil(self.registration.showNotification(data.title || 'Vote GA', {
 *     body: data.body,
 *     icon: '/assets/img/pwa/icon-192.png',
 *     badge: '/assets/img/pwa/icon-192.png',
 *     data: { url: data.url || '/' },
 *   }));
 * });
 *
 * self.addEventListener('notificationclick', (event) => {
 *   event.notification.close();
 *   event.waitUntil(clients.openWindow(event.notification.data.url || '/'));
 * });
 */
