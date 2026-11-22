import json,glob,csv,collections,statistics as st
R='/home/claude/bulk_compare_new/raw'
TOOLS=['hwpai','hancom','kordoc','hwp2hwpx','hwpConverter','pyhwpxlib','rhwp','hwpforge','hwp-convert','hwpxjs','jhwpx','h2h_asi','h2h_kossembly','h2h_yuson','ahwp']
FI=["page","cols","para_pair","para","para.align","para.line_spacing","para.indent","para.margin_lr","para.space_prev_next","para.break_kor","char","char.font","char.size","char.bold","char.italic","char.underline","char.color","char.spacing","char.ratio","tbl","tbl.span","tbl.width","tbl.height","tbl.border","tbl.fill","tbl.shape","tbl.place","obj","obj.size","obj.pos","obj.wrap"]
MET=["core_recall","core_precision","cell_text_recall","cell_text_precision","bin_recall","bin_precision"]
ref=set(json.loads(l)['key'] for p in glob.glob(f'{R}/fmt_*/hwpai.jsonl') for l in open(p))  # hangul 기준 있는 건
N=len(ref)
out=[];rows={}
for t in TOOLS:
    fmt={};ind={}
    for p in glob.glob(f'{R}/fmt_*/{t}.jsonl'):
        for l in open(p): x=json.loads(l); fmt[x['key']]=x
    for p in glob.glob(f'{R}/ind_*/{t}.jsonl'):
        for l in open(p): x=json.loads(l); ind[x['doc']]=x
    ok=[k for k in ref if fmt.get(k,{}).get('status')=='ok']
    def avgdoc(k):
        v=[fmt[k][f] for f in FI if isinstance(fmt[k].get(f),(int,float))]
        return sum(v)/len(v) if v else 0
    sc=[avgdoc(k) for k in ref]   # 변환 실패 = 0점 (전체 N건 기준)
    sc_ok=[avgdoc(k) for k in ok]
    full=sum(1 for k in ref if k in fmt and fmt[k].get('status')=='ok' and all(fmt[k][f]>=0.99 for f in FI if isinstance(fmt[k].get(f),(int,float))))
    def m(met):
        v=[ind[k]['a'][met] for k in ref if k in ind and ind[k].get('status')=='ok' and isinstance(ind[k].get('a',{}).get(met),(int,float))]
        return sum(v)/len(v) if v else None
    r=dict(tool=t,N=N,ok=len(ok),ok_rate=len(ok)/N,fmt_mean_all=sum(sc)/N,fmt_mean_ok=(sum(sc_ok)/len(sc_ok) if sc_ok else 0),fmt_full=full,fmt_full_rate=full/N,**{f'ind_{x}':m(x) for x in MET})
    for g in ['para','char','tbl','obj','page','cols']:
        v=[fmt[k][g] for k in ok if isinstance(fmt[k].get(g),(int,float))]; r['f_'+g]=sum(v)/len(v) if v else None
    rows[t]=r
w=csv.DictWriter(open('agg_new.csv','w',newline='',encoding='utf-8-sig'),fieldnames=list(rows['hwpai'].keys())); w.writeheader(); [w.writerow(r) for r in rows.values()]
f=lambda x:'-' if x is None else f'{x:.3f}'
print(f'기준(한글 저장본) 있는 건 N={N}')
print('도구 | 변환성공 | 서식평균(전체N,실패=0) | 서식평균(성공건) | 서식만점건(≥0.99) | 본문재현 | 표글재현 | 그림재현')
for r in sorted(rows.values(),key=lambda r:-r['fmt_mean_all']):
    print(f"{r['tool']} | {r['ok']}/{N} ({r['ok_rate']:.1%}) | {f(r['fmt_mean_all'])} | {f(r['fmt_mean_ok'])} | {r['fmt_full']} ({r['fmt_full_rate']:.1%}) | {f(r['ind_core_recall'])}/{f(r['ind_core_precision'])} | {f(r['ind_cell_text_recall'])} | {f(r['ind_bin_recall'])}")
