import sys,json,collections
sys.path.insert(0,'/home/claude/scorer')
import format_score as F
H,O=sys.argv[1],sys.argv[2]
keys=[l.strip() for l in open(sys.argv[3]) if l.strip()]
orig=F._obj_info
def sem(el,kind,grp=False):
    d=orig(el,kind,grp)
    cs,og=F.kid(el,'curSz'),F.kid(el,'orgSz')
    if grp and cs is not None and og is not None:
        w,h=F._int(cs.get('width'),0),F._int(cs.get('height'),0)
        d['w']=w or F._int(og.get('width')); d['h']=h or F._int(og.get('height'))
    return d
out={}
for k in keys:
    F._obj_info=orig
    R=F.read_fmt(H+'/'+k+'.hwpx'); P=F.read_fmt(O+'/'+k+'.hwpx')
    if not (R['ok'] and P['ok']): out[k]={'err':(R['why'],P['why'])}; continue
    res=F.compare_fmt(R,P)
    F._obj_info=sem
    R2=F.read_fmt(H+'/'+k+'.hwpx'); P2=F.read_fmt(O+'/'+k+'.hwpx'); res2=F.compare_fmt(R2,P2)
    F._obj_info=orig
    d={'bad':[it for it in ('page','cols','para','char','tbl','obj','tbl.place') if res.get(it) is not None and res[it]<0.99]}
    if 'obj' in d['bad']:
        d['obj_sem']=res2['obj']
        # remaining obj mismatches under semantic
        br,bo={},{}
        for o in R2['objs']: br.setdefault(o['kind'],[]).append(o)
        for o in P2['objs']: bo.setdefault(o['kind'],[]).append(o)
        rem=[]
        for kd,l in br.items():
            for i,ro in enumerate(l):
                oo=bo.get(kd,[])[i] if i<len(bo.get(kd,[])) else None
                if oo is None: rem.append((kd,'missing')); continue
                e=F._place_eq(ro,oo)
                if not all(e.values()): rem.append((kd,ro.get('in_group'),[x for x in e if not e[x]],(ro.get('w'),ro.get('h')),(oo.get('w'),oo.get('h')),ro.get('off'),oo.get('off')))
        d['obj_rem']=rem[:6]; d['obj_nrem']=len(rem)
    if 'char' in d['bad']:
        ra=[p for p in R['paras'] if p['chars']]; rb=[p for p in P['paras'] if p['chars']]
        pairs,ka,kb=F._pair_paras(ra,rb); C=collections.Counter()
        for i,j in pairs:
            A,B=ra[i]['chars'],rb[j]['chars']
            blocks=[(0,0,len(A))] if ka[i]==kb[j] else __import__('difflib').SequenceMatcher(None,ka[i],kb[j],autojunk=False).get_matching_blocks()
            for a0,b0,sz in blocks:
                for t in range(sz):
                    ch=A[a0+t][0]; x=F.char_key(A[a0+t][1],ch); y=F.char_key(B[b0+t][1],ch)
                    if x!=y and x and y:
                        names=('font','size','b','i','u','color','spacing','ratio')
                        for n,a,b in zip(names,x,y):
                            if a!=b: C[(n,a,b) if n in('font','color') else (n,)]+=1
        d['char_diff']=C.most_common(5)
    if 'para' in d['bad']:
        d['para']={k2:res[k2] for k2 in res if k2.startswith('para.') and res[k2] is not None and res[k2]<0.99}
    if 'tbl' in d['bad'] or 'tbl.place' in d['bad']:
        d['tbl']={k2:res[k2] for k2 in res if k2.startswith('tbl') and res[k2] is not None and res[k2]<0.99}
    if 'page' in d['bad'] or 'cols' in d['bad']: d['page']=(res['page'],res['cols'])
    out[k]=d
json.dump(out,open(sys.argv[4],'w'),ensure_ascii=False,indent=0)
