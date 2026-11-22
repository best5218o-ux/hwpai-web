// npm 라이브러리의 hwpToHwpx(bytes) 호출. 사용: node npm_hwptohwpx.mjs <패키지명> <in.hwp> <out.hwpx>
import fs from 'node:fs'; import path from 'node:path';
const NM = process.env.BCN_NODE_MODULES || '/dev/shm/bcn/npm/node_modules';
const [pkg, inp, out] = process.argv.slice(2);
const pj = JSON.parse(fs.readFileSync(path.join(NM, pkg, 'package.json'), 'utf8'));
const m = await import(path.join(NM, pkg, pj.module || pj.main || 'dist/index.js'));
const fn = m.hwpToHwpx ?? m.default?.hwpToHwpx;
const bytes = await fn(new Uint8Array(fs.readFileSync(inp)), { title: 'conv', creator: 'bulk-compare' });
fs.writeFileSync(out, Buffer.from(bytes));
