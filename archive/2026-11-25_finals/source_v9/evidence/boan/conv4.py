"""같은 hwpai 코드(v9)로 지정 엔진 core 로 원본 폴더를 변환. 사용: conv.py <core> <in> <out> <K> <N>"""
import os, sys, json, time
sys.path.insert(0, "/home/claude/hwpai_v9/app")
CORE, IN, OUT, K, N = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
os.environ["HWPAI_RHWP_CORE"] = CORE
from hwpai.engines import get_engine
from hwpai import viewtext as vt
e = get_engine("rhwp-wasm")
os.makedirs(OUT, exist_ok=True)
docs = sorted(f[:-4] for f in os.listdir(IN) if f.endswith(".hwp"))
docs = [d for i, d in enumerate(docs) if i % N == K and not os.path.exists(os.path.join(OUT, d + ".hwpx"))]
bad = 0
for d in docs:
    r = vt.convert_hwp(e, os.path.join(IN, d + ".hwp"), os.path.join(OUT, d + ".hwpx"), timeout=300)
    if not r.get("ok"):
        bad += 1; print("FAIL", d, (r.get("error") or "")[:120], flush=True)
print("done", len(docs), "bad", bad)
