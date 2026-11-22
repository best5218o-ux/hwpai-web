"""3차 변이 시험 표본 목록: 2,286건 변환본(v8out)의 도형 종류·변경 추적 표식 개수를 세어 기존 census.json 에 붙인다.
사용: python3 -I census3.py <census.json> <출력 census3.json>"""
import json, os, re, sys, zipfile
OUT, IN = "/home/claude/v8out", "/home/claude/v8in"
KINDS = ["rect", "line", "connectLine", "ellipse", "polygon", "container", "ole"]
c = json.load(open(sys.argv[1]))
for d, v in c.items():
    p = os.path.join(OUT, d + ".hwpx")
    if not os.path.exists(p):
        continue
    z = zipfile.ZipFile(p)
    s = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()
                if n.startswith("Contents/section") or n.startswith("Contents/masterpage"))
    for k in KINDS:
        v[k] = len(re.findall(r"<hp:%s[ >/]" % k, s))
    v["trk"] = s.count("<hp:deleteBegin") + s.count("<hp:insertBegin")
json.dump(c, open(sys.argv[2], "w"))
