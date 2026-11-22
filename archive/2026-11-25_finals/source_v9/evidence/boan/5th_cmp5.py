import json,sys,glob
S='<작업폴더>'
ITEMS=['format','page','cols','para','char','tbl','tbl.width','tbl.height','tbl.place','obj','obj.size','obj.pos','obj.wrap']
M=['core_recall','core_precision','cell_text_recall','cell_text_precision','bin_recall','bin_precision']
def load(globp,tool):
    d={}
    for p in glob.glob(f'{S}/{globp}/{tool}.jsonl'):
        for l in open(p): x=json.loads(l); d[x.get('key') or x.get('doc')]=x
    return d
def fmt(name,a,ta,b,tb):
    A,B=load(a,ta),load(b,tb)
    ks=[k for k in A if k in B]
    worse=[(k,it,A[k].get(it),B[k].get(it)) for k in ks for it in ITEMS if (B[k].get(it) or 0)<(A[k].get(it) or 0)-1e-9]
    def mean(R,it):
        v=[0.0 if R[k]['status']!='ok' else R[k][it] for k in ks if R[k]['status']!='ok' or R[k].get(it) is not None]; return round(sum(v)/len(v),4) if v else None
    print(name,len(ks),'pass',sum(bool(A[k].get('format_pass')) for k in ks),'->',sum(bool(B[k].get('format_pass')) for k in ks),'worse',len(worse),worse[:5])
    print('   means', {it:(mean(A,it),mean(B,it)) for it in ITEMS})
    print('   newfail',[k for k in ks if A[k].get('format_pass') and not B[k].get('format_pass')])
def ind(name,a,ta,b,tb):
    A,B=load(a,ta),load(b,tb); worse=[]
    for k in A:
        if k not in B: continue
        for ref in ('a','b'):
            x=A[k].get(ref); y=B[k].get(ref); x=x if isinstance(x,dict) else {}; y=y if isinstance(y,dict) else {}
            for m in M:
                if (y.get(m) or 0)<(x.get(m) or 0)-1e-9: worse.append((k,ref,m,x.get(m),y.get(m)))
            if x.get('cnt_match_all') and not y.get('cnt_match_all'): worse.append((k,ref,'cnt',{c:x[c] for c in x if c.startswith('cnt_')},{c:y[c] for c in y if c.startswith('cnt_')}))
    ca=sum(1 for v in A.values() if isinstance(v.get('a'),dict) and v['a'].get('cnt_match_all')); cb=sum(1 for v in B.values() if isinstance(v.get('a'),dict) and v['a'].get('cnt_match_all'))
    print('-- ind',name,len(A),'worse',len(worse),worse[:4],'cnt_all',ca,'->',cb)
if __name__=='__main__':
    fmt('heldout','fmt5_h','c102','fmt5f_h','r5'); ind('heldout','ind_h','c102','ind5_h','r5')
    fmt('fresh37','fmt5_f','c102','fmt5f_f','r5'); ind('fresh37','ind_f37','c102','ind5_f','r5')
