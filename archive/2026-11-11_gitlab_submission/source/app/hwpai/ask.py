"""모델 비종속 질의 — OpenAI 호환 채팅 API 면 어느 모델이든(HyperCLOVA X·Solar·EXAONE·GPT-OSS·Gemma 등).

  python -m hwpai ask 문서.hwp "질문" [--profile 이름 ...] [--profiles 설정.json]

모델 설정(프로필) — JSON 파일 또는 환경변수
  {"profiles": {"solar": {"base_url": "https://…/v1", "model": "solar-pro", "api_key_env": "SOLAR_API_KEY"},
                "clova": {"base_url": "https://…/v1", "model": "HCX-…", "api_key_env": "CLOVA_API_KEY"}}}
  환경변수만 쓸 때: HWPAI_LLM_BASE_URL · HWPAI_LLM_MODEL · HWPAI_LLM_API_KEY (프로필 이름 "env")
열쇠는 파일에 적지 않고 환경변수 이름만 적는다.

흐름: hwpai 가 문서를 읽고(변환 없이) 질의와 가까운 조각을 고른다 → 같은 근거·같은 지시문을 모델마다 보낸다(temperature 0) →
JSON {"answer", "evidence": [조각 번호]} 를 받아 모델끼리 비교한다. 문장 대신 핵심 값(숫자+단위·날짜·기관명)
집합을 비교하고(같으면 일치, 한쪽이 더 냈으면 부분, 서로 다르면 불일치 — 사람 확인), 값이 근거 조각에 있는지도 본다.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.request

SYSTEM = ("너는 공문서 판독 보조자다. 아래 [근거] 조각에 있는 내용으로만 답한다. 근거에 없으면 answer 를 \"근거 없음\" 으로 한다. "
          "반드시 JSON 한 개만 출력한다: {\"answer\": \"짧은 답\", \"evidence\": [근거 조각 번호 정수…]}")


def load_profiles(path: str | None) -> dict:
    prof = {}
    if path:
        with open(path, encoding="utf-8") as f:
            prof.update(json.load(f).get("profiles", {}))
    if os.environ.get("HWPAI_LLM_BASE_URL"):
        prof.setdefault("env", {"base_url": os.environ["HWPAI_LLM_BASE_URL"], "model": os.environ.get("HWPAI_LLM_MODEL", ""),
                                "api_key_env": "HWPAI_LLM_API_KEY"})
    return prof


def build_messages(doc_path: str, question: str, top_k: int = 5):
    from .mcp import t_search_chunks
    res = json.loads(t_search_chunks(doc_path, question, top_k))["results"]
    ctx = "\n\n".join(f"[근거 {r['id']}] ({' > '.join(r['heading_path'])})\n{r['text'][:1500]}" for r in res)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"[근거]\n{ctx}\n\n[질문]\n{question}"}], [r["id"] for r in res]


def _sha(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _record_evidence(profile: dict, url: str, req_bytes: bytes, status, resp_bytes: bytes, resp_headers: dict, t_start: float):
    """HWPAI_EVIDENCE_DIR 이 있으면 요청·응답 본문과 해시를 남긴다. 키·토큰은 어디에도 쓰지 않는다.
    해시는 파일이 나중에 바뀌지 않았음(무결성)을 보일 뿐, 제공사가 실제로 응답했음(진본성)을 증명하지 않는다."""
    d = os.environ.get("HWPAI_EVIDENCE_DIR")
    if not d:
        return
    import datetime
    import platform
    import sys
    os.makedirs(d, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    tag = (profile.get("name") or profile.get("model") or "model").replace("/", "_")
    base = f"{stamp}_{tag}"
    with open(os.path.join(d, base + ".request.json"), "wb") as f:
        f.write(req_bytes)
    with open(os.path.join(d, base + ".response.json"), "wb") as f:
        f.write(resp_bytes)
    try:
        j = json.loads(resp_bytes)
        rid, rmodel, rcreated = j.get("id"), j.get("model"), j.get("created")
    except Exception:
        rid = rmodel = rcreated = None
    keep = {k.lower(): v for k, v in (resp_headers or {}).items()
            if k.lower() in ("x-request-id", "request-id", "date", "content-type", "x-ncp-trace-id", "x-goog-request-id")}
    try:
        from . import __version__ as ver
    except Exception:
        ver = None
    meta = {"time_utc": stamp, "endpoint": url, "profile_model": profile.get("model"), "http_status": status,
            "request_sha256": _sha(req_bytes), "response_sha256": _sha(resp_bytes),
            "provider_response_id": rid, "provider_response_model": rmodel, "provider_created": rcreated,
            "provider_headers": keep, "elapsed_s": round(time.perf_counter() - t_start, 3),
            "env": {"os": platform.platform(), "python": sys.version.split()[0], "hwpai": ver},
            "note": "해시는 무결성 증빙이며 제공사 진본성 증명이 아니다. API 키는 기록하지 않는다."}
    with open(os.path.join(d, base + ".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


def chat(profile: dict, messages: list, timeout: float = 120.0) -> str:
    url = profile["base_url"].rstrip("/") + "/chat/completions"
    key = os.environ.get(profile.get("api_key_env", ""), "") if profile.get("api_key_env") else ""
    body = {"model": profile.get("model", ""), "messages": messages, "max_tokens": profile.get("max_tokens", 512)}
    if "temperature" in profile:
        body["temperature"] = profile["temperature"]
    body.update(profile.get("extra_body", {}))
    # extra_headers 값은 "ENV:이름" 꼴이면 환경변수에서 읽는다(파일에 비밀 금지).
    hdr = {"Content-Type": "application/json"}
    for k, v in (profile.get("extra_headers") or {}).items():
        hdr[k] = os.environ.get(v[4:], "") if isinstance(v, str) and v.startswith("ENV:") else v
    if key:
        hdr["Authorization"] = f"Bearer {key}"
    req_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, req_bytes, method="POST", headers=hdr)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        _record_evidence(profile, url, req_bytes, r.status, raw, dict(r.headers), t0)
    d = json.loads(raw)
    return d["choices"][0]["message"]["content"]


def parse_answer(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    ev = sorted({int(x) for x in d.get("evidence", []) if str(x).isdigit()}) if isinstance(d.get("evidence"), list) else []
    return {"answer": str(d.get("answer", "")).strip() or (text or "").strip()[:200], "evidence": ev, "json_ok": bool(d)}


def _canon(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\.,·\"'「」()]+", "", s)


# ---- 핵심 값 비교 — 문장이 달라도 숫자·단위·날짜·기관명이 같으면 같은 답으로 본다
_UNIT = (r"억\s?원|만\s?원|천\s?원|원|개소|개월|개|건|명|곳|회|차|분기|반기|주|일|월|년|시간|분|초|"
         r"%|퍼센트|배|쪽|장|대|권|부|kg|km|㎡|m")
_COUNTER = r"부서|기관|과|팀|곳|시설|문서|학교|시군구|지자체"
_NUM = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(" + _UNIT + r")(?:\s?(" + _COUNTER + r"))?(?![가-힣A-Za-z])?")
_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s?[.\-/년]\s?(\d{1,2})\s?[.\-/월]\s?(\d{1,2})\s?일?(?!\d)")
_ORG = re.compile(r"([가-힣]{2,}?(?:위원회|소방본부|소방서|공사|공단|본부|센터|부|처|청|과|팀))(?=[은는이가을를의에와도로]|[^가-힣]|$)")
_ORG_STOP = {"관계부처", "각부처", "해당부처", "전부처", "중앙부처", "일부", "전부", "내부", "외부", "세부", "여부", "결과", "효과", "성과"}


def key_values(text: str) -> dict:
    """답 글에서 핵심 값을 뽑는다 → {정규화 키: 화면에 보일 글}."""
    t = unicodedata.normalize("NFKC", text or "")
    out: dict = {}
    for m in _DATE.finditer(t):
        k = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        out.setdefault(k, m.group(0).strip())
    t2 = _DATE.sub(" ", t)
    for m in _NUM.finditer(t2):
        num = m.group(1).replace(",", "") + (("." + m.group(2)) if m.group(2) else "")
        unit = re.sub(r"\s", "", m.group(3)).replace("퍼센트", "%")
        k = num + unit
        shown = m.group(0).strip()
        if len(shown) > len(out.get(k, "")):
            out[k] = shown
    for m in _ORG.finditer(t2):
        w = m.group(1)
        if w in _ORG_STOP or re.fullmatch(r"[가-힣]?(?:부|처|청|과|팀)", w):
            continue
        out.setdefault("기관:" + w, w)
    return out


def compare(answers: dict, question: str = "", context: str = "") -> dict:
    """모델별 답의 핵심 값 집합을 비교한다.

    질문에 이미 있는 값(예: 「2분기」)은 되풀이일 뿐이라 비교에서 뺀다.
    판정: 일치(값 집합이 같다) · 부분(한쪽이 다른 쪽 값을 모두 담고 더 냈다 — 모순 없음) ·
          불일치(서로 다른 값을 냈다 → 사람 확인) · 값없음(비교할 핵심 값이 없다 → 글 그대로 비교)
    근거 대조: 각 값이 모델에게 보낸 근거 조각 안에 있는지(없으면 근거 밖 값 → 사람 확인).
    """
    qk = set(key_values(question))
    ctx = re.sub(r"[\s,]", "", unicodedata.normalize("NFKC", context or ""))
    per = {}
    for n, a in answers.items():
        kv = {k: v for k, v in key_values(a.get("answer", "")).items() if k not in qk}
        per[n] = kv
    sets = [set(v) for v in per.values()]
    shown = {}
    for kv in per.values():
        for k, v in kv.items():
            if len(v) > len(shown.get(k, "")):
                shown[k] = v
    if len(sets) < 2:
        return {"verdict": "단일", "common": [], "only": {}, "outside": [], "shown": shown}
    common = set.intersection(*sets)
    union = set.union(*sets)
    only = {n: sorted(set(kv) - common) for n, kv in per.items() if set(kv) - common}
    if not union:
        verdict = "값없음"
    elif common == union:
        verdict = "일치"
    elif common and sum(1 for s in sets if s - common) == 1:
        verdict = "부분"
    elif not common and sum(1 for s in sets if s) == 1:
        verdict = "부분"
    else:
        verdict = "불일치"

    def _in_ctx(k):
        if not ctx:
            return True
        if k.startswith("기관:"):
            return k[3:] in ctx
        v = re.sub(r"[\s,]", "", shown.get(k, k))
        num = re.match(r"[\d.]+", k)
        return v in ctx or (k in ctx) or (num and re.search(r"(?<![\d.])" + re.escape(num.group(0)) + re.escape(k[num.end():]), ctx) is not None)
    outside = sorted(k for k in union if not _in_ctx(k))
    order = sorted(union, key=lambda k: (k.startswith("기관:"), [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", k)]))
    return {"verdict": verdict, "common": [k for k in order if k in common], "only": only, "outside": outside,
            "shown": shown}


def evidence_overlap(answers: dict) -> float | None:
    ev = [set(a.get("evidence") or []) for a in answers.values()]
    if len(ev) < 2:
        return None
    u = set.union(*ev)
    return round(len(set.intersection(*ev)) / len(u), 2) if u else None


def agreement_line(r: dict) -> str:
    """사람이 읽는 한 줄 — 「핵심 값 일치: 12개 부서 · 8,500건 (예) · 근거 겹침 50% ([4] / [3, 4])」."""
    c = r.get("agree") or {}
    sh = c.get("shown", {})
    fmt = lambda ks: " · ".join(sh.get(k, k) for k in ks)
    v = c.get("verdict")
    if v == "일치":
        s = f"핵심 값 일치: {fmt(c['common'])} (예)"
    elif v == "부분":
        extra = sorted({k for ks in c["only"].values() for k in ks})
        who = ", ".join(c["only"])
        s = (f"핵심 값 일치: {fmt(c['common'])} (예) · " if c["common"] else "") + f"{who}만 더 낸 값: {fmt(extra)} — 모순 없음"
    elif v == "불일치":
        parts = "; ".join(f"{n}만 {fmt(ks)}" for n, ks in c["only"].items())
        s = f"불일치 — 사람 확인 (공통 {fmt(c['common']) or '없음'} · {parts})"
    elif v == "값없음":
        s = f"핵심 값 없음 — 글 그대로 비교: 답 {'같음' if r.get('agree_answer') else '다름'}"
    else:
        return ""
    if c.get("outside"):
        s += f" · 근거 조각에 없는 값: {fmt(c['outside'])} — 사람 확인"
    ok = [a for a in r.get("answers", {}).values() if "error" not in a]
    ov = r.get("evidence_overlap")
    if ov is not None:
        s += f" · 근거 겹침 {round(ov * 100)}% (" + " / ".join(str(a.get("evidence")) for a in ok) + ")"
    return s


def judge(out: dict, context: str = "") -> dict:
    """ask() 결과(또는 저장해 둔 답)에 일치 판정을 붙인다 — API 를 다시 부르지 않고도 쓸 수 있다."""
    ok = {n: a for n, a in out["answers"].items() if "error" not in a}
    out["agree_answer"] = len(ok) >= 2 and len({_canon(a["answer"]) for a in ok.values()}) == 1
    out["agree_evidence"] = len(ok) >= 2 and len({tuple(a["evidence"]) for a in ok.values()}) == 1
    out["agree"] = compare(ok, out.get("question", ""), context)
    out["agree_key"] = len(ok) >= 2 and out["agree"]["verdict"] in ("일치", "부분") and not out["agree"]["outside"]
    out["evidence_overlap"] = evidence_overlap(ok)
    out["agree_line"] = agreement_line(out)
    return out


def ask(doc_path: str, question: str, profiles: dict, names: list[str] | None = None, top_k: int = 5) -> dict:
    messages, ids = build_messages(doc_path, question, top_k)
    out = {"question": question, "retrieved": ids, "answers": {}}
    for n in (names or list(profiles)):
        p = profiles[n]
        t0 = time.perf_counter()
        try:
            raw = chat(p, messages)
            a = parse_answer(raw)
            a.update(model=p.get("model"), seconds=round(time.perf_counter() - t0, 2))
        except Exception as e:
            a = {"error": f"{type(e).__name__}: {e}", "model": p.get("model")}
        out["answers"][n] = a
    return judge(out, messages[1]["content"])
