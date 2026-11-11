"""민감정보 확인 — 검출은 「차단」이 아니라 「확인 요청」이다.

  변환 검증 판정(PASS/WARN/FAIL)과 민감정보 상태를 분리한다.
    상태: 없음 · 확인 필요 · 확인 완료(민감정보 아님) · 확인 완료(민감정보 있음)
  - 변환은 이 컴퓨터 안에서만 일어나므로 민감정보가 있어도 변환한다(기본). 이관대장에 「확인 필요 n건」으로 센다.
  - AI(ask·MCP)에 보여 주는 길만 막는다: 「확인 필요」 문서는 AI 에 보내지 않는다. 사람이 확인한 뒤에만 풀린다.
  - 확인 결과는 문서 SHA-256 으로 저장해 다음 실행에 재사용한다. 저장소에는 값(전화번호 등)을 넣지 않는다
    (종류·자리·길이·결정만). 누가·언제·무엇을 결정했는지는 민감확인_기록.jsonl 에 덧붙인다.
  - 「민감정보 있음」으로 확인된 문서는 (사용자 선택) mask: 그 값을 가린 채 AI 에 보이거나, block: AI 에는 계속 막는다.
검출은 형식(정규식)+문맥 규칙 기반이다. 이름·주소 같은 자유 글 개인정보는 못 잡는다(한계).
"""
from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import json
import os
import re

from .check import find_pii

# 종류별 색(검토 화면) — 전화 주황 · 주민번호 빨강 · 계좌 보라 · 이메일 파랑 · 성명 초록
KIND_COLOR = {
    "주민등록번호": "#d32f2f", "외국인등록번호": "#d32f2f", "휴대전화": "#ef6c00", "일반전화": "#ef6c00", "인터넷전화": "#ef6c00",
    "이메일": "#1565c0", "계좌번호 꼴": "#7b1fa2", "여권번호 꼴": "#7b1fa2", "성명": "#2e7d32", "생년월일": "#2e7d32",
}
SUSPECT, PROBABLY_OK = "의심", "추정 비민감"
STATES = ("없음", "확인 필요", "확인 완료(민감정보 아님)", "확인 완료(민감정보 있음)")

# ---- 문맥 규칙: 오탐을 줄이되 「안전한 쪽」으로만 풀어 준다(추정 비민감도 화면에는 항상 보이고 사람이 바꿀 수 있다) ----
_BIZ_CTX = re.compile(r"사업자|법인|등록\s*번호|문서\s*번호|과제|고시|공고|공문|시행|접수|관리\s*번호|계약|코드|ISBN|팩스|FAX|Fax|우편|일련|승인\s*번호|허가|인증|특허|출원|제\s*\d+\s*호|연구\s*번호|지로|납부")
_OFFICE_CTX = re.compile(r"문의|담당|☎|TEL|Tel|tel|전화|연락처|문의처|상황실|대표번호|콜센터|민원|센터|과\s|팀\s|부서|FAX|팩스")
_PUBLIC_MAIL = re.compile(r"@([\w-]+\.)*(go\.kr|korea\.kr|or\.kr|re\.kr|ac\.kr)$", re.I)


def _ctx_before(text: str, pos: int, n: int = 14) -> str:
    return text[max(0, pos - n):pos]


def classify(text: str, it: dict) -> tuple[str, str]:
    """(자동 분류, 이유). 분류: 의심(확인 필요) · 추정 비민감(기본값 「아님」으로 미리 표시, 사람이 바꿀 수 있음)."""
    kind, val, pos = it["kind"], it["text"], it["pos"]
    before = _ctx_before(text, pos)
    if kind in ("일반전화", "인터넷전화"):
        return PROBABLY_OK, "유선·인터넷 전화 — 기관 업무 연락처로 보는 것이 일반적(집 전화와 구분하지 못함)"
    if kind == "이메일" and _PUBLIC_MAIL.search(val):
        return PROBABLY_OK, "공공기관 도메인(go.kr·korea.kr 등) 이메일 — 업무용으로 추정"
    if kind == "계좌번호 꼴" and re.fullmatch(r"0(?:2|[3-6][1-5])-\d{3,4}-\d{4,5}", val):
        return PROBABLY_OK, "지역번호 꼴(유선 전화 추정) — 괄호 앞 표기 등으로 전화 패턴에서 빠진 것"
    if kind == "계좌번호 꼴" and _BIZ_CTX.search(before):
        return PROBABLY_OK, "앞 글에 사업자·문서·과제·고시·팩스 등 번호 표지 — 계좌가 아닌 번호로 추정"
    if kind == "휴대전화" and _OFFICE_CTX.search(before) and re.search(r"담당|문의|연락처", before):
        # 담당자 휴대전화는 업무용으로 적었더라도 개인 번호다 — 자동으로 풀지 않는다
        return SUSPECT, "담당자·문의 옆 휴대전화 — 업무용으로 적었더라도 개인 번호일 수 있어 확인"
    if kind == "주민등록번호" and not it.get("checksum", True):
        return SUSPECT, "주민등록번호 꼴(검사자리 불일치 — 2020년 이후 부여분일 수 있음)"
    return SUSPECT, "형식이 개인정보 꼴"


def detect(text: str) -> list[dict]:
    """검출 목록 [{kind,text,start,end,auto,reason,before,after}]."""
    out = []
    for it in find_pii(text):
        auto, why = classify(text, it)
        s = it["pos"]
        e = s + len(it["text"])
        out.append({"kind": it["kind"], "text": it["text"], "start": s, "end": e, "auto": auto, "reason": why,
                    "before": text[max(0, s - 24):s].replace("\n", " "), "after": text[e:e + 24].replace("\n", " ")})
    from .meta import meta_items
    out.extend(meta_items(text))
    return out


def item_key(it: dict) -> str:
    return f"{it['kind']}:{it['start']}:{it['end'] - it['start']}"


# ---- 저장소 ----
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Store:
    def __init__(self, root: str):
        self.root = root
        self.dir = os.path.join(root, "민감확인")

    def _p(self, sha: str) -> str:
        return os.path.join(self.dir, sha + ".json")

    def load(self, sha: str) -> dict | None:
        try:
            with open(self._p(sha), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save(self, sha: str, items: list[dict], decisions: dict, policy: str = "block", reviewer: str | None = None,
             source_name: str = "") -> dict:
        """decisions: {item_key: 'sensitive'|'not_sensitive'}. 값은 저장하지 않는다."""
        os.makedirs(self.dir, exist_ok=True)
        who = reviewer or _whoami()
        now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        rows = []
        for it in items:
            k = item_key(it)
            rows.append({"key": k, "kind": it["kind"], "len": it["end"] - it["start"], "auto": it["auto"],
                         "decision": decisions.get(k)})
        rec = {"sha256": sha, "name_hint": os.path.basename(source_name), "reviewer": who, "time": now, "policy": policy,
               "items": rows, "tool": "hwpai sens 1"}
        with open(self._p(sha), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        with open(os.path.join(self.dir, "민감확인_기록.jsonl"), "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"time": now, "reviewer": who, "doc_sha256": sha,
                                    "item_sha256": hashlib.sha256((sha + r["key"]).encode()).hexdigest(),
                                    "kind": r["kind"], "decision": r["decision"], "policy": policy}, ensure_ascii=False) + "\n")
        return rec


def _whoami() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def doc_text(path: str) -> str:
    from . import read
    from .grade import set_active, active
    from .render import plain_text
    saved = active()
    set_active(None)  # 검출용 읽기는 게이트를 거치지 않는다(게이트 자신이 부른다)
    try:
        from .meta import read_meta, meta_block
        return plain_text(read(path)) + meta_block(read_meta(path))
    finally:
        set_active(saved)


def status_of(items: list[dict], rec: dict | None) -> dict:
    """문서 상태. 결정이 없는 의심 항목이 하나라도 있으면 「확인 필요」."""
    if not items:
        return {"state": STATES[0], "pending": 0, "total": 0, "sensitive": 0, "probably_ok": 0, "kinds": {}}
    dec = {r["key"]: r.get("decision") for r in (rec or {}).get("items", [])}
    pend = sens = ok_auto = 0
    kinds: dict = {}
    for it in items:
        d = dec.get(item_key(it))
        if d == "sensitive":
            sens += 1
        elif d == "not_sensitive":
            pass
        elif it["auto"] == PROBABLY_OK:
            ok_auto += 1
        else:
            pend += 1
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    if pend:
        state = STATES[1]
    elif sens:
        state = STATES[3]
    elif rec is not None or ok_auto == len(items):
        state = STATES[2] if rec is not None else STATES[0]
    else:
        state = STATES[0]
    return {"state": state, "pending": pend, "total": len(items), "sensitive": sens, "probably_ok": ok_auto, "kinds": kinds,
            "policy": (rec or {}).get("policy")}


def scan_file(path: str, store: Store | None = None) -> dict:
    """문서 하나의 상태. 읽기 실패면 state=None(판독 불가)."""
    try:
        text = doc_text(path)
    except Exception as e:
        return {"state": None, "error": f"{type(e).__name__}: {e}"[:120], "items": []}
    items = detect(text)
    sha = sha256_file(path)
    rec = store.load(sha) if store else None
    st = status_of(items, rec)
    st.update({"sha256": sha, "items": items, "text": text})
    return st


def mask_values(text: str, items: list[dict], rec: dict | None) -> str:
    """확인 결과가 「민감정보 있음」인 항목(그리고 미확인 의심 항목)의 값을 가린다."""
    dec = {r["key"]: r.get("decision") for r in (rec or {}).get("items", [])}
    spans = []
    for it in items:
        d = dec.get(item_key(it))
        if d == "sensitive" or (d is None and it["auto"] == SUSPECT):
            spans.append((it["start"], it["end"]))
    for s, e in sorted(spans, reverse=True):
        text = text[:s] + "▇" * min(e - s, 8) + text[e:]
    return text


def mask_doc(doc, values) -> None:
    """문서 모델 안의 글에서 값들을 가린다(제자리 수정 — 원본 파일은 건드리지 않는다)."""
    vals = sorted({v for v in values if v}, key=len, reverse=True)

    def m(t: str) -> str:
        for v in vals:
            if v in t:
                t = t.replace(v, "▇" * min(len(v), 8))
        return t

    def walk(blocks):
        for b in blocks:
            if hasattr(b, "text") and isinstance(b.text, str):
                b.text = m(b.text)
            for attr in ("blocks", "cells"):
                sub = getattr(b, attr, None)
                if sub:
                    walk(sub)
            if hasattr(b, "caption") and isinstance(b.caption, str):
                b.caption = m(b.caption)

    walk(doc.blocks)


# ---------------------------------------------------------------- 명령줄
def _files(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    out = []
    for dp, dns, fns in os.walk(path):
        dns[:] = sorted(d for d in dns if not d.startswith("."))
        out += [os.path.join(dp, f) for f in sorted(fns) if f.lower().endswith((".hwp", ".hwpx"))]
    return out


def apply_decisions(store: Store, data: dict, files_by_sha: dict | None = None) -> int:
    """화면이 저장한 결정 파일(민감확인_결정.json)을 저장소에 반영한다. 값은 저장하지 않는다."""
    n = 0
    for d in data.get("docs", []):
        sha = d["sha256"]
        src = (files_by_sha or {}).get(sha)
        items = []
        if src:
            st = scan_file(src, None)
            items = st.get("items", [])
        else:  # 원문 없이 결정만 있으면 키로 항목을 복원한다(종류:시작:길이)
            for k in d["decisions"]:
                kind, s, ln = k.rsplit(":", 2)
                items.append({"kind": kind, "start": int(s), "end": int(s) + int(ln), "auto": SUSPECT, "text": ""})
        store.save(sha, items, d["decisions"], policy=d.get("policy", "block"), reviewer=data.get("reviewer"), source_name=d.get("name", ""))
        n += 1
    return n


def cmd_sens(a):
    from .sens_view import render_review_html
    store = Store(a.store or os.path.join(os.getcwd(), "hwpai_등급기록"))
    files = _files(a.path) if getattr(a, "path", None) else []
    if a.action == "scan":
        counts = {s: 0 for s in STATES}
        for f in files:
            st = scan_file(f, store)
            if st["state"] is None:
                print(f"[판독 불가] {f}: {st.get('error')}")
                continue
            counts[st["state"]] += 1
            if st["items"]:
                kinds = ", ".join(f"{k} {v}" for k, v in st["kinds"].items()) or "의심 없음"
                print(f"[{st['state']}] {f} — 검출 {st['total']}건 (확인 필요: {kinds}; 추정 비민감 {st['probably_ok']}건)")
        print("요약: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    if a.action == "review":
        docs = []
        for f in files:
            st = scan_file(f, store)
            if st["state"] is None or not st["items"]:
                continue
            rec = store.load(st["sha256"]) or {}
            decs = {r["key"]: r["decision"] for r in rec.get("items", []) if r.get("decision")}
            docs.append({"name": os.path.basename(f), "sha256": st["sha256"], "text": st["text"], "items": st["items"],
                         "decisions": decs, "policy": rec.get("policy")})
        out = a.out or os.path.join(os.getcwd(), "민감확인_검토.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_review_html(docs, reviewer=_whoami()))
        pend = sum(1 for d in docs if status_of(d["items"], {"items": [{"key": k, "decision": v} for k, v in d["decisions"].items()]})["state"] == STATES[1])
        print(f"검토 화면 {out} — 문서 {len(docs)}건(확인 대기 {pend}건). 브라우저로 열어 고른 뒤 「저장」 → 내려받은 파일을 apply 로 적용합니다.")
        return 0
    if a.action == "apply":
        data = json.load(open(a.decisions, encoding="utf-8"))
        by_sha = {sha256_file(f): f for f in files}
        n = apply_decisions(store, data, by_sha)
        print(f"{n}개 문서의 확인 결과를 저장했습니다(문서 SHA-256 기준, 값은 저장하지 않음). 기록: {store.dir}")
        return 0
    if a.action == "decide":
        for f in files:
            st = scan_file(f, store)
            if not st["items"]:
                continue
            dec = {item_key(it): a.set for it in st["items"] if not a.kind or it["kind"] == a.kind}
            old = store.load(st["sha256"]) or {}
            for r in old.get("items", []):
                if r.get("decision") and r["key"] not in dec:
                    dec[r["key"]] = r["decision"]
            store.save(st["sha256"], st["items"], dec, policy=a.policy, reviewer=a.reviewer, source_name=f)
            print(f"[결정] {f}: {a.set}" + (f" ({a.kind})" if a.kind else ""))
        return 0
    return 2
