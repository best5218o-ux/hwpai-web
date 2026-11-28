"""웹판 묶음 다시 만들기 — 본체(hwpai_v9/app) 코드·엔진을 웹판에 맞춘다.
  python3 tools/build.py 〈본체 app 폴더〉
1) py/hwpai 의 파일을 본체 같은 이름 파일로 덮고(본체에 새로 생긴 explain.py 는 추가)
2) 엔진(rhwp.js·rhwp_bg.wasm·package.json)을 vendor/rhwp-core 로 복사하고
3) js/py_bundle.js 와 payload/(file:// 용 gzip+base64 조각)·payload/manifest.js 를 다시 만든다.
"""
import base64, gzip, hashlib, json, os, shutil, sys

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/hwpai_v9/app"
CHUNK = 6291491

# 1) py 소스
extra = {"hwpai/explain.py", "hwpai/hwp3.py", "hwpai/hml.py", "hwpai/hml1.py"}
for dirpath, _, files in os.walk(os.path.join(W, "py", "hwpai")):
    for f in files:
        if f.endswith(".py"):
            rel = os.path.relpath(os.path.join(dirpath, f), os.path.join(W, "py")).replace(os.sep, "/")
            src = os.path.join(APP, rel)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(W, "py", rel))
for rel in extra:
    src = os.path.join(APP, rel)
    if os.path.isfile(src):
        shutil.copyfile(src, os.path.join(W, "py", rel))

# 1-2) 자료 파일(글자 부호 표·글꼴 표) — 일꾼은 py 묶음을 글로만 쓰므로 base64 로 담은 모듈을 만들고 webbridge 가 풀어 쓴다
DATA = ("hwp3_hangul_map.bin", "old_font_catalog.json", "fontmap_ko.json")
with open(os.path.join(W, "py", "hwpai_webdata.py"), "w", encoding="utf-8") as f:
    f.write('"""자동 생성(tools/build.py) — hwpai 패키지 자료 파일(base64)"""\nFILES = {\n')
    for n in DATA:
        src = os.path.join(APP, "hwpai", n)
        if os.path.isfile(src):
            f.write(f"    {n!r}: {base64.b64encode(open(src, 'rb').read()).decode()!r},\n")
    f.write("}\n")

# 2) 엔진
for n in ("rhwp.js", "rhwp_bg.wasm", "package.json"):
    shutil.copyfile(os.path.join(APP, "vendor", "rhwp-core", n), os.path.join(W, "vendor", "rhwp-core", n))

# 3) py_bundle
old = open(os.path.join(W, "js", "py_bundle.js"), encoding="utf-8").read()
order = list(json.loads(old[old.index("window.HWPAI_PY=") + len("window.HWPAI_PY="):].rstrip().rstrip(";")).keys())
files = {}
for dirpath, _, fs in os.walk(os.path.join(W, "py")):
    for f in fs:
        if f.endswith(".py"):
            rel = os.path.relpath(os.path.join(dirpath, f), os.path.join(W, "py")).replace(os.sep, "/")
            files[rel] = open(os.path.join(dirpath, f), encoding="utf-8").read()
keys = [k for k in order if k in files] + sorted(k for k in files if k not in order)
open(os.path.join(W, "js", "py_bundle.js"), "w", encoding="utf-8").write(
    "/* 자동 생성(tools/build.py) — py/ 소스 묶음 */\nwindow.HWPAI_PY=" + json.dumps({k: files[k] for k in keys}, ensure_ascii=False) + ";\n")

# payload: 엔진 세 파일만 다시(pyodide 쪽은 그대로)
man = open(os.path.join(W, "payload", "manifest.js"), encoding="utf-8").read()
lst = json.loads(man[man.index("=") + 1:].strip().rstrip(";"))
engine = {"rhwp.js": "rhwp.js", "rhwp_bg.wasm": "rhwp_bg.wasm", "rhwp-package.json": "package.json"}
for m in lst:
    if m["name"] in engine:
        for c in m["chunks"]:
            os.remove(os.path.join(W, c))
        raw = open(os.path.join(W, "vendor", "rhwp-core", engine[m["name"]]), "rb").read()
        gz = gzip.compress(raw, 9, mtime=0)
        b64 = base64.b64encode(gz).decode()
        parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)] or [""]
        m["raw"], m["gz"], m["sha256"], m["chunks"] = len(raw), len(gz), hashlib.sha256(raw).hexdigest(), []
        for i, p in enumerate(parts):
            name = f"payload/p_{m['name']}_{i:02d}.js"
            open(os.path.join(W, name), "w", encoding="ascii").write(f'__hwpaiChunk("{m["name"]}",{i},"{p}");\n')
            m["chunks"].append(name)
open(os.path.join(W, "payload", "manifest.js"), "w", encoding="utf-8").write("window.HWPAI_PAYLOAD=" + json.dumps(lst, ensure_ascii=False) + ";\n")
print("ok", len(keys), "py files")
