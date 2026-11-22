// hwpai — rhwp(@rhwp/core, MIT, Edward Kim) WASM 변환 일꾼.
// 표준입력으로 한 줄에 JSON 요청 하나 {"id","src","dst","password"} 를 받아
// rhwp 의 exportHwpxWithReport() 로 HWPX 를 쓰고, 한 줄 JSON 응답을 돌려준다.
// 변환 엔진은 rhwp 의 것이고, 이 파일은 프로세스 연결(일괄 처리용 상주 일꾼)만 맡는다.
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';

const coreDir = process.argv[2];
if (!coreDir) { process.stderr.write('usage: rhwp_worker.mjs <@rhwp/core 폴더>\n'); process.exit(2); }
const mod = await import(pathToFileURL(path.join(coreDir, 'rhwp.js')).href);
// 조판용 글자폭 콜백 — 변환(직렬화)에는 쓰이지 않지만, 로드 중 조판이 부를 수 있어 근사값을 준다.
globalThis.measureTextWidth = (font, text) => {
  const m = /(\d+(?:\.\d+)?)px/.exec(font || ''); const sz = m ? parseFloat(m[1]) : 12;
  let w = 0; for (const ch of text || '') w += (ch.codePointAt(0) > 0x2e80 ? 1.0 : 0.55) * sz; return w;
};
mod.initSync({ module: fs.readFileSync(path.join(coreDir, 'rhwp_bg.wasm')) });
const version = (() => { try { return mod.version ? mod.version() : JSON.parse(fs.readFileSync(path.join(coreDir, 'package.json'))).version; } catch { return '?'; } })();
process.stdout.write(JSON.stringify({ ready: true, engine: 'rhwp-wasm', version }) + '\n');

const rl = readline.createInterface({ input: process.stdin, terminal: false });
for await (const line of rl) {
  if (!line.trim()) continue;
  let req; try { req = JSON.parse(line); } catch (e) { process.stdout.write(JSON.stringify({ ok: false, error: 'bad request' }) + '\n'); continue; }
  const t0 = performance.now();
  const res = { id: req.id, ok: false };
  let doc = null;
  try {
    const t1 = performance.now();
    if (req.op === 'empty') {            // 자가 점검용: 빈 문서를 만들어 HWPX 로 저장
      doc = mod.HwpDocument.createEmpty();
      doc.createBlankDocument();          // rhwp 내장 빈 서식(HWP 2010) — 한글 호환 구조
      if (req.text) doc.insertText(0, 0, 0, String(req.text));
    } else {
      const data = new Uint8Array(fs.readFileSync(req.src));
      doc = req.password ? mod.HwpDocument.openWithPassword(data, req.password) : new mod.HwpDocument(data);
    }
    res.load_ms = +(performance.now() - t1).toFixed(1);
    if (req.op === 'empty' && req.dst.toLowerCase().endsWith('.hwp')) {   // 빈 HWP(5.0) 저장
      const b = doc.exportHwp();
      fs.writeFileSync(req.dst, b);
      res.ok = true; res.bytes = b.length; res.ms = +(performance.now() - t0).toFixed(1);
      try { doc.free(); } catch {}
      process.stdout.write(JSON.stringify(res) + '\n');
      continue;
    }
    const ex = doc.exportHwpxWithReport();
    let loss = null; try { loss = JSON.parse(ex.contentLoss()); } catch { loss = null; }
    const bytes = ex.takeBytes();
    try { ex.free(); } catch {}
    fs.mkdirSync(path.dirname(req.dst), { recursive: true });
    const tmp = req.dst + '.part';
    fs.writeFileSync(tmp, bytes); fs.renameSync(tmp, req.dst);
    res.ok = true; res.bytes = bytes.length; res.loss = loss;
  } catch (e) {
    res.error = String(e && e.message ? e.message : e).slice(0, 500);
  } finally {
    try { if (doc) doc.free(); } catch {}
  }
  res.ms = +(performance.now() - t0).toFixed(1);
  process.stdout.write(JSON.stringify(res) + '\n');
}
