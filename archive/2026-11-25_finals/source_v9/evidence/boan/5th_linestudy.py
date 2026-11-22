import zipfile,re,os,sys,collections
sys.path.insert(0,'<작업폴더>')
from h5shapes import shapes
KM={'$pic':'pic','$rec':'rect','$lin':'line','$con':'container','$ell':'ellipse','$pol':'polygon','$cur':'curve','$arc':'arc','$ole':'ole','$col':'connectLine'}
C=collections.Counter(); ex=collections.defaultdict(list)
for root in sys.argv[1:]:
  for f in sorted(os.listdir(root+'/hangul')):
    k=f[:-5]
    try: raw=shapes(root+'/원본/'+k+'.hwp')
    except Exception: continue
    z=zipfile.ZipFile(root+'/hangul/'+f); hx=[]
    for n in sorted([n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml',n)],key=lambda n:int(re.findall(r'\d+',n)[-1])):
        s=z.read(n).decode('utf-8','replace')
        for m in re.finditer(r'<hp:(pic|rect|line|ellipse|polygon|curve|arc|container|ole|connectLine) ([^>]*)>',s):
            body=s[m.end():m.end()+800]
            og=re.search(r'<hp:orgSz width="(\d+)" height="(\d+)"',body); cs=re.search(r'<hp:curSz width="(\d+)" height="(\d+)"',body)
            if og and cs: hx.append((m.group(1),(int(og[1]),int(og[2])),(int(cs[1]),int(cs[2])),'groupLevel="0"' not in m.group(2)))
    rk=[KM.get(r['id'],r['id']) for r in raw]
    if rk!=[x[0] for x in hx]: C['seq_mismatch']+=1; continue
    for r,(kind,og,cs,grp) in zip(raw,hx):
        cur,org=r['cur'],r['org']
        pred=tuple(0 if cur[d]==org[d] and cur[d]!=0 else cur[d] for d in (0,1))
        if kind=='line' and (0 in cur or max(cur)>0x7fffffff): C[('line0dim',grp,'hangul00' if cs==(0,0) else 'other',cur!=org)]+=1
        tag='rule_ok' if pred==cs else 'rule_bad'
        C[(kind,tag)]+=1
        if tag=='rule_bad' and len(ex[kind])<12: ex[kind].append((k,grp,org,cur,cs))
print(C)
for k,v in ex.items(): print(k,v)
