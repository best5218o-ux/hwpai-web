/* hwpai 웹 — 화면. 파일은 이 탭 밖으로 보내지 않는다(서버·CDN·AI 호출 없음). */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const R = window.HwpaiReview, E = window.HwpaiEngine, Z = window.HwpaiZip;
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
    const saved = LS.get('hwpai.opts.v1', {});
    const cores = navigator.hardwareConcurrency || 2;
    $('#optJobs').value = String(saved.jobs || Math.min(2, Math.max(1, cores - 1)));
    $('#optTimeout').value = saved.timeout || 120;
    $('#optPolicy').value = saved.policy || 'review';
    $('#optHwpx').checked = !!saved.include_hwpx;
    $('#optAuto').checked = saved.auto !== false;
    const persist = () => { const o = readOpts(); delete o.password; LS.set('hwpai.opts.v1', o); S.cfg.policy = o.policy; };
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
      txt.textContent = '엔진 준비됨';
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
  const isHwp = (n) => /\.(hwp|hwpx)$/i.test(n);
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
    for (const x of list) { const path = nfc(x.path.replace(/\\/g, '/')); if (!isHwp(path)) { skippedNon++; continue; } cand.push({ file: x.file, path }); }
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
      have.add(key); fresh.push({ rel, file: c.file });
    }
    const order = walkOrder(fresh.map(f => f.rel)); const byRel = new Map(fresh.map(f => [f.rel, f]));
    for (const rel of order) {
      const f = byRel.get(rel);
      S.items.push({ id: S.nextId++, rel, name: rel.split('/').pop(), size: f.file.size, mtime: f.file.lastModified, file: f.file, status: '대기', row: null, sens: null, hwpx: null, md: null, json: null, dst: '' });
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
      [/빈 파일|\(empty\)/, '빈 파일입니다.'], [/\(unknown\)/, 'HWP 문서가 아닙니다(확장자만 .hwp 인 다른 형식이거나 내용이 깨졌습니다).'],
      [/\(ole-broken\)/, '파일 구조(OLE)가 손상되어 읽을 수 없습니다.'], [/\(ole-not-hwp\)/, 'OLE 문서이지만 HWP 가 아닙니다(다른 오피스 파일).'],
      [/\(zip-broken\)/, 'HWPX(ZIP) 파일이 손상되었습니다.'], [/\(zip-not-hwpx\)/, 'ZIP 이지만 HWPX 가 아닙니다.'],
      [/DRM/, 'DRM 문서입니다 — 기관 DRM 을 해제한 뒤 다시 올리세요(변환하지 않음).'],
      [/열기 암호/, '열기 암호가 걸린 문서입니다 — 「처리 옵션」에 암호를 넣고 「실패·격리 다시 시도」를 누르세요.'],
      [/시간초과|시간 한도/, '시간 한도를 넘었습니다 — 「처리 옵션」에서 한도를 늘려 다시 시도하세요(아주 큰 문서일 수 있음).'],
      [/엔진중단|엔진 일꾼|crash/, '변환 엔진이 중단되었습니다(문서가 특이한 구조일 수 있음). 이 파일만 실패로 두고 엔진을 새로 띄웠습니다.'],
      [/엔진오류/, '변환 엔진이 이 문서를 읽지 못했습니다.'], [/처리 오류/, '처리 중 예상 못 한 오류가 났습니다.'],
      [/이미 HWPX/, '이미 HWPX 입니다 — 다시 저장해 검증하려면 「처리 옵션」에서 체크하세요.'],
      [/등급|차단/, '민감정보 정책에 따라 변환하지 않았습니다(처리 옵션의 정책을 「확인 요청」으로 두면 변환합니다).'],
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
    for (const it of todo) processItem(it);
    updateProgress(); renderAll();
  }
  function runFinished() {
    S.running = 0; S.runEnd = performance.now(); updateProgress(); renderAll();
    const s = counts(); toast(`처리 끝 — ${s.done}개 변환${s.fail ? ` · 실패·격리 ${s.fail}개` : ''}${s.wait ? ` · 민감정보 확인 대기 ${s.wait}개` : ''}`, 6000);
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
      row.민감정보_항목 = kinds + (st.probably_ok ? ` (추정 비민감 ${st.probably_ok}건)` : '');
      if (!st.total) { row.민감정보 = st.state; row.민감정보_항목 = ''; }
    }
  }
  function sensTag(it) {
    const st = sensStatus(it); if (!st) return it.sens && it.sens.state == null && it.row && it.row.상태 === '변환완료' ? '<span class="tag t-gray" title="판독하지 못해 민감정보를 확인할 수 없음">확인 불가</span>' : '';
    if (!st.total) return '<span class="tag t-ok">없음</span>';
    if (st.state === R.STATES[1]) return `<button class="tag t-wait sm-open" data-open="${it.id}" type="button" title="눌러서 확인 화면 열기">확인 필요 ${st.pending}건</button>`;
    if (st.state === R.STATES[2]) return `<button class="tag t-ok sm-open" data-open="${it.id}" type="button">확인 완료(아님)</button>`;
    return `<button class="tag t-warn sm-open" data-open="${it.id}" type="button">확인 완료(있음 ${st.sensitive})</button>`;
  }
  function verdictTag(it) {
    const r = it.row; if (!r) return '';
    if (r.판정 === 'PASS') return `<span class="tag t-pass">✔ PASS</span> <small>${r.검증점수 === '' ? '' : r.검증점수}</small>`;
    if (r.판정 === 'WARN') return `<span class="tag t-warn">▲ WARN</span> <small>${r.검증점수 === '' ? '' : r.검증점수}</small>`;
    if (r.판정 === 'FAIL') return `<span class="tag t-fail">✖ FAIL</span> <small>${r.검증점수 === '' || r.검증점수 == null ? '' : r.검증점수}</small>`;
    return '';
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
      case 'bad': return it.status === '변환실패' || it.status === '격리' || it.status === '등급차단';
      case 'wait': return !!(st && st.state === R.STATES[1]);
      case 'skip': return it.status === '건너뜀';
    }
    return true;
  }
  function renderSummary() {
    const c = counts();
    const mk = (cls, f, n, label) => `<button type="button" class="stat ${cls} ${S.filter === f ? 'on' : ''}" data-f="${f}"><b>${n}</b><span>${label}</span></button>`;
    $('#summary').innerHTML = S.items.length ? [mk('', 'all', c.total, '전체'), mk('pass', 'PASS', c.pass, 'PASS'), mk('warn', 'WARN', c.warn, 'WARN(사람이 볼 것)'), mk('fail', 'FAIL', c.fail, 'FAIL(내용 손실)'),
      mk('fail', 'bad', c.fail2, '실패·격리'), mk('wait', 'wait', c.wait, '민감정보 확인 대기')].join('') : '';
    $$('#summary .stat').forEach(b => b.onclick = () => { S.filter = b.dataset.f; renderAll(); });
  }
  function renderRows() {
    const tb = $('#rows'); const vis = S.items.filter(passFilter);
    const html = vis.map(it => {
      const r = it.row || {}; const why = friendlyReason(it);
      let reason = r.판정_이유 ? `<span title="${esc(r.판정_이유)}">${esc(String(r.판정_이유).slice(0, 160))}</span>` : '';
      if (why) reason = `<b>${esc(why)}</b><br><small class="mut">${esc(String(r.판정_이유 || '').slice(0, 160))}</small>`;
      if (it.status === '변환완료' && !r.판정_이유 && r.판정 === 'PASS') reason = '<span class="mut">원본과 변환본의 글·표·그림이 일치</span>';
      const acts = [];
      if (it.hwpx) acts.push(`<button class="btn sm" data-act="dl" data-id="${it.id}" type="button">HWPX</button>`);
      if (it.md) acts.push(`<button class="btn sm" data-act="detail" data-id="${it.id}" type="button">검증서</button>`);
      if (it.status === '변환완료' || it.row && it.row.원본_형식) acts.push(`<button class="btn sm" data-act="exp" data-id="${it.id}" type="button">MD·JSON</button>`);
      return `<tr data-id="${it.id}"><td class="c-sel"><input type="checkbox" data-sel="${it.id}" ${S.selected.has(it.id) ? 'checked' : ''} aria-label="선택"></td>
<td class="name" data-l="파일">${esc(it.rel)}${r.특성 ? `<small>${esc(r.원본_형식 || '')} ${esc(r.특성)}</small>` : ''}</td>
<td class="c-size" data-l="크기">${fmtSize(it.size)}</td><td data-l="변환">${statusTag(it)}</td><td data-l="판정">${verdictTag(it)}</td>
<td data-l="민감정보">${sensTag(it)}</td><td class="reason" data-l="설명">${reason}</td><td class="c-act" data-l="동작">${acts.join(' ')}</td></tr>`;
    }).join('');
    tb.innerHTML = html;
    $('#selAll').checked = vis.length > 0 && vis.every(i => S.selected.has(i.id));
  }
  function renderAll() {
    const has = S.items.length > 0;
    $('#toolbar').hidden = !has; $('#listWrap').hidden = !has; $('#emptyHint').hidden = has;
    renderSummary(); renderRows();
    const c = counts();
    const doneAny = S.items.some(i => i.hwpx);
    $('#btnZip').disabled = !doneAny || !!S.running; $('#btnZipSel').disabled = !S.selected.size || !!S.running;
    $('#btnExport').disabled = !S.items.some(i => i.row && i.row.원본_형식 && i.status !== '대기') || !S.ready;
    $('#btnReview').disabled = !S.items.some(i => i.sens && i.sens.items && i.sens.items.length);
    $('#btnReview').textContent = c.wait ? `확인 대기 열기 (${c.wait})` : '민감정보 검출 보기';
    $('#btnStart').hidden = !pending().length || !!S.running; $('#btnStart').disabled = !S.ready;
    $('#btnCancel').hidden = !S.running;
    $('#btnRetry').hidden = !S.items.some(i => i.status === '변환실패' || i.status === '격리') || !!S.running;
    const chips = [['all', '전체'], ['PASS', 'PASS'], ['WARN', 'WARN'], ['FAIL', 'FAIL'], ['bad', '실패·격리'], ['wait', '확인 대기'], ['skip', '건너뜀']];
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
<p class="btns" style="justify-content:flex-start"><button class="btn primary" id="xGo" type="button">내보내기 zip 받기</button></p>`;
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
  function showDetail(it) {
    const r = it.row || {}; const dlg = $('#detail');
    $('#detailTitle').textContent = '검증서 — ' + it.rel;
    const kv = [['원본 형식', r.원본_형식], ['원본 크기', fmtSize(r.원본_크기)], ['특성', r.특성], ['원본 SHA-256', r.원본_SHA256], ['변환본 크기', fmtSize(r.변환본_크기)], ['변환본 SHA-256', r.변환본_SHA256],
      ['엔진', r.엔진 ? `${r.엔진} ${r.엔진_판}` : ''], ['변환 소요', r.변환_소요ms ? r.변환_소요ms + ' ms' : ''], ['검증 점수·판정', r.판정 ? `${r.검증점수} · ${r.판정}` : ''], ['민감정보', r.민감정보 ? `${r.민감정보} ${r.민감정보_항목 || ''}` : '']].filter(x => x[1]);
    $('#detailBody').innerHTML = `<dl class="kv">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
<p class="btns" style="justify-content:flex-start"><button class="btn sm" id="dMd" type="button">검증서(.md) 받기</button> <button class="btn sm" id="dJson" type="button">검증서(.json) 받기</button></p>
<div>${mdToHtml(it.md || '')}</div>`;
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
    $('#netText').textContent = bad ? `외부 요청 ${bad}건 차단됨` : '네트워크 요청 0건';
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

  // ---------------------------------------------------------------- 이벤트
  function wire() {
    const drop = $('#drop');
    ['dragenter', 'dragover'].forEach(ev => document.addEventListener(ev, (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) { e.preventDefault(); drop.classList.add('over'); } }));
    document.addEventListener('dragleave', (e) => { if (!e.relatedTarget) drop.classList.remove('over'); });
    document.addEventListener('drop', async (e) => {
      if (!e.dataTransfer) return; e.preventDefault(); drop.classList.remove('over');
      const c = await collectFromDrop(e.dataTransfer);   // 동기 구간에서 entry 를 먼저 얻는다
      try { const r = await resolveDropped(c); addFiles(r.list, r); } catch (err) { toast('끌어놓은 항목을 읽지 못했습니다: ' + err.message, 7000); console.error(err); }
    });
    $('#pickFiles').onclick = () => $('#fileInput').click();
    $('#pickDir').onclick = () => $('#dirInput').click();
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#fileInput').click(); } });
    $('#fileInput').onchange = (e) => { addFiles(Array.from(e.target.files).map(f => ({ file: f, path: f.name })), null); e.target.value = ''; };
    $('#dirInput').onchange = (e) => { addFiles(Array.from(e.target.files).map(f => ({ file: f, path: f.webkitRelativePath || f.name })), null); e.target.value = ''; };
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
      else if (b.dataset.act === 'exp') askExport([it]);
    });
    $('#detailClose').onclick = () => $('#detail').close(); $('#netClose').onclick = () => $('#netDlg').close();
    $('#netBadge').onclick = showNet;
    window.addEventListener('beforeunload', (e) => { if (S.running) { e.preventDefault(); e.returnValue = ''; } });
  }

  initOpts(); wire(); renderAll();
  if (!('WebAssembly' in window) || !window.Worker) { $('#engineText').textContent = '이 브라우저는 WebAssembly 또는 Web Worker 를 지원하지 않습니다. 최신 Chrome·Edge·Firefox·Safari 를 쓰세요.'; }
  else bootPool();
})();
