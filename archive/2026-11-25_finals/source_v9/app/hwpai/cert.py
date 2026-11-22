"""보존 증명서 — 원본·변환본 해시, 줄 단위 대조, 감사 판정을 한 장으로.

대조 기준: 한글이 내보낸 텍스트(--ref, 있을 때). 없으면 미리보기(PrvText)만 본다.
글자·숫자만 남기고 줄 단위로 양방향 대조한다 (공백·기호 차이는 무시).
"""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import unicodedata


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _alnum(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return "".join(ch for ch in s if ch.isalnum())


def _leaves(doc) -> list[str]:
    from .model import Paragraph, Table
    out: list[str] = []

    def walk(blocks):
        for b in blocks:
            if isinstance(b, Paragraph):
                if b.text.strip():
                    out.append(b.text)
            elif isinstance(b, Table):
                for cell in b.cells:
                    walk(getattr(cell, "blocks", []) or [])
                    t = getattr(cell, "text", None)
                    if isinstance(t, str) and t.strip():
                        out.append(t)
    walk(doc.blocks)
    return out


def table_dup_check(doc) -> dict:
    """표 칸 기준 중복 검사 — 원본 칸 구조(판독 모델)와 마크다운 출력의 칸 글을 센다.

    기준은 판독기의 출력이 아니라 표 칸 모델(각 칸 글은 한 번)이다. 출력에서 어떤 칸 글이
    원본 칸 수보다 많이 나오면 '중복'으로 본다. 같은 판독기로 원본과 변환본을 비교하면
    판독기가 만든 중복을 잡지 못하므로 이 방식을 쓴다.
    """
    import collections
    from .model import walk_tables
    from .render import table_markdown, cell_text
    model = collections.Counter()
    tables = list(walk_tables(doc.blocks))
    for t in tables:
        for c in t.cells:
            k = _alnum(cell_text(c, " ").replace("<br>", " "))
            if len(k) >= 2:
                model[k] += 1
    out = collections.Counter()
    for t in tables:
        for line in table_markdown(t, html_merge=False).splitlines():
            if not line.startswith("|") or set(line) <= set("|- "):
                continue
            for cell in line.strip().strip("|").split(" | "):
                k = _alnum(cell.replace("<br>", " ").replace("\\|", "|"))
                if len(k) >= 2:
                    out[k] += 1
    over = [(k, out[k], model.get(k, 0)) for k in out if out[k] > model.get(k, 0)]
    over.sort(key=lambda x: -(x[1] - x[2]))
    return {"tables": len(tables), "dup_cells": len(over), "over": over[:20]}


def make_certificate(original: str, converted: str, out_dir: str,
                     title: str | None = None, reference: str | None = None) -> dict:
    from . import api
    from .audit import audit, write_audit
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(original))[0]
    title = title or base

    audit_base = os.path.join(out_dir, f"{base}_검증서")
    r = audit(original, converted)
    write_audit(r, audit_base)

    rows = []
    dup = table_dup_check(api.read(converted))
    ref_lines, miss_ref, miss_conv, ref_n, conv_n = [], [], [], 0, 0
    conv_all = _alnum("".join(_leaves(api.read(converted))))
    conv_n = len(conv_all)
    if reference:
        ref_lines = [x for x in open(reference, encoding="utf-8-sig").read().splitlines() if x.strip()]
        ref_all = _alnum("".join(ref_lines))
        ref_n = len(ref_all)
        miss_ref = [x for x in ref_lines if _alnum(x) and _alnum(x) not in conv_all]
        conv_leaves = _leaves(api.read(converted))
        miss_conv = [x for x in conv_leaves if _alnum(x) and _alnum(x) not in ref_all]

    lines = [f"# 원본 보존 증명서 — {title}", "",
             f"발급: {datetime.datetime.now():%Y-%m-%d %H:%M} (hwpai cert)", "",
             "## 1. 대상 파일 (SHA-256)", "| 구분 | 파일 | 바이트 | SHA-256 |", "|---|---|---|---|",
             f"| 원본 | {os.path.basename(original)} | {os.path.getsize(original)} | {_sha(original)} |"]
    if reference:
        lines.append(f"| 원본 전문 (한글 저장 텍스트) | {os.path.basename(reference)} | {os.path.getsize(reference)} | {_sha(reference)} |")
    lines.append(f"| 변환본 | {os.path.basename(converted)} | {os.path.getsize(converted)} | {_sha(converted)} |")
    lines += ["", "## 2. 대조 결과"]
    if reference:
        lines += [f"- 원본 전문 줄 수: {len(ref_lines)} / 변환본 단락·표 칸 수: {len(_leaves(api.read(converted)))}",
                  f"- 원본에 있으나 변환본에 없는 줄: {len(miss_ref)}",
                  f"- 변환본에만 있는 단락: {len(miss_conv)}",
                  f"- 글자·숫자 수 (원본 전문 / 변환본): {ref_n} / {conv_n}",
                  "- 대조 방식: 공백·기호를 뺀 글자·숫자만 줄 단위로 양방향 비교"]
    else:
        lines.append("- 한글 텍스트 저장본이 없어 전문 대조는 하지 않음 (감사 판정 안의 미리보기 대조만 확인)")
    lines.append(f"- 표 칸 중복 검사: 표 {dup['tables']}개, 원본 칸 수보다 많이 나온 칸 글 {dup['dup_cells']}종" + (" — 중복 없음" if not dup["dup_cells"] else " — 중복 있음"))
    for k, n_out, n_model in dup["over"][:5]:
        lines.append(f"  - 「{k[:30]}」: 출력 {n_out}회 / 원본 칸 {n_model}회")
    lines += ["", "## 3. 감사 판정 (hwpai audit)", f"- 판정: **{r.verdict}** · 점수 {r.score:.1f}/100",
              f"- 상세: {os.path.basename(audit_base)}.md / .json", "",
              "## 4. 결론"]
    ok = reference is not None and not miss_ref and not miss_conv and r.verdict == "PASS" and not dup["dup_cells"]
    if reference:
        lines.append("- 원본 전문과 변환본의 글자·숫자가 줄 단위로 모두 일치한다." if ok
                     else "- 차이가 있다. 위 목록을 확인해야 한다.")
    else:
        lines.append(f"- 감사 판정 {r.verdict}. 전문 대조 기준이 없으므로 내용 일치는 주장하지 않는다.")
    lines.append("- 한계: 서식(굵기·정렬·그림·도형 안 글)은 이 증명의 범위가 아니다. 자동 번호 값은 전문 텍스트와 다를 수 있다.")
    path = os.path.join(out_dir, f"{base}_보존증명서.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return {"path": path, "verdict": r.verdict, "ok": ok}
