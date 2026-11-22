import json, collections, sys
def load(p):
    t=collections.OrderedDict()
    for l in open(p):
        r=json.loads(l); t.setdefault((r['el'],r['how']),collections.Counter())[r['result']]+=1
    return t
b=load(sys.argv[1]); a=load(sys.argv[2])
print("| 요소 | 변이 | 수 | 전: FAIL/WARN/놓침 | 후: FAIL/WARN/놓침 |")
print("|---|---|---|---|---|")
T=[collections.Counter(),collections.Counter()]
for k in b:
    cb=b[k]; ca=a.get(k,collections.Counter()); T[0]+=cb; T[1]+=ca
    print(f"| {k[0]} | {k[1]} | {sum(cb.values())} | {cb['FAIL']}/{cb['WARN']}/{cb['놓침']} | {ca['FAIL']}/{ca['WARN']}/{ca['놓침']} |")
print(f"| 합계 | | {sum(T[0].values())} | {T[0]['FAIL']}/{T[0]['WARN']}/{T[0]['놓침']} | {T[1]['FAIL']}/{T[1]['WARN']}/{T[1]['놓침']} |")
