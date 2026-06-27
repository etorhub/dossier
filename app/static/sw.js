/* Dossier Service Worker */
const STATIC_CACHE = 'dossier-static-v1';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png'
];
const STATIC_EXTS = ['.png', '.jpg', '.ico', '.woff2', '.woff', '.ttf', '.css', '.js', '.svg'];

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(STATIC_CACHE).then(function(cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== STATIC_CACHE; })
            .map(function(k) { return caches.delete(k); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  if (e.request.method !== 'GET') return;
  var url = new URL(e.request.url);
  var isStatic = STATIC_EXTS.some(function(ext) {
    return url.pathname.endsWith(ext);
  });

  if (isStatic) {
    /* Cache-first for static assets */
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        return cached || fetch(e.request).then(function(res) {
          return caches.open(STATIC_CACHE).then(function(cache) {
            cache.put(e.request, res.clone());
            return res;
          });
        });
      })
    );
  } else {
    /* Network-first for HTML pages — cache on success, fall back if offline */
    e.respondWith(
      fetch(e.request).then(function(res) {
        if (res.ok) {
          var clone = res.clone();
          caches.open(STATIC_CACHE).then(function(cache) { cache.put(e.request, clone); });
        }
        return res;
      }).catch(function() {
        return caches.match(e.request);
      })
    );
  }
});
