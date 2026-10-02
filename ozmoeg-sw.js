const CACHE_NAME = 'ozmoeg-v1';
const PRECACHE = [
  '/ozmoeg-trader.html',
  '/ozmoeg-trader-us.html',
  '/ozmoeg-latest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Never cache tunnel/live endpoints — always fetch fresh with short timeout
  if (url.hostname === 'trip-planner.aeyeing.com') {
    event.respondWith(
      fetch(req, { signal: AbortSignal.timeout(6000) }).catch(() => caches.match(req))
    );
    return;
  }

  // For page, static assets, JSON: stale-while-revalidate
  event.respondWith(
    caches.match(req).then(cached => {
      const fetchPromise = fetch(req).then(networkRes => {
        if (networkRes && networkRes.ok && req.method === 'GET') {
          const clone = networkRes.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
        }
        return networkRes;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
