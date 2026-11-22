"""obj.size 불일치를 「HWPX curSz 차원별 0 = orgSz 와 같음」 규칙으로 다시 보면 몇 개가 실제 차이인지 센다(채점기 무수정, 분석용)."""
import sys,json,zipfile,re,collections
sys.path.insert(0,'/home/claude/scorer')
import format_score as F
def sem(el,kind,grp=False):
    d=F._obj_info(el,kind,grp)
    if grp:
        cs,og=F.kid(el,'curSz'),F.kid(el,'orgSz')
        if cs is not None and og is not None:
            w,h=F._int(cs.get('width'),0),F._int(cs.get('height'),0)
            d['w']=w or F._int(og.get('width')); d['h']=h or F._int(og.get('height'))
    return d
F._obj_info_orig=F._obj_info
def run(jsonl,H,O):
    rows=[json.loads(l) for l in open(jsonl)]
    fails=[r for r in rows if r.get('obj') is not None and r['obj']<0.99]
    tot=collections.Counter()
    for r in fails:
        k=r['key']
        orig=F._obj_info
        F._obj_info=lambda el,kind,grp=False: (sem.__wrapped__ if False else None) or _sem(el,kind,grp)
        R=F.read_fmt(H+'/'+k+'.hwpx'); P=F.read_fmt(O+'/'+k+'.hwpx')
        F._obj_info=orig
        res=F.compare_fmt(R,P)
        tot['docs']+=1; tot['sem_pass']+= res['obj']>=0.99
        print(k,'scorer obj',r['obj'],'-> semantic obj',res['obj'])
    print(dict(tot))
def _sem(el,kind,grp=False):
    d=F._obj_info_orig(el,kind,grp)
    if grp:
        cs,og=F.kid(el,'curSz'),F.kid(el,'orgSz')
        if cs is not None and og is not None:
            w,h=F._int(cs.get('width'),0),F._int(cs.get('height'),0)
            d['w']=w or F._int(og.get('width')); d['h']=h or F._int(og.get('height'))
    return d
if __name__=='__main__': run(*sys.argv[1:])
