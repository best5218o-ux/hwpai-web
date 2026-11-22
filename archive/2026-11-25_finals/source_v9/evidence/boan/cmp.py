import json, glob, collections, sys
def L(pat):
    d={}
    for f in glob.glob(pat):
        for l in open(f):
            r=json.loads(l); d[r['doc']]=r
    return d
o=L('reg_old_*.jsonl'); n=L('reg_new_*.jsonl')
both=sorted(set(o)&set(n))
print('both', len(both), 'old dist', collections.Counter(o[d]['verdict'] for d in both), 'new dist', collections.Counter(n[d]['verdict'] for d in both))
tr=collections.Counter((o[d]['verdict'],n[d]['verdict']) for d in both)
print('transitions', dict(tr))
newcodes=collections.Counter()
for d in both:
    for c in set(n[d]['codes'])-set(o[d]['codes']): newcodes[c]+=1
print('new codes', newcodes.most_common())
if len(sys.argv)>1:
    for d in both:
        nc=set(n[d]['codes'])-set(o[d]['codes'])
        if nc & set(sys.argv[1].split(',')):
            print(d, o[d]['verdict'],'->',n[d]['verdict'], [x for x in n[d].get('fails',[])+n[d].get('warns',[]) if x.split(':')[0] in nc][:3])
