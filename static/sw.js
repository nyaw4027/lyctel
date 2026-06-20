/**
 * Lynctel Service Worker v3 — Production Ready
 * Supports all mobile browsers: Chrome, Safari, Firefox, Samsung Internet
 */

const CACHE_VERSION  = 'lynctel-v3';
const STATIC_CACHE   = `${CACHE_VERSION}-static`;
const IMAGE_CACHE    = `${CACHE_VERSION}-images`;
const DYNAMIC_CACHE  = `${CACHE_VERSION}-dynamic`;

const PRECACHE_URLS = [
  '/',
  '/offline/',
  '/food/',
  '/products/',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
];

// ── INSTALL ───────────────────────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache =>
      cache.addAll(PRECACHE_URLS).catch(() => {})
    )
  );
});

// ── ACTIVATE ──────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => ![STATIC_CACHE, IMAGE_CACHE, DYNAMIC_CACHE].includes(k))
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── FETCH ─────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Skip non-GET, chrome-extension, websockets
  if (url.protocol === 'chrome-extension:') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  // Skip external resources except our CDN images
  if (url.origin !== location.origin &&
      !url.hostname.includes('storage.googleapis.com') &&
      !url.hostname.includes('res.cloudinary.com')) {
    return;
  }

  // Skip Django admin, API endpoints, CSRF
  if (url.pathname.startsWith('/admin/') ||
      url.pathname.startsWith('/api/') ||
      url.pathname.includes('csrftoken')) {
    return;
  }

  // Images → cache first, max 100 images
  if (req.destination === 'image' ||
      url.pathname.match(/\.(png|jpg|jpeg|gif|webp|svg|ico)$/i)) {
    event.respondWith(cacheFirstWithLimit(req, IMAGE_CACHE, 100));
    return;
  }

  // Static assets (JS, CSS, fonts) → cache first
  if (url.pathname.startsWith('/static/') ||
      req.destination === 'script' ||
      req.destination === 'style' ||
      req.destination === 'font') {
    event.respondWith(cacheFirst(req, STATIC_CACHE));
    return;
  }

  // HTML navigation → network first, fallback to cache, then offline page
  if (req.mode === 'navigate' || req.destination === 'document') {
    event.respondWith(networkFirst(req));
    return;
  }

  // Everything else → stale while revalidate
  event.respondWith(staleWhileRevalidate(req));
});

// ── STRATEGIES ────────────────────────────────────────
async function cacheFirst(req, cacheName) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const fresh = await fetch(req);
    if (fresh.ok) {
      const cache = await caches.open(cacheName);
      cache.put(req, fresh.clone());
    }
    return fresh;
  } catch {
    return new Response('', { status: 503 });
  }
}

async function cacheFirstWithLimit(req, cacheName, limit) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const fresh = await fetch(req);
    if (fresh.ok) {
      const cache = await caches.open(cacheName);
      const keys  = await cache.keys();
      if (keys.length >= limit) await cache.delete(keys[0]);
      cache.put(req, fresh.clone());
    }
    return fresh;
  } catch {
    return new Response('', { status: 503 });
  }
}

async function networkFirst(req) {
  try {
    const fresh = await fetch(req);
    if (fresh.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(req, fresh.clone());
    }
    return fresh;
  } catch {
    const cached = await caches.match(req);
    if (cached) return cached;
    const offline = await caches.match('/offline/');
    return offline || new Response(
      '<h1>You are offline</h1><p>Please check your connection.</p>',
      { headers: { 'Content-Type': 'text/html' }, status: 503 }
    );
  }
}

async function staleWhileRevalidate(req) {
  const cache  = await caches.open(DYNAMIC_CACHE);
  const cached = await cache.match(req);
  const fetchPromise = fetch(req).then(fresh => {
    if (fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  }).catch(() => null);
  return cached || fetchPromise;
}

// ── PUSH NOTIFICATIONS (future use) ───────────────────
self.addEventListener('push', event => {
  if (!event.data) return;
  try {
    const data = event.data.json();
    event.waitUntil(
      self.registration.showNotification(data.title || 'Lynctel', {
        body:  data.body  || 'You have a new notification',
        icon:  data.icon  || '/static/icons/icon-192x192.png',
        badge: data.badge || '/static/icons/icon-72x72.png',
        data:  data.url   || '/',
        vibrate: [100, 50, 100],
        actions: data.actions || [],
      })
    );
  } catch {
    event.waitUntil(
      self.registration.showNotification('Lynctel', {
        body: event.data.text(),
        icon: '/static/icons/icon-192x192.png',
      })
    );
  }
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = event.notification.data || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then(clientList => {
      for (const client of clientList) {
        if (client.url === url && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});