import json, os, sys, signal
sys.path.insert(0, sys.argv[1] + "/app")
from hwpai.audit import audit
O, C, OUTP, K, N = "/home/claude/heldout/원본", sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
docs = sorted(f[:-5] for f in os.listdir(C) if f.endswith(".hwpx") and os.path.exists(os.path.join(O, f[:-5] + ".hwp")))
docs = [d for i, d in enumerate(docs) if i % N == K]
class TO(Exception): pass
def h(*a): raise TO()
signal.signal(signal.SIGALRM, h)
with open(OUTP, "w") as fo:
    for d in docs:
        signal.alarm(900)
        try:
            a = audit(os.path.join(O, d + ".hwp"), os.path.join(C, d + ".hwpx"))
            rec = {"doc": d, "verdict": a.verdict, "codes": sorted({x["code"] for x in a.reasons}), "msgs": [x["code"] + ": " + x["msg"][:140] for x in a.reasons][:4]}
        except TO:
            rec = {"doc": d, "verdict": "TIMEOUT", "codes": []}
        except Exception as e:
            rec = {"doc": d, "verdict": "ERROR", "codes": [], "err": str(e)[:150]}
        finally:
            signal.alarm(0)
        fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
