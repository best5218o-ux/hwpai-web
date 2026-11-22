"""HWPX 서식 보존 텍스트 치환 + 변경 보고서 — AI(또는 사람)가 정한 수정을 원본 서식 그대로 새 HWPX 에 반영한다.

  python -m hwpai replace 문서.hwpx 치환.json [--out 새문서.hwpx]      치환.json = {"찾는 글": "바꿀 글", …}

규칙
  - 원본은 바꾸지 않는다. 결과는 새 파일(기본: 〈이름〉_수정.hwpx, 있으면 (2), (3)…).
  - 한 글 조각(hp:t) 안에서 찾으면 그 자리만 바꾼다(글자 모양 유지).
  - 한 문단에서 글 조각 여럿에 걸친 글은, 걸친 첫 조각의 글자 모양으로 합쳐 바꾼다(변경 보고서에 「여러 조각」으로 표시).
  - 문단을 바꾸면 그 문단의 줄 배치 캐시(linesegarray)만 지운다(한글이 열 때 다시 계산).
  - 바꾼 뒤 결과를 다시 읽어, 바뀐 곳 밖의 글·표 구조·그림이 같은지 확인한다.
  - 변경 보고서(〈결과〉_변경보고서.md)에 위치·이전·이후·못 찾은 항목을 적는다.
HWP 가 들어오면 먼저 엔진으로 HWPX 로 바꾼 뒤 처리한다.
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET

from .fill import _ln, _register, _drop_lineseg, _norm


def _unique(path: str) -> str:
    if not os.path.exists(path):
        return path
    b, e = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{b} ({n}){e}"):
        n += 1
    return f"{b} ({n}){e}"


def _where(el, parents):
    """요소가 속한 위치 설명: 표 칸이면 「표 n 행 r 열 c」, 아니면 본문."""
    cur, path = el, []
    while cur is not None:
        if _ln(cur.tag) == "tc":
            addr = next((c for c in cur if _ln(c.tag) == "cellAddr"), None)
            if addr is not None:
                path.append(f"표 칸({int(addr.get('rowAddr', 0)) + 1}행 {int(addr.get('colAddr', 0)) + 1}열)")
        cur = parents.get(cur)
    return " ▸ ".join(reversed(path)) or "본문"


def replace_hwpx(src: str, mapping: dict, dst: str) -> dict:
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        raw = {i.filename: z.read(i.filename) for i in infos}
    roots = {}
    for n in raw:
        if re.match(r"Contents/section\d+\.xml$", n):
            _register(raw[n])
            roots[n] = ET.fromstring(raw[n])
    changes, found = [], {k: 0 for k in mapping}
    for n, root in roots.items():
        parents = {c: p for p in root.iter() for c in p}
        for pi, p in enumerate([e for e in root.iter() if _ln(e.tag) == "p"]):
            ts = [t for t in p.iter() if _ln(t.tag) == "t"
                  and not any(_ln(a.tag) == "p" and a is not p for a in _ancestors(t, parents, p))]
            if not ts:
                continue
            touched = False
            for k, v in mapping.items():
                if not k:
                    continue
                v = str(v)
                # 1) 한 조각 안
                for t in ts:
                    if t.text and k in t.text:
                        c = t.text.count(k)
                        t.text = t.text.replace(k, v)
                        found[k] += c
                        changes.append({"section": n, "where": _where(p, parents), "before": k, "after": v, "count": c, "multi_run": False})
                        touched = True
                # 2) 여러 조각에 걸침 — 조각 글을 이어 붙여 찾는다. 1)에서 바꾼 글(바꿀 글에 찾는 글이 들어 있는 경우)을 다시 바꾸지 않도록,
                #    한 조각 안에서 온전히 찾아지던 것은 이미 처리됐으므로 조각 경계를 넘는 것만 센다.
                start = 0  # 바꾼 글 안에서 다시 찾지 않도록 바꾼 뒤부터 이어서 찾는다(바꿀 글이 찾는 글을 품어도 끝난다)
                while True:
                    joined = "".join(t.text or "" for t in ts)
                    i = joined.find(k, start)
                    if i < 0:
                        break
                    start = i + len(v)
                    bounds, pos_ = [], 0
                    for t_ in ts:
                        pos_ += len(t_.text or "")
                        bounds.append(pos_)
                    if not any(b_ > i and b_ < i + len(k) for b_ in bounds):
                        continue  # 한 조각 안(1에서 이미 바꿈) — 조각 경계를 넘지 않으면 건너뜀
                    pos, first = 0, True
                    for t in ts:
                        tx = t.text or ""
                        a, b = pos, pos + len(tx)
                        pos = b
                        if b <= i or a >= i + len(k):
                            continue
                        s, e = max(i, a) - a, min(i + len(k), b) - a
                        t.text = tx[:s] + (v if first else "") + tx[e:]
                        first = False
                    found[k] += 1
                    changes.append({"section": n, "where": _where(p, parents), "before": k, "after": v, "count": 1, "multi_run": True})
                    touched = True
            if touched:
                _drop_lineseg(p)
    tmp = dst + ".part"
    with zipfile.ZipFile(tmp, "w") as o:
        for info in infos:
            data = raw[info.filename]
            if info.filename in roots:
                body = ET.tostring(roots[info.filename], encoding="unicode")
                data = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + body).encode("utf-8")
            o.writestr(info, data, compress_type=zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED)
    os.replace(tmp, dst)
    return {"changes": changes, "not_found": [k for k, c in found.items() if c == 0], "counts": found}


def _ancestors(t, parents, stop):
    cur = parents.get(t)
    while cur is not None and cur is not stop:
        yield cur
        cur = parents.get(cur)


def verify_replace(src: str, out: str, mapping: dict, counts: dict) -> dict:
    """되읽기: (가) 바뀐 글이 들어갔는가 (나) 치환 규칙을 원본 글에 적용한 것과 결과 글이 같은가(그 밖은 그대로)
    (다) 표 구조·그림이 같은가."""
    from . import read
    from .render import plain_text
    from .model import walk_tables
    from .grade import suspended
    with suspended():
        a, b = read(src), read(out)
    from .aicheck import _iter_paras

    def exp_of(t):  # 문단마다 같은 규칙(글 조각 안·조각 경계 넘는 글 모두 문단 안에서만)으로 바꾼 기대값
        for k, v in mapping.items():
            if k:
                t = t.replace(k, str(v))
        return t
    exp = _norm("".join(exp_of(p.text or "") for p in _iter_paras(a.blocks)))
    tb = _norm("".join((p.text or "") for p in _iter_paras(b.blocks)))
    same_rest = exp == tb
    xa, xb = list(walk_tables(a.blocks)), list(walk_tables(b.blocks))
    same_tables = len(xa) == len(xb) and all(
        sorted((c.row, c.col, c.rowspan, c.colspan) for c in x.cells) == sorted((c.row, c.col, c.rowspan, c.colspan) for c in y.cells)
        for x, y in zip(xa, xb))
    same_images = sorted(a.images) == sorted(b.images)
    present = {k: (str(v) in plain_text(b)) for k, v in mapping.items() if counts.get(k)}
    ok = same_rest and same_tables and same_images and all(present.values())
    return {"ok": ok, "rest_same_as_expected": same_rest, "tables_structure_same": same_tables, "images_same": same_images,
            "values_present": present}


def report_md(src: str, out: str, res: dict, ver: dict) -> str:
    L = ["# 변경 보고서", "", f"- 원본: {os.path.basename(src)} (바꾸지 않음)", f"- 결과: {os.path.basename(out)}",
         f"- 변경 {sum(c['count'] for c in res['changes'])}곳 · 못 찾은 항목 {len(res['not_found'])}개",
         f"- 되읽기 검증: {'통과' if ver['ok'] else '확인 필요'} (바뀐 곳 밖 글 {'동일' if ver['rest_same_as_expected'] else '다름'}"
         f" · 표 구조 {'동일' if ver['tables_structure_same'] else '다름'} · 그림 {'동일' if ver['images_same'] else '다름'})", "",
         "| 위치 | 이전 | 이후 | 횟수 | 비고 |", "|---|---|---|---|---|"]
    for c in res["changes"]:
        L.append(f"| {c['where']} | {c['before']} | {c['after']} | {c['count']} | {'여러 글 조각에 걸침(첫 조각 글자 모양)' if c['multi_run'] else ''} |")
    if res["not_found"]:
        L += ["", "못 찾은 항목(문서에 없거나 표·개체 경계를 넘는 글): " + ", ".join(res["not_found"])]
    L += ["", "※ 글자 모양이 다른 조각에 걸친 글은 첫 조각의 모양으로 합쳐집니다. 문단의 줄 배치는 한글이 열 때 다시 계산합니다."]
    return "\n".join(L) + "\n"


def replace_text(path: str, mapping: dict, out: str | None = None) -> dict:
    src = path
    if not zipfile.is_zipfile(path):
        from .engines import get_engine
        tmp = os.path.splitext(out or path)[0] + "_변환.hwpx"
        with get_engine() as e:
            r = e.convert(path, tmp)
        if not r.get("ok"):
            raise RuntimeError(f"HWPX 변환 실패: {r.get('error')}")
        src = tmp
    if out and os.path.abspath(out) in (os.path.abspath(path), os.path.abspath(src)):
        raise ValueError("원본을 덮어쓸 수 없습니다.")
    out = _unique(out) if out else _unique(os.path.splitext(path)[0] + "_수정.hwpx")
    # 개선: 바꿀 글이 「찾는 글 + 줄바꿈 + 더할 글」이면 그 문단 뒤에 새 문단으로 넣는다(빠진 문단 채우기).
    # 새 인자·새 도구 없이 기존 치환 규칙(찾는 글 → 바꿀 글)의 줄바꿈 처리만 보강한 것.
    plain, adds = {}, []
    for k, v in mapping.items():
        v = str(v)
        if k and v.startswith(str(k) + "\n") and v[len(str(k)) + 1:].strip():
            prev = str(k)
            for line in v[len(str(k)) + 1:].split("\n"):
                if line.strip():
                    adds.append({"after": prev, "text": line})
                    prev = line
        else:
            plain[k] = v
    res = replace_hwpx(src, plain, out) if plain else {"changes": [], "not_found": [], "counts": {}}
    if not plain:
        import shutil
        shutil.copyfile(src, out)
    ins = {"inserted": [], "not_inserted": []}
    if adds:
        tmp2 = out + ".ins.part"
        ins = insert_hwpx(out, adds, tmp2)
        os.replace(tmp2, out)
        res["not_found"] = list(res["not_found"]) + [x["after"] for x in ins["not_inserted"]]
    mapping = plain
    ver = verify_replace(src, out, mapping, res["counts"]) if plain else {"ok": True, "note": "삽입만 함 — audit 로 다시 검증하세요"}
    rep = os.path.splitext(out)[0] + "_변경보고서.md"
    with open(rep, "w", encoding="utf-8") as f:
        f.write(report_md(src, out, res, ver))
    return {"out": out, "report": rep, "changed": sum(c["count"] for c in res["changes"]) + len(ins["inserted"]),
            "not_found": res["not_found"], "verify": ver, "inserted": ins["inserted"], "not_inserted": ins["not_inserted"]}


def insert_hwpx(src: str, items: list, dst: str) -> dict:
    """표 밖 본문 문단 뒤에 새 문단을 넣는다(검증서의 「빠진 글 채우기」용).

    items = [{"after": 앞 문단 글, "text": 넣을 글}, …]. 앞 문단은 글이 정확히 같은 표 밖 문단이 하나일 때만 쓴다
    (여럿이면 건너뛰고 not_inserted 에 이유를 적는다). 새 문단은 앞 문단의 문단·글자 모양을 그대로 복사한다.
    """
    import copy
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        raw = {i.filename: z.read(i.filename) for i in infos}
    roots = {}
    for n in raw:
        if re.match(r"Contents/section\d+\.xml$", n):
            _register(raw[n])
            roots[n] = ET.fromstring(raw[n])
    done, skipped = [], []
    for it in items:
        after, text = _norm(str(it.get("after", ""))), str(it.get("text", ""))
        cands = []
        for n, root in roots.items():
            parents = {c: p for p in root.iter() for c in p}
            for p in [e for e in root.iter() if _ln(e.tag) == "p"]:
                if any(_ln(a.tag) in ("tc", "tbl", "drawText", "subList") for a in _ancestors(p, parents, root)):
                    continue  # 표·글상자 안은 건드리지 않는다
                ts = [t for t in p.iter() if _ln(t.tag) == "t"]
                if ts and _norm("".join(t.text or "" for t in ts)) == after:
                    cands.append((n, root, parents, p, ts))
        if len(cands) != 1:
            skipped.append({"after": it.get("after"), "text": text, "reason": "앞 문단을 찾지 못함" if not cands else f"앞 문단이 {len(cands)}곳에 있어 한 곳으로 정할 수 없음"})
            continue
        n, root, parents, p, ts = cands[0]
        new = copy.deepcopy(p)
        nts = [t for t in new.iter() if _ln(t.tag) == "t"]
        for i, t in enumerate(nts):
            t.text = text if i == 0 else ""
        _drop_lineseg(new)
        par = parents[p]
        par.insert(list(par).index(p) + 1, new)
        done.append({"section": n, "after": it.get("after"), "text": text})
    tmp = dst + ".part"
    with zipfile.ZipFile(tmp, "w") as o:
        for info in infos:
            data = raw[info.filename]
            if info.filename in roots:
                body = ET.tostring(roots[info.filename], encoding="unicode")
                data = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + body).encode("utf-8")
            o.writestr(info, data, compress_type=zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED)
    os.replace(tmp, dst)
    return {"inserted": done, "not_inserted": skipped}
