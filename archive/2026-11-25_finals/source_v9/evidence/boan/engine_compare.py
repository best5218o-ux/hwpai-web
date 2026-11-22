"""엔진 판 대조 회귀: 같은 원본을 같은 hwpai 코드로 두 엔진(core A·B)에서 변환해 HWPX 안 파일을 비교한다.
같으면 둘 다 지우고, 다르면 남긴다. 사용: python3 -I -B conv2.py <coreA> <coreB> <출력 폴더> <결과.jsonl> <조각> <조각 수>"""
import json, os, sys, time, zipfile
sys.path.insert(0, "/home/claude/hwpai_v9/app")
from hwpai.engines import get_engine
from hwpai import viewtext as vt
from hwpai.audit import audit
import signal
class TO(Exception): pass
def _h(*a): raise TO()
signal.signal(signal.SIGALRM, _h)
def aud(src, p):
    signal.alarm(900)
    try:
        a = audit(src, p); return {"v": a.verdict, "codes": sorted({x["code"] for x in a.reasons})}
    except TO:
        return {"v": "TIMEOUT"}
    except Exception as e:
        return {"v": "ERROR", "err": str(e)[:100]}
    finally:
        signal.alarm(0)
CA, CB, OUTD, LOG, K, N = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
IN = "/home/claude/v8in"
os.makedirs(OUTD, exist_ok=True)
done = {json.loads(l)["doc"] for l in open(LOG)} if os.path.exists(LOG) else set()
docs = sorted(f[:-4] for f in os.listdir(IN) if f.endswith(".hwp"))
docs = [d for i, d in enumerate(docs) if i % N == K and d not in done]
os.environ["HWPAI_RHWP_CORE"] = CA; ea = get_engine("rhwp-wasm")
os.environ["HWPAI_RHWP_CORE"] = CB; eb = get_engine("rhwp-wasm")
with open(LOG, "a") as fo:
    for d in docs:
        src = os.path.join(IN, d + ".hwp"); pa = os.path.join(OUTD, d + ".A.hwpx"); pb = os.path.join(OUTD, d + ".B.hwpx")
        t = time.time(); ra = vt.convert_hwp(ea, src, pa, timeout=300); ta = time.time() - t
        t = time.time(); rb = vt.convert_hwp(eb, src, pb, timeout=300); tb = time.time() - t
        diff = None
        if ra.get("ok") and rb.get("ok"):
            try:
                za, zb = zipfile.ZipFile(pa), zipfile.ZipFile(pb)
                na, nb = set(za.namelist()), set(zb.namelist())
                diff = sorted((na ^ nb) | {n for n in na & nb if za.read(n) != zb.read(n)})
            except Exception as e:
                diff = ["<zip error " + str(e)[:80] + ">"]
        audA = aud(src, pa) if ra.get("ok") else None
        audB = (audA if diff == [] else aud(src, pb)) if rb.get("ok") else None
        if diff == []:
            for p in (pa, pb):
                try: os.remove(p)
                except OSError: pass
        fo.write(json.dumps({"doc": d, "okA": bool(ra.get("ok")), "okB": bool(rb.get("ok")), "diff": diff, "audA": audA, "audB": audB,
                             "errA": (ra.get("error") or "")[:160], "errB": (rb.get("error") or "")[:160],
                             "secA": round(ta, 2), "secB": round(tb, 2)}, ensure_ascii=False) + "\n"); fo.flush()
ea.close(); eb.close()
