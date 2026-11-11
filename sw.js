/* 자동 생성(tools/build.py) — HWP AI 어댑터 웹판 「앱」 오프라인 캐시.
 * 같은 출처의 정적 파일만 미리 저장하고, 문서 파일은 저장·전송하지 않는다(변환은 기기 안 Web Worker 에서만).
 * 다른 출처 요청은 건드리지 않는다(앱 자체가 외부 요청을 하지 않는다). */
const VERSION = 'hwpai-6ad199c6cee8';
const FILES = ["./", "./index.html", "./css/app.css", "./manifest.webmanifest", "./payload/manifest.js", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/maskable-192.png", "./icons/maskable-512.png", "./js/app.js", "./js/engine.js", "./js/pwa.js", "./js/py_bundle.js", "./js/review.js", "./js/worker.js", "./js/worker_src.js", "./js/zip.js", "./vendor/pyodide/pyodide.js", "./vendor/pyodide/pyodide.asm.js", "./vendor/pyodide/pyodide.asm.wasm", "./vendor/pyodide/python_stdlib.zip", "./vendor/pyodide/pyodide-lock.json", "./vendor/rhwp-core/rhwp.js", "./vendor/rhwp-core/rhwp_bg.wasm", "./vendor/rhwp-core/package.json"];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('hwpai-') && k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request)));
});
