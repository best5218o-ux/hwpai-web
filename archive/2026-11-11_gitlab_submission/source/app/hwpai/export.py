"""Markdown·구조화 JSON·RAG 청크 파일 출력 — 명령·화면·MCP 가 같은 함수를 쓴다.

  python -m hwpai export 문서|폴더 [--out 폴더] [--formats md,json,chunks] [--ai-folder]

만드는 파일(문서마다 〈이름〉/ 폴더)
  본문.md        마크다운: 제목 수준·표(병합 칸은 HTML 표)·그림 참조(images/…)·각주([^n])·수식($$)·글상자(>)·머리말/꼬리말(<!-- -->)
  구조.json      구조화 JSON(스키마 hwpai-structure/1): 블록 순서·문단·표 격자(칸 좌표·병합·글)·그림(이름·크기·SHA-256)·각주·머리말·수식·
                 글상자 + 문서 속성(작성자 등은 --ai-folder 일 때 뺀다)
  chunks.jsonl   RAG 조각(제목 경로 + 표 행 레코드)
  images/        그림 원본 바이트(이름은 문서 안 이름)
확인 대기 연동(--ai-folder): 결과 폴더가 AI 가 읽는 곳이라고 알리면 문서마다 민감정보 확인 상태를 본다.
  없음·확인완료(아님) → 쓴다 / 확인 필요 → 쓰지 않고 「확인대기_목록.md」에 올린다 / 확인완료(있음) → 가린본(mask 정책)만 쓰거나 쓰지 않는다.
  이 옵션 없이 쓴 결과는 사람이 읽는 용도이며, AI 폴더에 옮기기 전에 sens review 로 확인해야 한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from .model import Paragraph, Table, Image, Equation, Note, TextBox, HeaderFooter

SCHEMA = "hwpai-structure/1"


def _sha(b) -> str | None:
    return hashlib.sha256(b).hexdigest() if b else None


def _block(b, doc) -> dict:
    from .render import cell_text, is_tag_table
    if isinstance(b, Paragraph):
        return b.to_dict()
    if isinstance(b, Table):
        cells = [{"row": c.row, "col": c.col, "rowspan": c.rowspan, "colspan": c.colspan, "header": bool(c.is_header),
                  "text": cell_text(c, "\n"), "blocks": [_block(x, doc) for x in c.blocks if not isinstance(x, Paragraph)]} for c in b.cells]
        return {"type": "table", "id": b.id, "caption": b.caption, "rows": b.nrows, "cols": b.ncols,
                "merged_cells": sum(1 for c in b.cells if c.rowspan > 1 or c.colspan > 1), "cells": cells}
    if isinstance(b, Image):
        data = doc.image_bytes(b.name)
        return {"type": "image", "name": b.name, "orig_name": getattr(b, "orig_name", b.name), "caption": b.caption,
                "bytes": len(data) if data else None, "sha256": _sha(data)}
    if isinstance(b, Equation):
        return {"type": "equation", "script": b.script}
    if isinstance(b, Note):
        return {"type": b.kind, "number": b.number, "blocks": [_block(x, doc) for x in b.blocks]}
    if isinstance(b, TextBox):
        return {"type": "textbox", "blocks": [_block(x, doc) for x in b.blocks]}
    if isinstance(b, HeaderFooter):
        return {"type": b.role, "blocks": [_block(x, doc) for x in b.blocks]}
    return {"type": getattr(b, "kind", "unknown")}


def to_structure(doc, meta: dict | None = None, source_sha256: str | None = None) -> dict:
    return {"schema": SCHEMA, "source": doc.meta.get("source"), "source_sha256": source_sha256,
            "format": doc.meta.get("format"), "masked": bool(doc.meta.get("masked")),
            "properties": meta or {}, "warnings": list(doc.warnings),
            "blocks": [_block(b, doc) for b in doc.blocks]}


def _walk_blocks(blocks):
    for b in blocks:
        yield b
        if isinstance(b, Table):
            for c in b.cells:
                yield from _walk_blocks(c.blocks)
        elif isinstance(b, (Note, TextBox, HeaderFooter)):
            yield from _walk_blocks(b.blocks)


def stable_image_names(doc) -> dict:
    """그림 이름을 내용 해시 기반(〈sha256 앞 12자〉.확장자)으로 바꾼다 — HWP(BIN0001.png)와 HWPX(image1.png)의
    저장 이름이 달라도 같은 그림은 같은 이름이 되어 내보낸 파일이 형식과 무관하게 같다(라운드1 C54). 원래 이름은 orig_name 에 남긴다."""
    new_images, mapping = {}, {}
    for b in _walk_blocks(doc.blocks):
        if isinstance(b, Image):
            data = doc.image_bytes(b.name)
            if not data:
                continue
            if b.name not in mapping:
                ext = os.path.splitext(b.name)[1].lower() or ".bin"
                mapping[b.name] = hashlib.sha256(data).hexdigest()[:12] + ext
                new_images[mapping[b.name]] = data
            b.orig_name = b.name
            b.name = mapping[b.name]
    for nm in doc.images:  # 본문에서 참조되지 않은 그림도 보존
        if nm not in mapping:
            data = doc.image_bytes(nm)
            if data:
                new_images.setdefault(hashlib.sha256(data).hexdigest()[:12] + (os.path.splitext(nm)[1].lower() or ".bin"), data)
    doc.images = new_images
    return mapping


def _unique_dir(base: str) -> str:
    if not os.path.exists(base):
        return base
    n = 2
    while os.path.exists(f"{base} ({n})"):
        n += 1
    return f"{base} ({n})"


def export_doc(path: str, outdir: str, formats=("md", "json", "chunks"), ai_folder: bool = False, images: bool = True) -> dict:
    """문서 하나를 outdir 아래에 쓴다. 반환 {status: 쓴·확인대기·차단·실패, …}."""
    from . import read, grade
    from .render import to_markdown, to_chunks
    from .meta import read_meta
    gate_active = grade.active()
    if ai_folder:
        if gate_active is None:  # 라이브러리로 부른 경우에도 기본 정책(확인 요청)을 건다
            gate_active = grade.Gate(default=None, mode="cli", policy="review")
            grade.set_active(gate_active, tool="export_ai")
        grade.set_active(gate_active, tool="export_ai")
    try:
        doc = read(path, visible=True)   # C77: 화면에 보이는 글만 — 변경 추적으로 지운 글이 AI 폴더로 새지 않게(HWPX 는 이미 화면 글)
    except grade.GradeBlocked as e:
        return {"status": "확인대기" if "확인" in str(e) else "차단", "reason": str(e)[:200], "file": os.path.basename(path)}
    finally:
        if ai_folder:
            grade.set_active(gate_active, tool="export")
    stable_image_names(doc)
    props = read_meta(path)
    if ai_folder:  # 작성자 등 사람 이름이 들어갈 수 있는 속성은 AI 폴더로 보내지 않는다
        props = {k: v for k, v in props.items() if k not in ("작성자", "마지막 저장자", "키워드", "설명")}
    stem = _unique_dir(os.path.join(outdir, os.path.splitext(os.path.basename(path))[0]))
    os.makedirs(stem, exist_ok=True)
    wrote = {}
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if "md" in formats:
        with open(os.path.join(stem, "본문.md"), "w", encoding="utf-8") as f:
            f.write(to_markdown(doc) + "\n")
        wrote["md"] = "본문.md"
    if "json" in formats:
        with open(os.path.join(stem, "구조.json"), "w", encoding="utf-8") as f:
            json.dump(to_structure(doc, props, sha), f, ensure_ascii=False, indent=1)
        wrote["json"] = "구조.json"
    if "chunks" in formats:
        ch = to_chunks(doc)
        with open(os.path.join(stem, "chunks.jsonl"), "w", encoding="utf-8") as f:
            for c in ch:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        wrote["chunks"] = f"chunks.jsonl ({len(ch)}개)"
    n = 0
    if images and ({"md", "json"} & set(formats)):
        for nm in doc.images:
            data = doc.image_bytes(nm)
            if data:
                os.makedirs(os.path.join(stem, "images"), exist_ok=True)
                with open(os.path.join(stem, "images", nm), "wb") as f:
                    f.write(data)
                n += 1
    return {"status": "쓴", "file": os.path.basename(path), "dir": stem, "wrote": wrote, "images": n, "masked": bool(doc.meta.get("masked")),
            "sha256": sha}


def export_many(paths: list[str], outdir: str, formats=("md", "json", "chunks"), ai_folder: bool = False, log=print) -> dict:
    from .batch import scan
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += [os.path.join(p, rel) for rel in scan(p, True)]
        else:
            files.append(p)
    rows = []
    for f in files:
        try:
            r = export_doc(f, outdir, formats, ai_folder)
        except Exception as e:
            r = {"status": "실패", "file": os.path.basename(f), "reason": f"{type(e).__name__}: {e}"[:200]}
        rows.append(r)
        log(f"[{r['status']}] {r['file']}" + (f" — {r.get('reason', '')}" if r["status"] != "쓴" else ""))
    wait = [r for r in rows if r["status"] in ("확인대기", "차단")]
    os.makedirs(outdir, exist_ok=True)
    if wait:
        with open(os.path.join(outdir, "확인대기_목록.md"), "w", encoding="utf-8") as f:
            f.write("# 확인 대기 — AI 폴더에 쓰지 않은 문서\n\n민감정보 확인(hwpai sens review)을 마치면 다시 내보내세요. 내용은 이 목록에 적지 않습니다.\n\n")
            for r in wait:
                f.write(f"- {r['file']} ({r['status']})\n")
    return {"files": len(files), "written": sum(r["status"] == "쓴" for r in rows), "waiting": len(wait),
            "failed": sum(r["status"] == "실패" for r in rows), "out": outdir, "rows": rows}


def cmd_export(a):
    fm = tuple(x.strip() for x in a.formats.split(",") if x.strip())
    out = a.out or (a.path.rstrip("/\\") + "_export")
    r = export_many([a.path], out, fm, a.ai_folder)
    print(f"문서 {r['files']}개 — 씀 {r['written']} · 확인 대기 {r['waiting']} · 실패 {r['failed']} → {out}")
    return 0 if not r["failed"] else 1
