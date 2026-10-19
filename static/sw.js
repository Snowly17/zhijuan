const CACHE_NAME = 'zhijuan-v1';
const ASSETS = [
  '/static/style.css',
  '/manifest.json',
  '/static/echarts.min.js'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

self.addEventListener('fetch', (e) => {
  // 👇 核心修复：只处理静态资源的 GET 请求，其他的直接走网络
  if (e.request.method !== 'GET' || !e.request.url.includes('/static/')) {
    return; // 交给浏览器默认处理（走网络）
  }

  e.respondWith(
    caches.match(e.request).then((res) => {
      return res || fetch(e.request);
    })
  );
});