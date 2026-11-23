const {chromium}=require('playwright');
const URL_=process.argv[2]; const MBPS=+process.argv[3]||20; const CPU=+process.argv[4]||2; const VISITS=+process.argv[5]||2;
(async()=>{const b=await chromium.launch();const c=await b.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
const out=[];
for(let v=1;v<=VISITS;v++){
const p=await c.newPage(); const s=await c.newCDPSession(p);
await s.send('Network.enable');
if(CPU>1) await s.send('Emulation.setCPUThrottlingRate',{rate:CPU});
let bytes=0; s.on('Network.loadingFinished',e=>bytes+=e.encodedDataLength);
const t0=Date.now(); await p.goto(URL_);
let tE=null; while(Date.now()-t0<240000){ const r=await p.evaluate(()=>{const e=document.querySelector('#engine');return e&&e.classList.contains('ready')}).catch(()=>false); if(r){tE=Date.now()-t0;break;} await p.waitForTimeout(200);}
let tD=null;
if(tE){ await p.evaluate(()=>document.querySelector('#btnDemo').click()); const t1=Date.now();
 while(Date.now()-t1<240000){ const r=await p.evaluate(()=>/처리 끝/.test(document.body.innerText)).catch(()=>false); if(r){tD=Date.now()-t1;break;} await p.waitForTimeout(200);} }
out.push({visit:v,ready:tE,demo:tD,total:tE&&tD?tE+tD:null,MB:+(bytes/1e6).toFixed(1)});
await p.waitForTimeout(v==1?25000:1000); await p.close();}
console.log(URL_,MBPS+'Mbps cpu'+CPU,JSON.stringify(out));
await b.close()})();
