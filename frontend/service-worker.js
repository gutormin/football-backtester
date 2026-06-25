const CACHE_NAME = 'backtester-pro-v28';
const ASSETS = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js?v=48',
  '/manifest.json'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      // Allow install to complete even if some assets fail to cache (e.g. offline during development)
      return cache.addAll(ASSETS).catch(err => console.log("Cache pre-add warning:", err));
    })
  );
});

self.addEventListener('activate', event => {
  self.clients.claim();
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(cacheName => {
          return cacheName !== CACHE_NAME;
        }).map(cacheName => {
          return caches.delete(cacheName);
        })
      );
    })
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  // Only intercept local GET requests and avoid caching FastAPI API paths
  if (event.request.method === 'GET' && url.origin === self.location.origin && !url.pathname.startsWith('/api/')) {
    event.respondWith(
      caches.match(event.request).then(cachedResponse => {
        if (cachedResponse) {
          // Serve cached version immediately but update in the background (stale-while-revalidate)
          fetch(event.request).then(networkResponse => {
            if (networkResponse.status === 200) {
              caches.open(CACHE_NAME).then(cache => cache.put(event.request, networkResponse));
            }
          }).catch(() => {});
          return cachedResponse;
        }
        return fetch(event.request).then(networkResponse => {
          if (networkResponse.status === 200) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseToCache));
          }
          return networkResponse;
        });
      })
    );
  }
});
