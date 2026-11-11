/* hwpai 웹 — 엔진 적재와 일꾼 묶음(Pool). 모든 처리는 이 브라우저 안의 Web Worker 에서 일어난다.
 * 자산(Pyodide·rhwp wasm)은 같은 폴더의 파일(http 로 열 때) 또는 payload/*.js(file:// 로 열 때)에서만 읽는다. */
(function () {
  'use strict';
  const NET = { external: 0, local: 0, blocked: 0, log: [] };
  // 이 페이지(주 스레드)가 부르는 fetch 도 센다 — 같은 위치 자산 읽기와 그 밖을 구분한다.
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    let ext = true;
    try { const u = new URL(url, location.href); ext = !(u.origin === location.origin || u.protocol === 'blob:' || u.protocol === 'data:' || u.protocol === 'file:'); } catch (e) { /* */ }
    if (ext) { NET.external++; NET.log.push('차단: ' + url.slice(0, 100)); return Promise.reject(new TypeError('hwpai: 외부 요청 차단')); }
    NET.local++; NET.log.push('로컬: ' + url.slice(0, 100));
    return nativeFetch(input, init);
  };
  window.XMLHttpRequest = function () { NET.blocked++; throw new Error('hwpai: XMLHttpRequest 금지'); };
  window.WebSocket = function () { NET.blocked++; throw new Error('hwpai: WebSocket 금지'); };
  if (navigator.sendBeacon) navigator.sendBeacon = function () { NET.blocked++; return false; };
  try {  // 브라우저가 실제로 낸 요청(이미지·스크립트 등) 중 다른 출처가 있으면 센다
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        try { const u = new URL(e.name); if (u.protocol.startsWith('http') && u.origin !== location.origin) { NET.external++; NET.log.push('외부 요청: ' + e.name.slice(0, 100)); } } catch (x) { /* */ }
      }
    }).observe({ type: 'resource', buffered: true });
  } catch (e) { /* */ }

  const ASSET_FILES = {
    'pyodide.js': 'vendor/pyodide/pyodide.js', 'pyodide.asm.js': 'vendor/pyodide/pyodide.asm.js',
    'pyodide.asm.wasm': 'vendor/pyodide/pyodide.asm.wasm', 'python_stdlib.zip': 'vendor/pyodide/python_stdlib.zip',
    'pyodide-lock.json': 'vendor/pyodide/pyodide-lock.json', 'rhwp.js': 'vendor/rhwp-core/rhwp.js',
    'rhwp_bg.wasm': 'vendor/rhwp-core/rhwp_bg.wasm', 'rhwp-package.json': 'vendor/rhwp-core/package.json',
  };
  const chunkStore = {};
  window.__hwpaiChunk = (name, i, b64) => { (chunkStore[name] = chunkStore[name] || [])[i] = b64; };

  function loadScript(src) {
    return new Promise((res, rej) => {
      const s = document.createElement('script'); s.src = src; s.onload = () => { s.remove(); res(); }; s.onerror = () => rej(new Error('스크립트를 읽지 못함: ' + src));
      document.head.appendChild(s);
    });
  }
  async function gunzip(u8) {
    const ds = new DecompressionStream('gzip');
    const resp = new Response(new Blob([u8]).stream().pipeThrough(ds));
    return new Uint8Array(await resp.arrayBuffer());
  }
  function b64ToU8(b64) {
    const bin = atob(b64); const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  async function sha256hex(buf) {
    if (!(window.crypto && crypto.subtle)) return null;
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', buf));
    return Array.from(h, b => b.toString(16).padStart(2, '0')).join('');
  }

  /** 자산을 메모리로. mode: 'fetch'(http) | 'payload'(file://) */
  async function loadAssets(onProgress) {
    const manifest = window.HWPAI_PAYLOAD || [];
    const byName = Object.fromEntries(manifest.map(m => [m.name, m]));
    const names = Object.keys(ASSET_FILES);
    const assets = {};
    let mode = location.protocol === 'file:' ? 'payload' : 'fetch';
    let done = 0;
    const step = (label) => { done++; onProgress && onProgress(done / names.length, label); };
    if (mode === 'fetch') {
      try {
        for (const n of names) {
          const r = await window.fetch(ASSET_FILES[n]);
          if (!r.ok) throw new Error(n + ' ' + r.status);
          assets[n] = await r.arrayBuffer(); step(n);
        }
      } catch (e) { mode = 'payload'; done = 0; for (const k in assets) delete assets[k]; }
    }
    if (mode === 'payload') {
      for (const n of names) {
        const m = byName[n]; if (!m) throw new Error('payload 목록에 ' + n + ' 없음');
        for (const c of m.chunks) await loadScript(c);
        const parts = chunkStore[n].map(b64ToU8);
        let total = 0; parts.forEach(p => total += p.length);
        const gz = new Uint8Array(total); let o = 0; parts.forEach(p => { gz.set(p, o); o += p.length; });
        delete chunkStore[n];
        assets[n] = (await gunzip(gz)).buffer; step(n);
      }
    }
    // 무결성: 배포 목록의 SHA-256 과 대조(브라우저가 허용할 때)
    let verified = 0, skipped = 0;
    for (const n of names) {
      const m = byName[n]; if (!m) { skipped++; continue; }
      const h = await sha256hex(assets[n]);
      if (h == null) { skipped++; continue; }
      if (h !== m.sha256) throw new Error('엔진 파일 해시 불일치: ' + n);
      verified++;
    }
    return { assets, mode, verified, skipped };
  }

  function workerUrl() {
    return URL.createObjectURL(new Blob([window.HWPAI_WORKER_SRC], { type: 'text/javascript' }));
  }

  class Pool {
    constructor(size, assets, pyfiles) {
      this.size = size; this.assets = assets; this.pyfiles = pyfiles;
      this.slots = []; this.queue = []; this.seq = 0; this.info = null; this.url = workerUrl();
      this.onEvent = null;
    }
    async start(onStatus) {
      this.slots = Array.from({ length: this.size }, (_, i) => ({ i, w: null, ready: false, busy: false, pending: null, recVer: -1, cfgKey: '' }));
      await Promise.all(this.slots.map((s) => this._spawn(s, onStatus)));
      return this.info;
    }
    _spawn(slot, onStatus) {
      if (slot.w) { try { slot.w.terminate(); } catch (e) { /* */ } }
      slot.ready = false; slot.busy = false; slot.recVer = -1; slot.cfgKey = '';
      const w = new Worker(this.url);
      slot.w = w;
      w.onmessage = (ev) => this._onMsg(slot, ev.data);
      w.onerror = (ev) => { this._crash(slot, '일꾼 오류: ' + (ev.message || '알 수 없음')); };
      w.onmessageerror = () => this._crash(slot, '일꾼 메시지 오류');
      const assets = {}; for (const k in this.assets) assets[k] = this.assets[k].slice(0);
      const p = this._send(slot, { type: 'init', assets, pyfiles: this.pyfiles }, Object.values(assets), 0).then((info) => {
        slot.ready = true; this.info = info; onStatus && onStatus(slot.i, info); this._pump(); return info;
      });
      slot.booting = p;
      return p;
    }
    _send(slot, msg, transfer, timeoutMs) {
      return new Promise((resolve, reject) => {
        msg.id = ++this.seq;
        slot.pending = { id: msg.id, resolve, reject, timer: null };
        if (timeoutMs > 0) {
          slot.pending.timer = setTimeout(() => {
            const p = slot.pending; slot.pending = null;
            this._respawn(slot);
            p.reject(Object.assign(new Error('시간 한도 ' + Math.round(timeoutMs / 1000) + '초 초과'), { kind: 'timeout' }));
          }, timeoutMs);
        }
        slot.w.postMessage(msg, transfer || []);
      });
    }
    _onMsg(slot, m) {
      const p = slot.pending; if (!p || p.id !== m.id) return;
      slot.pending = null; if (p.timer) clearTimeout(p.timer);
      slot.busy = false;
      if (m.ok) p.resolve(m.value); else p.reject(Object.assign(new Error(m.error), { kind: 'engine_error' }));
      this._pump();
    }
    _crash(slot, why) {
      const p = slot.pending; slot.pending = null; if (p && p.timer) clearTimeout(p.timer);
      this._respawn(slot);
      if (p) p.reject(Object.assign(new Error(why), { kind: 'crash' }));
    }
    _respawn(slot) { this._spawn(slot).catch(() => { slot.dead = true; }); }
    /** 일 하나를 맡긴다. 반환 Promise. msg.type: process|export|finalize */
    run(msg, transfer, timeoutMs, records, recVer) {
      return new Promise((resolve, reject) => { this.queue.push({ msg, transfer, timeoutMs, resolve, reject, records, recVer }); this._pump(); });
    }
    _pump() {
      for (const s of this.slots) {
        if (!this.queue.length) return;
        if (!s.ready || s.busy || s.dead) continue;
        const t = this.queue.shift();
        s.busy = true;
        if (t.msg.cfg) {
          const key = JSON.stringify(t.msg.cfg);
          if (s.cfgKey === key) delete t.msg.cfg; else s.cfgKey = key;
        }
        if (t.records && s.recVer !== t.recVer) { t.msg.records = t.records; s.recVer = t.recVer; }
        this._send(s, t.msg, t.transfer, t.timeoutMs).then(t.resolve, t.reject);
      }
    }
    cancelQueued(pred) {
      const keep = [];
      for (const t of this.queue) { if (pred(t)) t.reject(Object.assign(new Error('취소됨'), { kind: 'cancel' })); else keep.push(t); }
      this.queue = keep;
    }
    terminate() { for (const s of this.slots) try { s.w.terminate(); } catch (e) { /* */ } try { URL.revokeObjectURL(this.url); } catch (e) { /* */ } }
  }
  window.HwpaiEngine = { NET, loadAssets, Pool };
})();
