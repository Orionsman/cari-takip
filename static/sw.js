const CACHE_NAME = 'cari-pwa-v2';
const SHELL = ['/', '/static/manifest.json', '/static/icon-192.png'];

// ── Install: shell cache ───────────────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c => c.addAll(SHELL))
  );
  self.skipWaiting();
});

// ── Activate: temizle ─────────────────────────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch stratejisi ──────────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // API: network first, offline'da queue'ya al
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request.clone()).catch(() =>
        new Response(JSON.stringify({error: 'Çevrimdışı - internet bağlantısı gerekli'}),
          {status: 503, headers: {'Content-Type': 'application/json'}})
      )
    );
    return;
  }

  // Shell: cache first, network fallback
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => caches.match('/'));
    })
  );
});
