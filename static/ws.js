/**
 * sw.js  — Lynctel Service Worker
 * Place at: /static/sw.js   (must be served from root scope)
 *
 * Strategy:
 *   - Static assets (CSS/JS/fonts/icons) → Cache-First
 *   - HTML pages                          → Network-First  (always fresh)
 *   - Images                              → Stale-While-Revalidate
 *   - API / POST requests                 → Network-Only   (never cache)
 */

const CACHE_VERSION = 'lynctel-v1';
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const IMAGE_CACHE   = `${CACHE_VERSION}-images`;
const ALL_CACHES    = [STATIC_CACHE, IMAGE_CACHE];

// Assets to pre-cache on install
const PRECACHE_URLS = [
  '/',
  '/static/css/main.css',     // adjust to your actual CSS file names
  '/static/js/main.js',       // adjust to your actual JS file names
  '/static/icons/icon-192x192.png',
  '/offline/',                // create a simple offline fallback page
];

// ── Install ────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(cacheNames =>
        Promise.all(
          cacheNames
            .filter(name => !ALL_CACHES.includes(name))
            .map(name => caches.delete(name))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch ──────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and cross-origin (Firebase Storage, etc.)
  if (request.method !== 'GET') return;
  if (url.origin !== location.origin &&
      !url.hostname.includes('storage.googleapis.com')) return;

  // Images → Stale-While-Revalidate
  if (isImage(request)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
    return;
  }

  // Static assets → Cache-First
  if (isStaticAsset(request)) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // HTML pages → Network-First with offline fallback
  event.respondWith(networkFirst(request));
});

// ── Strategies ─────────────────────────────────────────────
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  return cached || fetchAndCache(request, cacheName);
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || caches.match('/offline/');
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache  = await caches.open(cacheName);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then(response => {
    cache.put(request, response.clone());
    return response;
  });
  return cached || fetchPromise;
}

async function fetchAndCache(request, cacheName) {
  const response = await fetch(request);
  const cache = await caches.open(cacheName);
  cache.put(request, response.clone());
  return response;
}

// ── Helpers ────────────────────────────────────────────────
function isImage(request) {
  return request.destination === 'image' ||
    /\.(png|jpg|jpeg|gif|webp|svg|ico)(\?.*)?$/.test(request.url);
}

function isStaticAsset(request) {
  return /\.(css|js|woff2?|ttf|eot)(\?.*)?$/.test(request.url) ||
    request.url.includes('/static/');
}