import sys,os,collections,difflib,json
sys.path.insert(0,'/home/claude/scorer')
import format_score as F
C=collections.Counter(); docs=collections.defaultdict(set)
for H,O in [(a,b) for a,b in zip(sys.argv[1::2],sys.argv[2::2])]:
    for f in sorted(os.listdir(H)):
        k=f[:-5]
        if not os.path.exists(O+'/'+f): continue
        R=F.read_fmt(H+'/'+f); P=F.read_fmt(O+'/'+f)
        if not(R['ok'] and P['ok']): continue
        ra=[p for p in R['paras'] if p['chars']]; rb=[p for p in P['paras'] if p['chars']]
        pairs,ka,kb=F._pair_paras(ra,rb)
        for i,j in pairs:
            A,B=ra[i]['chars'],rb[j]['chars']
            blocks=[(0,0,len(A))] if ka[i]==kb[j] else difflib.SequenceMatcher(None,ka[i],kb[j],autojunk=False).get_matching_blocks()
            for a0,b0,sz in blocks:
                for t in range(sz):
                    ch=A[a0+t][0]; x=F.char_key(A[a0+t][1],ch); y=F.char_key(B[b0+t][1],ch)
                    if x and y:
                        C[(y[0],x[0])]+=1; docs[(y[0],x[0])].add(k)
json.dump([[k[0],k[1],v,len(docs[k])] for k,v in C.items()],open(sys.argv[-1] if len(sys.argv)%2==0 else '/dev/null','w'),ensure_ascii=False)
