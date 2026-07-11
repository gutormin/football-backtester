const CACHE_NAME = 'backtester-pro-v59';
const ASSETS = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js',
  '/js/utils.js',
  '/js/api.js',
  '/manifest.json'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS).catch(err => console.log("Cache pre-add warning:", err));
    })
  );
});

self.addEventListener('activate', event => {
  self.clients.claim();
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(cacheName => cacheName !== CACHE_NAME)
          .map(cacheName => caches.delete(cacheName))
      );
    })
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method === 'GET' && url.origin === self.location.origin && !url.pathname.startsWith('/api/')) {
    event.respondWith(
      // Network-first strategy for HTML/JS/CSS (always get latest)
      fetch(event.request).then(networkResponse => {
        if (networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseToCache));
        }
        return networkResponse;
      }).catch(() => {
        // Offline fallback: serve from cache
        return caches.match(event.request);
      })
    );
  }
});
