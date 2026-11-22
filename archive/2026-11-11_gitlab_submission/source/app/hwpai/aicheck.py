"""AI 친화도 점검 — 문서를 AI 가 읽고 쓰기 좋은 구조인지 알려 주는 보고서(변환 결과 자체는 바꾸지 않는다).

  python -m hwpai aicheck 문서.hwp|hwpx [--out 폴더]   →  AI친화도_점검.md / .json / .html

점검 항목(행정안전부 「AI 친화 행정문서 작성 가이드라인」의 취지에 맞춘 자체 항목. 가이드라인 원문의 항목 번호와의 1:1 대응은
원문 확인 후 표시한다 — 지금은 번호를 붙이지 않는다)
  1 표 병합 칸 과다        병합 칸이 많은 표는 칸 단위로 읽을 때 값이 어긋나기 쉽다
  2 표 머리글 행 없음      첫 행이 머리글로 표시되지 않은 표
  3 표 안의 표(중첩)       칸 안에 표가 또 있으면 평탄화가 어렵다
  4 그림 대체 글 없음      그림에 설명 글(shapeComment)이 없으면 AI 가 내용을 알 수 없다
  5 개체(글상자) 안 글     본문 흐름 밖에 있어 읽는 순서가 불확실하다
  6 연속 빈 문단           줄 간격을 빈 문단으로 맞춘 곳(3개 이상 연속)
  7 개요(제목) 서식 미사용 긴 문서인데 제목 스타일이 없으면 구조를 알 수 없다
  8 수동 글머리 기호       ○·-·※ 를 글자로 직접 친 문단(자동 번호·글머리표가 아님)
결과는 항목별 개수·위치·권고와 한 줄 판정(양호/주의/개선 권장). 점수는 매기지 않는다(근거 없는 숫자를 만들지 않기 위해).
"""
from __future__ import annotations

import html
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

from .model import Paragraph, Table, TextBox, Note, HeaderFooter, walk_tables

_BULLET = re.compile(r"^\s*[○●◦•▪■□◆◇※\-–ㆍ·]\s+\S")


def _ln(t):
    return t.rsplit("}", 1)[-1]


def _iter_paras(blocks):
    for b in blocks:
        if isinstance(b, Paragraph):
            yield b
        elif isinstance(b, Table):
            for c in b.cells:
                yield from _iter_paras(c.blocks)
        elif isinstance(b, (TextBox, Note, HeaderFooter)):
            yield from _iter_paras(b.blocks)


def _count_kind(blocks, cls):
    n = 0
    for b in blocks:
        if isinstance(b, cls):
            n += 1
        if isinstance(b, Table):
            for c in b.cells:
                n += _count_kind(c.blocks, cls)
        elif isinstance(b, (TextBox, Note, HeaderFooter)):
            n += _count_kind(b.blocks, cls)
    return n


def _pics_without_alt(hwpx: str):
    tot = no = 0
    with zipfile.ZipFile(hwpx) as z:
        for n in z.namelist():
            if re.match(r"Contents/section\d+\.xml$", n):
                root = ET.fromstring(z.read(n))
                for pic in (e for e in root.iter() if _ln(e.tag) == "pic"):
                    tot += 1
                    sc = next((c for c in pic.iter() if _ln(c.tag) == "shapeComment"), None)
                    if sc is None or not "".join(sc.itertext()).strip():
                        no += 1
    return tot, no


def check(path: str) -> dict:
    from . import read
    from .render import plain_text
    src, tmp = path, None
    if not zipfile.is_zipfile(path):  # HWP: 변환본 기준(그림 설명은 HWPX 쪽에서 읽는다)
        import tempfile
        from .engines import get_engine
        tmp = tempfile.mkdtemp(prefix="hwpai_aic_")
        src = os.path.join(tmp, "x.hwpx")
        with get_engine() as e:
            r = e.convert(path, src)
        if not r.get("ok"):
            raise RuntimeError(f"변환 실패: {r.get('error')}")
    try:
        doc = read(src)
        tabs = list(walk_tables(doc.blocks))
        paras = list(_iter_paras(doc.blocks))
        items = []

        def add(code, title, count, total, where, advice, level):
            items.append({"code": code, "title": title, "count": count, "of": total, "where": where[:8], "advice": advice, "level": level})

        merged = [(t, sum(1 for c in t.cells if c.rowspan > 1 or c.colspan > 1)) for t in tabs]
        heavy = [(t.id, m, len(t.cells)) for t, m in merged if t.cells and m / len(t.cells) > 0.3 and m >= 3]
        add(1, "표 병합 칸 과다(병합 칸이 30% 초과)", len(heavy), len(tabs),
            [f"표 {i}: 병합 {m}/{n}칸" for i, m, n in heavy],
            "가능하면 병합을 줄이고 머리글을 칸마다 적으세요. 병합된 표는 hwpai 가 칸을 펼쳐 읽지만 사람이 만든 요약은 어긋날 수 있습니다.", "주의")
        nohead = [t.id for t in tabs if t.cells and not any(c.is_header for c in t.cells) and t.nrows >= 2]
        add(2, "표 머리글 행 없음", len(nohead), len(tabs), [f"표 {i}" for i in nohead],
            "첫 행을 머리글 행으로 지정하면 AI 가 열 이름을 인식합니다.", "참고")
        nested = [t.id for t in tabs if any(any(isinstance(b, Table) for b in c.blocks) for c in t.cells)]
        add(3, "표 안의 표(중첩)", len(nested), len(tabs), [f"표 {i}" for i in nested],
            "표 속 표는 평탄화하면 칸 관계가 흐려집니다. 가능하면 한 겹 표로 나누세요.", "주의")
        ptot, pno = _pics_without_alt(src)
        add(4, "그림 대체 글(설명) 없음", pno, ptot, [f"그림 {pno}/{ptot}개 설명 없음"] if pno else [],
            "그림 설명(대체 텍스트)을 적으면 AI 가 그림의 뜻을 알 수 있습니다. 그림이 글을 담고 있다면 본문에도 적으세요.", "주의")
        tb = _count_kind(doc.blocks, TextBox)
        add(5, "개체(글상자) 안 글", tb, None, [], "글상자 속 글은 본문 흐름 밖이라 읽는 순서가 불확실합니다. 핵심 내용은 본문에 두세요.", "참고")
        run, worst, blanks = 0, 0, 0
        for p in paras:
            if not (p.text or "").strip():
                run += 1
                worst = max(worst, run)
                if run == 3:
                    blanks += 1
            else:
                run = 0
        add(6, "연속 빈 문단(3개 이상)", blanks, None, [f"가장 긴 연속 {worst}개"] if blanks else [],
            "줄 간격은 문단 간격 설정으로 맞추세요. 빈 문단은 AI 가 내용으로 오인할 수 있습니다.", "참고")
        nchar = len(plain_text(doc))
        outl = sum(1 for p in paras if p.outline)
        add(7, "개요(제목) 서식 미사용", 1 if (nchar > 3000 and outl == 0) else 0, None,
            [f"{nchar}자인데 개요 수준 문단 0개"] if (nchar > 3000 and outl == 0) else [],
            "제목에 개요 스타일을 쓰면 AI 가 문서 구조(장·절)를 알 수 있습니다.", "주의")
        manual = [p.text.strip()[:20] for p in paras if _BULLET.match(p.text or "")]
        add(8, "수동 글머리 기호(글자로 친 ○·-·※)", len(manual), len(paras), manual[:5],
            "자동 글머리표·번호 서식을 쓰면 목록 구조가 보존됩니다. 공문서 관행상 흔해 점검 결과는 참고로만 봅니다.", "참고")
        n_warn = sum(1 for i in items if i["level"] == "주의" and i["count"])
        n_note = sum(1 for i in items if i["level"] == "참고" and i["count"])
        verdict = "양호" if not n_warn and n_note <= 1 else ("주의" if n_warn <= 2 else "개선 권장")
        return {"file": os.path.basename(path), "verdict": verdict, "caution_items": n_warn, "note_items": n_note, "items": items,
                "basis": "행정안전부 AI 친화 행정문서 가이드라인의 취지에 맞춘 자체 항목(원문 항목 번호 대응은 원문 확인 후)"}
    finally:
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


def to_markdown(r: dict) -> str:
    L = [f"# AI 친화도 점검 — {r['file']}", "", f"- 판정: **{r['verdict']}** (주의 항목 {r['caution_items']}개 · 참고 항목 {r['note_items']}개)",
         f"- 근거: {r['basis']}", "", "| # | 항목 | 해당 | 위치 | 권고 |", "|---|---|---|---|---|"]
    for i in r["items"]:
        cnt = f"{i['count']}" + (f"/{i['of']}" if i["of"] is not None else "")
        L.append(f"| {i['code']} | {i['title']} ({i['level']}) | {cnt} | {'; '.join(i['where']) or '-'} | {i['advice'] if i['count'] else '해당 없음'} |")
    return "\n".join(L) + "\n"


def to_html(r: dict) -> str:
    rows = "".join(
        f"<tr class=\"{'hit' if i['count'] else ''}\"><td>{i['code']}</td><td>{html.escape(i['title'])} <small>({i['level']})</small></td>"
        f"<td>{i['count']}{'/' + str(i['of']) if i['of'] is not None else ''}</td><td>{html.escape('; '.join(i['where']) or '-')}</td>"
        f"<td>{html.escape(i['advice']) if i['count'] else '해당 없음'}</td></tr>" for i in r["items"])
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>AI 친화도 점검</title><style>:root{{color-scheme:light dark}}body{{font:15px system-ui,'Malgun Gothic',sans-serif;margin:24px;max-width:980px}}"
            f"table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #8884;padding:6px 8px;vertical-align:top}}tr.hit{{background:#f5a62322}}</style>"
            f"<h1>AI 친화도 점검 — {html.escape(r['file'])}</h1><p>판정 <b>{r['verdict']}</b> · 주의 {r['caution_items']} · 참고 {r['note_items']}</p>"
            f"<table><tr><th>#</th><th>항목</th><th>해당</th><th>위치</th><th>권고</th></tr>{rows}</table><p><small>{html.escape(r['basis'])}</small></p>")


def cmd_aicheck(a):
    r = check(a.path)
    out = a.out or os.path.dirname(os.path.abspath(a.path))
    os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, "AI친화도_점검")
    with open(stem + ".md", "w", encoding="utf-8") as f:
        f.write(to_markdown(r))
    with open(stem + ".json", "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    with open(stem + ".html", "w", encoding="utf-8") as f:
        f.write(to_html(r))
    print(to_markdown(r))
    print("저장:", stem + ".md / .json / .html")
    return 0
