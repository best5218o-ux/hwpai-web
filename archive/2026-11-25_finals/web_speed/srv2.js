const http=require('http'),fs=require('fs'),path=require('path'),zlib=require('zlib');
const root=process.argv[2],port=+process.argv[3],BPS=(+process.argv[4]||20)*1e6/8;
const T={'.html':'text/html; charset=utf-8','.js':'application/javascript','.css':'text/css','.wasm':'application/wasm','.json':'application/json','.zip':'application/zip','.png':'image/png','.hwp':'application/octet-stream','.webmanifest':'application/manifest+json'};
const gzc={};
// shared link: queue of chunks, drained at BPS
const q=[]; setInterval(()=>{let budget=BPS/100;while(q.length&&budget>0){const it=q[0];const n=Math.min(budget,it.b.length-it.o);it.s.write(it.b.subarray(it.o,it.o+n));it.o+=n;budget-=n;if(it.o>=it.b.length){it.s.end();q.shift();}}},10);
http.createServer((rq,s)=>{setTimeout(()=>{let p=decodeURIComponent(rq.url.split('?')[0]);if(p.endsWith('/'))p+='index.html';const f=path.join(root,p);
if(!fs.existsSync(f)||fs.statSync(f).isDirectory()){s.writeHead(404);return s.end();}const ext=path.extname(f);const h={'Content-Type':T[ext]||'application/octet-stream','Cache-Control':'max-age=600','ETag':'"'+fs.statSync(f).mtimeMs+'"'};
if(rq.headers['if-none-match']===h.ETag){s.writeHead(304,h);return s.end();}
let b=fs.readFileSync(f);if(['.html','.js','.css','.wasm','.json'].includes(ext)){b=gzc[f]||(gzc[f]=zlib.gzipSync(b,{level:6}));h['Content-Encoding']='gzip';}
h['Content-Length']=b.length;s.writeHead(200,h);q.push({s,b,o:0});},60);}).listen(port);
