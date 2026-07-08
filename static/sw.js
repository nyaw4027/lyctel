/**
 * ============================================================
 * Lynctel Service Worker v4
 * Production Ready
 * Offline Cache
 * Web Push Notifications
 * Background Sync
 * WebSocket Safe
 * ============================================================
 */

const VERSION = "lynctel-v4";

const STATIC_CACHE = `${VERSION}-static`;
const IMAGE_CACHE = `${VERSION}-images`;
const DYNAMIC_CACHE = `${VERSION}-dynamic`;

const PRECACHE = [
    "/",
    "/offline/",
    "/food/",
    "/products/",
    "/static/icons/icon-192x192.png",
    "/static/icons/icon-512x512.png",
];


/* ============================================================
   INSTALL
============================================================ */

self.addEventListener("install", event => {

    self.skipWaiting();

    event.waitUntil(

        caches.open(STATIC_CACHE)
            .then(cache => cache.addAll(PRECACHE))
            .catch(() => {})

    );

});


/* ============================================================
   ACTIVATE
============================================================ */

self.addEventListener("activate", event => {

    event.waitUntil(

        (async () => {

            const keys = await caches.keys();

            await Promise.all(

                keys.map(key => {

                    if (
                        key !== STATIC_CACHE &&
                        key !== IMAGE_CACHE &&
                        key !== DYNAMIC_CACHE
                    ) {
                        return caches.delete(key);
                    }

                })

            );

            await self.clients.claim();

        })()

    );

});


/* ============================================================
   FETCH
============================================================ */

self.addEventListener("fetch", event => {

    const req = event.request;

    if (req.method !== "GET") return;

    const url = new URL(req.url);

    /* Ignore websocket traffic */

    if (
        req.headers.get("upgrade") === "websocket" ||
        url.pathname.startsWith("/ws/") ||
        url.protocol === "ws:" ||
        url.protocol === "wss:"
    ) {
        return;
    }

    if (url.protocol === "chrome-extension:") return;

    /* Ignore admin/api */

    if (
        url.pathname.startsWith("/admin/") ||
        url.pathname.startsWith("/api/")
    ) {
        return;
    }

    /* Images */

    if (
        req.destination === "image" ||
        /\.(png|jpg|jpeg|gif|svg|webp|ico)$/i.test(url.pathname)
    ) {

        event.respondWith(cacheFirst(req, IMAGE_CACHE));

        return;

    }

    /* Static assets */

    if (
        req.destination === "style" ||
        req.destination === "script" ||
        req.destination === "font" ||
        url.pathname.startsWith("/static/")
    ) {

        event.respondWith(cacheFirst(req, STATIC_CACHE));

        return;

    }

    /* HTML */

    if (
        req.mode === "navigate" ||
        req.destination === "document"
    ) {

        event.respondWith(networkFirst(req));

        return;

    }

    /* Default */

    event.respondWith(staleWhileRevalidate(req));

});


/* ============================================================
   CACHE FIRST
============================================================ */

async function cacheFirst(req, cacheName) {

    const cache = await caches.open(cacheName);

    const cached = await cache.match(req);

    if (cached) {

        return cached;

    }

    try {

        const fresh = await fetch(req);

        if (fresh.ok) {

            cache.put(req, fresh.clone());

        }

        return fresh;

    } catch {

        return new Response("", { status: 503 });

    }

}


/* ============================================================
   NETWORK FIRST
============================================================ */

async function networkFirst(req) {

    const cache = await caches.open(DYNAMIC_CACHE);

    try {

        const fresh = await fetch(req);

        if (fresh.ok) {

            cache.put(req, fresh.clone());

        }

        return fresh;

    } catch {

        const cached = await cache.match(req);

        if (cached) return cached;

        const offline = await caches.match("/offline/");

        if (offline) return offline;

        return new Response("Offline", {

            status:503,

            headers:{
                "Content-Type":"text/plain"
            }

        });

    }

}


/* ============================================================
   STALE WHILE REVALIDATE
============================================================ */

async function staleWhileRevalidate(req) {

    const cache = await caches.open(DYNAMIC_CACHE);

    const cached = await cache.match(req);

    const fetchPromise = fetch(req)

        .then(response => {

            if (response.ok) {

                cache.put(req, response.clone());

            }

            return response;

        })

        .catch(() => cached);

    return cached || fetchPromise;

}


/* ============================================================
   PUSH NOTIFICATIONS
============================================================ */

self.addEventListener("push", event => {

    if (!event.data) return;

    let data = {};

    try {

        data = event.data.json();

    } catch {

        data = {

            title:"Lynctel",

            body:event.data.text()

        };

    }

    event.waitUntil(

        self.registration.showNotification(

            data.title || "Lynctel",

            {

                body:data.body || "You have a new message.",

                icon:data.icon || "/static/icons/icon-192x192.png",

                badge:data.badge || "/static/icons/icon-72x72.png",

                image:data.image || undefined,

                tag:data.tag || "lynctel",

                renotify:true,

                requireInteraction:true,

                silent:false,

                vibrate:[200,100,200],

                timestamp:Date.now(),

                data:{
                    url:data.url || "/"
                },

                actions:data.actions || [

                    {

                        action:"open",

                        title:"Open"

                    },

                    {

                        action:"dismiss",

                        title:"Dismiss"

                    }

                ]

            }

        )

    );

});


/* ============================================================
   NOTIFICATION CLICK
============================================================ */

self.addEventListener("notificationclick", event => {

    event.notification.close();

    if (event.action === "dismiss") {

        return;

    }

    const url = event.notification.data.url || "/";

    event.waitUntil(

        clients.matchAll({

            type:"window",

            includeUncontrolled:true

        }).then(windowClients => {

            for (const client of windowClients) {

                if (client.url.includes(url) && "focus" in client) {

                    return client.focus();

                }

            }

            return clients.openWindow(url);

        })

    );

});


/* ============================================================
   NOTIFICATION CLOSED
============================================================ */

self.addEventListener("notificationclose", () => {

    // Future analytics

});


/* ============================================================
   BACKGROUND SYNC
============================================================ */

self.addEventListener("sync", event => {

    if (event.tag === "sync-chat") {

        event.waitUntil(syncPendingMessages());

    }

});

async function syncPendingMessages() {

    return;

}


/* ============================================================
   PUSH SUBSCRIPTION CHANGED
============================================================ */

self.addEventListener("pushsubscriptionchange", event => {

    console.log("Push subscription changed.");

});


/* ============================================================
   MESSAGE FROM PAGE
============================================================ */

self.addEventListener("message", event => {

    if (event.data === "skipWaiting") {

        self.skipWaiting();

    }

});