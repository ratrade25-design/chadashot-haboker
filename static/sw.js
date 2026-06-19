const CACHE = 'boker-v1';
const STATIC = ['/', '/static/manifest.json', '/static/icon-192.png'];

self.addEventListener('install', e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting()))
);
self.addEventListener('activate', e =>
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))
);
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // API calls: network-first, fallback to cache
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request)
        .then(r => { const c = r.clone(); caches.open(CACHE).then(cx=>cx.put(e.request,c)); return r; })
        .catch(() => caches.match(e.request))
    );
  } else {
    // Static: cache-first
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
