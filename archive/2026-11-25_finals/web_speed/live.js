const {chromium,devices}=require('playwright');
(async()=>{const b=await chromium.launch();const c=await b.newContext({...devices['Pixel 7']});
const p=await c.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(e.message));
const t0=Date.now(); await p.goto('https://best5218o-ux.github.io/hwpai-web/demo.html');
let tE=null; while(Date.now()-t0<180000){ if(await p.evaluate(()=>document.querySelector('#engine')?.classList.contains('ready')).catch(()=>false)){tE=Date.now()-t0;break;} await p.waitForTimeout(200);}
await p.evaluate(()=>document.querySelector('#btnDemo').click()); const t1=Date.now(); let tD=null;
while(Date.now()-t1<180000){ if(await p.evaluate(()=>/처리 끝/.test(document.body.innerText)).catch(()=>false)){tD=Date.now()-t1;break;} await p.waitForTimeout(200);}
const info=await p.evaluate(()=>({eng:document.querySelector('#engineInfo')?.textContent, rows:[...document.querySelectorAll('#list tr, .row, tbody tr')].map(r=>r.innerText.replace(/\s+/g,' ').slice(0,80)).slice(0,8)}));
await p.screenshot({path:'/tmp/qr/live.png'});
console.log(JSON.stringify({ready:tE,demo:tD,errs,info},null,1));
await p.waitForTimeout(15000);
const sw=await p.evaluate(()=>window.HWPAI_PWA&&window.HWPAI_PWA.sw); const ks=await p.evaluate(async()=>(await caches.keys()));
console.log('sw',sw,ks);
// second visit
const p2=await c.newPage(); const t2=Date.now(); await p2.goto('https://best5218o-ux.github.io/hwpai-web/demo.html');
let tE2=null; while(Date.now()-t2<120000){ if(await p2.evaluate(()=>document.querySelector('#engine')?.classList.contains('ready')).catch(()=>false)){tE2=Date.now()-t2;break;} await p2.waitForTimeout(200);}
console.log('visit2 ready',tE2);
await b.close()})();
