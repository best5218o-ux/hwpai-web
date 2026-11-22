"""4차 회귀: 2,286건 원본 대 C102 변환본(엔진 C102 + 4차 뒤처리로 새로 변환한 폴더).
사용: python3 -I -B regress4.py <코드 폴더> <결과.jsonl> <조각> <조각 수> [변환본 폴더=/home/claude/c102_2286]"""
import json, os, sys, time, signal
CODE, OUTP, K, N = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
sys.path.insert(0, os.path.join(CODE, "app"))
from hwpai.audit import audit
IN = "/home/claude/v8in"
OUT = sys.argv[5] if len(sys.argv) > 5 else "/home/claude/c102_2286"
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
        conv = os.path.join(OUT, d + ".hwpx")
        t0 = time.time()
        signal.alarm(900)
        try:
            a = audit(os.path.join(IN, d + ".hwp"), conv)
            rec = {"doc": d, "conv": "C102", "verdict": a.verdict, "codes": sorted({x["code"] for x in a.reasons}),
                   "fails": [x["code"] + ": " + x["msg"][:160] for x in a.reasons if x["level"] == "FAIL"][:4],
                   "warns": [x["code"] + ": " + x["msg"][:160] for x in a.reasons if x["level"] == "WARN"][:4],
                   "shape_kinds": a.checks.get("shape_kinds"), "trk": [a.checks.get("tracked_deleted_chars"), a.checks.get("tracked_inserted_chars")]}
        except TO:
            rec = {"doc": d, "verdict": "TIMEOUT", "codes": []}
        except Exception as e:
            rec = {"doc": d, "verdict": "ERROR", "codes": [], "err": f"{type(e).__name__}: {e}"[:200]}
        finally:
            signal.alarm(0)
        rec["sec"] = round(time.time() - t0, 2)
        fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
