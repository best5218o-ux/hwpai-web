import fs from 'node:fs'; import path from 'node:path'; import { pathToFileURL } from 'node:url';
const core=process.argv[2]; const mod=await import(pathToFileURL(path.join(core,'rhwp.js')).href);
globalThis.measureTextWidth=(font,text)=>{const m=/(\d+(?:\.\d+)?)px/.exec(font||'');const sz=m?parseFloat(m[1]):12;let w=0;for(const ch of text||'')w+=(ch.codePointAt(0)>0x2e80?1.0:0.55)*sz;return w;};
mod.initSync({module:fs.readFileSync(path.join(core,'rhwp_bg.wasm'))});
const doc=mod.HwpDocument.createEmpty(); doc.createBlankDocument();
const rows=JSON.parse(fs.readFileSync(process.argv[3]));
const out=[];
for(const r of rows){ let w=null,h=null; try{const svg=doc.renderEquationPreview(r[1],r[2],0); const m=/width="([\d.]+)" height="([\d.]+)"/.exec(svg); w=+m[1]*75; h=+m[2]*75;}catch(e){} out.push([r[0],r[3],r[4],w,h,r[1].slice(0,40)]); }
fs.writeFileSync(process.argv[4],JSON.stringify(out));
