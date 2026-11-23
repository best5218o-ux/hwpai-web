import sys, os, csv, hashlib, collections
def load(d):
    h = {f: hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest() for f in os.listdir(d) if f.endswith('.hwpx')}
    led = {r['원본']: r for r in csv.DictReader(open(os.path.join(d, '이관대장.csv'), encoding='utf-8-sig'))}
    return h, led
hn, ln = load(sys.argv[1])
for d in sys.argv[2:]:
    h, l = load(d)
    same = sum(1 for k, v in hn.items() if h.get(k) == v)
    vd = sum(1 for k in ln if k in l and ln[k]['판정'] == l[k]['판정'] and ln[k]['검증점수'] == l[k]['검증점수'])
    print(os.path.basename(d), '엔진', dict(collections.Counter(r['엔진'] for r in l.values())),
          '| HWPX 바이트 동일', same, '/', len(hn), '| 판정·점수 동일', vd, '/', len(ln),
          '| 판정', dict(collections.Counter(r['판정'] for r in l.values())))
print('기존판 판정', dict(collections.Counter(r['판정'] for r in ln.values())))
