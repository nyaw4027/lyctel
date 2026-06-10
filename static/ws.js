/**
 * Lynctel Service Worker (Production Ready)
 */

const CACHE_VERSION = 'lynctel-v2';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const IMAGE_CACHE  = `${CACHE_VERSION}-images`;

const PRECACHE_URLS = [
  '/',
  '/offline/',
  '/static/icons/icon-192x192.png'
];

// ───────── INSTALL ─────────
self.addEventListener('install', event => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache => {
      return cache.addAll(PRECACHE_URLS);
    })
  );
});

// ───────── ACTIVATE ─────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(k => ![STATIC_CACHE, IMAGE_CACHE].includes(k))
          .map(k => caches.delete(k))
      );
    })
  );

  self.clients.claim();
});

// ───────── FETCH ─────────
self.addEventListener('fetch', event => {
  const req = event.request;

  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Skip external APIs (Stripe, Firebase, etc.)
  if (url.origin !== location.origin &&
      !url.hostname.includes('storage.googleapis.com')) {
    return;
  }

  // Images → cache first
  if (req.destination === 'image') {
    event.respondWith(cacheFirst(req, IMAGE_CACHE));
    return;
  }

  // HTML → network first
  if (req.mode === 'navigate') {
    event.respondWith(networkFirst(req));
    return;
  }

  // Static assets → cache first
  event.respondWith(cacheFirst(req, STATIC_CACHE));
});

// ───────── STRATEGIES ─────────
async function cacheFirst(req, cacheName) {
  const cached = await caches.match(req);
  if (cached) return cached;

  const fresh = await fetch(req);
  const cache = await caches.open(cacheName);
  cache.put(req, fresh.clone());
  return fresh;
}

async function networkFirst(req) {
  try {
    const fresh = await fetch(req);
    const cache = await caches.open(STATIC_CACHE);
    cache.put(req, fresh.clone());
    return fresh;
  } catch (err) {
    return caches.match(req) || caches.match('/offline/');
  }
}