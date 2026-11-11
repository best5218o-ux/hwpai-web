/* hwpai 웹 — 일꾼(Web Worker). 이 파일은 Blob 으로 띄워지므로 file:// 에서도 동작한다.
 * 하는 일: (1) Pyodide(브라우저용 Python)에 hwpai 본체를 올리고 (2) rhwp WebAssembly 로 HWP→HWPX 변환.
 * 네트워크: 쓰지 않는다. fetch·importScripts 를 메모리 자산으로만 답하도록 바꿔 두고, 모르는 주소는 거부한다.
 */
'use strict';
const nativeImportScripts = self.importScripts.bind(self);
const nativeFetch = self.fetch ? self.fetch.bind(self) : null;
let ASSETS = null;           // {이름: ArrayBuffer}
const blobUrls = {};
let netAttempts = [];        // 허용하지 않은 요청 시도(검증용)
const SCHEME = 'https://hwpai.invalid/';

function baseName(u) { return String(u).split('?')[0].split('/').pop(); }
function assetBytes(name) {
  const a = ASSETS[name];
  if (!a) throw new Error('자산 없음: ' + name);
  return a;
}
function mime(name) { return name.endsWith('.wasm') ? 'application/wasm' : name.endsWith('.json') ? 'application/json' : name.endsWith('.js') ? 'text/javascript' : 'application/octet-stream'; }
function blobUrl(name) {
  if (!blobUrls[name]) blobUrls[name] = URL.createObjectURL(new Blob([assetBytes(name)], { type: mime(name) }));
  return blobUrls[name];
}
// fetch: 우리 자산 주소(SCHEME)만 메모리에서 답한다. 그 밖은 모두 거부(네트워크 0건 보장).
self.fetch = function (input, init) {
  const url = typeof input === 'string' ? input : (input && input.url) || String(input);
  if (url.startsWith(SCHEME)) {
    const name = baseName(url);
    if (ASSETS && ASSETS[name]) {
      return Promise.resolve(new Response(ASSETS[name], { status: 200, headers: { 'Content-Type': mime(name) } }));
    }
  }
  netAttempts.push(url);
  return Promise.reject(new TypeError('hwpai: 네트워크 요청은 허용되지 않습니다 — ' + url.slice(0, 80)));
};
self.XMLHttpRequest = function () { throw new Error('hwpai: XMLHttpRequest 금지'); };
self.WebSocket = function () { throw new Error('hwpai: WebSocket 금지'); };
self.importScripts = function (...urls) {
  const mapped = urls.map(u => (String(u).startsWith(SCHEME) ? blobUrl(baseName(u)) : u));
  for (const m of mapped) if (!String(m).startsWith('blob:')) { netAttempts.push(String(m)); throw new Error('hwpai: importScripts 금지 ' + m); }
  return nativeImportScripts(...mapped);
};

// ---------------------------------------------------------------- AES-128 ECB 복호(배포용 HWP 용)
const AES = (() => {
  const sbox = new Uint8Array(256), inv = new Uint8Array(256);
  let p = 1, q = 1;
  do {
    p = p ^ ((p << 1) & 0xff) ^ (p & 0x80 ? 0x1b : 0);
    q ^= q << 1; q ^= q << 2; q ^= q << 4; q &= 0xff; if (q & 0x80) q ^= 0x09;
    const x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4));
    sbox[p] = (x ^ 0x63) & 0xff;
  } while (p !== 1);
  sbox[0] = 0x63;
  for (let i = 0; i < 256; i++) inv[sbox[i]] = i;
  const mul = (a, b) => { let r = 0; while (b) { if (b & 1) r ^= a; a = ((a << 1) ^ (a & 0x80 ? 0x1b : 0)) & 0xff; b >>= 1; } return r; };
  const m9 = new Uint8Array(256), m11 = new Uint8Array(256), m13 = new Uint8Array(256), m14 = new Uint8Array(256);
  for (let i = 0; i < 256; i++) { m9[i] = mul(i, 9); m11[i] = mul(i, 11); m13[i] = mul(i, 13); m14[i] = mul(i, 14); }
  function expand(key) {
    const w = new Uint8Array(176); w.set(key.subarray(0, 16));
    let rcon = 1;
    for (let i = 16; i < 176; i += 4) {
      let t0 = w[i - 4], t1 = w[i - 3], t2 = w[i - 2], t3 = w[i - 1];
      if (i % 16 === 0) { const a = t0; t0 = sbox[t1] ^ rcon; t1 = sbox[t2]; t2 = sbox[t3]; t3 = sbox[a]; rcon = ((rcon << 1) ^ (rcon & 0x80 ? 0x1b : 0)) & 0xff; }
      w[i] = w[i - 16] ^ t0; w[i + 1] = w[i - 15] ^ t1; w[i + 2] = w[i - 14] ^ t2; w[i + 3] = w[i - 13] ^ t3;
    }
    return w;
  }
  function decrypt(key, data) {
    const w = expand(key), out = new Uint8Array(data.length - (data.length % 16)), s = new Uint8Array(16), t = new Uint8Array(16);
    for (let o = 0; o < out.length; o += 16) {
      for (let i = 0; i < 16; i++) s[i] = data[o + i] ^ w[160 + i];
      for (let r = 9; r >= 0; r--) {
        // InvShiftRows + InvSubBytes
        t[0] = inv[s[0]]; t[4] = inv[s[4]]; t[8] = inv[s[8]]; t[12] = inv[s[12]];
        t[1] = inv[s[13]]; t[5] = inv[s[1]]; t[9] = inv[s[5]]; t[13] = inv[s[9]];
        t[2] = inv[s[10]]; t[6] = inv[s[14]]; t[10] = inv[s[2]]; t[14] = inv[s[6]];
        t[3] = inv[s[7]]; t[7] = inv[s[11]]; t[11] = inv[s[15]]; t[15] = inv[s[3]];
        for (let i = 0; i < 16; i++) t[i] ^= w[r * 16 + i];
        if (r === 0) { s.set(t); break; }
        for (let c = 0; c < 16; c += 4) {
          const a = t[c], b = t[c + 1], d = t[c + 2], e = t[c + 3];
          s[c] = m14[a] ^ m11[b] ^ m13[d] ^ m9[e];
          s[c + 1] = m9[a] ^ m14[b] ^ m11[d] ^ m13[e];
          s[c + 2] = m13[a] ^ m9[b] ^ m14[d] ^ m11[e];
          s[c + 3] = m11[a] ^ m13[b] ^ m9[d] ^ m14[e];
        }
      }
      out.set(s, o);
    }
    return out;
  }
  return { decrypt };
})();
self.hwpaiAesEcbDecrypt = (key, data) => AES.decrypt(key, data);

// ---------------------------------------------------------------- rhwp (WebAssembly)
let rhwp = null, rhwpVersion = '?', rhwpDirty = false;
self.measureTextWidth = (font, text) => {   // 조판용 글자폭 근사 — 변환(직렬화)에는 쓰이지 않는다(데스크톱 일꾼과 같은 값)
  const m = /(\d+(?:\.\d+)?)px/.exec(font || ''); const sz = m ? parseFloat(m[1]) : 12;
  let w = 0; for (const ch of text || '') w += (ch.codePointAt(0) > 0x2e80 ? 1.0 : 0.55) * sz; return w;
};
async function loadRhwp() {
  const url = blobUrl('rhwp.js');
  const mod = await import(url);
  mod.initSync({ module: new Uint8Array(assetBytes('rhwp_bg.wasm')) });
  rhwp = mod; rhwpDirty = false;
  try { rhwpVersion = JSON.parse(new TextDecoder().decode(assetBytes('rhwp-package.json'))).version; } catch (e) { rhwpVersion = '?'; }
}
let FS = null;
self.hwpaiConvert = function (src, dst, password) {
  const out = { ok: false };
  let doc = null;
  try {
    if (rhwpDirty) throw new Error('엔진 상태 불량 — 재시작 필요');
    const data = FS.readFile(src);
    doc = password ? rhwp.HwpDocument.openWithPassword(data, password) : new rhwp.HwpDocument(data);
    const ex = doc.exportHwpxWithReport();
    let loss = null; try { loss = JSON.parse(ex.contentLoss()); } catch (e) { loss = null; }
    const bytes = ex.takeBytes();
    try { ex.free(); } catch (e) { /* */ }
    FS.mkdirTree(dst.substring(0, dst.lastIndexOf('/')));
    FS.writeFile(dst + '.part', bytes);
    FS.rename(dst + '.part', dst);
    out.ok = true; out.bytes = bytes.length; out.loss = loss;
  } catch (e) {
    const msg = String(e && e.message ? e.message : e);
    out.error = msg.slice(0, 500);
    if (/unreachable|out of bounds|memory access|RuntimeError|recursive use|null pointer/i.test(msg) || (e && e.name === 'RuntimeError')) {
      rhwpDirty = true; out.kind = 'crash';   // wasm 이 중단됨 — 다음 파일 전에 엔진을 새로 올린다
    }
  } finally {
    try { if (doc) doc.free(); } catch (e) { /* */ }
  }
  return out;
};

// ---------------------------------------------------------------- Pyodide
let py = null, bridge = null;
async function boot(msg) {
  ASSETS = msg.assets;
  nativeImportScripts(blobUrl('pyodide.js'));
  py = await self.loadPyodide({ indexURL: SCHEME + 'pyodide/', stdout: () => {}, stderr: () => {} });
  FS = py.FS;
  for (const [path, text] of Object.entries(msg.pyfiles)) {
    const full = '/home/pyodide/lib/' + path;
    FS.mkdirTree(full.substring(0, full.lastIndexOf('/')));
    FS.writeFile(full, text);
  }
  py.runPython("import sys\nsys.path.insert(0,'/home/pyodide/lib')\nimport webbridge");
  bridge = py.pyimport('webbridge');
  FS.mkdirTree('/work');
  await loadRhwp();
  // 메모리 절약: Pyodide 가 이미 올라갔으므로 그 파일들은 놓는다(엔진 재시작용 rhwp 자산만 남김)
  for (const n of ['pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json', 'pyodide.asm.js', 'pyodide.js']) { delete ASSETS[n]; if (blobUrls[n]) { try { URL.revokeObjectURL(blobUrls[n]); } catch (e) { /* */ } delete blobUrls[n]; } }
}

function readTree(root, rels) {
  const out = {};
  for (const r of rels) {
    const bytes = FS.readFile(root + '/' + r);
    out[r] = (bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength) ? bytes.buffer
      : bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  }
  return out;
}

function prep(m) {
  if (m.cfg) bridge.configure(JSON.stringify(m.cfg));
  if (m.records) bridge.put_records(JSON.stringify(m.records));
}

const handlers = {
  async init(m) {
    await boot(m);
    return { engine: 'rhwp-wasm', version: rhwpVersion, python: py.runPython('import sys;sys.version.split()[0]'), netAttempts };
  },
  async configure(m) {
    return bridge.configure(JSON.stringify(m.cfg));
  },
  async records(m) { return bridge.put_records(JSON.stringify(m.records)); },
  async process(m) {
    prep(m);
    if (rhwpDirty) await loadRhwp();
    const job = 'j' + m.id;
    const inPath = '/work/' + job + '/in/' + m.rel;
    FS.mkdirTree(inPath.substring(0, inPath.lastIndexOf('/')));
    FS.writeFile(inPath, new Uint8Array(m.data));
    const t0 = performance.now();
    let res;
    try {
      res = JSON.parse(bridge.process(job, m.rel, m.dst, JSON.stringify(m.opts)));
      const files = readTree('/work/' + job + '/out', res.files || []);
      res.buffers = files;
      res.ms = Math.round(performance.now() - t0);
    } finally {
      try { bridge.cleanup(job); } catch (e) { /* */ }
    }
    const tr = Object.values(res.buffers || {});
    return { __transfer: tr, value: res };
  },
  async export(m) {
    prep(m);
    if (rhwpDirty) await loadRhwp();
    const job = 'x' + m.id;
    const inPath = '/work/' + job + '/in/' + m.rel;
    FS.mkdirTree(inPath.substring(0, inPath.lastIndexOf('/')));
    FS.writeFile(inPath, new Uint8Array(m.data));
    let res;
    try {
      res = JSON.parse(bridge.export_doc(job, m.rel, JSON.stringify(m.formats), !!m.aiFolder));
      res.buffers = readTree('/work/' + job + '/export', res.files || []);
    } finally { try { bridge.cleanup(job); } catch (e) { /* */ } }
    return { __transfer: Object.values(res.buffers), value: res };
  },
  async finalize(m) {
    const job = 'f' + m.id;
    const res = JSON.parse(bridge.finalize(job, JSON.stringify(m.rows), JSON.stringify(m.order), m.wall || 0));
    res.buffers = readTree('/work/' + job + '/final', res.files);
    try { bridge.cleanup(job); } catch (e) { /* */ }
    return { __transfer: Object.values(res.buffers), value: res };
  },
  async selftest() { return { netAttempts }; },
};

self.onmessage = async (ev) => {
  const m = ev.data;
  try {
    const r = await handlers[m.type](m);
    if (r && r.__transfer) self.postMessage({ id: m.id, ok: true, value: r.value }, r.__transfer);
    else self.postMessage({ id: m.id, ok: true, value: r });
  } catch (e) {
    let msg = String(e && e.message ? e.message : e);
    self.postMessage({ id: m.id, ok: false, error: msg.slice(0, 2000) });
  }
};
