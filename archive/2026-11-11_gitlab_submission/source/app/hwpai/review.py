"""개인정보 가림 — 사람이 확정하는 검토 흐름.

  make   : 문서에서 후보를 찾아 검토 파일(JSON)을 만든다. 아직 아무것도 가리지 않는다.
  decide : 후보마다 「가림」 또는 「남김」을 고른다 (--all 로 한꺼번에).
  apply  : 모든 후보가 결정된 뒤에만 확정본을 쓴다. 누가·언제·무엇을 가렸는지 확정기록을 남긴다.

규칙: 결정되지 않은 후보가 하나라도 있으면 apply 는 거부한다. 원본은 바꾸지 않는다.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re

from .check import find_pii, doc_names

MARK = "▇▇▇"


def _ctx(text: str, pos: int, width: int = 24) -> str:
    return text[max(0, pos - width): pos + width].replace("\n", " ")


def make(doc: str, out_dir: str | None = None) -> str:
    from . import read
    from .render import to_markdown
    d = read(doc)
    whole = to_markdown(d)
    items: dict[tuple, dict] = {}
    for it in find_pii(whole):
        k = (it["kind"], it["text"])
        if k not in items:
            items[k] = {"kind": it["kind"], "text": it["text"], "count": 0, "context": _ctx(whole, it["pos"]), "decision": None}
        items[k]["count"] += 1
    for nm in sorted(doc_names(whole)):
        k = ("성명", nm)
        if k not in items:
            m = re.search(re.escape(nm), whole)
            items[k] = {"kind": "성명", "text": nm, "count": len(re.findall(re.escape(nm), whole)),
                        "context": _ctx(whole, m.start()) if m else "", "decision": None}
    rows = sorted(items.values(), key=lambda x: (x["kind"], x["text"]))
    for i, r in enumerate(rows, 1):
        r["id"] = i
    base = os.path.splitext(os.path.basename(doc))[0]
    # 원본 폴더 안에는 쓰지 않는다: 원본 폴더 옆에 「<폴더>_가림검토」를 만든다
    folder = os.path.dirname(os.path.abspath(doc))
    out_dir = out_dir or os.path.join(folder + "_가림검토", base)
    os.makedirs(out_dir, exist_ok=True)
    rev = {"source": os.path.abspath(doc), "source_sha256": hashlib.sha256(open(doc, "rb").read()).hexdigest(),
           "created": datetime.datetime.now().isoformat(timespec="seconds"), "items": rows, "applied": None}
    path = os.path.join(out_dir, "검토.json")
    json.dump(rev, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = [f"후보 {len(rows)}개 → {path}"]
    for r in rows:
        lines.append(f"  {r['id']:>3}  [{r['kind']}] {r['text']}  ({r['count']}회)  …{r['context']}…")
    return "\n".join(lines)


def add(path: str, text: str, kind: str = "기타") -> str:
    """검토자가 놓친 항목을 직접 추가한다. 추가 항목은 「가림」으로 시작하고 출처를 「사람 추가」로 남긴다."""
    text = text.strip()
    if not text:
        raise SystemExit("추가할 글자를 적어 주세요 (--text)")
    rev = _load(path)
    if any(r["text"] == text and r["kind"] == kind for r in rev["items"]):
        raise SystemExit("이미 있는 후보입니다")
    from . import read
    from .render import to_markdown
    whole = to_markdown(read(rev["source"]))
    if text not in whole:
        raise SystemExit("원문에서 그 글자를 찾지 못했습니다. 띄어쓰기·글자를 다시 확인하세요")
    pos = whole.index(text)
    nid = max([r["id"] for r in rev["items"]] + [0]) + 1
    rev["items"].append({"id": nid, "kind": kind, "text": text, "count": whole.count(text),
                         "context": _ctx(whole, pos), "decision": "가림", "source": "사람 추가"})
    json.dump(rev, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return f"후보 {nid} 추가: [{kind}] {text} ({whole.count(text)}회) — 「가림」으로 표시했습니다. 확정 전에 바꿀 수 있습니다."


def _load(path: str) -> dict:
    return json.load(open(path, encoding="utf-8"))


def decide(path: str, ids: list[int] | None, action: str | None, all_action: str | None = None) -> str:
    rev = _load(path)
    if action not in (None, "가림", "남김"):
        raise SystemExit("결정은 「가림」 또는 「남김」만 가능합니다")
    targets = rev["items"] if all_action else [r for r in rev["items"] if r["id"] in (ids or [])]
    val = all_action or action
    for r in targets:
        r["decision"] = val
    json.dump(rev, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    left = sum(1 for r in rev["items"] if r["decision"] is None)
    return f"{len(targets)}개를 「{val}」로 정했습니다. 아직 정하지 않은 후보: {left}개"


def apply(path: str, reviewer: str) -> str:
    if not reviewer.strip():
        raise SystemExit("확정자 이름을 적어야 합니다 (--by)")
    rev = _load(path)
    undecided = [r["id"] for r in rev["items"] if r["decision"] is None]
    if undecided:
        raise SystemExit(f"결정되지 않은 후보가 있습니다: {undecided}. 모두 정한 뒤 다시 실행하세요.")
    src = rev["source"]
    if hashlib.sha256(open(src, "rb").read()).hexdigest() != rev["source_sha256"]:
        raise SystemExit("원본이 검토 뒤에 바뀌었습니다. 검토를 다시 만드세요.")
    from . import read
    from .render import to_markdown
    text = to_markdown(read(src))
    masked, hidden = text, []
    for r in sorted(rev["items"], key=lambda x: -len(x["text"])):
        if r["decision"] == "가림" and r["text"] in masked:
            hidden.append({"id": r["id"], "kind": r["kind"], "count": masked.count(r["text"])})
            masked = masked.replace(r["text"], MARK)
    d = os.path.dirname(os.path.abspath(path))
    out_md = os.path.join(d, "확정본.md")
    open(out_md, "w", encoding="utf-8").write(masked)
    rec = {"reviewer": reviewer.strip(), "applied_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "source": src, "source_sha256": rev["source_sha256"],
           "output": out_md, "output_sha256": hashlib.sha256(masked.encode("utf-8")).hexdigest(),
           "hidden": hidden, "kept": [r["id"] for r in rev["items"] if r["decision"] == "남김"],
           "added_by_reviewer": [{"id": r["id"], "kind": r["kind"], "count": r["count"]} for r in rev["items"] if r.get("source") == "사람 추가"]}
    json.dump(rec, open(os.path.join(d, "확정기록.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rev["applied"] = rec["applied_at"]
    json.dump(rev, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return f"확정본: {out_md}\n확정기록: {os.path.join(d, '확정기록.json')} (확정자: {rec['reviewer']})"
