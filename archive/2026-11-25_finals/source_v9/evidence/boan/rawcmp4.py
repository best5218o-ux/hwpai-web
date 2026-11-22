import sys,os,collections
sys.path.insert(0,'/home/claude/scorer'); sys.path.insert(0,'<작업폴더>')
from format_score import read_fmt,near
from h5cells import tables
from h5ctrl import ctrls
H,O,OUT=sys.argv[1],sys.argv[2],sys.argv[3]
C=collections.Counter(); ex=collections.defaultdict(list)
for f in sorted(os.listdir(H)):
    k=f[:-5]
    if not os.path.exists(OUT+'/'+f) or not os.path.exists(O+'/'+k+'.hwp'): continue
    try:
        R=read_fmt(H+'/'+f); P=read_fmt(OUT+'/'+f); T=tables(O+'/'+k+'.hwp'); tc=ctrls(O+'/'+k+'.hwp',{'tbl '})
    except Exception as e: C['err']+=1; continue
    if not (len(R['tables'])==len(P['tables'])==len(T)==len(tc)): C['tcount_mismatch']+=1; continue
    for rt,pt,t,c in zip(R['tables'],P['tables'],T,tc):
        for dim,rv,pv,raw in (('tw',rt['w'],pt['w'],c['w']),('th',rt['h'],pt['h'],c['h'])):
            a=near(rv,raw,75); b=near(rv,pv,75)
            C[(dim,'hangul=raw' if a else 'hangul!=raw','ours=hangul' if b else 'ours!=hangul')]+=1
            if not a and len(ex[dim])<5: ex[dim].append((k,rv,raw,pv))
        cells={(x['row'],x['col']):x for x in t['cells']}
        for key,cc in rt['cells'].items():
            x=cells.get(key); d=pt['cells'].get(key)
            if x is None or d is None: continue
            for dim,rv,pv,raw in (('cw',cc['w'],d['w'],x['w']),('ch',cc['h'],d['h'],x['h'])):
                a=near(rv,raw,75); b=near(rv,pv,75)
                C[(dim,'hangul=raw' if a else 'hangul!=raw','ours=hangul' if b else 'ours!=hangul')]+=1
                if not a and len(ex[dim])<8: ex[dim].append((k,key,rv,raw,pv))
for k,v in sorted(C.items(),key=str): print(k,v)
for k,v in ex.items(): print(k,v)
