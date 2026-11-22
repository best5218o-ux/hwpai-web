// hwpai 신뢰성 시험용 렌더 일꾼 — rhwp wasm 으로 문서(HWP·HWPX)를 쪽별 SVG 로 렌더한다.
// 요청(한 줄 JSON): {"src","outdir","maxPages"}  응답: {"ok","pages","rendered","ms"}
import fs from 'node:fs'; import path from 'node:path'; import readline from 'node:readline'; import { pathToFileURL } from 'node:url';
const coreDir = process.argv[2];
const mod = await import(pathToFileURL(path.join(coreDir, 'rhwp.js')).href);
globalThis.measureTextWidth = (font, text) => { const m = /(\d+(?:\.\d+)?)px/.exec(font || ''); const sz = m ? parseFloat(m[1]) : 12; let w = 0; for (const ch of text || '') w += (ch.codePointAt(0) > 0x2e80 ? 1.0 : 0.55) * sz; return w; };
mod.initSync({ module: fs.readFileSync(path.join(coreDir, 'rhwp_bg.wasm')) });
process.stdout.write(JSON.stringify({ ready: true }) + '\n');
const rl = readline.createInterface({ input: process.stdin, terminal: false });
for await (const line of rl) {
  if (!line.trim()) continue;
  const req = JSON.parse(line); const t0 = performance.now(); const res = { ok: false };
  let doc = null;
  try {
    doc = new mod.HwpDocument(new Uint8Array(fs.readFileSync(req.src)));
    const n = doc.pageCount(); res.pages = n;
    fs.mkdirSync(req.outdir, { recursive: true });
    const lim = Math.min(n, req.maxPages || 5);
    for (let i = 0; i < lim; i++) fs.writeFileSync(path.join(req.outdir, `p${i}.svg`), doc.renderPageSvg(i));
    res.rendered = lim; res.ok = true;
  } catch (e) { res.error = String(e && e.message ? e.message : e).slice(0, 300); }
  finally { try { if (doc) doc.free(); } catch {} }
  res.ms = +(performance.now() - t0).toFixed(1);
  process.stdout.write(JSON.stringify(res) + '\n');
}
