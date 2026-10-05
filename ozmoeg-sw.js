// OzMoEg Trader — service worker.
// ONLY caches static HTML/JS/CSS assets. All live data (manifests, snapshots,
// tunnel endpoints, raw GitHub) is always fetched from the network. This prevents
// months-old cached scan data from being served on slow/mobile networks.
const CACHE_NAME = 'ozmoeg-v2';
const PRECACHE = [
  '/ozmoeg-trader.html',
  '/ozmoeg-trader-us.html'
];

// URL patterns that must never be cached (live data in any form).
const NEVER_CACHE_PATTERNS = [
  /^https?:\/\/trip-planner\.aeyeing\.com/,
  /^https?:\/\/raw\.githubusercontent\.com\/Melshayeb\/aeyeing\.com\/main\/ozmoeg-/,
  /ozmoeg-(manifest|latest|manifest-au|latest-au)/,
  /\.json\?_/,
  /ozmoeg-sw\.js/
];

function shouldNeverCache(req, url) {
  if (req.method !== 'GET') return true;
  const fullUrl = req.url;
  for (const p of NEVER_CACHE_PATTERNS) {
    if (p.test(fullUrl)) return true;
  }
  return false;
}

function isStaticAsset(req, url) {
  const pathname = url.pathname;
  return pathname.endsWith('.html') || pathname.endsWith('.js') || pathname.endsWith('.css') || pathname.endsWith('.png') || pathname.endsWith('.svg');
}

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE))
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

  // Always fetch live data from the network, never cache.
  if (shouldNeverCache(req, url)) {
    event.respondWith(
      fetch(req, { cache: 'no-store', signal: AbortSignal.timeout(10000) })
        .catch(() => new Response(JSON.stringify({ error: 'network unavailable' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        }))
    );
    return;
  }

  // Static assets: stale-while-revalidate, short timeout.
  if (isStaticAsset(req, url)) {
    event.respondWith(
      caches.match(req).then(cached => {
        const fetchPromise = fetch(req, { cache: 'no-store' }).then(networkRes => {
          if (networkRes && networkRes.ok) {
            const clone = networkRes.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
          }
          return networkRes;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Default: pass through without caching.
  event.respondWith(fetch(req, { cache: 'no-store' }));
});
