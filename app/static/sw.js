/* Dossier Service Worker */
const STATIC_CACHE = 'dossier-static-v1';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png'
];
const STATIC_EXTS = ['.png', '.jpg', '.ico', '.woff2', '.woff', '.ttf'];

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
    /* Network-first for HTML pages — fall back to cache if offline */
    e.respondWith(
      fetch(e.request).catch(function() {
        return caches.match(e.request);
      })
    );
  }
});

self.addEventListener('push', function(e) {
  var data = {};
  try { data = e.data ? e.data.json() : {}; } catch(err) {}
  var title = data.title || 'Dossier';
  var body = data.body || 'New stories ready for you';
  e.waitUntil(
    self.registration.showNotification(title, {
      body: body,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: { url: data.url || '/' }
    })
  );
});

self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then(function(list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].url === url && 'focus' in list[i]) return list[i].focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
