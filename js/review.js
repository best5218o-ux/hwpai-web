/* hwpai 웹 — 민감정보 확인 화면. 데스크톱판 sens_view.py 의 화면 코드를 같은 동작으로 옮긴 것이다
 * (검출 구간 종류별 색 네모·밑줄, 항목별 「민감정보임/아님」, 일괄 선택, 키보드). 네트워크를 쓰지 않는다. */
(function () {
  'use strict';
  const KIND_COLOR = {
    '주민등록번호': '#d32f2f', '외국인등록번호': '#d32f2f', '휴대전화': '#ef6c00', '일반전화': '#ef6c00', '인터넷전화': '#ef6c00',
    '이메일': '#1565c0', '계좌번호 꼴': '#7b1fa2', '여권번호 꼴': '#7b1fa2', '성명': '#2e7d32', '생년월일': '#2e7d32',
  };
  const colorOf = (k) => KIND_COLOR[k] || (String(k).startsWith('문서속성') ? '#00838f' : '#888');
  const STATES = ['없음', '확인 필요', '확인 완료(민감정보 아님)', '확인 완료(민감정보 있음)'];
  const PROBABLY_OK = '추정 비민감';
  const MAX_FULL = 200000;
  const itemKey = (it) => it.kind + ':' + it.start + ':' + (it.end - it.start);

  /** sens.status_of 의 옮김 — items: 검출 목록, rec: 저장된 기록(없으면 null) */
  function statusOf(items, rec) {
    if (!items || !items.length) return { state: STATES[0], pending: 0, total: 0, sensitive: 0, probably_ok: 0, kinds: {} };
    const dec = {}; ((rec && rec.items) || []).forEach(r => { dec[r.key] = r.decision; });
    let pend = 0, sens = 0, okAuto = 0; const kinds = {};
    for (const it of items) {
      const d = dec[itemKey(it)];
      if (d === 'sensitive') sens++;
      else if (d === 'not_sensitive') { /* */ }
      else if (it.auto === PROBABLY_OK) okAuto++;
      else { pend++; kinds[it.kind] = (kinds[it.kind] || 0) + 1; }
    }
    let state;
    if (pend) state = STATES[1];
    else if (sens) state = STATES[3];
    else if (rec != null || okAuto === items.length) state = rec != null ? STATES[2] : STATES[0];
    else state = STATES[0];
    return { state, pending: pend, total: items.length, sensitive: sens, probably_ok: okAuto, kinds, policy: rec ? rec.policy : undefined };
  }

  /** sens.Store.save 의 옮김 — 값은 저장하지 않는다(종류·자리·길이·결정) */
  function makeRecord(sha, items, decisions, policy, reviewer, name) {
    return {
      sha256: sha, name_hint: String(name || '').split('/').pop(), reviewer: reviewer || 'web', time: new Date().toISOString(),
      policy: policy || 'block',
      items: items.map(it => ({ key: itemKey(it), kind: it.kind, len: it.end - it.start, auto: it.auto, decision: decisions[itemKey(it)] || null })),
      tool: 'hwpai sens 1 (web)',
    };
  }

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let P = null, di = 0, ci = 0, handlers = null, wired = false, prevFocus = null;

  function prepare(docs) {
    return docs.map(d => {
      const items = d.items.map(it => Object.assign({}, it, { key: itemKey(it) }));
      let pieces = null;
      if ((d.text || '').length > MAX_FULL) {
        const segs = items.map(it => [Math.max(0, it.start - 300), Math.min(d.text.length, it.end + 300)]).sort((a, b) => a[0] - b[0]);
        const merged = [];
        for (const [a, b] of segs) { if (merged.length && a <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], b); else merged.push([a, b]); }
        pieces = merged.map(([a, b]) => [a, b, d.text.slice(a, b)]);
      }
      return { id: d.id, name: d.name, sha256: d.sha256, text: pieces ? '' : d.text, pieces, items, dec: Object.assign({}, d.decisions || {}), policy: d.policy || 'block', len: (d.text || '').length };
    });
  }
  const dec = (d, it) => d.dec[it.key] || (it.auto === PROBABLY_OK ? 'not_sensitive_auto' : null);
  function state(d) { let pend = 0, sens = 0; d.items.forEach(it => { const v = dec(d, it); if (v === 'sensitive') sens++; else if (!v) pend++; }); return pend ? 1 : (sens ? 3 : (d.items.length ? 2 : 0)); }
  const SN = ['없음', '확인 필요', '확인 완료(아님)', '확인 완료(민감정보 있음)'];
  function visible(d) { const kf = $('#rv-kindf').value, op = $('#rv-onlyPend').checked; return d.items.map((it, i) => [it, i]).filter(([it]) => (!kf || it.kind === kf) && (!op || !dec(d, it))); }

  function drawDocs() {
    $('#rv-docs').innerHTML = P.docs.map((d, i) => {
      const s = state(d); const pend = d.items.filter(it => !dec(d, it)).length;
      return `<div class="rdoc ${i === di ? 'sel' : ''}" data-i="${i}" tabindex="0" role="button"><span class="rb rb${s}">${SN[s]}</span> ${esc(d.name)}<small>검출 ${d.items.length}건 · 미확인 ${pend}건</small></div>`;
    }).join('') || '<div class="empty">확인할 문서가 없습니다</div>';
    document.querySelectorAll('.rdoc').forEach(e => { e.onclick = () => { di = +e.dataset.i; ci = 0; draw(); }; e.onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); e.click(); } }; });
  }
  function drawText() {
    const d = P.docs[di]; if (!d) { $('#rv-text').innerHTML = ''; return; }
    const out = []; const vis = new Set(visible(d).map(([it]) => it.key));
    const pieces = d.pieces || [[0, d.text.length, d.text]];
    pieces.forEach(([a, b, t], pi) => {
      if (d.pieces && pi === 0 && a > 0) out.push('<span class="hint">… </span>');
      let pos = a;
      d.items.filter(it => it.start >= a && it.end <= b).sort((x, y) => x.start - y.start).forEach(it => {
        if (it.start < pos) return;
        out.push(esc(t.slice(pos - a, it.start - a)));
        const v = dec(d, it); const col = colorOf(it.kind);
        const cls = ['mk', it.auto === PROBABLY_OK ? 'ok' : '', v === 'sensitive' ? 'dsens' : (v ? 'dno' : ''), (d.items[ci] && d.items[ci].key === it.key) ? 'cur' : ''].join(' ');
        out.push(`<mark class="${cls}" data-k="${esc(it.key)}" style="border-bottom:3px ${it.auto === PROBABLY_OK ? 'dashed' : 'solid'} ${col};${vis.has(it.key) ? '' : 'opacity:.35'}" title="${esc(it.kind)} — ${esc(it.reason)}">${esc(t.slice(it.start - a, it.end - a))}</mark>`);
        pos = it.end;
      });
      out.push(esc(t.slice(pos - a)));
      if (d.pieces) out.push('<span class="hint"> …\n</span>');
    });
    $('#rv-text').innerHTML = out.join('');
    document.querySelectorAll('mark.mk').forEach(m => { m.onclick = () => { const i = d.items.findIndex(x => x.key === m.dataset.k); ci = i; draw(); }; });
  }
  function drawItems() {
    const d = P.docs[di]; if (!d) { $('#rv-items').innerHTML = ''; return; }
    const v = visible(d);
    if (!v.length) { $('#rv-items').innerHTML = '<div class="empty">보이는 항목이 없습니다</div>'; return; }
    $('#rv-items').innerHTML = v.map(([it, i]) => {
      const val = dec(d, it); const col = colorOf(it.kind);
      return `<div class="ritem ${i === ci ? 'cur' : ''}" data-i="${i}" tabindex="0"><span class="k" style="background:${col}">${esc(it.kind)}</span> <span class="val">${esc(it.text)}</span>
  <div class="ctx">…${esc(it.before)}<b>${esc(it.text)}</b>${esc(it.after)}…</div><div class="hint">${esc(it.reason)}</div>
  <div class="rrow"><label><input type="radio" name="r${i}" value="sensitive" ${val === 'sensitive' ? 'checked' : ''}> 민감정보임</label><label><input type="radio" name="r${i}" value="not_sensitive" ${(val === 'not_sensitive' || val === 'not_sensitive_auto') ? 'checked' : ''}> 민감정보 아님(업무 연락처 등)</label></div></div>`;
    }).join('');
    document.querySelectorAll('.ritem').forEach(e => {
      e.onclick = ev => { ci = +e.dataset.i; if (ev.target.tagName !== 'INPUT') { drawText(); markCur(); } };
      e.querySelectorAll('input').forEach(r => r.onchange = () => { set(+e.dataset.i, r.value); });
    });
    const c = document.querySelector('.ritem.cur'); if (c) c.scrollIntoView({ block: 'nearest' });
  }
  function markCur() { document.querySelectorAll('.ritem').forEach(e => e.classList.toggle('cur', +e.dataset.i === ci)); const cm = document.querySelector('mark.cur'); if (cm) cm.scrollIntoView({ block: 'nearest' }); }
  function set(i, v) { const d = P.docs[di]; d.dec[d.items[i].key] = v; draw(); }
  function draw() { drawDocs(); drawText(); drawItems(); const cm = document.querySelector('mark.cur'); if (cm) cm.scrollIntoView({ block: 'nearest' }); if (P.docs[di]) $('#rv-policy').value = P.docs[di].policy || 'block'; }
  function move(n) { const d = P.docs[di]; if (!d) return; const v = visible(d).map(([, i]) => i); if (!v.length) return; let p = v.indexOf(ci); p = p < 0 ? 0 : Math.min(v.length - 1, Math.max(0, p + n)); ci = v[p]; draw(); }
  function bulk(v) { const d = P.docs[di]; if (!d) return; visible(d).forEach(([it]) => { d.dec[it.key] = v; }); draw(); }
  function outDocs() {
    return P.docs.map(d => ({ id: d.id, sha256: d.sha256, name: d.name, policy: d.policy || 'block', items: d.items,
      decisions: Object.fromEntries(Object.entries(d.dec).filter(([, v]) => v === 'sensitive' || v === 'not_sensitive')) }));
  }
  function save() {
    handlers.onSave(outDocs(), $('#rv-who').value || '');
    $('#rv-msg').textContent = '저장했습니다 — 이 브라우저 안에서만 쓰입니다(값은 저장하지 않음).';
    draw();
  }
  function exportFile() {
    const out = { reviewer: $('#rv-who').value || '', saved: new Date().toISOString(),
      docs: outDocs().map(d => ({ sha256: d.sha256, name: d.name, policy: d.policy, decisions: d.decisions })) };
    handlers.onExportFile(out);
  }
  async function importFile(file) {
    try {
      const data = JSON.parse(await file.text()); let n = 0;
      for (const x of (data.docs || [])) {
        const d = P.docs.find(q => q.sha256 === x.sha256);
        if (d) { Object.assign(d.dec, x.decisions || {}); if (x.policy) d.policy = x.policy; n++; }
      }
      $('#rv-msg').textContent = `결정 파일에서 ${n}개 문서의 결정을 가져왔습니다 — 확인 후 「저장」을 누르세요.`;
      draw();
    } catch (e) { $('#rv-msg').textContent = '결정 파일을 읽지 못했습니다: ' + e.message; }
  }
  function onKey(e) {
    if ($('#review').hidden) return;
    if (e.key === 'Escape') { close(); return; }
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) && e.target.type !== 'radio' && e.target.type !== 'checkbox') return;
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'j') move(1); else if (e.key === 'k') move(-1);
    else if (e.key === 's') { if (P.docs[di] && P.docs[di].items[ci]) set(ci, 'sensitive'); }
    else if (e.key === 'n') { if (P.docs[di] && P.docs[di].items[ci]) set(ci, 'not_sensitive'); }
    else if (e.key === ']') { di = Math.min(P.docs.length - 1, di + 1); ci = 0; draw(); }
    else if (e.key === '[') { di = Math.max(0, di - 1); ci = 0; draw(); }
  }
  function wire() {
    if (wired) return; wired = true;
    $('#rv-bulkNo').onclick = () => bulk('not_sensitive'); $('#rv-bulkYes').onclick = () => bulk('sensitive');
    $('#rv-onlyPend').onchange = $('#rv-kindf').onchange = draw;
    $('#rv-policy').onchange = () => { if (P.docs[di]) P.docs[di].policy = $('#rv-policy').value; };
    $('#rv-save').onclick = save; $('#rv-export').onclick = exportFile;
    $('#rv-import').onclick = () => $('#rv-importFile').click();
    $('#rv-importFile').onchange = (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ''; };
    $('#rv-close').onclick = close;
    document.addEventListener('keydown', onKey);
  }
  function open(opts) {
    P = { docs: prepare(opts.docs) }; handlers = opts; di = Math.max(0, opts.startIndex || 0); ci = 0;
    wire();
    prevFocus = document.activeElement;
    $('#rv-who').value = opts.reviewer || '';
    const kinds = [...new Set(P.docs.flatMap(d => d.items.map(i => i.kind)))];
    $('#rv-kindf').innerHTML = '<option value="">종류 전체</option>' + kinds.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('');
    $('#rv-legend').innerHTML = kinds.map(k => `<span><i class="sw" style="background:${colorOf(k)}"></i>${esc(k)}</span>`).join('');
    $('#rv-msg').textContent = '';
    $('#review').hidden = false; document.body.style.overflow = 'hidden';
    draw(); $('#rv-save').focus();
  }
  function close() {
    if (!P) return;
    $('#review').hidden = true; document.body.style.overflow = '';
    if (handlers && handlers.onClose) handlers.onClose();
    if (prevFocus && prevFocus.focus) try { prevFocus.focus(); } catch (e) { /* */ }
  }
  window.HwpaiReview = { open, close, statusOf, makeRecord, itemKey, colorOf, STATES, PROBABLY_OK };
})();
