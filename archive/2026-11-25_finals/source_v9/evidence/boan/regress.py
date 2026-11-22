"""표본 회귀: 같은 원본·변환본 쌍을 검증기 판(제출본/보완판)으로 각각 검증해 판정을 남긴다.
사용: python3 -I -B regress.py <코드 폴더> <결과.jsonl> <조각 번호> <조각 수>"""
import json, os, sys, time, signal
CODE, OUTP, K, N = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
sys.path.insert(0, os.path.join(CODE, "app"))
from hwpai.audit import audit
IN, OUT = "/home/claude/v8in", "/home/claude/v8out"
done = set()
if os.path.exists(OUTP):
    done = {json.loads(l)["doc"] for l in open(OUTP)}
docs = sorted(f[:-5] for f in os.listdir(OUT) if f.endswith(".hwpx") and os.path.exists(os.path.join(IN, f[:-5] + ".hwp")))
docs = [d for i, d in enumerate(docs) if i % N == K and d not in done]
class TO(Exception): pass
def h(*a): raise TO()
signal.signal(signal.SIGALRM, h)
with open(OUTP, "a") as fo:
    for d in docs:
        t0 = time.time()
        signal.alarm(900)
        try:
            a = audit(os.path.join(IN, d + ".hwp"), os.path.join(OUT, d + ".hwpx"))
            rec = {"doc": d, "verdict": a.verdict, "codes": sorted({x["code"] for x in a.reasons}),
                   "fails": [x["code"] + ": " + x["msg"][:160] for x in a.reasons if x["level"] == "FAIL"][:4],
                   "warns": [x["code"] + ": " + x["msg"][:160] for x in a.reasons if x["level"] == "WARN"][:4]}
        except TO:
            rec = {"doc": d, "verdict": "TIMEOUT", "codes": []}
        finally:
            signal.alarm(0)
        rec["sec"] = round(time.time() - t0, 2)
        fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
