import zipfile,re,os,sys,collections
sys.path.insert(0,'<작업폴더>')
from h5shapes import shapes
KM={'$pic':'pic','$rec':'rect','$lin':'line','$con':'container','$ell':'ellipse','$pol':'polygon','$cur':'curve','$arc':'arc','$ole':'ole','$col':'connectLine'}
C=collections.Counter(); ex=collections.defaultdict(list)
H='/home/claude/heldout/hangul/'; O='/home/claude/heldout/원본/'
for f in sorted(os.listdir(H)):
    k=f[:-5]
    try: raw=shapes(O+k+'.hwp')
    except Exception: continue
    z=zipfile.ZipFile(H+f); hx=[]
    for n in sorted([n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml',n)],key=lambda n:int(re.findall(r'\d+',n)[-1])):
        s=z.read(n).decode('utf-8','replace')
        for m in re.finditer(r'<hp:(pic|rect|line|ellipse|polygon|curve|arc|container|ole|connectLine) ([^>]*)>',s):
            body=s[m.end():m.end()+600]
            og=re.search(r'<hp:orgSz width="(\d+)" height="(\d+)"',body); cs=re.search(r'<hp:curSz width="(\d+)" height="(\d+)"',body)
            gl=re.search(r'groupLevel="(\d+)"',m.group(2))
            if og and cs: hx.append((m.group(1),int(gl.group(1)) if gl else 0,(int(og[1]),int(og[2])),(int(cs[1]),int(cs[2]))))
    rk=[(KM.get(r['id'],r['id']),r) for r in raw]
    if [x[0] for x in rk]!=[x[0] for x in hx]:
        C['seq_mismatch']+=1; continue
    for (kind,r),(_,gl,og,cs) in zip(rk,hx):
        if og!=r['org']: C['org_diff']+=1
        for d in (0,1):
            rc=r['cur'][d]; ro=r['org'][d]; hc=cs[d]
            if rc==ro and rc!=0: t='EQ_keep' if hc==rc else ('EQ_zero' if hc==0 else 'EQ_other')
            elif hc==rc: t='same'
            elif hc==0 and rc==ro: t='0_cur==org'
            elif hc==0: t='0_other'
            else: t='other'
            C[(kind,'grp' if gl else 'top',t)]+=1
            if t in('0_other','other') and len(ex[(kind,t)])<4: ex[(kind,t)].append((k,gl,r['org'],r['cur'],cs))
for k,v in sorted(C.items(),key=str): print(k,v)
for k,v in ex.items(): print(k,v)
