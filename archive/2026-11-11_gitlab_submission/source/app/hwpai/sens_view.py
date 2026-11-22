"""민감정보 확인 화면(HTML) — 이 컴퓨터 안에서만 쓰는 단일 파일. 네트워크 요청 없음.

문서 미리보기에서 검출 구간을 종류별 색으로 표시하고, 항목마다 「민감정보임 / 민감정보 아님」을 고른다.
화면(GUI)·명령줄·브라우저 전용 웹 버전이 같은 함수를 쓴다.

  render_review_html(docs, reviewer="", api=None) -> str
    docs: [{"name","sha256","text","items":[{kind,text,start,end,auto,reason,before,after}],"decisions":{key:"sensitive"|"not_sensitive"},"policy":"mask"|"block"}]
    api : 저장 주소(예 "/api/sens/save"). 없으면 「저장」이 결정 파일(민감확인_결정.json)을 내려받게 한다.
          결정 파일은 `python -m hwpai sens apply 민감확인_결정.json` 으로 적용한다.

웹 버전 연동: 웹 쪽은 이 HTML 문자열(또는 아래 TEMPLATE 의 JS)을 그대로 쓰고, payload 의 docs 를 자기 검출 결과로 채우면 된다
(검출 규칙은 sens.detect 의 규칙을 JS 로 옮기거나, 로컬 서버가 있으면 /api/sens/scan 을 부른다).
"""
from __future__ import annotations

import html
import json

from .sens import KIND_COLOR, item_key

MAX_FULL = 200_000


def _doc_payload(d: dict) -> dict:
    text = d["text"]
    items = d["items"]
    for it in items:
        it["key"] = item_key(it)
    segs = None
    if len(text) > MAX_FULL:   # 큰 문서는 검출 주변만 보인다
        segs = []
        for it in items:
            segs.append((max(0, it["start"] - 300), min(len(text), it["end"] + 300)))
        merged = []
        for a, b in sorted(segs):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        segs = merged
    return {"name": d["name"], "sha256": d.get("sha256", ""), "text": text if segs is None else "", "segs": segs,
            "full": text if segs is not None else None, "items": [{k: it[k] for k in ("key", "kind", "text", "start", "end", "auto", "reason", "before", "after")} for it in items],
            "decisions": d.get("decisions", {}), "policy": d.get("policy") or "block"}


def render_review_html(docs: list[dict], reviewer: str = "", api: str | None = None) -> str:
    payload = {"docs": [], "colors": KIND_COLOR, "reviewer": reviewer, "api": api}
    for d in docs:
        p = _doc_payload(d)
        if p["segs"] is not None:   # 서버에서 조각으로 자른다
            full = p.pop("full")
            p["pieces"] = [[a, b, full[a:b]] for a, b in p["segs"]]
        else:
            p.pop("full", None)
        payload["docs"].append(p)
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("/*__DATA__*/", data)


TEMPLATE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>민감정보 확인 — hwpai</title>
<style>
:root{--bg:#fafafa;--fg:#1d1d1f;--mut:#666;--card:#fff;--bd:#d9d9de;--acc:#0b57d0}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#eee;--mut:#9a9aa0;--card:#202024;--bd:#38383d;--acc:#8ab4f8}}
*{box-sizing:border-box}body{margin:0;font:14px/1.55 "Malgun Gothic","Noto Sans KR",system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--bd);padding:8px 12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
header h1{font-size:15px;margin:0 8px 0 0}button,select,input{font:inherit}button{padding:4px 10px;border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:6px;cursor:pointer}
button.p{background:var(--acc);color:#fff;border-color:var(--acc)}button:focus-visible,input:focus-visible,select:focus-visible,.item:focus-visible{outline:2px solid var(--acc)}
main{display:grid;grid-template-columns:230px 1fr 380px;gap:10px;padding:10px;height:calc(100vh - 56px)}
@media (max-width:1000px){main{grid-template-columns:1fr;height:auto}}
.pane{background:var(--card);border:1px solid var(--bd);border-radius:8px;overflow:auto;padding:8px;min-height:200px}
.doc{padding:6px 8px;border-radius:6px;cursor:pointer;border:1px solid transparent;word-break:break-all}.doc.sel{border-color:var(--acc)}.doc small{display:block;color:var(--mut)}
.badge{display:inline-block;padding:0 6px;border-radius:9px;font-size:12px;color:#fff}.b0{background:#2e7d32}.b1{background:#c62828}.b2{background:#2e7d32}.b3{background:#ef6c00}
#text{white-space:pre-wrap;word-break:break-word;font-family:"Malgun Gothic",system-ui,sans-serif}
mark{background:transparent;border-radius:3px;padding:0 1px;cursor:pointer;color:inherit}
mark.ok{border-bottom-style:dashed!important}mark.cur{outline:3px solid var(--acc)}
mark.dsens{background:rgba(211,47,47,.18)}mark.dno{opacity:.65}
.item{border:1px solid var(--bd);border-radius:6px;padding:6px 8px;margin-bottom:6px}.item.cur{border-color:var(--acc);box-shadow:0 0 0 2px var(--acc) inset}
.ctx{color:var(--mut);font-size:12px;word-break:break-all}.val{font-weight:700}.k{display:inline-block;padding:0 6px;border-radius:4px;color:#fff;font-size:12px}
.row{display:flex;gap:10px;margin-top:4px;flex-wrap:wrap}.row label{cursor:pointer}.legend span{margin-right:8px}.sw{display:inline-block;width:12px;height:12px;vertical-align:middle;border-radius:2px;margin-right:3px}
.hint{font-size:12px;color:var(--mut)}.empty{color:var(--mut);padding:12px}
</style></head><body>
<header><h1>민감정보 확인</h1>
<span id="legend" class="legend"></span>
<label>확인자 <input id="who" size="10"></label>
<label><input type="checkbox" id="onlyPend"> 미확인만</label>
<select id="kindf"><option value="">종류 전체</option></select>
<button id="bulkNo" title="이 문서에서 보이는 항목 모두 「아님」">보이는 항목 모두 아님</button>
<button id="bulkYes" title="이 문서에서 보이는 항목 모두 「민감정보임」">보이는 항목 모두 민감정보임</button>
<label>민감정보 있는 문서는 <select id="policy"><option value="mask">가려서 AI 에 보이기</option><option value="block">AI 에 계속 막기(변환은 허용)</option></select></label>
<button class="p" id="save">저장 (Ctrl+S)</button><span id="msg" class="hint" role="status"></span></header>
<main><nav class="pane" id="docs" aria-label="문서 목록"></nav>
<section class="pane" id="view" aria-label="문서 미리보기"><div id="text"></div></section>
<aside class="pane" id="items" aria-label="검출 항목"></aside></main>
<div class="hint" style="padding:0 12px 10px">키보드: j/k 다음·이전 항목 · s 민감정보임 · n 아님 · [ ] 이전·다음 문서 · Ctrl+S 저장. 점선 밑줄 = 업무 연락처 등 「추정 비민감」(기본 표시는 아님, 바꿀 수 있음). 이 화면은 네트워크를 쓰지 않습니다.</div>
<script id="data" type="application/json">/*__DATA__*/</script>
<script>
const P=JSON.parse(document.getElementById('data').textContent);
const $=s=>document.querySelector(s);let di=0,ci=0;
$('#who').value=P.reviewer||'';
const kinds=[...new Set(P.docs.flatMap(d=>d.items.map(i=>i.kind)))];
kinds.forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=k;$('#kindf').appendChild(o)});
$('#legend').innerHTML=Object.entries(P.colors).filter(([k])=>kinds.includes(k)).map(([k,c])=>`<span><i class="sw" style="background:${c}"></i>${k}</span>`).join('');
P.docs.forEach(d=>{d.dec=Object.assign({},d.decisions||{})});
const dec=(d,it)=>d.dec[it.key]||(it.auto==='추정 비민감'?'not_sensitive_auto':null);
function state(d){let pend=0,sens=0;d.items.forEach(it=>{const v=dec(d,it);if(v==='sensitive')sens++;else if(!v)pend++});return pend?1:(sens?3:(d.items.length?2:0))}
const SN=['없음','확인 필요','확인 완료(아님)','확인 완료(민감정보 있음)'];
function visible(d){const kf=$('#kindf').value,op=$('#onlyPend').checked;return d.items.map((it,i)=>[it,i]).filter(([it])=>(!kf||it.kind===kf)&&(!op||!dec(d,it)))}
function drawDocs(){$('#docs').innerHTML=P.docs.map((d,i)=>{const s=state(d);const pend=d.items.filter(it=>!dec(d,it)).length;return `<div class="doc ${i===di?'sel':''}" data-i="${i}" tabindex="0"><span class="badge b${s}">${SN[s]}</span> ${esc(d.name)}<small>검출 ${d.items.length}건 · 미확인 ${pend}건</small></div>`}).join('')||'<div class="empty">문서가 없습니다</div>';
 document.querySelectorAll('.doc').forEach(e=>{e.onclick=()=>{di=+e.dataset.i;ci=0;draw()};e.onkeydown=ev=>{if(ev.key==='Enter')e.click()}})}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function drawText(){const d=P.docs[di];const out=[];const vis=new Set(visible(d).map(([it])=>it.key));
 const pieces=d.pieces||[[0,d.text.length,d.text]];
 pieces.forEach(([a,b,t],pi)=>{if(d.pieces&&pi===0&&a>0)out.push('<span class="hint">… </span>');let pos=a;
  d.items.filter(it=>it.start>=a&&it.end<=b).forEach(it=>{out.push(esc(t.slice(pos-a,it.start-a)));const v=dec(d,it);const col=P.colors[it.kind]||'#888';
   const cls=['mk',it.auto==='추정 비민감'?'ok':'',v==='sensitive'?'dsens':(v?'dno':''),(d.items[ci]&&d.items[ci].key===it.key)?'cur':''].join(' ');
   out.push(`<mark class="${cls}" data-k="${it.key}" style="border-bottom:3px solid ${col};${vis.has(it.key)?'':'opacity:.35'}" title="${esc(it.kind)} — ${esc(it.reason)}">${esc(t.slice(it.start-a,it.end-a))}</mark>`);pos=it.end});
  out.push(esc(t.slice(pos-a)));if(d.pieces)out.push('<span class="hint"> …\n</span>')});
 $('#text').innerHTML=out.join('');document.querySelectorAll('mark.mk').forEach(m=>m.onclick=()=>{const i=d.items.findIndex(x=>x.key===m.dataset.k);ci=i;draw()})}
function drawItems(){const d=P.docs[di];const v=visible(d);if(!v.length){$('#items').innerHTML='<div class="empty">보이는 항목이 없습니다</div>';return}
 $('#items').innerHTML=v.map(([it,i])=>{const val=dec(d,it);const col=P.colors[it.kind]||'#888';
  return `<div class="item ${i===ci?'cur':''}" data-i="${i}" tabindex="0"><span class="k" style="background:${col}">${esc(it.kind)}</span> <span class="val">${esc(it.text)}</span>
  <div class="ctx">…${esc(it.before)}<b>${esc(it.text)}</b>${esc(it.after)}…</div><div class="hint">${esc(it.reason)}</div>
  <div class="row"><label><input type="radio" name="r${i}" value="sensitive" ${val==='sensitive'?'checked':''}> 민감정보임</label><label><input type="radio" name="r${i}" value="not_sensitive" ${(val==='not_sensitive'||val==='not_sensitive_auto')?'checked':''}> 민감정보 아님(업무 연락처 등)</label></div></div>`}).join('');
 document.querySelectorAll('.item').forEach(e=>{e.onclick=ev=>{ci=+e.dataset.i;if(ev.target.tagName!=='INPUT')drawText()};e.querySelectorAll('input').forEach(r=>r.onchange=()=>{set(+e.dataset.i,r.value)})});
 const c=document.querySelector('.item.cur');if(c)c.scrollIntoView({block:'nearest'})}
function set(i,v){const d=P.docs[di];d.dec[d.items[i].key]=v;draw()}
function draw(){drawDocs();drawText();drawItems();const cm=document.querySelector('mark.cur');if(cm)cm.scrollIntoView({block:'nearest'});$('#policy').value=P.docs[di].policy||'mask'}
function move(n){const d=P.docs[di];const v=visible(d).map(([,i])=>i);if(!v.length)return;let p=v.indexOf(ci);p=p<0?0:Math.min(v.length-1,Math.max(0,p+n));ci=v[p];draw()}
function bulk(v){const d=P.docs[di];visible(d).forEach(([it])=>{d.dec[it.key]=v});draw()}
$('#bulkNo').onclick=()=>bulk('not_sensitive');$('#bulkYes').onclick=()=>bulk('sensitive');$('#onlyPend').onchange=$('#kindf').onchange=draw;
$('#policy').onchange=()=>{P.docs[di].policy=$('#policy').value};
function save(){const out={reviewer:$('#who').value||'',saved:new Date().toISOString(),docs:P.docs.map(d=>({sha256:d.sha256,name:d.name,policy:d.policy||'mask',decisions:Object.fromEntries(Object.entries(d.dec).filter(([k,v])=>v==='sensitive'||v==='not_sensitive'))}))};
 if(P.api){fetch(P.api,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(out)}).then(r=>r.json()).then(j=>{$('#msg').textContent='저장했습니다 — '+(j.msg||'')}).catch(e=>{$('#msg').textContent='저장 실패: '+e})}
 else{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));a.download='민감확인_결정.json';a.click();$('#msg').textContent='결정 파일을 내려받았습니다 — python -m hwpai sens apply 민감확인_결정.json'}}
$('#save').onclick=save;
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)&&e.target.type!=='radio')return;
 if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();save();return}
 if(e.key==='j')move(1);else if(e.key==='k')move(-1);else if(e.key==='s'){set(ci,'sensitive')}else if(e.key==='n'){set(ci,'not_sensitive')}
 else if(e.key===']'){di=Math.min(P.docs.length-1,di+1);ci=0;draw()}else if(e.key==='['){di=Math.max(0,di-1);ci=0;draw()}});
draw();
</script></body></html>"""
