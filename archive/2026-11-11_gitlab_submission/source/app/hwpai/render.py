"""문서 모델 → 마크다운 / JSON / CSV / RAG 청크."""
from __future__ import annotations

import csv
import io
import json
import os
import re

from .model import (Document, Equation, HeaderFooter, Image, Note, Paragraph, Table, TextBox,
                    table_grid, walk_tables)


# ---------- 블록 → 글 ----------
def is_tag_table(t) -> bool:
    """글 한 줄짜리 꼬리표 표(분야 칸의 「국정과제」「기관중점」 같은 색 딱지)는 셀 글에 바로 넣는다.
    한 칸·글만·20자 이하. 이런 표를 「[표N 참조]」로 빼면 한글 화면과 어긋난다 (2026-11-09, 0242 확인)."""
    cells = list(getattr(t, "cells", []) or [])
    if len(cells) != 1:
        return False
    blocks = cells[0].blocks
    if any(not isinstance(x, Paragraph) for x in blocks):
        return False
    s = " ".join(x.text.replace("\n", " ") for x in blocks).strip()
    return 0 < len(s) <= 20


def _tag_text(t) -> str:
    return " ".join(x.text.replace("\n", " ") for x in t.cells[0].blocks).strip()


def _flat_text(blocks, sep: str, nested_ref: bool = True) -> str:
    """셀·글상자 속 블록을 한 덩어리 글로. 표 속 표는 [표N 참조]."""
    parts = []
    for b in blocks:
        if isinstance(b, Paragraph):
            parts.append(b.text.replace("\n", sep))
        elif isinstance(b, Table):
            parts.append(_tag_text(b) if is_tag_table(b) else f"[표{b.id} 참조]")
        elif isinstance(b, Image):
            parts.append(f"[그림:{b.name}]" + (f" {b.caption}" if b.caption else ""))
        elif isinstance(b, Equation):
            parts.append(f"${b.script}$")
        elif isinstance(b, Note):
            parts.append(f"[^{b.number}]")
        elif isinstance(b, TextBox):
            parts.append(_flat_text(b.blocks, sep))
        # 머리말·꼬리말은 셀 글에 넣지 않는다
    return sep.join(p for p in parts if p)


def _nested_tables(blocks) -> list:
    """글상자·머리말·꼬리말 속(글상자 안 글상자 포함)의 표 — 꼬리표 표는 글에 이미 들어가므로 뺀다. 표 칸 속 표는 호출한 쪽이 따로 다룬다."""
    out = []
    for b in blocks:
        if isinstance(b, Table):
            if not is_tag_table(b):
                out.append(b)
        elif isinstance(b, TextBox):
            out.extend(_nested_tables(b.blocks))
    return out


def cell_text(cell, sep: str = " ") -> str:
    return _flat_text(cell.blocks, sep)


def grid_of(t: Table, sep: str = " ", fill_cols: bool = True, fill_rows: bool = True) -> list[list[str]]:
    return table_grid(t, lambda c: cell_text(c, sep), fill_cols, fill_rows)


def _md_escape(s: str) -> str:
    return (s or " ").replace("|", "\\|").replace("\n", "<br>")


def _table_html(t: Table) -> str:
    """병합 셀이 있는 표: rowspan·colspan 을 살려 HTML 표로 낸다 (글을 복제하지 않는다)."""
    import html as _h
    rows: dict[int, list[str]] = {}
    for c in sorted(t.cells, key=lambda c: (c.row, c.col)):
        tag = "th" if c.is_header else "td"
        attrs = (f' rowspan="{c.rowspan}"' if c.rowspan > 1 else "") + (f' colspan="{c.colspan}"' if c.colspan > 1 else "")
        body = _h.escape(cell_text(c, "\n"), quote=False).replace("\n", "<br>")
        rows.setdefault(c.row, []).append(f"<{tag}{attrs}>{body}</{tag}>")
    head = "**[표%d]%s**" % (t.id, (" " + t.caption) if t.caption else "")
    body = "\n".join(f"<tr>{''.join(rows[r])}</tr>" for r in sorted(rows))
    return head + "\n\n<table>\n" + body + "\n</table>"


def table_markdown(t: Table, html_merge: bool = True) -> str:
    if html_merge and any(c.rowspan > 1 or c.colspan > 1 for c in t.cells):
        return _table_html(t)
    g = grid_of(t, "<br>", fill_cols=False, fill_rows=False)
    if not g or not g[0]:
        return ""
    head = "**[표%d]%s**" % (t.id, (" " + t.caption) if t.caption else "")
    lines = ["| " + " | ".join(_md_escape(x) for x in g[0]) + " |", "|" + "---|" * len(g[0])]
    lines += ["| " + " | ".join(_md_escape(x) for x in r) + " |" for r in g[1:]]
    return head + "\n\n" + "\n".join(lines)


def table_records(t: Table) -> list[dict]:
    """첫 행을 머리글로 보고 행마다 {열이름: 값} 으로 푼다 (검색·DB 투입용)."""
    g = grid_of(t, " ")
    if len(g) < 2 or len(g[0]) < 2:
        return []
    heads = [h.strip() or f"열{i + 1}" for i, h in enumerate(g[0])]
    return [{h: v for h, v in zip(heads, row)} for row in g[1:] if any(x.strip() for x in row)]


# ---------- 마크다운 ----------
def to_markdown(doc: Document, with_headerfooter: bool = True) -> str:
    out: list[str] = []
    hf_seen: set[str] = set()

    def emit(blocks):
        for b in blocks:
            if isinstance(b, Paragraph):
                if b.outline:
                    out.append("#" * min(b.outline + 1, 6) + " " + b.text.replace("\n", " "))
                else:
                    out.append(b.text)
            elif isinstance(b, Table):
                md = table_markdown(b)
                if md:
                    out.append(md)
                for c in b.cells:           # 표 속 표는 바깥 표 뒤에 따로
                    emit([x for x in c.blocks if isinstance(x, Table) and not is_tag_table(x)])
                for c in b.cells:           # 셀 안 각주 본문
                    emit([x for x in c.blocks if isinstance(x, Note)])
            elif isinstance(b, Image):
                alt = b.caption or "그림"
                out.append(f"![{alt}](images/{b.name})")
            elif isinstance(b, Equation):
                out.append(f"$$ {b.script} $$")
            elif isinstance(b, Note):
                txt = _flat_text(b.blocks, " ")
                tag = f"[^{b.number}]" if b.kind == "footnote" else f"[^미{b.number}]"
                out.append(f"{tag}: {txt}")
            elif isinstance(b, TextBox):
                txt = _flat_text(b.blocks, "  \n")
                if txt:
                    out.append("> " + txt.replace("\n", "\n> "))
                emit(_nested_tables(b.blocks))      # C71: 글상자 속 표 내용도 낸다([표N 참조]만 남기지 않는다)
                emit([x for x in b.blocks if isinstance(x, Note)])   # C80: 글상자 속 각주·미주 본문도 낸다
            elif isinstance(b, HeaderFooter):
                if with_headerfooter:
                    txt = _flat_text(b.blocks, " ")
                    key = b.role + txt
                    if txt and key not in hf_seen:
                        hf_seen.add(key)
                        out.append(f"<!-- {'머리말' if b.role == 'header' else '꼬리말'}: {txt} -->")
                        emit(_nested_tables(b.blocks))  # C71: 머리말·꼬리말 속 표 내용(같은 머리말은 한 번만)

    emit(doc.blocks)
    return "\n\n".join(x for x in out if x)


def squash_latent_rows(t: Table) -> tuple:
    """셀이 하나도 시작하지 않는 「잠재 행」(위 칸의 세로 병합에 모두 덮인 행)을 격자에서 뺀 표를 돌려준다.
    HWP 는 행 수(rowCount)에 이 행을 세지만, HWPX 는 tr 에 실제 칸이 있는 행만 쓴다 — 같은 표의 두 표기이므로 비교 전에 양쪽을 같은 모양으로 맞춘다(C94, 검증기 정정)."""
    import dataclasses
    starts = {c.row for c in t.cells}
    latent = [r for r in range(t.nrows) if r not in starts]
    if not latent:
        return t, 0
    def newrow(r):
        return r - sum(1 for x in latent if x < r)
    cells = []
    for c in t.cells:
        end = c.row + max(c.rowspan, 1)
        span = sum(1 for r in range(c.row, end) if r in starts)
        cells.append(dataclasses.replace(c, row=newrow(c.row), rowspan=max(span, 1)))
    return dataclasses.replace(t, nrows=t.nrows - len(latent), cells=cells), len(latent)


def plain_text(doc: Document) -> str:
    """서식 표시 없는 순수 글 (평가용). 표는 행 단위로 칸을 탭으로 이어 붙인다."""
    out: list[str] = []

    def emit(blocks):
        for b in blocks:
            if isinstance(b, Paragraph):
                out.append(b.text)
            elif isinstance(b, Table):
                for row in grid_of(squash_latent_rows(b)[0], " "):
                    out.append("\t".join(row))
                for c in b.cells:
                    emit([x for x in c.blocks if (isinstance(x, Table) and not is_tag_table(x)) or isinstance(x, Note)])
            elif isinstance(b, (Note, TextBox)):
                emit(b.blocks)
            elif isinstance(b, Equation):
                out.append(b.script)
            elif isinstance(b, Image) and b.caption:
                out.append(b.caption)

    emit(doc.blocks)
    return "\n".join(out)


# ---------- 파일로 저장 ----------
def write_outputs(doc: Document, outdir: str, name: str = "본문") -> dict:
    os.makedirs(outdir, exist_ok=True)
    md = to_markdown(doc)
    mdp = os.path.join(outdir, f"{name}.md")
    with open(mdp, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    with open(os.path.join(outdir, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(doc.to_dict(), f, ensure_ascii=False, indent=1)
    tabs = list(walk_tables(doc.blocks))
    if tabs:
        d = os.path.join(outdir, "tables")
        os.makedirs(d, exist_ok=True)
        for t in tabs:
            with open(os.path.join(d, f"표{t.id:03d}.csv"), "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(grid_of(t, "\n"))
    nimg = 0
    for nm in doc.images:
        data = doc.image_bytes(nm)
        if data:
            os.makedirs(os.path.join(outdir, "images"), exist_ok=True)
            with open(os.path.join(outdir, "images", nm), "wb") as f:
                f.write(data)
            nimg += 1
    chunks = to_chunks(doc)
    with open(os.path.join(outdir, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return {"markdown": mdp, "tables": len(tabs), "images": nimg, "chunks": len(chunks), "chars": len(md)}


# ---------- RAG 청크 ----------
_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_HEADING_PATTERNS = [
    (re.compile(r"^[" + _ROMAN + r"]\s*[\.\s]"), 1),
    (re.compile(r"^제\s*\d+\s*[장편]"), 1),
    (re.compile(r"^\d{1,2}\s*\.\s+\S"), 2),
    (re.compile(r"^[□■▣]\s*\S"), 3),
]


def _heading_level(p: Paragraph) -> int:
    if p.outline:
        return p.outline
    t = p.text.strip()
    if 0 < len(t) <= 60 and "\n" not in t:
        for rx, lv in _HEADING_PATTERNS:
            if rx.match(t):
                return lv
    return 0


def to_chunks(doc: Document, max_chars: int = 1500) -> list[dict]:
    """제목 경로가 붙은 검색용 조각. 표는 독립 조각(행 레코드 포함)."""
    chunks: list[dict] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []
    hf_seen: set[str] = set()
    pend: list = []   # C75: 본문 없이 제목만 있는 항목(바로 다음에 다른 제목이 오는 번호 문단 등)이 조각에서 사라지지 않게 한다

    def hp():
        return [t for _, t in path]

    def emit_pending():
        if pend:
            hpath, txt = pend[0]
            pend.clear()
            chunks.append({"id": len(chunks) + 1, "type": "heading", "heading_path": hpath, "text": txt})

    def flush():
        txt = "\n".join(buf).strip()
        buf.clear()
        if txt:
            chunks.append({"id": len(chunks) + 1, "type": "text", "heading_path": hp(), "text": txt})

    def add_text(s: str):
        if s.strip():
            pend.clear()
        if sum(len(x) for x in buf) + len(s) > max_chars:
            flush()
        buf.append(s)

    def walk(blocks):
        for b in blocks:
            if isinstance(b, Paragraph):
                lv = _heading_level(b)
                if lv:
                    flush()
                    emit_pending()
                    while path and path[-1][0] >= lv:
                        path.pop()
                    htxt = b.text.strip().replace("\n", " ")
                    path.append((lv, htxt))
                    if htxt:
                        pend.append((hp()[:-1], htxt))
                else:
                    add_text(b.text)
            elif isinstance(b, Table):
                flush()
                md = table_markdown(b)
                if md:
                    pend.clear()
                    chunks.append({"id": len(chunks) + 1, "type": "table", "table_id": b.id,
                                   "heading_path": hp(), "caption": b.caption, "text": md,
                                   "records": table_records(b)})
                for c in b.cells:
                    walk([x for x in c.blocks if (isinstance(x, Table) and not is_tag_table(x)) or isinstance(x, Note)])
            elif isinstance(b, Note):
                add_text(f"[^{b.number}]: " + _flat_text(b.blocks, " "))
            elif isinstance(b, TextBox):
                add_text(_flat_text(b.blocks, " "))
                nt = _nested_tables(b.blocks)           # C71: 글상자 속 표는 독립 표 조각으로
                if nt:
                    flush()
                    walk(nt)
            elif isinstance(b, HeaderFooter):
                txt = _flat_text(b.blocks, " ")         # C71: 머리말·꼬리말도 같은 내용은 한 번만 조각으로
                key = b.role + txt
                if txt and key not in hf_seen:
                    hf_seen.add(key)
                    flush()
                    emit_pending()
                    chunks.append({"id": len(chunks) + 1, "type": "header" if b.role == "header" else "footer", "heading_path": [], "text": txt})
                    nt = _nested_tables(b.blocks)
                    if nt:
                        walk(nt)
            elif isinstance(b, Equation):
                add_text(f"$$ {b.script} $$")
            elif isinstance(b, Image):
                add_text(f"[그림:{b.name}]" + (f" {b.caption}" if b.caption else ""))

    walk(doc.blocks)
    flush()
    emit_pending()
    return chunks
