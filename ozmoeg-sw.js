// OzMoEg Trader — service worker self-destruct.
// This worker replaces any previously cached worker and immediately unregisters itself
// so that live scan data is never cached again.
self.addEventListener('install', function(event) {
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(keys) {
            return Promise.all(keys.map(function(key) { return caches.delete(key); }));
        }).then(function() {
            return self.registration.unregister();
        }).then(function() {
            return self.clients.claim();
        })
    );
});

self.addEventListener('fetch', function(event) {
    // Pass through all requests without caching.
    event.respondWith(fetch(event.request));
});
