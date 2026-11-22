import sys
sys.path.insert(0,'/home/claude/scorer')
from format_score import read_fmt, _place_eq
H='/home/claude/heldout/hangul/'
def odiff(key,out='/home/claude/v9_heldout/',verbose=True):
    R=read_fmt(H+key+'.hwpx'); O=read_fmt(out+key+'.hwpx')
    br,bo={},{}
    for o in R['objs']: br.setdefault(o['kind'],[]).append(o)
    for o in O['objs']: bo.setdefault(o['kind'],[]).append(o)
    res=[]
    for k,l in br.items():
        ol=bo.get(k,[])
        for i,ro in enumerate(l):
            oo=ol[i] if i<len(ol) else None
            if oo is None: res.append((k,i,'MISSING')); continue
            e=_place_eq(ro,oo)
            if not all(e.values()):
                res.append((k,i,{x:v for x,v in e.items() if not v},'ref',ro.get('w'),ro.get('h'),ro.get('in_group'),ro.get('goff'),ro.get('off'),ro.get('wrap'),'out',oo.get('w'),oo.get('h'),oo.get('goff'),oo.get('off'),oo.get('wrap')))
    if verbose:
        print(key,{k:(len(v),len(bo.get(k,[]))) for k,v in br.items()})
        for r in res: print('  ',r)
    return res
if __name__=='__main__':
    for k in sys.argv[1:]: odiff(k)
