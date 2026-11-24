/* 자동 생성(tools/build.py) — HWP AI 어댑터 웹판 「앱」 오프라인 캐시.
 * 같은 출처의 정적 파일만 미리 저장하고, 문서 파일은 저장·전송하지 않는다(변환은 기기 안 Web Worker 에서만).
 * 다른 출처 요청은 건드리지 않는다(앱 자체가 외부 요청을 하지 않는다). */
const VERSION = 'hwpai-cert-20261124b';
const FILES = ["./", "./index.html", "./css/app.css", "./manifest.webmanifest", "./payload/manifest.js", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/maskable-192.png", "./icons/maskable-512.png", "./js/app.js", "./js/engine.js", "./js/pwa.js", "./js/py_bundle.js", "./js/review.js", "./js/settle.js", "./js/worker.js", "./js/worker_src.js", "./js/zip.js", "./vendor/pyodide/pyodide.js", "./vendor/pyodide/pyodide.asm.js", "./vendor/pyodide/pyodide.asm.wasm", "./vendor/pyodide/python_stdlib.zip", "./vendor/pyodide/pyodide-lock.json", "./vendor/rhwp-core/rhwp.js", "./vendor/rhwp-core/rhwp_bg.wasm", "./vendor/rhwp-core/package.json"];
// 큰 엔진 파일은 화면이 이미 받아 둔 저장본(hwpaiheavy-v1)이나 옛 판 저장본을 그대로 옮겨 담는다 — 같은 파일을 두 번 받지 않는다(2026-11-23 속도 개선).
const HEAVY = /\/(payload|vendor)\//;
self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => Promise.all(FILES.map(async f => {
    if (HEAVY.test(f)) { const hit = await caches.match(f, { ignoreSearch: true }); if (hit) return c.put(f, hit); }
    const r = await fetch(new Request(f, { cache: 'no-cache' }));
    if (!r.ok) throw new Error(f + ' ' + r.status);
    return c.put(f, r);
  }))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('hwpai-') && k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// 화면 파일(html·js·css 등)은 서버의 새 판을 먼저 받고, 연결이 없을 때만 저장본을 쓴다(옛 화면이 남던 문제 수정, 2026-11-23).
// 큰 엔진 파일(payload·vendor)은 바뀔 때 이름이 바뀌므로 저장본을 먼저 쓴다.
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  const heavy = /\/(payload|vendor)\//.test(u.pathname);
  if (heavy) { e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request))); return; }
  e.respondWith((async () => {
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 5000);
      const r = await fetch(e.request, { cache: 'no-cache', signal: ctl.signal }); clearTimeout(t);
      if (r && r.ok) { const c = await caches.open(VERSION); const key = u.pathname.endsWith('/') ? './' : e.request; c.put(key, r.clone()).catch(() => {}); }
      return r;
    } catch (err) {
      const r = await caches.match(e.request, { ignoreSearch: true }) || (e.request.mode === 'navigate' ? await caches.match('./index.html') : null);
      if (r) return r; throw err;
    }
  })());
});
