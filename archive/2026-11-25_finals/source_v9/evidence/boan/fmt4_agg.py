import json,glob,csv,sys,collections
S='<작업폴더>'
def load(pat,tool):
    out={}
    for p in glob.glob(f'{S}/{pat}/{tool}.jsonl'):
        for l in open(p):
            x=json.loads(l); out[x.get('key') or x.get('doc')]=x
    return out
ITEMS=['format','page','para','char','tbl','tbl.width','tbl.height','tbl.place','obj','obj.size','obj.pos']
def fmt(name,pat,a,b):
    A,B=load(pat,a),load(pat,b)
    print(f'== {name} ({len(A)})')
    for t,R in ((a,A),(b,B)):
        n=len(R); p=sum(bool(x.get('format_pass')) for x in R.values())
        means={}
        for it in ITEMS:
            v=[0.0 if x['status']!='ok' else x[it] for x in R.values() if x['status']!='ok' or x.get(it) is not None]
            means[it]=round(sum(v)/len(v),4) if v else None
        print(t,'pass',p,'fail',n-p,means)
    worse=[(k,it,A[k].get(it),B[k].get(it)) for k in A if k in B for it in ITEMS if (B[k].get(it) or 0)<(A[k].get(it) or 0)-1e-9]
    newfail=[k for k in A if A[k].get('format_pass') and not B[k].get('format_pass')]
    print('worse items',len(worse),worse[:8],'new fails',newfail)
M=['core_recall','core_precision','cell_text_recall','cell_text_precision','bin_recall','bin_precision']
def ind(name,pat,a,b):
    A,B=load(pat,a),load(pat,b)
    worse=[]
    for k in A:
        if k not in B: continue
        for ref in ('a','b'):
            x,y=A[k].get(ref),B[k].get(ref); x=x if isinstance(x,dict) else {}; y=y if isinstance(y,dict) else {}
            for m in M:
                if (y.get(m) or 0)<(x.get(m) or 0)-1e-9: worse.append((k,ref,m,x.get(m),y.get(m)))
            if x.get('cnt_match_all') and not y.get('cnt_match_all'): worse.append((k,ref,'cnt',None,None))
        if A[k].get('hwpx_parse_ok') and not B[k].get('hwpx_parse_ok'): worse.append((k,'parse'))
    better=sum(1 for k in A if k in B and not A[k].get('hwpx_parse_ok',True) and B[k].get('hwpx_parse_ok'))
    print(f'-- independent {name}: docs {len(A)} worse {len(worse)} {worse[:6]} parse-fixed {better}',
          'cnt_all a/b', sum(bool(isinstance(x.get('a'),dict) and x['a'].get('cnt_match_all')) for x in A.values()), sum(bool(isinstance(x.get('a'),dict) and x['a'].get('cnt_match_all')) for x in B.values()))
fmt('heldout532','fmt_h_cmp','v9','c102'); ind('heldout532','ind_h','v9','c102')
fmt('fresh37','fmt_f37_cmp','c101','c102'); ind('fresh37','ind_f37','c101','c102')
fmt('bulk1969','fmt_bulk_*','c101','c102'); ind('bulk1969','ind_bulk_*','c101','c102')
