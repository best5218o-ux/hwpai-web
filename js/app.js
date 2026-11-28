/* hwpai 웹 — 화면. 파일은 이 탭 밖으로 보내지 않는다(서버·CDN·AI 호출 없음). */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const R = window.HwpaiReview, E = window.HwpaiEngine, Z = window.HwpaiZip, ST = window.HwpaiSettle;
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtSize = (n) => (n == null || n === '' ? '' : n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB');
  const nfc = (s) => (s.normalize ? s.normalize('NFC') : s);
  const LS = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* */ } } };

  const S = {
    items: [], nextId: 1, pool: null, assets: null, ready: false, booting: false, running: 0, runStart: 0,
    records: LS.get('hwpai.sens.v1', {}), recVer: 1, filter: 'all', selected: new Set(), outName: '', cancelled: false,
    cfg: { policy: 'review', engine_version: '?' }, info: null, assetMode: '', verified: 0, doneCount: 0, totalCount: 0,
  };
  window.__hwpai = S; // 시험용

  // ---------------------------------------------------------------- 알림
  let toastT = 0;
  function toast(msg, ms) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, ms || 3500); }

  // ---------------------------------------------------------------- 옵션
  function readOpts() {
    return {
      jobs: Math.max(1, Math.min(4, +$('#optJobs').value || 1)), timeout: Math.max(10, +$('#optTimeout').value || 120),
      policy: $('#optPolicy').value, password: $('#optPw').value, include_hwpx: $('#optHwpx').checked, auto: $('#optAuto').checked,
    };
  }
  function initOpts() {
    const saved = LS.get('hwpai.opts.v2', {});
    // 동시 처리 수: 코어가 많은 기기는 3개(큰 문서 여러 건을 나눠 처리), 아니면 2개까지. 메모리가 적으면 줄인다.
    const cores = navigator.hardwareConcurrency || 2; const mem = navigator.deviceMemory || 4;
    const autoJobs = cores >= 8 && mem >= 4 ? 3 : Math.min(2, Math.max(1, cores - 1));
    const qj = +new URLSearchParams(location.search).get('jobs');   // 속도 비교용: 주소 끝 &jobs=2 처럼 동시 처리 수를 정해 열 수 있다
    $('#optJobs').value = String((qj >= 1 && qj <= 4 && qj) || saved.jobs || autoJobs);
    $('#optTimeout').value = saved.timeout || 120;
    $('#optPolicy').value = saved.policy || 'review';
    $('#optHwpx').checked = !!saved.include_hwpx;
    $('#optAuto').checked = saved.auto !== false;
    const persist = () => { const o = readOpts(); delete o.password; LS.set('hwpai.opts.v2', o); S.cfg.policy = o.policy; };
    $$('#opts select,#opts input').forEach(e => e.addEventListener('change', persist));
    $('#optJobs').addEventListener('change', () => { if (!S.running) bootPool(); else toast('처리가 끝난 뒤에 동시 처리 수가 바뀝니다.'); });
    S.cfg.policy = $('#optPolicy').value;
  }

  // ---------------------------------------------------------------- 엔진
  async function bootPool() {
    if (S.booting) return;
    S.booting = true; S.ready = false;
    const opts = readOpts();
    const txt = $('#engineText'), bar = $('#engineBar');
    try {
      if (!S.assets) {
        txt.textContent = '엔진 파일을 읽는 중…';
        const a = await E.loadAssets((p, n) => { bar.style.width = (p * 50) + '%'; txt.textContent = '엔진 파일을 읽는 중… ' + n; });
        S.assets = a.assets; S.assetMode = a.mode; S.verified = a.verified;
      }
      if (S.pool) S.pool.terminate();
      txt.textContent = `엔진을 시작하는 중(일꾼 ${opts.jobs}개)…`; bar.style.width = '60%';
      S.pool = new E.Pool(opts.jobs, S.assets, window.HWPAI_PY);
      let n = 0;
      const info = await S.pool.start(() => { n++; bar.style.width = (60 + 40 * n / opts.jobs) + '%'; });
      S.info = info; S.cfg.engine_version = info.version; S.ready = true;
      txt.textContent = '엔진 준비됨'; $('#engine').classList.add('ready');
      try { window.dispatchEvent(new Event('hwpai-engine-ready')); } catch (e) { /* */ }
      $('#engineInfo').textContent = `rhwp ${info.version} (WebAssembly) · Python ${info.python} (Pyodide) · hwpai 검증서 판 1.1 · 일꾼 ${opts.jobs}개 · 파일 읽기 방식: ${S.assetMode === 'payload' ? 'file:// 내장 묶음' : '같은 위치 정적 파일'}${S.verified ? ' · 엔진 파일 SHA-256 대조 ' + S.verified + '건 일치' : ''}`;
      bar.style.width = '100%';
      setTimeout(() => { $('#engine').classList.add('done'); }, 600);
      renderAll();
      kick();
    } catch (e) {
      txt.textContent = '엔진을 시작하지 못했습니다: ' + e.message;
      $('#engineInfo').textContent = '브라우저가 WebAssembly·Web Worker·DecompressionStream 을 지원하는지 확인하세요(최신 Chrome·Edge·Firefox·Safari).';
      console.error(e);
    } finally { S.booting = false; }
  }

  // ---------------------------------------------------------------- 파일 모으기
  const isHwp = (n) => /\.(hwp|hwpx|hml|hwt|hwtx)$/i.test(n);   // 0.9.2: 옛 한글(1.x·2.x·3.0)은 .hwp, HML(HWPML)·서식 파일도 받는다
  function readAllEntries(reader) {
    return new Promise((resolve, reject) => {
      const all = [];
      (function next() { reader.readEntries((batch) => { if (!batch.length) return resolve(all); all.push(...batch); next(); }, reject); })();
    });
  }
  async function walkEntry(entry, prefix, out, skipped) {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file, path: prefix + entry.name });
    } else if (entry.isDirectory) {
      if (/^(\.|_검증서$|_격리$)/.test(entry.name) && prefix) { skipped.dirs++; return; }
      const kids = await readAllEntries(entry.createReader());
      for (const k of kids) await walkEntry(k, prefix + entry.name + '/', out, skipped);
    }
  }
  // ---- 폴더 고르기 자동화: 폴더를 끌어놓으면 그 폴더를 바로 쓰기 허용으로 열고(선택창 없음), 보관 폴더는 폴더 안 「_원본보관」을 자동으로 만든다
  async function useRootHandle(h) {   // 쓰기 허용을 받아 폴더를 훑고 목록에 올린다
    let perm = await h.queryPermission({ mode: 'readwrite' });
    if (perm !== 'granted') perm = await h.requestPermission({ mode: 'readwrite' });
    if (perm !== 'granted') { toast('폴더 쓰기를 허용하지 않아 읽기만 합니다. 제자리 교체를 하려면 허용해 주세요.', 7000); return false; }
    toast('폴더를 읽는 중…', 20000);
    const out = []; await ST.walk(h, h.name + '/', out);
    S.rootH = h; addFiles(out, null); return true;
  }
  async function openRWHandle(hps) {   // 끌어놓은 것이 폴더 하나이면 그 폴더를 바로 연다
    if (!hps.length) return false;
    const hs = (await Promise.all(hps)).filter(Boolean);
    if (hs.length !== 1 || hs[0].kind !== 'directory') return false;
    return await useRootHandle(hs[0]);
  }
  async function collectFromDrop(dt) {
    // webkitGetAsEntry 는 drop 이벤트 안에서 동기로 불러야 한다(이후엔 null)
    const entries = [];
    const items = dt.items ? Array.from(dt.items) : [];
    for (const it of items) { if (it.kind !== 'file') continue; const en = it.webkitGetAsEntry ? it.webkitGetAsEntry() : null; if (en) entries.push(en); }
    const files = dt.files ? Array.from(dt.files) : [];
    return { entries, files };
  }
  async function resolveDropped(c) {
    const out = [], skipped = { dirs: 0 };
    if (c.entries.length) { for (const en of c.entries) await walkEntry(en, '', out, skipped); }
    else for (const f of c.files) out.push({ file: f, path: f.webkitRelativePath || f.name });
    return { list: out, skipped, topDirs: c.entries.filter(e => e.isDirectory).length, topFiles: c.entries.filter(e => e.isFile).length };
  }

  function splitext(p) { const b = p.lastIndexOf('/'); const base = p.slice(b + 1); const i = base.lastIndexOf('.'); return (i <= 0) ? [p, ''] : [p.slice(0, b + 1 + i), base.slice(i)]; }
  /** os.walk 순서(한 폴더의 파일을 먼저, 그다음 하위 폴더 — 각각 이름순)로 정렬 */
  function walkOrder(paths) {
    const root = { files: [], dirs: new Map() };
    for (const p of paths) {
      const parts = p.split('/'); let n = root;
      for (let i = 0; i < parts.length - 1; i++) { if (!n.dirs.has(parts[i])) n.dirs.set(parts[i], { files: [], dirs: new Map() }); n = n.dirs.get(parts[i]); }
      n.files.push(p);
    }
    const out = [];
    (function w(n) { n.files.sort((a, b) => { const x = a.split('/').pop(), y = b.split('/').pop(); return x < y ? -1 : x > y ? 1 : 0; }); out.push(...n.files); for (const k of Array.from(n.dirs.keys()).sort()) w(n.dirs.get(k)); })(root);
    return out;
  }
  function assignNames() {
    // batch.run() 과 같은 이름 겹침 처리 — 대소문자만 다른 이름·「가.hwp」와「가.hwpx」
    const seen = new Set();
    for (const it of S.items) {
      let d = splitext(it.rel)[0] + '.hwpx'; let k = d.toLowerCase(), n = 2;
      while (seen.has(k)) { d = splitext(it.rel)[0] + ' (' + n + ').hwpx'; k = d.toLowerCase(); n++; }
      seen.add(k); it.dst = d;
    }
  }
  function addFiles(list, info) {
    let skippedNon = 0, dup = 0;
    const cand = [];
    for (const x of list) { const path = nfc(x.path.replace(/\\/g, '/')); if (!isHwp(path)) { skippedNon++; continue; } cand.push({ file: x.file, path, fh: x.fh, dh: x.dh }); }
    // 폴더 하나만 놓았으면 그 폴더 이름을 벗겨 데스크톱판과 같은 구조로(결과 zip 이름에 쓴다)
    const heads = new Set(cand.map(c => c.path.split('/')[0])), loose = cand.some(c => !c.path.includes('/'));
    let strip = null;
    if (!S.items.length && cand.length && !loose && heads.size === 1 && cand.every(c => c.path.includes('/'))) { strip = [...heads][0]; S.outName = strip; }
    else if (!S.items.length) S.outName = '';
    const have = new Set(S.items.map(i => i.rel + '|' + i.size + '|' + i.mtime));
    const fresh = [];
    for (const c of cand) {
      const rel = strip ? c.path.slice(strip.length + 1) : c.path;
      const key = rel + '|' + c.file.size + '|' + c.file.lastModified;
      if (have.has(key)) { dup++; continue; }
      have.add(key); fresh.push({ rel, file: c.file, fh: c.fh, dh: c.dh });
    }
    const order = walkOrder(fresh.map(f => f.rel)); const byRel = new Map(fresh.map(f => [f.rel, f]));
    for (const rel of order) {
      const f = byRel.get(rel);
      S.items.push({ id: S.nextId++, rel, name: rel.split('/').pop(), size: f.file.size, mtime: f.file.lastModified, file: f.file, fh: f.fh, dh: f.dh, status: '대기', row: null, sens: null, hwpx: null, md: null, json: null, dst: '' });
    }
    assignNames();
    const added = fresh.length;
    let msg = `${added}개를 목록에 넣었습니다`;
    if (skippedNon) msg += ` · HWP 가 아닌 파일 ${skippedNon}개 제외`;
    if (dup) msg += ` · 이미 있는 ${dup}개 건너뜀`;
    if (info && info.skipped && info.skipped.dirs) msg += ` · 숨김·결과 폴더 ${info.skipped.dirs}개 제외`;
    if (!added && !dup) msg = skippedNon ? `HWP·HWPX 파일이 없습니다(다른 파일 ${skippedNon}개는 제외했습니다).` : '올릴 파일이 없습니다.';
    toast(msg, 5000);
    renderAll();
    if (added && readOpts().auto) kick();
  }

  // ---------------------------------------------------------------- 처리
  function friendlyReason(it) {
    const r = it.row || {}; const t = String(r.판정_이유 || '');
    const map = [
      [/빈 파일|\(empty\)/, '빈 파일입니다.'], [/\(unknown\)/, 'HWP 문서가 아닙니다.'],
      [/\(ole-broken\)/, '파일이 손상되어 읽을 수 없습니다.'], [/\(ole-not-hwp\)/, 'HWP 문서가 아닙니다.'],
      [/\(zip-broken\)/, '파일이 손상되었습니다.'], [/\(zip-not-hwpx\)/, 'HWPX 문서가 아닙니다.'],
      [/DRM/, 'DRM이 걸린 문서입니다. 해제 후 다시 올리세요.'],
      [/열기 암호/, '암호가 걸린 문서입니다. 설정에 암호를 넣고 다시 시도하세요.'],
      [/시간초과|시간 한도/, '너무 오래 걸려 멈췄습니다. 설정에서 시간을 늘려 보세요.'],
      [/엔진중단|엔진 일꾼|crash/, '이 문서는 변환하지 못했습니다.'],
      [/엔진오류/, '이 문서는 변환하지 못했습니다.'], [/처리 오류/, '처리 중 오류가 났습니다.'],
      [/이미 HWPX/, '이미 HWPX 입니다.'],
      [/등급|차단/, '개인정보 설정에 따라 변환하지 않았습니다.'],
    ];
    for (const [re, m] of map) if (re.test(t)) return m;
    return '';
  }
  async function processItem(it) {
    const o = readOpts();
    it.status = '처리중'; it.t0 = performance.now(); scheduleRender();
    let buf;
    try { buf = await it.file.arrayBuffer(); }
    catch (e) { finish(it, { row: { 원본: it.rel, 상태: '격리', 판정_이유: '읽기 실패: ' + e.message, 처리시각: new Date().toISOString() } }); return; }
    try {
      const res = await S.pool.run({ type: 'process', rel: it.rel, dst: it.dst, data: buf, opts: { timeout: o.timeout, password: o.password, include_hwpx: o.include_hwpx }, cfg: { policy: o.policy, engine_version: S.cfg.engine_version } },
        [buf], (o.timeout + 60) * 1000, S.records, S.recVer);
      finish(it, res);
    } catch (e) {
      if (e.kind === 'cancel') { it.status = '대기'; scheduleRender(); return; }
      const kind = e.kind === 'timeout' ? '시간초과' : e.kind === 'crash' ? '엔진중단' : '엔진오류';
      finish(it, { row: { 원본: it.rel, 원본_크기: it.size, 상태: '변환실패', 판정: 'FAIL', 판정_이유: `${kind}: ${String(e.message).slice(0, 200)}`, 처리시각: new Date().toISOString() } });
    }
  }
  function finish(it, res) {
    const row = res.row || {}; it.row = row; it.sens = res.sens || null; it.status = row.상태 || '변환실패';
    const bufs = res.buffers || {};
    if (bufs[it.dst]) { const u = new Uint8Array(bufs[it.dst]); it.hwpx = { blob: new Blob([u], { type: 'application/octet-stream' }), crc: Z.crc32(u), size: u.length }; }
    const dec = new TextDecoder();
    for (const k of Object.keys(bufs)) {
      if (k.startsWith('_검증서/')) { const t = dec.decode(bufs[k]); if (k.endsWith('.md')) it.md = t; else if (k.endsWith('.json')) it.json = t; }
    }
    it.ms = res.ms; syncRowSens(it);
    S.doneCount++; scheduleRender(); updateProgress();
    if (S.doneCount >= S.totalCount) runFinished();
  }
  function pending() { return S.items.filter(i => i.status === '대기'); }
  function kick() {
    if (!S.ready) return;
    const todo = pending();
    if (!todo.length) { return; }
    if (!S.running) { S.runStart = performance.now(); S.doneCount = 0; S.totalCount = 0; S.cancelled = false; }
    S.running += todo.length; S.totalCount += todo.length;
    for (const it of todo) { it.status = '큐'; }
    // 큰 파일부터 일꾼에 넣는다(가장 오래 걸리는 문서가 마지막에 혼자 남지 않게 — 전체 시간 단축). 화면 표 순서는 그대로.
    const sz = (it) => (it.file && it.file.size) || it.size || 0;
    const ord = todo.slice().sort((a, b) => sz(b) - sz(a));
    // 단, 가장 작은 파일 하나는 마지막 일꾼 몫으로 앞에 넣어 첫 결과가 바로 보이게 한다
    const w = Math.max(1, readOpts().jobs || 1);
    if (ord.length > w && w >= 2) ord.splice(w - 1, 0, ord.pop());
    for (const it of ord) processItem(it);
    updateProgress(); renderAll();
  }
  function runFinished() {
    S.running = 0; S.runEnd = performance.now(); updateProgress(); renderAll();
    try { window.dispatchEvent(new Event('hwpai-run-finished')); } catch (e) { /* */ }
    const s = counts(); toast(`처리 끝 — ${s.done}개 변환${s.fail ? ` · 실패·격리 ${s.fail}개` : ''}${s.wait ? ` · 개인정보 확인 대기 ${s.wait}개` : ''}`, 6000);
  }
  function updateProgress() {
    const done = S.doneCount, tot = S.totalCount;
    $('#runBar').style.width = tot ? (100 * done / tot) + '%' : '0%';
    let t = '';
    if (tot && S.running) {
      const el = (performance.now() - S.runStart) / 1000; const eta = done ? el / done * (tot - done) : 0;
      t = `${done} / ${tot} 처리 · ${el.toFixed(0)}초 경과` + (done && done < tot ? ` · 남은 시간 약 ${Math.ceil(eta)}초` : '');
    } else if (tot) t = `${done} / ${tot} 처리 끝 · ${(((S.runEnd || performance.now()) - S.runStart) / 1000).toFixed(1)}초`;
    $('#runText').textContent = t;
  }

  // ---------------------------------------------------------------- 민감정보 상태(화면 갱신용 — 저장된 결정 반영)
  function sensStatus(it) {
    if (!it.sens || it.sens.state == null) return null;
    const rec = it.sens.sha256 ? S.records[it.sens.sha256] || null : null;
    return R.statusOf(it.sens.items || [], rec);
  }
  function syncRowSens(it) {
    const row = it.row; if (!row) return;
    const st = sensStatus(it);
    if (!st) return;
    if (it.sens && it.sens.items && it.sens.items.length || row.민감정보) {
      row.민감정보 = st.state;
      const kinds = Object.entries(st.kinds).map(([k, v]) => `${k} ${v}`).join(', ');
      row.민감정보_항목 = kinds + (st.probably_ok ? ` (개인정보 아닌 항목 ${st.probably_ok}건 자동 제외)` : '');
      if (!st.total) { row.민감정보 = st.state; row.민감정보_항목 = ''; }
    }
  }
  function sensTag(it) {
    const st = sensStatus(it); if (!st) return it.sens && it.sens.state == null && it.row && it.row.상태 === '변환완료' ? '<span class="tag t-gray" title="판독하지 못해 민감정보를 확인할 수 없음">확인 불가</span>' : '';
    if (!st.total) return '<span class="tag t-ok">없음</span>';
    if (st.state === R.STATES[1]) return `<button class="tag t-wait sm-open" data-open="${it.id}" type="button" title="눌러서 확인 화면 열기">확인해 주세요 (${st.pending}건)</button>`;
    if (st.state === R.STATES[2]) return `<button class="tag t-ok sm-open" data-open="${it.id}" type="button">확인함 · 개인정보 아님</button>`;
    if (!st.sensitive && !st.pending) return `<button class="tag t-ok sm-open" data-open="${it.id}" type="button" title="개인정보로 보이지 않는 항목(담당 부서 등)만 있어 자동으로 걸렀습니다">없음</button>`;
    return `<button class="tag t-warn sm-open" data-open="${it.id}" type="button">개인정보 있음 ${st.sensitive}건</button>`;
  }
  const VWORD = { PASS: ['t-pass', '✔ PASS · 원본과 같음'], WARN: ['t-warn', '▲ 확인 필요'], FAIL: ['t-fail', '✖ FAIL · 원본과 다름'] };
  function verdictTag(it) {
    const r = it.row; if (!r) return '';
    const v = VWORD[r.판정]; return v ? `<span class="tag ${v[0]}">${v[1]}</span>` : '';
  }
  function statusTag(it) {
    switch (it.status) {
      case '대기': return '<span class="tag t-gray">대기</span>';
      case '큐': return '<span class="tag t-gray">차례 기다림</span>';
      case '처리중': return '<span class="tag t-gray"><span class="spin"></span>처리 중</span>';
      case '변환완료': return '<span class="tag t-ok">변환 완료</span>';
      case '건너뜀': return '<span class="tag t-gray">건너뜀</span>';
      case '변환실패': return '<span class="tag t-fail">변환 실패</span>';
      case '격리': return '<span class="tag t-fail">격리(변환 안 함)</span>';
      case '등급차단': return '<span class="tag t-warn">정책 차단</span>';
      default: return `<span class="tag t-gray">${esc(it.status)}</span>`;
    }
  }

  // ---------------------------------------------------------------- 표
  let rafId = 0;
  function scheduleRender() { if (rafId) return; rafId = requestAnimationFrame(() => { rafId = 0; renderAll(); }); }
  function counts() {
    const c = { total: S.items.length, done: 0, pass: 0, warn: 0, fail: 0, fail2: 0, wait: 0, skip: 0, doing: 0 };
    for (const it of S.items) {
      if (it.status === '변환완료') { c.done++; if (it.row.판정 === 'PASS') c.pass++; else if (it.row.판정 === 'WARN') c.warn++; else if (it.row.판정 === 'FAIL') c.fail++; }
      else if (it.status === '변환실패' || it.status === '격리') c.fail2++;
      else if (it.status === '건너뜀' || it.status === '등급차단') c.skip++;
      else c.doing++;
      const st = sensStatus(it); if (st && st.state === R.STATES[1]) c.wait++;
    }
    c.fail += 0; c.failall = c.fail2;
    return c;
  }
  function passFilter(it) {
    const f = S.filter;
    if (f === 'all') return true;
    const st = sensStatus(it);
    switch (f) {
      case 'PASS': return it.row && it.row.판정 === 'PASS' && it.status === '변환완료';
      case 'WARN': return it.row && it.row.판정 === 'WARN';
      case 'FAIL': return it.row && it.row.판정 === 'FAIL' && it.status === '변환완료';
      case 'bad': return it.status === '변환실패' || it.status === '격리' || it.status === '등급차단' || !!(it.row && it.row.판정 === 'FAIL' && it.status === '변환완료');
      case 'wait': return !!(st && st.state === R.STATES[1]);
      case 'skip': return it.status === '건너뜀';
    }
    return true;
  }
  function renderSummary() {
    const c = counts();
    const mk = (cls, f, n, label) => `<button type="button" class="stat ${cls} ${S.filter === f ? 'on' : ''}" data-f="${f}"><b>${n}</b><span>${label}</span></button>`;
    $('#summary').innerHTML = S.items.length ? [mk('', 'all', c.total, '전체'), mk('pass', 'PASS', c.pass, '정상 변환'), mk('warn', 'WARN', c.warn, '확인 필요'), mk('fail', 'bad', c.fail2 + c.fail, '변환 실패'), mk('wait', 'wait', c.wait, '개인정보 확인 대기')].join('') : '';
    $$('#summary .stat').forEach(b => b.onclick = () => { S.filter = b.dataset.f; renderAll(); });
  }
  function renderRows() {
    const tb = $('#rows'); const vis = S.items.filter(passFilter);
    const html = vis.map(it => {
      const r = it.row || {}; const why = friendlyReason(it);
      let reason = r.판정_이유 ? `<span title="${esc(r.판정_이유)}">${esc(String(r.판정_이유).slice(0, 160))}</span>` : '';
      if (why) reason = `<b title="${esc(r.판정_이유 || '')}">${esc(why)}</b>`;
      if (it.status === '변환완료' && !r.판정_이유 && r.판정 === 'PASS') reason = '<span class="mut">원본과 같습니다</span>';
      if (it.settleMsg) reason += `<br><small class="mut">${esc(it.settleMsg)}</small>`;
      const acts = [];
      if (it.hwpx) acts.push(`<button class="btn sm primary" data-act="dl" data-id="${it.id}" type="button">HWPX</button>`);
      if (it.md) acts.push(`<button class="btn sm" data-act="detail" data-id="${it.id}" type="button">검증서</button>`);
      if (it.status === '변환완료' || it.row && it.row.원본_형식) acts.push(`<button class="btn sm" data-act="exp" data-id="${it.id}" type="button">AI용</button>`);
      return `<tr data-id="${it.id}"><td class="c-sel"><input type="checkbox" data-sel="${it.id}" ${S.selected.has(it.id) ? 'checked' : ''} aria-label="선택"></td>
<td class="name" data-l="파일">${esc(it.rel)}</td>
<td data-l="결과">${it.status === '변환완료' && it.row && VWORD[it.row.판정] ? verdictTag(it) : statusTag(it)}</td>
<td data-l="개인정보">${sensTag(it)}</td><td class="reason" data-l="설명">${reason}</td><td class="c-act" data-l="동작">${acts.join(' ')}</td></tr>`;
    }).join('');
    tb.innerHTML = html;
    $('#selAll').checked = vis.length > 0 && vis.every(i => S.selected.has(i.id));
  }
  function renderAll() {
    const has = S.items.length > 0;
    $('#toolbar').hidden = !has; $('#listWrap').hidden = !has;
    document.body.classList.toggle('has-items', has);
    renderSummary(); renderRows();
    const c = counts();
    const doneAny = S.items.some(i => i.hwpx);
    $('#btnZip').disabled = !doneAny || !!S.running; $('#btnZipSel').disabled = !S.selected.size || !!S.running;
    $('#btnExport').disabled = !S.items.some(i => i.row && i.row.원본_형식 && i.status !== '대기') || !S.ready;
    $('#btnReview').disabled = !S.items.some(i => i.sens && i.sens.items && i.sens.items.length);
    $('#btnReview').textContent = c.wait ? `개인정보 확인 (${c.wait})` : '개인정보 보기';
    $('#btnStart').hidden = !pending().length || !!S.running; $('#btnStart').disabled = !S.ready;
    const canSettle = ST && ST.supported() && S.rootH && !S.running && S.items.some(i => i.fh && i.row && i.row.판정 === 'PASS' && i.hwpx && !i.settled && /\.hwp$/i.test(i.name));
    $('#settleBar').hidden = !canSettle;
    if (canSettle) {
      const n = S.items.filter(i => i.fh && i.row && i.row.판정 === 'PASS' && i.hwpx && !i.settled && /\.hwp$/i.test(i.name)).length;
      $('#settleTitle').textContent = `검증 통과 ${n}개 문서를 바꿀 수 있습니다`;
      $('#settleDesc').textContent = ` 「${S.rootH.name}」 폴더 안에서 .hwp → .hwpx 로 바뀌고, 원본 .hwp 는 「_원본보관」 폴더로 옮겨집니다(삭제 안 함).`;
    }
    { const bd = $('#btnDemo'); if (bd && bd.disabled && !S.running && S.items.length && !pending().length) bd.textContent = '✔ 변환 완료 — 아래 결과를 확인하세요'; }
    $('#btnCancel').hidden = !S.running;
    $('#btnRetry').hidden = !S.items.some(i => i.status === '변환실패' || i.status === '격리') || !!S.running;
    const chips = [['all', '전체'], ['PASS', '정상 변환'], ['WARN', '확인 필요'], ['bad', '변환 실패'], ['wait', '개인정보 확인 대기'], ['skip', '건너뜀']];
    $('.filters').innerHTML = chips.map(([f, l]) => `<button type="button" class="chip ${S.filter === f ? 'on' : ''}" data-f="${f}">${l}</button>`).join('');
    $$('.filters .chip').forEach(b => b.onclick = () => { S.filter = b.dataset.f; renderAll(); });
    updateNet();
  }

  // ---------------------------------------------------------------- 내려받기
  function download(blob, name) {
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
  }
  const enc = new TextEncoder();
  const te = (name, text) => ({ name, bytes: enc.encode(text) });
  let finSeq = 0;
  async function buildResultZip(items) {
    const entries = []; const rows = []; const order = [];
    for (const it of items) {
      if (!it.row) continue;
      syncRowSens(it); rows.push(it.row); order.push(it.rel);
      if (it.hwpx) entries.push({ name: it.dst, blob: it.hwpx.blob, crc: it.hwpx.crc, size: it.hwpx.size });
      if (it.md) entries.push(te('_검증서/' + it.rel + '.md', it.md));
      if (it.json) entries.push(te('_검증서/' + it.rel + '.json', it.json));
    }
    const fin = await S.pool.run({ type: 'finalize', id: 0, rows, order, wall: ((S.runEnd || performance.now()) - S.runStart) / 1000 }, [], 120000);
    const dec = new TextDecoder();
    for (const k of Object.keys(fin.buffers)) entries.push({ name: k, bytes: new Uint8Array(fin.buffers[k]) });
    const shas = new Set(items.map(i => i.sens && i.sens.sha256).filter(Boolean));
    const recs = Object.values(S.records).filter(r => shas.has(r.sha256));
    if (recs.length) entries.push(te('민감확인_결정.json', JSON.stringify(decisionFile(recs), null, 1)));
    entries.push(te('웹판_변환정보.json', JSON.stringify({
      tool: 'hwpai 웹 (브라우저 전용)', engine: S.info && ('rhwp-wasm ' + S.info.version), python: S.info && S.info.python, audit_version: '1.1',
      created: new Date().toISOString(), files: rows.length, note: '원본은 브라우저 밖으로 나가지 않았고, 이 zip 은 이 브라우저에서 만들어졌습니다. 격리(_격리) 사본은 만들지 않습니다.',
    }, null, 1)));
    return Z.makeZip(entries);
  }
  function decisionFile(recs) {
    return { reviewer: '', saved: new Date().toISOString(), docs: recs.map(r => ({ sha256: r.sha256, name: r.name_hint, policy: r.policy, decisions: Object.fromEntries((r.items || []).filter(i => i.decision).map(i => [i.key, i.decision])) })) };
  }
  async function zipAll(only) {
    const items = only ? S.items.filter(i => S.selected.has(i.id)) : S.items.filter(i => i.row);
    if (!items.length) return;
    toast('zip 을 만드는 중…'); 
    try { const blob = await buildResultZip(items); download(blob, (S.outName || 'hwpai') + '_hwpx변환.zip'); toast(`zip 을 내려받습니다 (${fmtSize(blob.size)})`); }
    catch (e) { toast('zip 만들기 실패: ' + e.message, 8000); console.error(e); }
  }

  // ---------------------------------------------------------------- 내보내기(Markdown·JSON·RAG 조각)
  async function exportDocs(items, opts) {
    const formats = opts.formats, aiFolder = opts.aiFolder; const entries = []; const used = new Set(); const rows = [];
    let n = 0;
    toast('내보내는 중…', 20000);
    for (const it of items) {
      n++; $('#runText').textContent = `내보내기 ${n} / ${items.length}`;
      let buf; try { buf = await it.file.arrayBuffer(); } catch (e) { rows.push({ file: it.name, status: '실패', reason: '읽기 실패' }); continue; }
      const o = readOpts();
      try {
        const res = await S.pool.run({ type: 'export', id: 0, rel: it.rel, data: buf, formats, aiFolder, cfg: { policy: o.policy, engine_version: S.cfg.engine_version } }, [buf], (o.timeout + 60) * 1000, S.records, S.recVer);
        res.file = it.name; rows.push(res);
        if (res.status === '쓴') {
          const stem = (it.rel.replace(/\.[^./]+$/, ''));
          let base = stem.split('/').pop(), name = base, k = 2; while (used.has(name.toLowerCase())) { name = base + ' (' + k + ')'; k++; } used.add(name.toLowerCase());
          const first = res.dir ? res.dir.split('/').pop() : base;
          for (const f of Object.keys(res.buffers)) {
            const rest = f.startsWith(first + '/') ? f.slice(first.length + 1) : f;
            entries.push({ name: '내보내기/' + name + '/' + rest, bytes: new Uint8Array(res.buffers[f]) });
          }
        }
      } catch (e) { rows.push({ file: it.name, status: '실패', reason: e.message.slice(0, 200) }); }
    }
    const wait = rows.filter(r => r.status === '확인대기' || r.status === '차단');
    if (wait.length) entries.push(te('내보내기/확인대기_목록.md', '# 확인 대기 — AI 폴더에 쓰지 않은 문서\n\n민감정보 확인을 마치면 다시 내보내세요. 내용은 이 목록에 적지 않습니다.\n\n' + wait.map(r => `- ${r.file} (${r.status})`).join('\n') + '\n'));
    entries.push(te('내보내기/내보내기_안내.txt', (aiFolder ? 'AI 폴더용 내보내기 — 민감정보 확인이 끝난 문서만 포함했습니다(확인 필요 문서는 확인대기_목록.md 에 이름만 올렸습니다).\n' : '사람이 읽는 용도의 내보내기 — AI 폴더에 옮기기 전에 민감정보 확인을 마치세요.\n') + `형식: ${formats.join(', ')}\n`));
    const w = rows.filter(r => r.status === '쓴').length, fl = rows.filter(r => r.status === '실패').length;
    if (!w) { toast(`내보낸 문서가 없습니다${wait.length ? ' — 민감정보 확인 대기 ' + wait.length + '개는 확인 뒤에 내보낼 수 있습니다.' : ''}${fl ? ' (실패 ' + fl + ')' : ''}`, 7000); updateProgress(); return; }
    download(Z.makeZip(entries), (S.outName || (items.length === 1 ? items[0].name.replace(/\.[^.]+$/, '') : 'hwpai')) + '_내보내기.zip');
    toast(`내보내기 ${w}개${wait.length ? ' · 확인 대기로 제외 ' + wait.length + '개' : ''}${fl ? ' · 실패 ' + fl + '개' : ''}`, 7000);
    updateProgress();
  }
  function askExport(items) {
    const dlg = $('#detail'); const sel = items.length;
    $('#detailTitle').textContent = 'Markdown·JSON 내보내기';
    $('#detailBody').innerHTML = `<p>${sel}개 문서를 내보냅니다. 본문.md(제목 수준·표·그림 참조·각주), 구조.json(스키마 hwpai-structure/1), chunks.jsonl(RAG 조각)과 그림 파일이 문서마다 폴더로 들어갑니다.</p>
<div class="grid" style="display:grid;gap:8px">
<label><input type="checkbox" id="xMd" checked> 본문.md (Markdown)</label><label><input type="checkbox" id="xJson" checked> 구조.json</label><label><input type="checkbox" id="xCh"> chunks.jsonl (RAG 조각)</label>
<label><input type="checkbox" id="xAi" checked> <b>AI 폴더용</b> — 민감정보 「확인 필요」 문서는 쓰지 않고 목록에만 올립니다(작성자 등 문서 속성도 뺌). 끄면 사람이 읽는 용도입니다.</label></div>
<p class="btns" style="justify-content:flex-start"><button class="btn primary" id="xGo" type="button">내려받기</button></p>`;
    dlg.showModal();
    $('#xGo').onclick = () => {
      const formats = [$('#xMd').checked && 'md', $('#xJson').checked && 'json', $('#xCh').checked && 'chunks'].filter(Boolean);
      if (!formats.length) { toast('형식을 하나 이상 고르세요'); return; }
      dlg.close(); exportDocs(items, { formats, aiFolder: $('#xAi').checked });
    };
  }

  // ---------------------------------------------------------------- 민감정보 확인 화면
  function openReview(startId) {
    const items = S.items.filter(i => i.sens && i.sens.items && i.sens.items.length);
    if (!items.length) { toast('검출된 민감정보 후보가 없습니다.'); return; }
    // 확인 필요 문서를 앞으로
    const ord = items.slice().sort((a, b) => {
      const sa = sensStatus(a).state === R.STATES[1] ? 0 : 1, sb = sensStatus(b).state === R.STATES[1] ? 0 : 1; return sa - sb;
    });
    const docs = ord.map(i => {
      const rec = S.records[i.sens.sha256]; const decisions = {};
      if (rec) rec.items.forEach(r => { if (r.decision) decisions[r.key] = r.decision; });
      return { id: i.id, name: i.rel, sha256: i.sens.sha256, text: i.sens.text || '', items: i.sens.items, decisions, policy: rec && rec.policy };
    });
    const startIndex = Math.max(0, docs.findIndex(d => d.id === startId));
    R.open({
      docs, startIndex, reviewer: LS.get('hwpai.reviewer', ''),
      onSave(out, who) {
        if (who) LS.set('hwpai.reviewer', who);
        for (const d of out) {
          const had = S.records[d.sha256];
          if (!Object.keys(d.decisions).length && !had) continue;
          S.records[d.sha256] = R.makeRecord(d.sha256, d.items, d.decisions, d.policy, who, d.name);
        }
        S.recVer++; LS.set('hwpai.sens.v1', S.records);
        S.items.forEach(syncRowSens); renderAll();
      },
      onExportFile(data) { download(new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' }), '민감확인_결정.json'); },
      onClose() { renderAll(); },
    });
  }

  // ---------------------------------------------------------------- 검증서 보기
  function mdToHtml(md) {
    const lines = md.split('\n'); const out = []; let inTable = false, inList = false;
    const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
    const closeAll = () => { if (inTable) { out.push('</tbody></table>'); inTable = false; } if (inList) { out.push('</ul>'); inList = false; } };
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (/^\s*\|.*\|\s*$/.test(l)) {
        if (/^\s*\|[\s:|-]+\|\s*$/.test(l)) continue;
        const cells = l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        if (!inTable) { if (inList) { out.push('</ul>'); inList = false; } out.push('<table><thead><tr>' + cells.map(c => '<th>' + inline(c) + '</th>').join('') + '</tr></thead><tbody>'); inTable = true; }
        else out.push('<tr>' + cells.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>');
        continue;
      }
      if (inTable) { out.push('</tbody></table>'); inTable = false; }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) { closeAll(); out.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`); continue; }
      if (/^\s*[-*]\s+/.test(l)) { if (!inList) { out.push('<ul>'); inList = true; } out.push('<li>' + inline(l.replace(/^\s*[-*]\s+/, '')) + '</li>'); continue; }
      if (inList) { out.push('</ul>'); inList = false; }
      if (l.trim()) out.push('<p>' + inline(l) + '</p>');
    }
    closeAll(); return out.join('\n');
  }
  // 시연(?demo)에서 「AI용」: 파일 묶음을 내려받게 하지 않고, AI가 읽게 될 모습을 바로 보여 준다(파일은 「파일로 받기」로).
  function aiSafeHtml(md) {
    const tbl = (t) => esc(t).replace(/&lt;(\/?)(table|tr|td|th)((?:\s+(?:colspan|rowspan)=(?:&quot;|")\d+(?:&quot;|"))*)&gt;/g, (m, c, tag, at) => '<' + c + tag + (at || '').replace(/&quot;/g, '"') + '>').replace(/&lt;br\s*\/?&gt;/g, '<br>');
    const pic = (h) => h.replace(/!\[[^\]]*\]\([^)]*\)|\[그림:[^\]]*\]/g, '<span class="aipic">🖼 그림</span>').replace(/&lt;br\s*\/?&gt;/g, '<br>');
    const out = []; let last = 0; const re = /<table>[\s\S]*?<\/table>/g; let m;
    while ((m = re.exec(md))) { out.push(pic(mdToHtml(md.slice(last, m.index)))); out.push(pic(tbl(m[0]))); last = re.lastIndex; }
    out.push(pic(mdToHtml(md.slice(last)))); return out.join('\n');
  }
  async function previewAI(it) {
    const dlg = $('#detail'); $('#detailTitle').textContent = 'AI용 — ' + it.rel;
    const st = sensStatus(it);
    if (st && st.state === R.STATES[1]) {
      $('#detailBody').innerHTML = `<div class="rhero warn"><u>🔒</u><div><b>잠금</b><em>개인정보 확인 전</em><p>사람이 확인하기 전에는 AI용으로 내보내지 않습니다</p></div></div><div class="rpii wait"><u>🔒</u><div><b>${esc(Object.entries(st.kinds || {}).map(([k, v]) => k + ' ' + v + '건').join(', '))}</b><p>확인을 마치면 AI용으로 내보낼 수 있습니다</p><button class="btn primary sm" id="aiReview" type="button">개인정보 확인하기</button></div></div>`;
      $('#aiReview').onclick = () => { dlg.close(); openReview(it.id); };
      if (!dlg.open) dlg.showModal(); return;
    }
    $('#detailBody').innerHTML = `<div class="rhero ok"><u>🤖</u><div><b>AI용</b><em>만드는 중…</em><p>AI가 읽기 쉬운 꼴로 바꾸고 있습니다</p></div></div>`;
    if (!dlg.open) dlg.showModal();
    try {
      if (!it._ai) {
        const buf = await it.file.arrayBuffer(); const o = readOpts();
        const res = await S.pool.run({ type: 'export', id: 0, rel: it.rel, data: buf, formats: ['md', 'chunks'], aiFolder: false, cfg: { policy: o.policy, engine_version: S.cfg.engine_version } }, [buf], (o.timeout + 60) * 1000, S.records, S.recVer);
        const dec = new TextDecoder(); const ks = Object.keys(res.buffers || {}); const km = ks.find(f => /\.md$/.test(f)); const kc = ks.find(f => /\.jsonl$/.test(f));
        if (!km) throw new Error('본문을 만들지 못했습니다');
        const md = dec.decode(new Uint8Array(res.buffers[km])); const ch = kc ? dec.decode(new Uint8Array(res.buffers[kc])).split('\n').filter(x => x.trim()).length : 0;
        it._ai = { md, ch };
      }
      const md = it._ai.md; const nT = (md.match(/\*\*\[표\d+\]\*\*/g) || []).length; const nP = (md.match(/!\[[^\]]*\]\([^)]*\)|\[그림:[^\]]*\]/g) || []).length;
      let cut = md.slice(0, 2600); const e = Math.max(cut.lastIndexOf('</table>') + 8, cut.lastIndexOf('\n\n')); if (e > 600) cut = cut.slice(0, e);
      const N = (n) => Number(n).toLocaleString('ko-KR');
      $('#detailBody').innerHTML = `<div class="rhero ok"><u>🤖</u><div><b>AI용</b><em>준비됨</em><p>AI가 표와 글을 그대로 읽습니다</p></div></div>
<div class="rtiles"><div class="rt ok"><u>📝</u><b>${N(md.length)}</b><span>글자</span></div><div class="rt ok"><u>▦</u><b>${N(nT)}</b><span>표</span></div><div class="rt ok"><u>🧩</u><b>${N(it._ai.ch)}</b><span>검색 조각</span></div></div>
<p class="rnote">AI가 읽는 모습 (앞부분)</p>
<div class="aiprev">${aiSafeHtml(cut)}</div>
<div class="aifmt"><span>본문.md</span><span>구조.json</span><span>chunks.jsonl</span>${nP ? `<span>그림 ${N(nP)}개</span>` : ''}</div>
<p class="btns" style="justify-content:center"><button class="btn sm" id="aiFiles" type="button">파일로 받기</button></p>`;
      $('#aiFiles').onclick = () => askExport([it]);
    } catch (e) { $('#detailBody').innerHTML = `<div class="rhero gray"><u>•</u><div><b>AI용</b><p>${esc(e.message || String(e))}</p></div></div>`; }
  }
  // 검증서 쉬운 설명: 어디가 다른지 · 왜 그런지 · 어떻게 하면 되는지 (본체 explain.py 가 만든 쉬운설명)
  function explainHtml(it) {
    let x = null; try { x = JSON.parse(it.json || 'null'); } catch (e) { /* */ }
    x = x && x['쉬운설명']; if (!x) return '';
    const df = x['다른 부분'] || [];
    const dh = df.length ? `<h3>달라진 곳</h3><ol>${df.slice(0, 8).map(d => `<li><b>${esc(d['종류'])}</b> · ${esc(d['위치'])}<br>원본: 「${esc(d['원본'])}」<br>변환본: 「${esc(d['변환본'])}」</li>`).join('')}</ol>${df.length > 8 ? `<p class="mut">그 밖에 ${df.length - 8}곳</p>` : ''}` : '';
    const wy = x['왜 그런가'] || [];
    const wh = wy.length ? `<h3>왜 그런가</h3><ul>${wy.map(c => `<li>${esc(c['왜'])}<br><b>${esc(c['어떻게'])}</b></li>`).join('')}</ul>` : '';
    const fx = (x['AI가_고치려면'] || {})['수정안'] || [];
    const fh = fx.length ? `<h3>AI가 고칠 수 있습니다</h3><p>AI에 이 검증서(.json)를 주면 바로 고쳐서 다시 변환합니다. (${fx.length}곳)</p>` : '';
    const cmp = (x['비교한 것'] || []).map(c => `<tr><td>${esc(c['항목'])}</td><td>${esc(c['원본'])}</td><td>${esc(c['변환본'])}</td><td>${c['결과'] === '같음' ? '같음' : '다름'}</td></tr>`).join('');
    return `<div class="plain">${dh}${wh}${fh}<details class="more"><summary>비교한 항목</summary><table class="cmp"><thead><tr><th>항목</th><th>원본</th><th>변환본</th><th>결과</th></tr></thead><tbody>${cmp}</tbody></table></details></div>`;
  }
  function showDetail(it) {
    const r = it.row || {}; const dlg = $('#detail');
    $('#detailTitle').textContent = '검증서 — ' + it.rel;
    const fp = (h) => h ? String(h).slice(0, 8) + '…' + String(h).slice(-4) : '';
    const V = { PASS: '원본과 같습니다. 그대로 쓰셔도 됩니다.', WARN: '일부가 다를 수 있습니다. 한글에서 한번 열어 보세요.', FAIL: '내용이 빠졌습니다. 그대로 쓰지 마세요.' }[r.판정] || '';
    const same = r.원본_SHA256 && r.변환본_SHA256;
    // 두 가지를 따로 보인다: ① 변환이 제대로 됐는가 ② AI에 넘기기 전 개인정보 확인이 필요한가
    const vcls = { PASS: 'ok', WARN: 'warn', FAIL: 'bad' }[r.판정] || 'gray';
    const vtxt = { PASS: '✔ 정상 변환', WARN: '▲ 확인 필요', FAIL: '✖ 변환 실패' }[r.판정] || esc(it.status || '');
    const st = sensStatus(it);
    const kinds = st ? Object.entries(st.kinds || {}).map(([k, v]) => `${k} ${v}건`).join(', ') : '';
    let scls = 'gray', stxt = '—', sdesc = '판독하지 못해 확인할 수 없습니다.', sbtn = '';
    if (st && !st.total) { scls = 'ok'; stxt = '✔ 없음'; sdesc = '개인정보로 보이는 것이 없습니다.'; }
    else if (st && st.state === R.STATES[1]) { scls = 'wait'; stxt = '⚠ 확인해 주세요'; sdesc = `발견: ${kinds}. 변환에는 문제가 없고, AI에 넘기기 전에 사람이 한 번 확인합니다.`; sbtn = `<button class="btn primary sm" id="dReview" type="button">개인정보 확인하기</button>`; }
    else if (st && st.state === R.STATES[2]) { scls = 'ok'; stxt = '✔ 확인 완료'; sdesc = '사람이 확인했습니다 — 개인정보 아님.'; }
    else if (st && !st.sensitive && !st.pending) { scls = 'ok'; stxt = '✔ 없음'; sdesc = `담당 부서 같은 업무 정보 ${st.probably_ok || ''}건은 개인정보가 아니라서 자동으로 제외했습니다.`; }
    else if (st) { scls = 'warn'; stxt = `개인정보 있음 ${st.sensitive}건`; sdesc = 'AI에는 가리거나 막아서 넘깁니다.'; sbtn = `<button class="btn sm" id="dReview" type="button">다시 보기</button>`; }
    const cards = `<div class="dcards"><div class="dcard ${vcls}"><span>변환</span><b>${vtxt}</b><p>${esc(V)}</p></div><div class="dcard ${scls}"><span>개인정보 (AI에 넘기기 전)</span><b>${stxt}</b><p>${esc(sdesc)}</p>${sbtn}</div></div>`;
    const tech = [['원본 크기', fmtSize(r.원본_크기)], ['변환본 크기', fmtSize(r.변환본_크기)], ['원본 형식', r.원본_형식], ['특성', r.특성], ['원본 파일 지문(SHA-256)', r.원본_SHA256], ['변환본 파일 지문(SHA-256)', r.변환본_SHA256],
      ['엔진', r.엔진 ? `${r.엔진} ${r.엔진_판}` : ''], ['변환 소요', r.변환_소요ms ? r.변환_소요ms + ' ms' : ''], ['검증 점수·판정', r.판정 ? `${r.검증점수} · ${r.판정}` : '']].filter(x => x[1]);
    let xx = null; try { xx = JSON.parse(it.json || 'null'); } catch (e) { /* */ }
    const cmpAll = ((xx && xx['쉬운설명'] || {})['비교한 것'] || []);
    const IC = { '글': '📝', '표': '▦', '그림': '🖼', '각주': '※', '미주': '※', '수식': '∑' };
    const num = (v) => { const m = /^([\d,]+)\s*(.*)$/.exec(String(v || '')); return m ? [Number(m[1].replace(/,/g, '')).toLocaleString('ko-KR'), m[2]] : [String(v || ''), '']; };
    const tiles = cmpAll.filter(c => ['글', '표', '그림'].indexOf(c['항목']) >= 0 || parseInt(c['원본'], 10) > 0).map(c => { const [n, u] = num(c['원본']); const same = c['결과'] === '같음'; return `<div class="rt ${same ? 'ok' : 'bad'}"><u>${IC[c['항목']] || '•'}</u><b>${esc(n)}</b><span>${esc(c['항목'] === '글' ? '글자' : c['항목'])}</span><em>${same ? '✔ 같음' : '✖ 다름'}</em></div>`; }).join('');
    const cellNote = (cmpAll.find(c => c['항목'] === '표') || {})['설명'] || '';
    const hero = { PASS: ['ok', '✔', 'PASS', '원본과 같음', '그대로 쓰셔도 됩니다'], WARN: ['warn', '▲', '확인 필요', '일부가 다를 수 있음', '한글에서 한 번 열어 보세요'], FAIL: ['bad', '✖', 'FAIL', '원본과 다름', '그대로 쓰지 마세요'] }[r.판정] || ['gray', '•', esc(it.status || ''), '', ''];
    const flow = (r.원본_크기 && r.변환본_크기) ? `<div class="rflow"><span class="a">HWP<small>${esc(fmtSize(r.원본_크기))}</small></span><i><em>${r.변환_소요ms ? (r.변환_소요ms / 1000).toFixed(1) + '초' : ''}</em><s></s></i><span class="b">HWPX<small>${esc(fmtSize(r.변환본_크기))}</small></span></div>` : '';
    const pcard = `<div class="rpii ${scls}"><u>${scls === 'ok' ? '🔓' : '🔒'}</u><div><b>개인정보 ${scls === 'ok' ? '없음' : (kinds ? esc(kinds) : stxt.replace(/^[✔⚠]\s*/, ''))}</b><p>${scls === 'ok' ? 'AI에 넘겨도 되는 문서입니다' : 'AI에 넘기기 전에 사람이 한 번 확인합니다'}</p>${sbtn}</div></div>`;
    $('#detailBody').innerHTML = `<div class="rhero ${hero[0]}"><u>${hero[1]}</u><div><b>${hero[2]}</b><em>${hero[3]}</em><p>${hero[4]}</p></div></div>
${flow}
<div class="rtiles">${tiles}</div>
${cellNote ? `<p class="rnote">${esc(cellNote)}</p>` : ''}
${pcard}
${(xx && (xx['쉬운설명'] || {})['다른 부분'] || []).length ? explainHtml(it) : ''}
<details class="more"><summary>자세히 보기 · 검증서 받기</summary>
${same ? `<p class="fpbox"><b>파일 지문</b> 원본 <code>${esc(fp(r.원본_SHA256))}</code> · 바뀐 파일 <code>${esc(fp(r.변환본_SHA256))}</code> <button class="btn sm" id="dCopy" type="button">지문 복사</button></p>` : ''}
<p class="btns" style="justify-content:flex-start"><button class="btn sm" id="dMd" type="button">검증서(.md) 받기</button> <button class="btn sm" id="dJson" type="button">검증서(.json) 받기</button></p>
<dl class="kv">${tech.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><div>${mdToHtml(String(it.md || '').split('# 자세한 기록 (전문가용)').pop())}</div></details>`;
    $('#detailBody').querySelectorAll('details.more').forEach(d => d.addEventListener('toggle', () => { if (d.open) { try { d.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) { /* */ } } }));
    const cp = $('#dCopy'); if (cp) cp.onclick = () => { try { navigator.clipboard.writeText(`원본 ${r.원본_SHA256}\n변환본 ${r.변환본_SHA256}`); cp.textContent = '복사했습니다'; } catch (e) { cp.textContent = '복사 못 함'; } };
    const dr = $('#dReview'); if (dr) dr.onclick = () => { dlg.close(); openReview(it.id); };
    $('#dMd').onclick = () => download(new Blob([it.md || ''], { type: 'text/markdown' }), it.name + '.검증서.md');
    $('#dJson').onclick = () => download(new Blob([it.json || ''], { type: 'application/json' }), it.name + '.검증서.json');
    dlg.showModal();
  }

  // ---------------------------------------------------------------- 네트워크 점검 배지
  async function netReport() {
    let worker = [];
    if (S.pool) { for (const s of S.pool.slots) { try { const r = await S.pool.run({ type: 'selftest' }, [], 5000); worker = worker.concat(r.netAttempts || []); break; } catch (e) { /* */ } } }
    return worker;
  }
  function updateNet() {
    const n = E.NET; const bad = n.external + n.blocked;
    $('#netText').textContent = bad ? `외부 요청 ${bad}건 차단됨` : '외부 전송 0건';
    $('#netBadge').classList.toggle('bad', !!bad); $('#netBadge').classList.toggle('ok', !bad);
  }
  async function showNet() {
    const n = E.NET; const w = await netReport();
    $('#netBody').innerHTML = `<p>이 페이지는 처리에 서버·CDN·AI 모델을 부르지 않습니다. 아래는 이 탭이 센 수치입니다.</p>
<dl class="kv"><dt>외부로 나간 요청</dt><dd>${n.external}건</dd><dt>차단한 시도(XHR·WebSocket 등)</dt><dd>${n.blocked}건</dd>
<dt>일꾼(Worker)의 거부 기록</dt><dd>${w.length}건</dd><dt>같은 위치 엔진 파일 읽기</dt><dd>${n.local}건 (${S.assetMode === 'payload' ? 'file:// 에서는 내장 묶음(payload/*.js)을 읽음' : '정적 파일'})</dd>
<dt>파일 읽기 방식</dt><dd>${esc(location.protocol)} · 엔진 파일 SHA-256 대조 ${S.verified}건 일치</dd>
<dt>콘텐츠 보안 정책(CSP)</dt><dd>connect-src 'self' blob: data: · form-action 'none'</dd></dl>
<p class="mut">브라우저 개발자 도구(F12) → 네트워크 탭에서 파일을 올린 뒤에도 새 요청이 생기지 않는 것을 직접 확인할 수 있습니다.</p>
${(n.log.length || w.length) ? `<pre>${esc(n.log.concat(w).slice(-40).join('\n'))}</pre>` : ''}`;
    $('#netDlg').showModal();
  }

  // ---------------------------------------------------------------- 보관 원본 정리(기한 지난 .hwp)
  function openPurge() {
    if (!(ST && ST.supported())) { toast('이 브라우저는 폴더 쓰기를 지원하지 않습니다(Chrome·Edge 데스크톱).', 6000); return; }
    const P = { arch: null, root: null };
    $('#detailTitle').textContent = '보관 원본 정리';
    $('#detailBody').innerHTML = `<p>기한이 지난 보관 원본(.hwp)만 지웁니다. 먼저 <b>보관 폴더</b>(안에 보관대장.csv)와 <b>원본 폴더</b>(제자리 .hwpx 가 있는 폴더)를 차례로 엽니다. 삭제 전에 미리보기를 보여 드리며, 제자리 .hwpx 나 보관 원본의 SHA-256 이 기록과 다르면 지우지 않습니다.</p>
<p class="btns" style="justify-content:flex-start"><button class="btn" id="pgA" type="button">① 보관 폴더 열기</button><button class="btn" id="pgR" type="button">② 원본 폴더 열기</button><button class="btn primary" id="pgPv" type="button" disabled>③ 미리보기</button><button class="btn" id="pgGo" type="button" hidden>기한 지난 원본 삭제 실행</button></p><pre id="pgOut" class="mut">아직 열지 않았습니다.</pre>`;
    const out = (t) => { $('#pgOut').textContent = t; };
    const fmt = (r) => `기한 지난 ${r.대상}건 — 삭제 ${r.삭제} · 보류 ${r.보류} · 기한 전 ${r.아직}` + r.내역.slice(0, 30).map(x => `\n  ${x[1]}: ${x[0]}${x[2] ? ' — ' + x[2] : ''}`).join('');
    const ready = () => { $('#pgPv').disabled = !(P.arch && P.root); };
    $('#pgA').onclick = async () => { try { P.arch = await window.showDirectoryPicker({ mode: 'readwrite' }); out('보관 폴더: ' + P.arch.name + (P.root ? ' · 원본 폴더: ' + P.root.name : '')); ready(); } catch (e) { /* 취소 */ } };
    $('#pgR').onclick = async () => { try { P.root = await window.showDirectoryPicker({ mode: 'readwrite' }); if (!P.arch) { try { P.arch = await P.root.getDirectoryHandle(ST.AUTO_ARC); } catch (e2) { /* 자동 보관 폴더 없음 */ } } out((P.arch ? '보관 폴더: ' + P.arch.name + ' · ' : '') + '원본 폴더: ' + P.root.name); ready(); } catch (e) { /* 취소 */ } };
    $('#pgPv').onclick = async () => { try { const r = await ST.purge(P.arch, P.root, true); out(fmt(r) + (r.삭제 ? '\n\n실제로 지우려면 「기한 지난 원본 삭제 실행」을 누르세요.' : '')); $('#pgGo').hidden = !r.삭제; } catch (e) { out('오류: ' + e.message); $('#pgGo').hidden = true; } };
    $('#pgGo').onclick = async () => {
      if (!confirm('기한이 지난 보관 원본(.hwp)을 지웁니다. 되돌릴 수 없습니다.\n미리보기에서 본 항목만 지워지며 SHA-256 이 어긋난 것은 건너뜁니다. 실행할까요?')) return;
      try { const r = await ST.purge(P.arch, P.root, false); out(fmt(r)); $('#pgGo').hidden = true; } catch (e) { out('오류: ' + e.message); }
    };
    $('#detail').showModal();
  }

  // ---------------------------------------------------------------- 이벤트
  function wire() {
    const drop = $('#drop');
    ['dragenter', 'dragover'].forEach(ev => document.addEventListener(ev, (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) { e.preventDefault(); drop.classList.add('over'); } }));
    document.addEventListener('dragleave', (e) => { if (!e.relatedTarget) drop.classList.remove('over'); });
    document.addEventListener('drop', async (e) => {
      if (!e.dataTransfer) return; e.preventDefault(); drop.classList.remove('over');
      const hps = (ST && ST.supported()) ? Array.from(e.dataTransfer.items || []).filter(it => it.kind === 'file' && it.getAsFileSystemHandle).map(it => it.getAsFileSystemHandle()) : [];   // 동기 구간에서 핸들 요청까지 시작해 둔다
      const c = await collectFromDrop(e.dataTransfer);   // 동기 구간에서 entry 를 먼저 얻는다
      try { if (await openRWHandle(hps)) return; } catch (err) { console.error(err); }
      try { const r = await resolveDropped(c); addFiles(r.list, r); } catch (err) { toast('끌어놓은 항목을 읽지 못했습니다: ' + err.message, 7000); console.error(err); }
    });
    $('#pickFiles').onclick = () => $('#fileInput').click();
    drop.addEventListener('click', (e) => { if (e.target.closest('button,input')) return; $('#fileInput').click(); });
    $('#pickDir').onclick = () => $('#dirInput').click();
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#fileInput').click(); } });
    $('#fileInput').onchange = (e) => { addFiles(Array.from(e.target.files).map(f => ({ file: f, path: f.name })), null); e.target.value = ''; };
    $('#dirInput').onchange = (e) => { addFiles(Array.from(e.target.files).map(f => ({ file: f, path: f.webkitRelativePath || f.name })), null); e.target.value = ''; };
    if (ST && ST.supported()) { $('#rwCard').hidden = false; $('#optKeepWrap').hidden = false; }
    $('#pickRW').onclick = async () => {
      try {
        const h = await window.showDirectoryPicker({ mode: 'readwrite' });
        await useRootHandle(h);
      } catch (e) { if (e.name !== 'AbortError') toast('폴더를 열지 못했습니다: ' + e.message, 7000); }
    };
    $('#btnSettle').onclick = async () => {
      const keep = +$('#optKeep').value;   // 기본 30일, 0=계속 보관
      const items = S.items.filter(i => i.fh && i.row && i.row.판정 === 'PASS' && i.hwpx && !i.settled && /\.hwp$/i.test(i.name));
      if (!items.length) return;
      const pickArc = $('#optPickArc') && $('#optPickArc').checked;
      if (!confirm(`폴더에 적용: 검증 PASS인 ${items.length}개 문서의 .hwpx 를 원래 자리에 두고, 원본 .hwp 는 ` + (pickArc ? '이어서 고르는 보관 폴더로' : '이 폴더 안의 「_원본보관」 폴더로') + ` 옮깁니다(지워지지 않습니다). 계속할까요?`)) return;
      let archH;
      try { archH = pickArc ? await window.showDirectoryPicker({ mode: 'readwrite' }) : await ST.autoArchive(S.rootH); } catch (e) { if (e.name !== 'AbortError') toast('보관 폴더를 열지 못했습니다: ' + e.message, 7000); return; }
      try {
        const res = await ST.settle(items, S.rootH, archH, keep, (n, t, rel) => { $('#runText').textContent = `제자리 교체 ${n} / ${t} · ${rel}`; });
        let ok = 0; for (const r of res) { r.it.settleMsg = r.msg; if (r.ok) { r.it.settled = true; ok++; } }
        toast(`제자리 교체 ${ok}개 완료 · 안 한 것 ${res.length - ok}개(사유는 표의 설명 칸) · 보관: ${archH.name}`, 9000);
      } catch (e) { toast('제자리 교체를 하지 못했습니다: ' + e.message, 9000); }
      updateProgress(); renderAll();
    };
    $('#btnPurge').onclick = () => openPurge();
    $('#btnStart').onclick = () => kick();
    $('#btnCancel').onclick = () => {
      S.pool.cancelQueued(() => true); S.cancelled = true;
      for (const it of S.items) if (it.status === '큐') it.status = '대기';
      toast('대기 중인 파일을 취소했습니다. 진행 중인 파일은 끝까지 처리합니다.'); renderAll();
    };
    $('#btnZip').onclick = () => zipAll(false); $('#btnZipSel').onclick = () => zipAll(true);
    $('#btnExport').onclick = () => askExport(S.selected.size ? S.items.filter(i => S.selected.has(i.id)) : S.items.filter(i => i.row && i.row.원본_형식 && i.status !== '대기'));
    $('#btnReview').onclick = () => openReview();
    $('#btnRetry').onclick = () => { for (const it of S.items) if (it.status === '변환실패' || it.status === '격리') { it.status = '대기'; it.row = null; it.sens = null; } renderAll(); kick(); };
    $('#btnClear').onclick = () => {
      if (S.running && !confirm('처리 중입니다. 목록을 비우면 진행 중인 결과가 사라집니다. 비울까요?')) return;
      if (S.running) { S.pool.cancelQueued(() => true); }
      S.items = []; S.selected.clear(); S.running = 0; S.doneCount = S.totalCount = 0; S.outName = ''; renderAll(); updateProgress();
    };
    $('#selAll').onchange = (e) => { S.items.filter(passFilter).forEach(i => { if (e.target.checked) S.selected.add(i.id); else S.selected.delete(i.id); }); renderAll(); };
    $('#rows').addEventListener('click', (e) => {
      const b = e.target.closest('button'); const cb = e.target.closest('input[data-sel]');
      if (cb) { const id = +cb.dataset.sel; if (cb.checked) S.selected.add(id); else S.selected.delete(id); renderAll(); return; }
      if (!b) return;
      if (b.dataset.open) { openReview(+b.dataset.open); return; }
      const it = S.items.find(i => i.id === +b.dataset.id); if (!it) return;
      if (b.dataset.act === 'dl') download(it.hwpx.blob, it.dst.split('/').pop());
      else if (b.dataset.act === 'detail') showDetail(it);
      else if (b.dataset.act === 'exp') { if (new URLSearchParams(location.search).has('demo')) previewAI(it); else askExport([it]); }
    });
    $('#detailClose').onclick = () => $('#detail').close(); $('#netClose').onclick = () => $('#netDlg').close();
    $('#netBadge').onclick = showNet;
    window.addEventListener('beforeunload', (e) => { if (S.running) { e.preventDefault(); e.returnValue = ''; } });
  }

  // 글자 크기(큰 글씨): 기본 크게, 이 브라우저에만 기억
  (function () {
    const set = (z) => { document.documentElement.style.setProperty('--z', z); LS.set('hwpai.z.v1', z); $$('.fsz button').forEach(b => b.classList.toggle('on', +b.dataset.z === +z)); };
    $$('.fsz button').forEach(b => b.addEventListener('click', () => set(+b.dataset.z)));
    set(1.25);   // 글자 크기 고정(크게) — 선택 단추는 없앴다
  })();
  initOpts(); wire(); renderAll();
  // 현장 시연: 주소에 ?demo 가 있을 때만 예제 HWP 를 불러오는 단추를 보인다(같은 출처 정적 파일, 외부 전송 없음)
  (function () {
    if (!new URLSearchParams(location.search).has('demo')) return;
    // 큰 문서를 먼저 넣어 여러 일꾼이 동시에 맡게 하고, 작은 문서는 그 사이 빈 일꾼이 처리한다
    const SAMPLES = [['s2.hwp', '산업부_보도자료(표46·그림23).hwp'], ['s1.hwp', '질병청_보도참고자료(표29·그림29).hwp'], ['s3.hwp', '경기도_사업계획서(표48·병합칸510).hwp'], ['s6.hwp', '국립국어원_업무계획(표16).hwp'], ['s5.hwp', '군청_물품요구서(병합칸425).hwp'], ['s4.hwp', '과기정통부_보도자료(표12·그림5).hwp']];
    const card = $('#demoCard'); card.hidden = false;
    // 엔진을 올리는 동안 예제 파일을 미리 받아 둔다(단추를 누르면 바로 시작)
    // 엔진 파일을 받는 동안 회선을 나눠 쓰지 않도록, 예제는 엔진이 준비된 직후(또는 단추를 누를 때) 받는다
    let pre = null;
    const getPre = () => { if (!pre) { pre = SAMPLES.map(([f]) => fetch('samples/' + f).then(r => { if (!r.ok) throw new Error(f + ' ' + r.status); return r.blob(); })); pre.forEach(p => p.catch(() => {})); } return pre; };
    window.addEventListener('hwpai-engine-ready', getPre, { once: true });
    // 현장 시연 보기: 단추를 누르면 기다리지 않고 바로 화면이 넘어가며 기능을 차례로 보여 준다(새 기능이 아니라 시연 화면).
    // 보여 주는 수치·그림은 같은 예제 문서를 PC판으로 미리 돌린 실제 결과(pc/ 폴더). 그동안 이 기기에서도 실제 변환이 돌아가고, 끝나면 아래 띠에 결과를 적는다.
    let demoRun = false, story = null;
    const SL = [
      { t: 5200, h: `<div class="shero"><div class="sdocI a"><b>HWP</b><i></i><i></i><i></i></div><div class="sarrow"><span></span></div><div class="sdocI b"><b>HWPX</b><i></i><i></i><i></i><em>✔</em></div></div><p class="slead">바꾸고, <b>제대로 바뀌었는지</b>까지<br>확인합니다</p><div class="sfiles">${['산업부 보도자료', '질병청 보도참고자료', '경기도 사업계획서', '국립국어원 업무계획', '군청 물품요구서', '과기정통부 보도자료'].map((n, i) => `<div class="sfile" style="animation-delay:${(0.5 + i * 0.55).toFixed(2)}s"><span class="sx">HWP</span><span class="sy">HWPX ✔</span><i>${n}</i></div>`).join('')}</div><p class="snote">실제 정부 문서 6건 · 표 111개짜리 보도자료 · 병합 칸 510개짜리 계획서</p><p class="shint">화면을 누르면 다음으로 넘어갑니다</p>` },
      { t: 5200, h: `<div class="skick">① 원본 대조 검증</div><p class="slead">변환 엔진과 <b>다른 판독기</b>로<br>원본을 직접 읽어 맞춰 봅니다</p><div class="stiles"><div><u>📝</u><b data-n="45555">0</b><span>글자</span><em>✔ 같음</em></div><div><u>▦</u><b data-n="111">0</b><span>표</span><em>✔ 같음</em></div><div><u>🖼</u><b data-n="23">0</b><span>그림</span><em>✔ 같음</em></div></div><div class="sbar">표 칸 <b>5,746개</b> 중 다른 칸 <b>0개</b></div><div class="sstamp ok">✔ PASS <small>원본과 같음</small></div><p class="snote">산업부 보도자료 · 실제 검증 결과 · 문서마다 판정과 파일 지문을 대장(엑셀)에 기록</p>` },
      { t: 6000, h: `<div class="skick">② 차이를 찾아내는 검증서</div><p class="slead">숫자 <b>한 곳</b>만 달라도<br>통과시키지 않습니다</p><div class="sdiff"><div><span>원본</span>무역수지 17.6억 달러 흑자 (<mark class="g">15개월</mark> 연속 흑자)</div><div><span>변환본</span>무역수지 17.6억 달러 흑자 (<mark class="r">51개월</mark> 연속 흑자)</div></div><div class="sstamp">✖ FAIL <small>원본과 다름</small></div><div class="schips"><span>어디가 — 본문 8번째 문단 · 표 5</span><span>왜 그런가</span><span>어떻게 고치나 — 수정안 2곳</span></div><p class="snote">변환본의 숫자를 일부러 바꾼 뒤 검증한 PC판 실제 결과 · 글 45,555자 가운데 두 글자</p>` },
      { t: 5200, h: `<div class="skick">③ 쪽별 나란히 비교</div><p class="slead">원본과 변환본을<br><b>쪽마다 나란히</b> 놓고 봅니다</p><div class="spair"><span>원본 HWP</span><span>변환본 HWPX</span></div><div class="simgw"><img class="simg" src="pc/visual_pair.jpg" alt="산업부 보도자료 1쪽의 원본과 변환본을 나란히 놓은 화면"><i class="sscanv"></i></div><div class="sbar"><b>39쪽 → 39쪽</b> 일치</div><p class="snote">PC판 시각 비교 보고서 실물(산업부 보도자료)</p>` },
      { t: 5200, h: `<div class="skick">④ 개인정보 확인</div><p class="slead">개인정보로 보이는 곳을<br><b>색으로 표시</b>합니다</p><div class="sdoc"><small>사업 담당 · 주무관 · 전화번호</small><mark class="y">010-0000-0000</mark><i class="sscan"></i></div><div class="sgate"><span>📄 문서</span><i>→</i><b>🔒 사람이 확인</b><i>→</i><span>🤖 AI</span></div><p class="snote">사람이 확인하기 전에는 AI로 넘기지 않습니다 · 경기도 사업계획서(번호는 가상)</p>` },
      { t: 6000, h: `<div class="skick">⑤ 폴더 자동 감시</div><p class="slead">폴더를 지정해 두면 <b>30초마다</b><br>새 HWP를 자동으로 바꿉니다</p><div class="swatch"><div class="sin"><span>새 HWP</span><span>새 HWP</span><span>새 HWP</span></div><div class="sfolder"><u>📂</u><div class="sring"><b>30초</b></div><small>지정한 폴더</small></div><div class="sout"><span class="ok">HWPX ✔</span><span class="ok">HWPX ✔</span><span class="keep">🗄 원본 보관</span></div></div><div class="schips"><span>3,000건 폴더도 1초</span><span>검증 통과만 교체</span><span>작업 중 문서는 건너뜀</span></div><p class="snote">한 번 지정하면 사람 손 없이 계속 · PC판 기능</p>` },
      { t: 6000, h: `<div class="skick">⑥ AI가 바로 씁니다</div><p class="slead">AI가 어댑터를 <b>도구로 불러</b><br>HWP를 직접 읽습니다</p><div class="schat"><div class="q">7월 반도체 수출 금액과 증감률은?</div><div class="tool">search_chunks · 산업부_보도자료.hwp <i class="sdots"><b></b><b></b><b></b></i></div><div class="a">[표39] 반도체 수출액/증감률(억 달러, %)<br>(’20.7) 78.8(5.6) → (’21.7) <b>110.0(39.6)</b></div></div><div class="schips"><span>마크다운·JSON 내보내기</span><span>도구 8개</span><span>업무망 온AI 8문항 모두 정답</span></div><p class="snote">PC판 도구의 실제 응답 · 표 꺼내기 · 서식 그대로 글 바꾸기 · 양식 채우기</p>` },
      { t: 0, h: `<div class="sbig sm">설치 없이,<br>이 기기 안에서만</div><div class="sgrid"><span><u>🔄</u>자동 변환</span><span><u>📋</u>대조 검증서</span><span><u>📑</u>쪽별 비교</span><span><u>🔒</u>개인정보 확인</span><span><u>📂</u>폴더 자동 감시</span><span><u>🤖</u>AI 연결</span></div><div class="sbtns"><button class="btn primary" id="storyClose" type="button">이 휴대폰의 변환 결과 보기</button><button class="btn" id="storyAgain" type="button">처음부터 다시 보기</button></div>` }
    ];
    const NARR = [12612, 12828, 10236, 6108, 7500, 7644, 10548, 10428];   // 해설 음성 길이(ms)+여유
    let snd = null, sndOn = true;
    function say(n) {
      if (!snd) return; try { snd.pause(); } catch (e) { /* */ }
      if (!sndOn) return; try { snd.src = 'pc/n' + n + '.mp3'; snd.currentTime = 0; const p = snd.play(); if (p && p.catch) p.catch(() => {}); } catch (e) { /* */ }
    }
    function liveText() {
      const tot = S.items.length, c = counts(); const done = S.items.filter(i => i.row || /실패|격리|건너/.test(i.status || '')).length;
      if (tot && !S.running && S.runEnd) return `✔ 이 휴대폰에서도 ${c.done}건 변환·검증 완료 · ${(((S.runEnd) - S.runStart) / 1000).toFixed(1)}초 · 외부 전송 0건`;
      return `이 휴대폰에서 실제 변환 중… ${done} / ${tot || 6}`;
    }
    function openStory() {
      if (story) { story.el.remove(); clearTimeout(story.tm); clearTimeout(story.pt); clearInterval(story.iv); }
      if (!snd) { try { snd = new Audio(); snd.preload = 'auto'; } catch (e) { snd = null; } }
      const el = document.createElement('div'); el.id = 'story'; el.className = 'story'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', '기능 보기');
      el.innerHTML = `<div class="sprog">${SL.map(() => '<i><b></b></i>').join('')}</div><button class="ssnd" type="button" aria-label="해설 소리 끄기">🔊</button><button class="sclose" type="button" aria-label="닫기">✕</button><div class="sstage"></div><div class="slive"><div class="gtxt" aria-live="polite"></div><div class="gauge"><span class="gA">HWP</span><div class="grail"><div class="gfill"></div><div class="gman"><svg viewBox="-34 -8 164 76" width="123" height="57" aria-hidden="true"><defs><linearGradient id="gJ" x1="0" x2="1"><stop offset="0" stop-color="#c2410c"/><stop offset=".45" stop-color="#f97316"/><stop offset="1" stop-color="#fb923c"/></linearGradient><linearGradient id="gH" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fde047"/><stop offset="1" stop-color="#eab308"/></linearGradient></defs><g class="gcart"><ellipse cx="17" cy="62" rx="17" ry="2.4" fill="#000" opacity=".25"/><path d="M4 14 h17 l7 7 v24 a3 3 0 0 1 -3 3 h-21 a3 3 0 0 1 -3 -3 v-28 a3 3 0 0 1 3 -3z" fill="#3b82f6"/><path d="M21 14 l7 7 h-5 a2 2 0 0 1 -2 -2z" fill="#93c5fd"/><path class="gdocg" d="M4 14 h17 l7 7 v24 a3 3 0 0 1 -3 3 h-21 a3 3 0 0 1 -3 -3 v-28 a3 3 0 0 1 3 -3z" fill="#22c55e" opacity="0"/><path d="M6 25h14M6 29h16" stroke="#fff" stroke-width="1.6" opacity=".55" stroke-linecap="round"/><text x="14.5" y="42" font-size="8.6" font-weight="900" fill="#fff" text-anchor="middle" font-family="system-ui,sans-serif">HWP</text><path d="M-1 48 h33 a2 2 0 0 1 0 4.4 h-33 a2 2 0 0 1 0 -4.4z" fill="#94a3b8"/><path d="M-1 51 h33" stroke="#64748b" stroke-width="1"/><g class="gw"><circle cx="7" cy="57" r="5.2" fill="#1e293b" stroke="#e2e8f0" stroke-width="2"/><path d="M7 52.6v8.8M2.6 57h8.8" stroke="#e2e8f0" stroke-width="1.3"/><circle cx="7" cy="57" r="1.3" fill="#e2e8f0"/></g><g class="gw"><circle cx="25" cy="57" r="5.2" fill="#1e293b" stroke="#e2e8f0" stroke-width="2"/><path d="M25 52.6v8.8M20.6 57h8.8" stroke="#e2e8f0" stroke-width="1.3"/><circle cx="25" cy="57" r="1.3" fill="#e2e8f0"/></g></g><path class="grope" d="M31 31 L82 17.5" stroke="#fde68a" stroke-width="2.2" stroke-linecap="round" fill="none"/><path class="gropeS" d="M31 31 Q52 58 76 60" stroke="#fde68a" stroke-width="2.2" stroke-linecap="round" fill="none" opacity="0"/><g class="pA" transform="translate(92 37)"><g class="pp pull"><ellipse class="gshadow" cx="2" cy="27" rx="15" ry="2.6" fill="#000" opacity=".28"/><g class="pbob"><g class="thigh tB"><path d="M0 0 L0 12" stroke="#273449" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#273449" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#0f172a"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g><g class="pup" transform="rotate(24)"><g class="aB"><path d="M1 -21 L-8 -15 L-17 -15" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="-17" cy="-15" r="3.5" fill="#374151"/><path d="M-19.4 -17.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g><g class="torso"><path d="M-7.6 1 Q-9.2 -13 -6 -23.5 Q0 -27.5 6.4 -23.5 Q9.6 -13 7.8 1 Q0 3.4 -7.6 1Z" fill="url(#gJ)"/><path d="M-8.3 -9.5 Q0 -7.6 8.6 -9.5 M-8.5 -5.6 Q0 -3.7 8.5 -5.6" stroke="#fde047" stroke-width="2.3" fill="none"/><path d="M-8.4 -7.5 Q0 -5.6 8.5 -7.5" stroke="#e5e7eb" stroke-width="1" fill="none"/><path d="M-7.7 -.6 Q0 1.6 7.8 -.6" stroke="#1f2937" stroke-width="2.4" fill="none"/><rect x="-1.6" y="-1.3" width="3.2" height="2.8" rx=".6" fill="#facc15"/><path d="M-4.6 -24.4 Q0 -21 5 -24.4 L5.6 -27 Q0 -29 -5 -27Z" fill="#7c2d12"/><path d="M2 -24 L3.2 -9.6" stroke="#c2410c" stroke-width="1"/></g><g class="head"><path d="M-2.5 -27 h5.5 v3 h-5.5z" fill="#f2b990"/><circle cx="1.2" cy="-33.6" r="6.6" fill="#fcd5b5"/><path d="M-4.6 -31.4 a2 2 0 1 0 .2 -3.6" fill="#f2b990"/><path d="M6.8 -33.4 q2 .8 .6 2.2" fill="#fcd5b5"/><ellipse cx="4.6" cy="-34.6" rx=".95" ry="1.25" fill="#1f2937"/><path d="M3.2 -37.1 q1.6 -.9 3 0" stroke="#7c4a2d" stroke-width=".9" fill="none" stroke-linecap="round"/><path d="M3.6 -30.4 q1.6 1.1 3 -.1" stroke="#b45309" stroke-width=".9" fill="none" stroke-linecap="round"/><circle cx="2.6" cy="-31.8" r="1.3" fill="#fb923c" opacity=".45"/><path d="M-6.4 -35.4 a8 8 0 0 1 15.4 -2.2 l4.2 1.5 q.9 .4 .9 1.3 v1 h-20.6z" fill="url(#gH)"/><path d="M-6.4 -35.4 l-3.4 7.2 q2.6 1.2 4.6 .2 l1.2 -6z" fill="#eab308"/><path d="M1 -44.4 q1.6 -.5 2.4 1 l.2 7.6 h-3.4z" fill="#ca8a04"/><path d="M4.4 -40.6 h4.2 l.8 3.6 h-5z" fill="#dc2626"/><path d="M-6.2 -34.4 h20" stroke="#a16207" stroke-width=".9"/></g><g class="aF"><path d="M2 -21 L-6 -12 L-15.5 -11.5" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="-15.5" cy="-11.5" r="3.5" fill="#374151"/><path d="M-17.9 -14.1l4.6 1" stroke="#fde047" stroke-width="1.3"/></g></g><g class="thigh tF"><path d="M0 0 L0 12" stroke="#334155" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#334155" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#111827"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g></g></g><g class="pp cheer"><ellipse class="gshadow" cx="2" cy="27" rx="15" ry="2.6" fill="#000" opacity=".28"/><g class="pbob"><g class="thigh tB"><path d="M0 0 L0 12" stroke="#273449" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#273449" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#0f172a"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g><g class="pup" transform="rotate(0)"><g class="aB"><path d="M0 -22 L-7 -31 L-8 -41" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="-8" cy="-41" r="3.5" fill="#374151"/><path d="M-10.4 -43.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g><g class="torso"><path d="M-7.6 1 Q-9.2 -13 -6 -23.5 Q0 -27.5 6.4 -23.5 Q9.6 -13 7.8 1 Q0 3.4 -7.6 1Z" fill="url(#gJ)"/><path d="M-8.3 -9.5 Q0 -7.6 8.6 -9.5 M-8.5 -5.6 Q0 -3.7 8.5 -5.6" stroke="#fde047" stroke-width="2.3" fill="none"/><path d="M-8.4 -7.5 Q0 -5.6 8.5 -7.5" stroke="#e5e7eb" stroke-width="1" fill="none"/><path d="M-7.7 -.6 Q0 1.6 7.8 -.6" stroke="#1f2937" stroke-width="2.4" fill="none"/><rect x="-1.6" y="-1.3" width="3.2" height="2.8" rx=".6" fill="#facc15"/><path d="M-4.6 -24.4 Q0 -21 5 -24.4 L5.6 -27 Q0 -29 -5 -27Z" fill="#7c2d12"/><path d="M2 -24 L3.2 -9.6" stroke="#c2410c" stroke-width="1"/></g><g class="head"><path d="M-2.5 -27 h5.5 v3 h-5.5z" fill="#f2b990"/><circle cx="1.2" cy="-33.6" r="6.6" fill="#fcd5b5"/><path d="M-4.6 -31.4 a2 2 0 1 0 .2 -3.6" fill="#f2b990"/><path d="M6.8 -33.4 q2 .8 .6 2.2" fill="#fcd5b5"/><ellipse cx="4.6" cy="-34.6" rx=".95" ry="1.25" fill="#1f2937"/><path d="M3.2 -37.1 q1.6 -.9 3 0" stroke="#7c4a2d" stroke-width=".9" fill="none" stroke-linecap="round"/><path d="M3.6 -30.4 q1.6 1.1 3 -.1" stroke="#b45309" stroke-width=".9" fill="none" stroke-linecap="round"/><circle cx="2.6" cy="-31.8" r="1.3" fill="#fb923c" opacity=".45"/><path d="M-6.4 -35.4 a8 8 0 0 1 15.4 -2.2 l4.2 1.5 q.9 .4 .9 1.3 v1 h-20.6z" fill="url(#gH)"/><path d="M-6.4 -35.4 l-3.4 7.2 q2.6 1.2 4.6 .2 l1.2 -6z" fill="#eab308"/><path d="M1 -44.4 q1.6 -.5 2.4 1 l.2 7.6 h-3.4z" fill="#ca8a04"/><path d="M4.4 -40.6 h4.2 l.8 3.6 h-5z" fill="#dc2626"/><path d="M-6.2 -34.4 h20" stroke="#a16207" stroke-width=".9"/></g><g class="aF"><path d="M2 -22 L9 -31 L11 -41" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="11" cy="-41" r="3.5" fill="#374151"/><path d="M8.6 -43.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g></g><g class="thigh tF"><path d="M0 0 L0 12" stroke="#334155" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#334155" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#111827"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g></g></g><g class="pp wipe"><ellipse class="gshadow" cx="2" cy="27" rx="15" ry="2.6" fill="#000" opacity=".28"/><g class="pbob"><g class="thigh tB"><path d="M0 0 L0 12" stroke="#273449" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#273449" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#0f172a"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g><g class="pup" transform="rotate(4)"><g class="aB"><path d="M1 -21 L-5 -12 L-4 -3" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="-4" cy="-3" r="3.5" fill="#374151"/><path d="M-6.4 -5.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g><g class="torso"><path d="M-7.6 1 Q-9.2 -13 -6 -23.5 Q0 -27.5 6.4 -23.5 Q9.6 -13 7.8 1 Q0 3.4 -7.6 1Z" fill="url(#gJ)"/><path d="M-8.3 -9.5 Q0 -7.6 8.6 -9.5 M-8.5 -5.6 Q0 -3.7 8.5 -5.6" stroke="#fde047" stroke-width="2.3" fill="none"/><path d="M-8.4 -7.5 Q0 -5.6 8.5 -7.5" stroke="#e5e7eb" stroke-width="1" fill="none"/><path d="M-7.7 -.6 Q0 1.6 7.8 -.6" stroke="#1f2937" stroke-width="2.4" fill="none"/><rect x="-1.6" y="-1.3" width="3.2" height="2.8" rx=".6" fill="#facc15"/><path d="M-4.6 -24.4 Q0 -21 5 -24.4 L5.6 -27 Q0 -29 -5 -27Z" fill="#7c2d12"/><path d="M2 -24 L3.2 -9.6" stroke="#c2410c" stroke-width="1"/></g><g class="head"><path d="M-2.5 -27 h5.5 v3 h-5.5z" fill="#f2b990"/><circle cx="1.2" cy="-33.6" r="6.6" fill="#fcd5b5"/><path d="M-4.6 -31.4 a2 2 0 1 0 .2 -3.6" fill="#f2b990"/><path d="M6.8 -33.4 q2 .8 .6 2.2" fill="#fcd5b5"/><ellipse cx="4.6" cy="-34.6" rx=".95" ry="1.25" fill="#1f2937"/><path d="M3.2 -37.1 q1.6 -.9 3 0" stroke="#7c4a2d" stroke-width=".9" fill="none" stroke-linecap="round"/><path d="M3.6 -30.4 q1.6 1.1 3 -.1" stroke="#b45309" stroke-width=".9" fill="none" stroke-linecap="round"/><circle cx="2.6" cy="-31.8" r="1.3" fill="#fb923c" opacity=".45"/><path d="M-6.4 -35.4 a8 8 0 0 1 15.4 -2.2 l4.2 1.5 q.9 .4 .9 1.3 v1 h-20.6z" fill="url(#gH)"/><path d="M-6.4 -35.4 l-3.4 7.2 q2.6 1.2 4.6 .2 l1.2 -6z" fill="#eab308"/><path d="M1 -44.4 q1.6 -.5 2.4 1 l.2 7.6 h-3.4z" fill="#ca8a04"/><path d="M4.4 -40.6 h4.2 l.8 3.6 h-5z" fill="#dc2626"/><path d="M-6.2 -34.4 h20" stroke="#a16207" stroke-width=".9"/></g><g class="aF"><path d="M2 -21 L10 -27 L6.5 -36" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="6.5" cy="-36" r="3.5" fill="#374151"/><path d="M4.1 -38.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g></g><g class="thigh tF"><path d="M0 0 L0 12" stroke="#334155" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#334155" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#111827"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g></g></g></g><g class="pB" transform="translate(-22 37)"><g class="pp pushp"><ellipse class="gshadow" cx="2" cy="27" rx="15" ry="2.6" fill="#000" opacity=".28"/><g class="pbob"><g class="thigh tB"><path d="M0 0 L0 12" stroke="#273449" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#273449" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#0f172a"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g><g class="pup" transform="rotate(26)"><g class="aB"><path d="M1 -21 L10 -17 L18 -19" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="18" cy="-19" r="3.5" fill="#374151"/><path d="M15.6 -21.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g><g class="torso"><path d="M-7.6 1 Q-9.2 -13 -6 -23.5 Q0 -27.5 6.4 -23.5 Q9.6 -13 7.8 1 Q0 3.4 -7.6 1Z" fill="url(#gJ)"/><path d="M-8.3 -9.5 Q0 -7.6 8.6 -9.5 M-8.5 -5.6 Q0 -3.7 8.5 -5.6" stroke="#fde047" stroke-width="2.3" fill="none"/><path d="M-8.4 -7.5 Q0 -5.6 8.5 -7.5" stroke="#e5e7eb" stroke-width="1" fill="none"/><path d="M-7.7 -.6 Q0 1.6 7.8 -.6" stroke="#1f2937" stroke-width="2.4" fill="none"/><rect x="-1.6" y="-1.3" width="3.2" height="2.8" rx=".6" fill="#facc15"/><path d="M-4.6 -24.4 Q0 -21 5 -24.4 L5.6 -27 Q0 -29 -5 -27Z" fill="#7c2d12"/><path d="M2 -24 L3.2 -9.6" stroke="#c2410c" stroke-width="1"/></g><g class="head"><path d="M-2.5 -27 h5.5 v3 h-5.5z" fill="#f2b990"/><circle cx="1.2" cy="-33.6" r="6.6" fill="#fcd5b5"/><path d="M-4.6 -31.4 a2 2 0 1 0 .2 -3.6" fill="#f2b990"/><path d="M6.8 -33.4 q2 .8 .6 2.2" fill="#fcd5b5"/><ellipse cx="4.6" cy="-34.6" rx=".95" ry="1.25" fill="#1f2937"/><path d="M3.2 -37.1 q1.6 -.9 3 0" stroke="#7c4a2d" stroke-width=".9" fill="none" stroke-linecap="round"/><path d="M3.6 -30.4 q1.6 1.1 3 -.1" stroke="#b45309" stroke-width=".9" fill="none" stroke-linecap="round"/><circle cx="2.6" cy="-31.8" r="1.3" fill="#fb923c" opacity=".45"/><path d="M-6.4 -35.4 a8 8 0 0 1 15.4 -2.2 l4.2 1.5 q.9 .4 .9 1.3 v1 h-20.6z" fill="url(#gH)"/><path d="M-6.4 -35.4 l-3.4 7.2 q2.6 1.2 4.6 .2 l1.2 -6z" fill="#eab308"/><path d="M1 -44.4 q1.6 -.5 2.4 1 l.2 7.6 h-3.4z" fill="#ca8a04"/><path d="M4.4 -40.6 h4.2 l.8 3.6 h-5z" fill="#dc2626"/><path d="M-6.2 -34.4 h20" stroke="#a16207" stroke-width=".9"/></g><g class="aF"><path d="M2 -20 L11 -13 L19.5 -13" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="19.5" cy="-13" r="3.5" fill="#374151"/><path d="M17.1 -15.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g></g><g class="thigh tF"><path d="M0 0 L0 12" stroke="#334155" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#334155" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#111827"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g></g></g><g class="pp sit"><ellipse class="gshadow" cx="2" cy="27" rx="15" ry="2.6" fill="#000" opacity=".28"/><g class="pbob"><g class="thigh tB"><path d="M0 0 L0 12" stroke="#273449" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#273449" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#0f172a"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g><g class="pup" transform="rotate(-8)"><g class="aB"><path d="M1 -21 L6 -12 L13 -6" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="13" cy="-6" r="3.5" fill="#374151"/><path d="M10.6 -8.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g><g class="torso"><path d="M-7.6 1 Q-9.2 -13 -6 -23.5 Q0 -27.5 6.4 -23.5 Q9.6 -13 7.8 1 Q0 3.4 -7.6 1Z" fill="url(#gJ)"/><path d="M-8.3 -9.5 Q0 -7.6 8.6 -9.5 M-8.5 -5.6 Q0 -3.7 8.5 -5.6" stroke="#fde047" stroke-width="2.3" fill="none"/><path d="M-8.4 -7.5 Q0 -5.6 8.5 -7.5" stroke="#e5e7eb" stroke-width="1" fill="none"/><path d="M-7.7 -.6 Q0 1.6 7.8 -.6" stroke="#1f2937" stroke-width="2.4" fill="none"/><rect x="-1.6" y="-1.3" width="3.2" height="2.8" rx=".6" fill="#facc15"/><path d="M-4.6 -24.4 Q0 -21 5 -24.4 L5.6 -27 Q0 -29 -5 -27Z" fill="#7c2d12"/><path d="M2 -24 L3.2 -9.6" stroke="#c2410c" stroke-width="1"/></g><g class="head"><path d="M-2.5 -27 h5.5 v3 h-5.5z" fill="#f2b990"/><circle cx="1.2" cy="-33.6" r="6.6" fill="#fcd5b5"/><path d="M-4.6 -31.4 a2 2 0 1 0 .2 -3.6" fill="#f2b990"/><path d="M6.8 -33.4 q2 .8 .6 2.2" fill="#fcd5b5"/><ellipse cx="4.6" cy="-34.6" rx=".95" ry="1.25" fill="#1f2937"/><path d="M3.2 -37.1 q1.6 -.9 3 0" stroke="#7c4a2d" stroke-width=".9" fill="none" stroke-linecap="round"/><path d="M3.6 -30.4 q1.6 1.1 3 -.1" stroke="#b45309" stroke-width=".9" fill="none" stroke-linecap="round"/><circle cx="2.6" cy="-31.8" r="1.3" fill="#fb923c" opacity=".45"/><path d="M-6.4 -35.4 a8 8 0 0 1 15.4 -2.2 l4.2 1.5 q.9 .4 .9 1.3 v1 h-20.6z" fill="url(#gH)"/><path d="M-6.4 -35.4 l-3.4 7.2 q2.6 1.2 4.6 .2 l1.2 -6z" fill="#eab308"/><path d="M1 -44.4 q1.6 -.5 2.4 1 l.2 7.6 h-3.4z" fill="#ca8a04"/><path d="M4.4 -40.6 h4.2 l.8 3.6 h-5z" fill="#dc2626"/><path d="M-6.2 -34.4 h20" stroke="#a16207" stroke-width=".9"/></g><g class="aF"><path d="M2 -21 L8 -11 L16 -5" stroke="#ea580c" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="16" cy="-5" r="3.5" fill="#374151"/><path d="M13.6 -7.6l4.6 1" stroke="#fde047" stroke-width="1.3"/></g></g><g class="thigh tF"><path d="M0 0 L0 12" stroke="#334155" stroke-width="8.5" stroke-linecap="round" fill="none"/><g class="shin"><path d="M0 12 L0 21" stroke="#334155" stroke-width="7.5" stroke-linecap="round" fill="none"/><path d="M-2.2 15.5h4.4" stroke="#fde047" stroke-width="1.6"/><path d="M-4 19.5h7.5l6 3.2q1.4 .8 1.4 2.3v.9h-14.9z" fill="#111827"/><path d="M-4 24.6h14.9v1.5h-14.9z" fill="#facc15"/></g></g></g></g></g><text class="gfx gfxT" x="112" y="30" font-size="13" font-weight="900" fill="#fde047" font-family="system-ui,sans-serif" opacity="0">앗!</text><text class="gfx gfxR" x="104" y="2" font-size="12" opacity="0">💦</text><text class="gfx gfxF" x="60" y="60" font-size="11" opacity="0">💨</text></svg></div></div><span class="gB">HWPX</span></div></div><div class="snav"><button type="button" class="sprev" aria-label="이전"></button><button type="button" class="snext" aria-label="다음"></button></div>`;
      document.body.appendChild(el); document.body.classList.add('story-open');
      const st = story = { el, i: -1, tm: 0, iv: 0 };
      const stage = el.querySelector('.sstage'), bars = [...el.querySelectorAll('.sprog i b')];
      const close = () => { clearTimeout(st.tm); clearTimeout(st.pt); clearInterval(st.iv); try { if (snd) snd.pause(); } catch (e) { /* */ } el.remove(); document.body.classList.remove('story-open'); story = null; const lw = $('#listWrap'); if (lw && !lw.hidden) lw.scrollIntoView({ block: 'start' }); };
      const go = (n) => {
        n = Math.max(0, Math.min(SL.length - 1, n)); st.i = n; clearTimeout(st.tm); const s = SL[n]; const dur = s.t ? NARR[n] : 0;
        stage.innerHTML = `<div class="slide">${s.h}</div>`;
        const fit = () => { const sl = stage.firstChild; if (!sl || !sl.isConnected) return; sl.style.transform = 'translate(-50%,-50%)'; const k = Math.min(1, (stage.clientHeight - 6) / sl.scrollHeight, stage.clientWidth / sl.scrollWidth); sl.style.transform = `translate(-50%,-50%) scale(${k.toFixed(3)})`; };
        fit(); stage.querySelectorAll('img').forEach(m => m.addEventListener('load', fit)); setTimeout(fit, 300); setTimeout(fit, 1200);
        bars.forEach((b, k) => { b.style.transition = 'none'; b.style.width = k < n ? '100%' : '0'; });
        el.classList.toggle('last', !s.t);
        if (dur) { void bars[n].offsetWidth; bars[n].style.transition = `width ${dur}ms linear`; bars[n].style.width = '100%'; st.tm = setTimeout(() => go(n + 1), dur); } else bars[n].style.width = '100%';
        say(n);
        stage.querySelectorAll('[data-n]').forEach(e => { const N = +e.dataset.n, t0 = performance.now(); const f = (t) => { const k = Math.min(1, (t - t0) / 900); e.textContent = Math.round(N * (1 - Math.pow(1 - k, 3))).toLocaleString('ko-KR'); if (k < 1 && e.isConnected) requestAnimationFrame(f); }; requestAnimationFrame(f); });
        const c = stage.querySelector('#storyClose'); if (c) c.onclick = close;
        const a = stage.querySelector('#storyAgain'); if (a) a.onclick = () => go(0);
        tick();
      };
      let gp = 0, gLast = -1, gT = performance.now();
      const tick = () => {
        const t = liveText(); const ok = t.charAt(0) === '✔'; el.querySelector('.gtxt').textContent = t; el.querySelector('.slive').classList.toggle('ok', ok);
        const f = el.querySelector('#storyFinal'); if (f) { f.textContent = t; f.classList.toggle('ok', ok); }
        const tot = S.items.length || 6; const done = S.items.filter(i => i.row || /실패|격리|건너/.test(i.status || '')).length;
        if (done !== gLast) { gLast = done; gT = performance.now(); }
        const el0 = S.runStart ? (performance.now() - S.runStart) / 1000 : 0;   // 건수와 경과 시간 가운데 앞선 쪽을 따라 끊기지 않고 나아간다
        let tg = ok ? 1 : Math.min(0.94, Math.max((done + Math.min(0.85, (performance.now() - gT) / 5000)) / tot, el0 / 15)); gp = Math.max(gp, tg); st.gp = gp;
        el.querySelector('.gfill').style.width = (gp * 100).toFixed(1) + '%'; el.querySelector('.gman').style.left = (gp * 100).toFixed(1) + '%'; const gt = el.querySelector('.gman .gcart text'); if (gt) { gt.textContent = ok ? 'HWPX' : 'HWP'; gt.setAttribute('font-size', ok ? '7.2' : '8.6'); }
      };
      st.iv = setInterval(tick, 200);
      const POSES = [['', 4000], ['push', 4000]];   // 끌기 → 뒤에서 밀기 (넘어지기·땀 닦기는 공식 자리에 맞지 않아 뺌)
      let pk = 0; const pose = () => { if (!el.isConnected) return; const g = el.querySelector('.gman'); const done = el.querySelector('.slive').classList.contains('ok'); let ps = POSES[pk % POSES.length][0]; if ((st.gp || 0) > 0.5 && ps !== 'trip') ps = 'push';   // 절반을 넘으면 뒤에서 밀어 HWPX 까지 간다
        g.className = 'gman' + (done ? '' : (ps ? ' ' + ps : '')); st.pt = setTimeout(pose, done ? 800 : POSES[pk % POSES.length][1]); pk++; };
      pose();
      el.querySelector('.sclose').onclick = close;
      const sb = el.querySelector('.ssnd'); const paint = () => { sb.textContent = sndOn ? '🔊' : '🔇'; sb.setAttribute('aria-label', sndOn ? '해설 소리 끄기' : '해설 소리 켜기'); }; paint();
      sb.onclick = () => { sndOn = !sndOn; paint(); if (sndOn) say(st.i); else { try { snd.pause(); } catch (e) { /* */ } } };
      el.querySelector('.snext').onclick = () => { if (st.i < SL.length - 1) go(st.i + 1); };
      el.querySelector('.sprev').onclick = () => go(st.i - 1);
      go(0);
    }
    $('#btnDemo').onclick = async () => {
      const b = $('#btnDemo'); b.disabled = true; b.textContent = '예제 문서를 불러오는 중…';
      try { openStory(); } catch (e) { console.error(e); }
      try {
        const list = [];
        for (const [f, name] of SAMPLES) {
          const blob = await getPre()[list.length];
          list.push({ file: new File([blob], name, { lastModified: 1763769600000 }), path: '예제문서/' + name });
        }
        demoRun = true;
        addFiles(list, null);
        if (!readOpts().auto) kick();
        b.textContent = '▶ 기능 다시 보기'; b.disabled = false; b.onclick = openStory;
      } catch (e) { b.disabled = false; b.textContent = '▶ 예제로 체험하기'; toast('예제 문서를 불러오지 못했습니다: ' + e.message, 7000); }
    };
  })();

  if (!('WebAssembly' in window) || !window.Worker) { $('#engineText').textContent = '이 브라우저는 WebAssembly 또는 Web Worker 를 지원하지 않습니다. 최신 Chrome·Edge·Firefox·Safari 를 쓰세요.'; }
  else bootPool();
})();
