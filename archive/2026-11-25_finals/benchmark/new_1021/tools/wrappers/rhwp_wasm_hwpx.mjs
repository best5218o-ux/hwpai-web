// rhwp(@rhwp/core WASM) HwpDocument.exportHwpx() 로 HWP→HWPX. 사용: node rhwp_wasm_hwpx.mjs <in.hwp> <out.hwpx>
import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module';
const NM = process.env.BCN_NODE_MODULES || '/dev/shm/bcn/npm/node_modules';
const core = await import(path.join(NM, '@rhwp/core/rhwp.js'));
const wasm = fs.readFileSync(path.join(NM, '@rhwp/core/rhwp_bg.wasm'));
// rhwp 는 SVG 측정용 measureTextWidth 전역 함수를 요구할 수 있어 근사 구현을 둔다(변환 출력에는 무관)
globalThis.measureTextWidth ??= (font, text) => [...text].length * 8;
await (core.default ?? core.init)({ module_or_path: wasm }).catch(async () => (core.default)(wasm));
const [inp, out] = process.argv.slice(2);
const doc = new core.HwpDocument(new Uint8Array(fs.readFileSync(inp)));
const bytes = doc.exportHwpx();
fs.writeFileSync(out, Buffer.from(bytes));
