"""학습자료용 출처 붙은 조각(JSONL)과 품질 점검.

조각마다 원본 파일명·원본 SHA-256·제목 경로·위치 번호를 붙여, 나중에 「이 답이 어느 문서에서 왔나」를
되짚을 수 있게 한다. 품질 점검은 같은 문단 반복(병합 칸 중복 포함), 깨진 문자, 빈 본문을 찾아 문서별
상태(OK·REVIEW·BAD)를 낸다. 글을 지우는 중복 제거는 여기서 하지 않는다(원본과 달라지므로 별도 결정).
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re

from .model import Paragraph, Table
from .render import to_chunks

MIN_DUP_CHARS = 20                       # 이보다 짧은 문단 반복은 정상 문구로 본다
_WS = re.compile(r"\s+")
_BAD = re.compile("[�\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _norm(s: str) -> str:
    return _WS.sub("", s or "")


def _paras(blocks, out: list) -> list:
    """표 칸·글상자·각주 안까지 모든 문단 글을 모은다(병합 칸 중복을 보려고 칸마다 따로 센다)."""
    for b in blocks:
        if isinstance(b, Paragraph):
            out.append(b.text or "")
        elif isinstance(b, Table):
            for c in b.cells:
                _paras(c.blocks, out)
        elif hasattr(b, "blocks"):
            _paras(b.blocks or [], out)
    return out


def build_records(doc, source_path: str, max_chars: int = 1500) -> list[dict]:
    sha = _sha256(source_path)
    src = os.path.basename(source_path)
    recs = []
    for i, c in enumerate(to_chunks(doc, max_chars), start=1):
        r = {
            "doc_id": sha[:16],
            "source_file": src,
            "source_sha256": sha,
            "chunk_index": i,
            "type": c["type"],
            "heading_path": c.get("heading_path", []),
            "text": c["text"],
            "char_count": len(c["text"]),
        }
        if c["type"] == "table":
            r.update(table_id=c.get("table_id"), caption=c.get("caption"), records=c.get("records"))
        recs.append(r)
    return recs


def check(doc, records: list[dict]) -> dict:
    paras = [_norm(p) for p in _paras(doc.blocks, []) if len(_norm(p)) >= MIN_DUP_CHARS]
    cnt = collections.Counter(paras)
    dups = {k: v for k, v in cnt.items() if v >= 2}
    bad = [r["chunk_index"] for r in records if _BAD.search(r["text"])]
    issues = []
    if dups:
        issues.append({"code": "DUP_PARA", "distinct_paragraphs": len(dups),
                       "max_repeat": max(dups.values()),
                       "examples": [k[:40] for k in list(dups)[:3]]})
    if bad:
        issues.append({"code": "BAD_CHARS", "chunks": bad[:20], "count": len(bad)})
    if not records:
        issues.append({"code": "NO_TEXT"})
    if not records or bad:
        status = "BAD"
    elif dups:
        status = "REVIEW"
    else:
        status = "OK"
    return {"status": status, "chunks": len(records), "issues": issues}


def write_corpus(path: str, outdir: str) -> dict:
    from .api import read
    doc = read(path, visible=True)   # C77
    recs = build_records(doc, path)
    rep = check(doc, recs)
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    jp = os.path.join(outdir, base + ".corpus.jsonl")
    with open(jp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rp = os.path.join(outdir, base + ".quality.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return {"corpus": jp, "quality": rp, "status": rep["status"], "chunks": rep["chunks"]}
