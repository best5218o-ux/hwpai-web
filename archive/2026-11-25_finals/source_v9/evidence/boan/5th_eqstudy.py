import sys,os,zipfile,re,collections,json,statistics
sys.path.insert(0,'<작업폴더>')
from h5ctrl import ctrls
C=collections.Counter(); rows=[]
for root,out in [('/home/claude/heldout','/home/claude/c102_heldout'),('/home/claude/bulkfail','/home/claude/bulkfail/c102'),('/home/claude/fresh37','/home/claude/fresh37/c102')]:
    for f in sorted(os.listdir(root+'/hangul')):
        k=f[:-5]
        try: raw=ctrls(root+'/원본/'+k+'.hwp',{'eqed'})
        except Exception: continue
        if not raw: continue
        def eqs(p):
            z=zipfile.ZipFile(p); r=[]
            for n in sorted([n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml',n)],key=lambda n:int(re.findall(r'\d+',n)[-1])):
                s=z.read(n).decode()
                for m in re.finditer(r'<hp:equation\b([^>]*)>(.*?)</hp:equation>',s,re.S):
                    sz=re.search(r'<hp:sz width="(\d+)"[^>]*height="(\d+)"',m.group(2)); sc=re.search(r'<hp:script>(.*?)</hp:script>',m.group(2),re.S)
                    bl=re.search(r'baseLine="(\d+)"',m.group(1)); bu=re.search(r'baseUnit="(\d+)"',m.group(1))
                    r.append((int(sz.group(1)),int(sz.group(2)),int(bl.group(1)) if bl else None,bu.group(1) if bu else None,sc.group(1) if sc else ''))
            return r
        H=eqs(root+'/hangul/'+f); O=eqs(out+'/'+f)
        if not(len(H)==len(O)==len(raw)): C['count_mismatch']+=1; continue
        for (hw,hh,hb,hbu,hs),(ow,oh,ob,obu,osc),r in zip(H,O,raw):
            rawsame = abs(hw-r['w'])<=75 and abs(hh-r['h'])<=75
            oursame = abs(hw-ow)<=75 and abs(hh-oh)<=75
            C[('raw=hangul' if rawsame else 'raw!=hangul','ours=hangul' if oursame else 'ours!=hangul')]+=1
            if not oursame: rows.append((k,r['w'],r['h'],ow,oh,hw,hh,hbu,hs[:50]))
print(C)
docs=collections.Counter(r[0] for r in rows); print(len(docs),docs.most_common(12))
for r in rows[:25]: print(r)
json.dump(rows,open('<작업폴더>/eqrows.json','w'),ensure_ascii=False)
