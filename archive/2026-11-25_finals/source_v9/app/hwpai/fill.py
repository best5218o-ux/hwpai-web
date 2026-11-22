"""HWPX 양식 채우기 — AI(또는 사람)가 만든 값을 양식의 칸에 서식을 유지한 채 넣고, 쓴 뒤 되읽어 검증한다.

  python -m hwpai fill 양식.hwpx 값.json [--out 결과.hwpx]
  (양식이 .hwp 면 먼저 엔진으로 HWPX 로 바꾼 뒤 채운다)

값.json 은 {"키": "값", …}. 키를 찾는 순서
  1) 자리표시  본문·칸 글 속 「{{키}}」 → 값으로 바꾼다(같은 글자 모양 유지)
  2) 이름표 칸  표에서 글이 「키」인 칸(공백 무시)의 오른쪽 칸이 비어 있으면 거기에 쓴다
               오른쪽이 없거나 차 있으면 아래 칸이 비어 있을 때 아래에 쓴다
바꾸는 것: 해당 hp:t 의 글, 그 문단의 줄 배치 캐시(hp:linesegarray — 한글이 열 때 다시 계산)
바꾸지 않는 것: 나머지 모든 XML·그림·서식 정의
쓴 뒤 검증: 결과 파일을 hwpai 로 다시 읽어 (가) 값이 들어갔는지 (나) 채운 칸·문단 밖의 글·표·그림이 양식과 같은지 확인한다.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
# 양식의 안내문 칸(「이곳에 … 입력하세요」 등)은 빈 칸처럼 채운다
GUIDE = re.compile(r"(입력|기재|작성|기입|적어|적으)\s*(하세요|해\s*주세요|하십시오|하여\s*주십시오|주세요)")


def _ln(t):
    return t.rsplit("}", 1)[-1]


def _register(xml: bytes):
    for _ev, (pfx, uri) in ET.iterparse(io.BytesIO(xml), events=("start-ns",)):
        try:
            ET.register_namespace(pfx, uri)
        except ValueError:
            pass


def _text(el) -> str:
    return "".join((t.text or "") for t in el.iter() if _ln(t.tag) == "t")


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def _drop_lineseg(p):
    for c in list(p):
        if _ln(c.tag) == "linesegarray":
            p.remove(c)


def _set_cell(tc, value: str, parents):
    """칸의 첫 문단 첫 글 자리에 값을 쓰고 나머지 글은 비운다(글자 모양은 첫 run 의 것 유지)."""
    sub = next((c for c in tc if _ln(c.tag) == "subList"), None)
    if sub is None:
        return False
    paras = [p for p in sub if _ln(p.tag) == "p"]
    if not paras:
        return False
    p0 = paras[0]
    ns = p0.tag.rsplit("}", 1)[0] + "}" if "}" in p0.tag else ""
    runs = [r for r in p0 if _ln(r.tag) == "run"]
    if not runs:
        r = ET.SubElement(p0, ns + "run", {"charPrIDRef": "0"})
        runs = [r]
    first_t = None
    for r in runs:
        for t in [t for t in r if _ln(t.tag) == "t"]:
            if first_t is None:
                first_t = t
            else:
                t.text = ""
                for c in list(t):
                    t.remove(c)
    if first_t is None:
        first_t = ET.Element(ns + "t")
        runs[0].append(first_t)
    for c in list(first_t):
        first_t.remove(c)
    lines = value.split("\n")
    first_t.text = lines[0]
    for extra in lines[1:]:  # 줄바꿈은 hp:lineBreak
        lb = ET.SubElement(first_t, ns + "lineBreak")
        lb.tail = extra
    for p in paras[1:]:  # 칸의 나머지 문단 글은 비운다
        for t in p.iter():
            if _ln(t.tag) == "t":
                t.text = ""
                for c in list(t):
                    t.remove(c)
        _drop_lineseg(p)
    _drop_lineseg(p0)
    return True


def _grid(tbl):
    cells = []
    for tr in [c for c in tbl if _ln(c.tag) == "tr"]:
        for tc in [c for c in tr if _ln(c.tag) == "tc"]:
            a = next((c for c in tc if _ln(c.tag) == "cellAddr"), None)
            s = next((c for c in tc if _ln(c.tag) == "cellSpan"), None)
            if a is None:
                continue
            cells.append((int(a.get("rowAddr", 0)), int(a.get("colAddr", 0)),
                          int(s.get("rowSpan", 1)) if s is not None else 1, int(s.get("colSpan", 1)) if s is not None else 1, tc))
    return cells


def fill_hwpx(src: str, values: dict, dst: str) -> dict:
    with zipfile.ZipFile(src) as z:
        raw = {i.filename: z.read(i.filename) for i in z.infolist()}
    secs = [n for n in raw if re.match(r"Contents/section\d+\.xml$", n)]
    roots = {}
    for n in secs:
        _register(raw[n])
        roots[n] = ET.fromstring(raw[n])
    placed, replaced = {}, []
    # 1 자리표시
    for n, root in roots.items():
        parents = {c: p for p in root.iter() for c in p}
        for t in root.iter():
            if _ln(t.tag) != "t" or not t.text or "{{" not in t.text:
                continue
            def rep(m):
                k = m.group(1).strip()
                if k in values:
                    placed.setdefault(k, []).append(f"{n} 자리표시")
                    return str(values[k])
                return m.group(0)
            new = re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", rep, t.text)
            if new != t.text:
                t.text = new
                p = t
                while p is not None and _ln(p.tag) != "p":
                    p = parents.get(p)
                if p is not None:
                    _drop_lineseg(p)
    # 2 이름표 칸
    for k, v in values.items():
        if k in placed:
            continue
        for n, root in roots.items():
            parents = {c: p for p in root.iter() for c in p}
            done = False
            for tbl in [e for e in root.iter() if _ln(e.tag) == "tbl"]:
                cells = _grid(tbl)
                at = {(r, c): (rs, cs, tc) for r, c, rs, cs, tc in cells}
                for r, c, rs, cs, tc in cells:
                    if _norm(_text(tc)) != _norm(k):
                        continue
                    for tr_, tc_ in ((r, c + cs), (r + rs, c)):
                        tgt = at.get((tr_, tc_))
                        old_txt = _text(tgt[2]) if tgt else ""
                        if tgt and (not _norm(old_txt) or GUIDE.search(old_txt)):
                            if old_txt.strip():
                                replaced.append(old_txt)
                            if _set_cell(tgt[2], str(v), parents):
                                placed.setdefault(k, []).append(f"{n} 표 칸({tr_ + 1}행 {tc_ + 1}열)")
                                done = True
                                break
                    if done:
                        break
                if done:
                    break
            if done:
                break
    tmp = dst + ".part"
    with zipfile.ZipFile(tmp, "w") as o:
        for info in z.infolist():
            n = info.filename
            data = raw[n]
            if n in roots:
                body = ET.tostring(roots[n], encoding="unicode")
                data = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + body).encode("utf-8")
            o.writestr(info, data, compress_type=zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)
    os.replace(tmp, dst)
    missing = [k for k in values if k not in placed]
    return {"placed": placed, "missing": missing, "replaced_guides": replaced}


def verify_fill(form: str, filled: str, values: dict, placed: dict, replaced: list | None = None) -> dict:
    """되읽기 검증: 값이 들어갔는가 + 채운 곳 밖은 양식과 같은가."""
    from . import read
    from .render import plain_text, grid_of
    from .model import walk_tables
    from .grade import suspended
    with suspended():
        a, b = read(form), read(filled)
    tb = plain_text(b)
    present = {k: str(v).split("\n")[0].strip() in tb for k, v in values.items() if k in placed}
    # 양식의 글 중 자리표시·채운 칸을 뺀 나머지가 그대로인지: 양식 글에서 값/자리표시를 지우고 비교
    def strip(s):
        s = re.sub(r"\{\{[^{}]+\}\}", "", s)
        for g in replaced or []:
            s = s.replace(g, "")
        for v in values.values():
            for line in str(v).split("\n"):
                if line.strip():
                    s = s.replace(line.strip(), "")
        return _norm(s)
    same_text = strip(plain_text(a)) == strip(tb)
    ta, tbs = list(walk_tables(a.blocks)), list(walk_tables(b.blocks))
    same_tables = len(ta) == len(tbs) and all(
        sorted((c.row, c.col, c.rowspan, c.colspan) for c in x.cells) == sorted((c.row, c.col, c.rowspan, c.colspan) for c in y.cells)
        for x, y in zip(ta, tbs))
    same_images = sorted(i for i in a.images) == sorted(i for i in b.images)
    ok = all(present.values()) and same_text and same_tables and same_images
    return {"ok": ok, "values_present": present, "rest_text_same": same_text, "tables_structure_same": same_tables,
            "images_same": same_images}


def fill(form: str, values: dict, out: str | None = None, engine_check: bool = True) -> dict:
    src = form
    if not zipfile.is_zipfile(form):  # HWP 양식 → 먼저 HWPX
        from .engines import get_engine
        tmp = os.path.splitext(out or form)[0] + "_양식변환.hwpx"
        with get_engine() as e:
            r = e.convert(form, tmp)
        if not r.get("ok"):
            raise RuntimeError(f"양식 HWPX 변환 실패: {r.get('error')}")
        src = tmp
    out = out or os.path.splitext(form)[0] + "_채움.hwpx"
    res = fill_hwpx(src, values, out)
    res["verify"] = verify_fill(src, out, values, res["placed"], res.get("replaced_guides"))
    if engine_check:  # 다른 구현(rhwp)으로도 열리는지 — 열리면 다시 저장까지 해 본다
        try:
            from .engines import get_engine
            import tempfile
            with get_engine() as e, tempfile.TemporaryDirectory() as d:
                r = e.convert(out, os.path.join(d, "re.hwpx"), timeout=60)
            res["verify"]["engine_reopen"] = bool(r.get("ok"))
            if not r.get("ok"):
                res["verify"]["engine_error"] = r.get("error", "")[:200]
        except Exception as ex:
            res["verify"]["engine_reopen"] = None
            res["verify"]["engine_error"] = f"엔진 없음: {type(ex).__name__}"
    res["out"] = out
    return res
