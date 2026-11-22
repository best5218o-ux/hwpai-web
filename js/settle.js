/* hwpai 웹 — 변환 뒤 「제자리 교체 + 원본 보관 + 기한 뒤 삭제」(선택 기능, 기본 꺼짐).
 * 데스크톱판 settle.py 와 같은 규칙·같은 보관대장.csv 칸. 브라우저의 File System Access API(쓰기 허용 폴더)로만 동작한다
 * (Chrome·Edge 데스크톱). 파일은 이 탭에서 사용자가 연 폴더 안에서만 읽고 쓰며, 서버로 나가지 않는다.
 *  - 변환·검증이 PASS 인 문서만, 변환 중 원본이 바뀌지 않았을 때만(SHA-256 대조) 처리한다.
 *  - 같은 이름 .hwpx 가 이미 있고 내용이 다르면 건드리지 않는다.
 *  - 원본은 지우지 않고 보관 폴더로 옮긴다(복사 → SHA-256 확인 → 원본 제거). 삭제는 purge 만 하며 미리보기 → 확인 뒤에만. */
(function () {
  'use strict';
  const enc = new TextEncoder(), dec = new TextDecoder();
  const COLS = ['원본경로', '보관위치', '원본_SHA256', 'HWPX위치', 'HWPX_SHA256', '보관일', '삭제예정일', '상태', '삭제일', '비고'];
  const LEDGER = '보관대장.csv', DELLOG = '삭제기록.csv';
  const supported = () => typeof window.showDirectoryPicker === 'function' && !!(window.crypto && crypto.subtle);

  async function sha(buf) {
    if (!(window.crypto && crypto.subtle)) throw new Error('SHA-256(crypto.subtle)을 쓸 수 없는 환경(HTTPS 또는 localhost 필요)이라 제자리 교체를 하지 않습니다');
    const h = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(h), b => b.toString(16).padStart(2, '0')).join('');
  }
  const today = () => new Date().toLocaleDateString('sv-SE');
  const addDays = (iso, n) => { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toLocaleDateString('sv-SE'); };
  const nfc = (s) => (s.normalize ? s.normalize('NFC') : s);

  // 폴더 훑기: HWP·HWPX 파일만 읽고(getFile) 핸들을 함께 돌려준다. 숨김·결과 폴더는 건너뛴다
  async function walk(dh, prefix, out) {
    for await (const [name, h] of dh.entries()) {
      if (h.kind === 'directory') { if (/^(\.|_검증서$|_격리$|_원본보관$)/.test(name)) continue; await walk(h, prefix + name + '/', out); }
      else if (/\.(hwp|hwpx)$/i.test(name)) out.push({ file: await h.getFile(), path: prefix + name, fh: h, dh });
    }
  }

  // ---- CSV (보관대장.csv — 데스크톱판과 같은 칸, UTF-8 BOM)
  const q = (v) => { v = v == null ? '' : String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const toCsv = (rows, cols) => '﻿' + [cols.join(',')].concat(rows.map(r => cols.map(c => q(r[c])).join(','))).join('\r\n') + '\r\n';
  function parseCsv(text) {
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    const rows = []; let row = [], f = '', inq = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inq) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else inq = false; } else f += c; }
      else if (c === '"') inq = true;
      else if (c === ',') { row.push(f); f = ''; }
      else if (c === '\n') { row.push(f); rows.push(row); row = []; f = ''; }
      else if (c !== '\r') f += c;
    }
    if (f !== '' || row.length) { row.push(f); rows.push(row); }
    if (!rows.length) return [];
    const head = rows[0];
    return rows.slice(1).filter(r => r.length > 1).map(r => Object.fromEntries(head.map((h, i) => [h, r[i] == null ? '' : r[i]])));
  }
  async function readFileText(dirH, name) {
    try { const f = await (await dirH.getFileHandle(name)).getFile(); return dec.decode(await f.arrayBuffer()); }
    catch (e) { if (e.name === 'NotFoundError') return null; throw e; }
  }
  async function writeData(dirH, name, data) {
    const fh = await dirH.getFileHandle(name, { create: true });
    const w = await fh.createWritable(); await w.write(data); await w.close(); return fh;
  }
  async function writeLedger(archH, rows) { await writeData(archH, LEDGER, new Blob([toCsv(rows, COLS)], { type: 'text/csv' })); }
  async function readLedger(archH) { const t = await readFileText(archH, LEDGER); return t == null ? null : parseCsv(t); }
  async function exists(dirH, name) { try { await dirH.getFileHandle(name); return true; } catch (e) { if (e.name === 'NotFoundError' || e.name === 'TypeMismatchError') return false; throw e; } }
  async function readSha(dirH, name) { const f = await (await dirH.getFileHandle(name)).getFile(); return sha(await f.arrayBuffer()); }

  async function subdir(root, parts, create) {
    let d = root;
    for (const p of parts) d = await d.getDirectoryHandle(p, { create });
    return d;
  }
  async function uniqueName(dirH, name) {
    if (!(await exists(dirH, name))) return name;
    const i = name.lastIndexOf('.'), base = i > 0 ? name.slice(0, i) : name, ext = i > 0 ? name.slice(i) : '';
    for (let n = 2; ; n++) { const c = `${base} (${n})${ext}`; if (!(await exists(dirH, c))) return c; }
  }

  const AUTO_ARC = '_원본보관';   // 폴더를 따로 고르지 않을 때 원본 폴더 안에 자동으로 만드는 보관 폴더(훑기에서는 건너뜀)
  async function autoArchive(rootH) { return rootH.getDirectoryHandle(AUTO_ARC, { create: true }); }
  async function checkOutside(rootH, archH) {
    if (await rootH.isSameEntry(archH) || (await archH.resolve(rootH))) throw new Error('보관 폴더는 원본 폴더 밖이어야 합니다(서로 포함하면 안 됨)');
    const rel = await rootH.resolve(archH);   // 원본 폴더 안에 있으면: 자동 보관 폴더(_원본보관) 바로 그 폴더만 허용
    if (rel && !(rel.length === 1 && rel[0] === AUTO_ARC)) throw new Error('보관 폴더는 원본 폴더 밖이어야 합니다(서로 포함하면 안 됨)');
  }

  /** items: it.rel(루트 기준 상대경로) · it.name · it.fh · it.dh · it.row(원본_SHA256·변환본_SHA256·판정) · it.hwpx.blob
   *  반환: [{it, ok, msg}] — ok 인 것만 제자리 교체가 끝난 것 */
  async function settle(items, rootH, archH, keepDays, onProgress) {
    await checkOutside(rootH, archH);
    const ledger = (await readLedger(archH)) || [];
    const out = []; let n = 0, sinceSave = 0;
    try {
      for (const it of items) {
        n++; if (onProgress) onProgress(n, items.length, it.rel);
        const res = { it, ok: false, msg: '' };
        out.push(res);
        try {
          const r = it.row || {};
          if (r.상태 !== '변환완료' || r.판정 !== 'PASS') { res.msg = '안 함 — 검증 PASS 가 아님'; continue; }
          if (!it.hwpx || !it.fh || !it.dh) { res.msg = '안 함 — 쓰기 허용 폴더로 연 파일이 아님'; continue; }
          if (!/\.hwp$/i.test(it.name)) { res.msg = '안 함 — .hwp 가 아님'; continue; }
          const cur = await it.fh.getFile();
          const shaO = await sha(await cur.arrayBuffer());
          if (shaO !== r.원본_SHA256) { res.msg = '안 함 — 변환 뒤 원본이 바뀜(다시 변환 필요)'; continue; }
          const cbuf = await it.hwpx.blob.arrayBuffer();
          const shaC = await sha(cbuf);
          if (shaC !== r.변환본_SHA256) { res.msg = '안 함 — 변환본 SHA-256 불일치'; continue; }
          const target = it.name.replace(/\.hwp$/i, '') + '.hwpx';
          if (await exists(it.dh, target)) {
            if ((await readSha(it.dh, target)) !== shaC) { res.msg = '안 함 — 같은 이름 .hwpx 가 이미 있고 내용이 다름(건드리지 않음)'; continue; }
          } else {
            await writeData(it.dh, target, new Blob([cbuf]));
            if ((await readSha(it.dh, target)) !== shaC) { try { await it.dh.removeEntry(target); } catch (e) { /* */ } res.msg = '안 함 — 쓴 .hwpx 확인 실패'; continue; }
          }
          const parts = it.rel.split('/'); const fname = parts.pop();
          const ad = await subdir(archH, parts, true);
          const aname = await uniqueName(ad, fname);
          await writeData(ad, aname, new Blob([await cur.arrayBuffer()]));
          if ((await readSha(ad, aname)) !== shaO) { try { await ad.removeEntry(aname); } catch (e) { /* */ } res.msg = 'HWPX 두기만 함 — 원본 보관 복사 확인 실패(원본 그대로)'; continue; }
          try { await it.dh.removeEntry(it.name); }
          catch (e) { try { await ad.removeEntry(aname); } catch (e2) { /* */ } res.msg = 'HWPX 두기만 함 — 원본을 옮기지 못함(열려 있음?): ' + e.name; continue; }
          const t = today();
          const relH = parts.concat([aname]).join('/');
          ledger.push({ 원본경로: rootH.name + '/' + it.rel, 보관위치: relH, 원본_SHA256: shaO,
            HWPX위치: rootH.name + '/' + parts.concat([target]).join('/'), HWPX_SHA256: shaC, 보관일: t,
            삭제예정일: keepDays ? addDays(t, keepDays) : '', 상태: '보관중', 삭제일: '', 비고: '웹판' });
          res.ok = true; res.msg = '완료' + (keepDays ? ` (삭제 예정 ${addDays(t, keepDays)})` : ' (삭제 안 함)');
          if (++sinceSave >= 20) { await writeLedger(archH, ledger); sinceSave = 0; }
        } catch (e) { res.msg = '안 함 — ' + (e.name || 'Error') + ': ' + String(e.message || e).slice(0, 120); }
      }
    } finally { if (sinceSave || ledger.length) await writeLedger(archH, ledger); }
    return out;
  }

  /** 기한 지난 보관 원본 정리. 미리보기(dry) → 사용자가 확인하면 dry=false 로 다시 */
  async function purge(archH, rootH, dry) {
    const rows = await readLedger(archH);
    if (rows == null) throw new Error('그 폴더에 보관대장.csv 가 없습니다');
    const t = today(); const res = { 대상: 0, 삭제: 0, 보류: 0, 아직: 0, 내역: [] }; const dels = [];
    for (const r of rows) {
      if (r.상태 !== '보관중' && r.상태 !== '삭제보류') continue;
      if (!r.삭제예정일) continue;
      if (r.삭제예정일 > t) { res.아직++; continue; }
      res.대상++;
      let why = '';
      const aparts = r.보관위치.split('/'); const aname = aparts.pop();
      const hparts = String(r.HWPX위치).replace(/\\/g, '/').split('/');
      const isWeb = r.비고 === '웹판' && hparts[0] === rootH.name;
      try {
        let ad = null; try { ad = await subdir(archH, aparts, false); } catch (e) { /* */ }
        if (!ad || !(await exists(ad, aname))) why = '보관된 원본이 없음';
        else if (!isWeb) why = '다른 판(데스크톱 등)에서 만든 기록 — 그 판에서 정리하세요';
        else {
          const hname = hparts.pop(); let hd = null; try { hd = await subdir(rootH, hparts.slice(1), false); } catch (e) { /* */ }
          if (!hd || !(await exists(hd, hname))) why = '제자리 HWPX 가 없음 — 지우면 문서가 사라짐';
          else if ((await readSha(hd, hname)) !== r.HWPX_SHA256) why = '제자리 HWPX 가 변환 당시와 다름(수정됨) — 사람 확인';
          else if ((await readSha(ad, aname)) !== r.원본_SHA256) why = '보관된 원본이 기록과 다름';
          else dels.push({ r, ad, aname });
        }
      } catch (e) { why = '확인 실패: ' + (e.name || 'Error'); }
      if (why) { res.보류++; res.내역.push([r.보관위치, '보류', why]); if (!dry) { r.상태 = '삭제보류'; r.비고 = why; } }
      else res.내역.push([r.보관위치, dry ? '삭제 예정' : '삭제', '']);
    }
    if (dry) { res.삭제 = dels.length; return res; }
    const logRows = [];
    for (const d of dels) {
      try { await d.ad.removeEntry(d.aname); d.r.상태 = '삭제됨'; d.r.삭제일 = t; d.r.비고 = '웹판'; res.삭제++; logRows.push({ 삭제일: t, 보관위치: d.r.보관위치, 원본경로: d.r.원본경로, 원본_SHA256: d.r.원본_SHA256, HWPX위치: d.r.HWPX위치 }); }
      catch (e) { res.보류++; d.r.상태 = '삭제보류'; d.r.비고 = '삭제 실패 ' + (e.name || 'Error'); }
    }
    await writeLedger(archH, rows);
    if (logRows.length) {
      const dcols = ['삭제일', '보관위치', '원본경로', '원본_SHA256', 'HWPX위치'];
      const old = parseCsv((await readFileText(archH, DELLOG)) || '');
      await writeData(archH, DELLOG, new Blob([toCsv(old.concat(logRows), dcols)], { type: 'text/csv' }));
    }
    return res;
  }

  window.HwpaiSettle = { supported, walk, settle, purge, checkOutside, autoArchive, AUTO_ARC, parseCsv, toCsv, sha };
})();
