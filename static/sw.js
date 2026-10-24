// Service worker лише для встановлення на екран телефону і сторінки «немає інтернету».
// Сторінки з даними навмисно не кешуємо: без входу і без мережі даних не видно.
const CACHE = 'shell-v1';
const OFFLINE = '/static/offline.html';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([OFFLINE, '/static/icon-192.png'])));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE)));
  }
});
