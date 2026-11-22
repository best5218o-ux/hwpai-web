"""AI 투입 점검 — 문서를 AI(검색·학습·온AI RAG 등록)에 넣기 전에 본다.

  python -m hwpai check 문서|폴더 [--out 결과폴더] [--mask]

점검
  1 개인정보   주민등록번호(생년월일·성별자리 검사)·외국인등록번호·휴대전화·일반전화·이메일·계좌 꼴·여권번호 꼴
  2 공개 구분  공문 끝의 「공개」「부분공개(n)」「비공개(n)」 표시(정보공개법 제9조 제1항 각 호 번호)
  3 공문 구조  수신·(경유)·제목·붙임·끝·발신명의·시행/접수 번호 — 있으면 공문서로 보고 항목을 뽑는다
  4 AI 가독성  판독 성공·글 양·표 비율·그림만 있는 쪽(글 없는 문서)·판독 경고 → 0~100
판정: 투입 가능 / 검토 필요 / 투입 불가 와 그 이유. --mask 면 개인정보를 가린 마크다운·청크를 쓴다.
※ 개인정보 탐지는 형식(패턴) 기반이다. 이름·주소 같은 자유 글 개인정보는 잡지 못한다(한계).
"""
from __future__ import annotations

import json
import os
import re

PII = [
    ("주민등록번호", re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\s?-\s?([1-4])\d{6}(?!\d)")),
    ("주민등록번호", re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[1-4]\d{6}(?!\d)")),  # 하이픈 없는 13자리 — find_pii 가 문맥·검사자리로 거른다
    ("외국인등록번호", re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\s?-\s?([5-8])\d{6}(?!\d)")),
    ("휴대전화", re.compile(r"(?<!\d)\(?01[016789]\)?\s{0,2}[-.]?\s{0,2}\d{3,4}\s{0,2}[-.]?\s{0,2}\d{4}(?!\d)")),
    ("일반전화", re.compile(r"(?<![\d(])\(?0(2|[3-6][1-5])(?:\)\s?|[-.\s])\d{3,4}[-.\s]\d{4}(?!\d)")),
    ("인터넷전화", re.compile(r"(?<![\d(])\(?070(?:\)\s?|[-.\s]?)\d{3,4}[-.\s]?\d{4}(?!\d)")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")),
    ("계좌번호 꼴", re.compile(r"(?<![\d-])\d{3,6}-\d{2,6}-\d{2,7}(-\d{1,3})?(?![\d-])")),
    ("여권번호 꼴", re.compile(r"(?<![A-Z0-9])[MSROD]\d{8}(?![0-9])")),
]
# 라벨 뒤의 값 — 성명·생년월일 (표 칸은 라벨과 값이 붙어 나오므로 라벨 기준으로 찾는다)
# 값 자리만 가린다. 가림은 넓게 잡는다(잘못 가려도 안전, 놓치면 위험).
LABELED = [
    ("성명", re.compile(r"(?:성\s*명|이\s*름)[\s|:：]*([가-힣]{2,4})")),
    ("생년월일", re.compile(r"생\s*년\s*월\s*일[^\n]{0,30}?((?:19|20)\d{2}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}(?:\s*일)?|\d{6}(?!\d))")),
]
# 주민번호 검사자리 — 2020-10 이후 부여분은 검사자리가 없어 형식만 본다(맞으면 「확실」, 아니면 「꼴」)
_W = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]


def _rrn_checksum(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    if len(d) != 13:
        return False
    return (11 - sum(int(a) * w for a, w in zip(d, _W)) % 11) % 10 == int(d[12])


DISCLOSE = re.compile(r"(비공개|부분\s*공개|공개)\s*(\(\s*([1-8](\s*[,·]\s*[1-8])*)\s*\))?")
STRUCT = {
    "수신": re.compile(r"^\s*수\s*신\s*[:：]?\s*(.+)$", re.M),
    "경유": re.compile(r"^\s*\(?\s*경\s*유\s*\)?\s*[:：]?\s*(.*)$", re.M),
    "제목": re.compile(r"^\s*제\s*목\s*[:：]?\s*(.+)$", re.M),
    "붙임": re.compile(r"^\s*붙\s*임\s*(.*)$", re.M),
    "끝": re.compile(r"\s끝\.\s*$", re.M),
    "시행": re.compile(r"시\s*행\s+([^\s].{2,40}?)(?:\s{2,}|\(|$)", re.M),
    "접수": re.compile(r"접\s*수\s+([^\s].{2,40}?)(?:\s{2,}|\(|$)", re.M),
}


# 「성명」 표 머리칸 뒤에 이어 나오는 다른 머리칸 이름 — 이름이 아니다 (1,000건 차단 문서 실측에서 모음)
NAME_HEADER_WORDS = {
    "한글", "한자", "영문", "재산", "선정", "직위", "직급", "직책", "직명", "소속", "부서", "기관", "좌장", "학력", "경력",
    "연락처", "전화", "주소", "비고", "구분", "성별", "나이", "연령", "생년", "생년월일", "사유", "훈격", "서명", "날인",
    "국적", "관계", "직업", "분야", "역할", "담당", "업무", "사진", "약력", "번호", "순번", "연번", "작품", "작품명",
    "부문", "등급", "점수", "결과", "내용", "일자", "날짜", "주민", "등록", "이메일", "휴대폰", "휴대전화", "직렬",
    "제목", "주요", "주요경력", "공적", "공적요지", "제외", "수상", "대상", "장르", "또는", "및", "포함",
    "서기관", "주무관", "사무관", "소방령", "소방위", "소방경", "소방장", "기획관", "과장", "국장", "팀장", "담당관", "연구관",
    "권리", "모집", "명단", "고려사항", "위촉", "기재", "인지", "인터뷰", "함께", "설립일", "노동시장",
}
_PARTICLE_END = re.compile(r"[을를은는이가의에도로과와만]$")


def _name_like(text: str, m) -> bool:
    """「성명」「이름」 라벨 뒤 값이 사람 이름처럼 보이는지 — 검출은 좁게(오탐 줄임), 가림(mask)은 넓게 둔다.
    거르는 것: 줄을 넘어간 값(표 머리줄 다음 줄), 표 머리칸 이름, 쌍점 없이 조사로 끝나는 말(「이름 등을」)."""
    v = m.group(1)
    sep = text[m.start(0):m.start(1)]
    if "\n" in sep or "\r" in sep:
        return False
    if v in NAME_HEADER_WORDS or v[:2] in NAME_HEADER_WORDS:
        return False
    if ":" not in sep and "：" not in sep and _PARTICLE_END.search(v):
        return False
    return True


def find_pii(text: str) -> list[dict]:
    out = []
    for kind, rx in PII:
        for m in rx.finditer(text):
            s = m.group(0)
            if kind == "계좌번호 꼴" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):  # 날짜
                continue
            if kind == "주민등록번호" and "-" not in s and not re.search(r"\s", s) and not _rrn_checksum(s) \
                    and "주민" not in text[max(0, m.start() - 16):m.start()]:
                continue  # 하이픈 없는 13자리는 검사자리가 맞거나 「주민」 문맥이 있을 때만
            item = {"kind": kind, "text": s, "pos": m.start()}
            if kind == "주민등록번호":
                item["checksum"] = _rrn_checksum(s)
            out.append(item)
    for kind, rx in LABELED:
        for m in rx.finditer(text):
            if kind == "성명" and not _name_like(text, m):
                continue
            out.append({"kind": kind, "text": m.group(1), "pos": m.start(1)})
    for m in _ROLE_NAME.finditer(text):   # 신청인·대표자·담당자 등 역할 표기 뒤 이름 — 성씨로 시작하고 표 머리말·조사 꼴이 아닌 것만
        v = m.group(1)
        if v[0] in _SURNAMES and _name_like(text, m) and v not in NAME_HEADER_WORDS and not v.endswith(("님", "등")):
            out.append({"kind": "성명", "text": v, "pos": m.start(1)})
    # 같은 자리 중복(주민번호가 계좌 꼴에도 걸림 등) 제거 — 먼저 잡힌 종류 우선
    seen, uniq = set(), []
    for it in sorted(out, key=lambda x: x["pos"]):
        span = range(it["pos"], it["pos"] + len(it["text"]))
        if any(p in seen for p in span):
            continue
        seen.update(span)
        uniq.append(it)
    return uniq


_SURNAMES = set("김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용")
_ROLE_NAME = re.compile(r"(?:신청인|대표자|담당자|작성자|제안자|응시자|참가자|접수자|보호자)\s*[:：]\s*([가-힣]{2,4})")  # 역할 표기는 쌍점이 있을 때만(표 머리칸·「참가자 모집」 같은 말과 구분)
_NAME_RX = LABELED[0][1]


def doc_names(text: str) -> set[str]:
    """라벨(성명·이름) 뒤에 나온 이름들 — 문서 어디에 나오든 가린다."""
    return {m.group(1) for m in _NAME_RX.finditer(text) if len(m.group(1)) >= 2}


def mask(text: str, names: set[str] | None = None) -> str:
    for nm in sorted((names or set()) | doc_names(text), key=len, reverse=True):
        text = text.replace(nm, nm[0] + "*" * (len(nm) - 1))
    def rep(m):
        s = m.group(0)
        return re.sub(r"[0-9A-Za-z]", "*", s[:-4]) + s[-4:] if len(s) > 6 else "*" * len(s)
    def lab(kind):
        def f(m):
            v = m.group(1)
            hid = (v[0] + "*" * (len(v) - 1)) if kind == "성명" else "*" * len(v)
            return m.group(0)[:m.start(1) - m.start(0)] + hid + m.group(0)[m.end(1) - m.start(0):]
        return f
    for kind, rx in LABELED:
        text = rx.sub(lab(kind), text)
    for kind, rx in PII:
        if kind == "이메일":
            text = rx.sub(lambda m: m.group(0)[0] + "***@" + m.group(0).split("@", 1)[1], text)
        elif kind in ("주민등록번호", "외국인등록번호"):
            text = rx.sub(lambda m: m.group(0)[:m.group(0).index("-") + 2 if "-" in m.group(0) else 7] + "******", text)
        else:
            text = rx.sub(rep, text)
    return text


def check_doc(path: str) -> dict:
    from . import read
    from .model import Image, Table, walk_tables
    from .render import plain_text
    res = {"file": os.path.basename(path)}
    try:
        doc = read(path)
    except Exception as e:
        res.update(verdict="투입 불가", reasons=[f"판독 실패: {type(e).__name__}: {e}"], score=0)
        return res
    text = plain_text(doc)
    pii = find_pii(text)
    tail = text[-600:]
    disc = [m.group(0) for m in DISCLOSE.finditer(tail)]
    # 「공개」 단어가 본문에도 흔하므로 끝부분의 마지막 표시만 쓴다
    disclosure = disc[-1].replace(" ", "") if disc else ""
    struct = {}
    for k, rx in STRUCT.items():
        m = rx.search(text)
        if m:
            struct[k] = (m.group(1).strip()[:80] if m.groups() and m.group(1) else True)
    is_official = sum(k in struct for k in ("수신", "제목", "끝", "시행")) >= 3
    tabs = list(walk_tables(doc.blocks))
    nimg = sum(1 for b in doc.blocks if isinstance(b, Image))
    chars = len(re.sub(r"\s", "", text))
    from .render import grid_of
    table_chars = sum(len(re.sub(r"\s", "", "".join("".join(r) for r in grid_of(t)))) for t in tabs)
    score = 100
    notes = []
    if chars < 50:
        score -= 60
        notes.append("글이 거의 없음(그림·스캔 문서일 수 있음 — OCR 필요)")
    if nimg and chars < 200:
        score -= 20
        notes.append("그림 위주 문서")
    if doc.warnings:
        score -= min(20, 5 * len(doc.warnings))
        notes.append(f"판독 경고 {len(doc.warnings)}건")
    if chars and table_chars / chars > 0.8:
        notes.append("표 위주 문서 — 표 레코드(get_tables)로 쓰는 것이 낫다")
    score = max(score, 0)
    reasons = []
    sure_rrn = [p for p in pii if p["kind"] in ("주민등록번호", "외국인등록번호") and p.get("checksum")]
    if disclosure.startswith("비공개"):
        verdict = "투입 불가"
        reasons.append(f"공개 구분 「{disclosure}」")
    elif sure_rrn:
        verdict = "투입 불가"
        reasons.append(f"주민등록번호 {len(sure_rrn)}건(검사자리 일치) — 가린 뒤 다시 점검")
    elif pii or disclosure.startswith("부분공개") or score < 50:
        verdict = "검토 필요"
        if pii:
            kinds = {}
            for p in pii:
                kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
            reasons.append("개인정보 꼴 " + ", ".join(f"{k} {v}" for k, v in kinds.items()))
        if disclosure.startswith("부분공개"):
            reasons.append(f"공개 구분 「{disclosure}」")
        if score < 50:
            reasons.append("AI 가독성 낮음: " + "; ".join(notes))
    else:
        verdict = "투입 가능"
    res.update(verdict=verdict, reasons=reasons, score=score, notes=notes, disclosure=disclosure or "표시 없음",
               official=is_official, structure=struct,
               pii=[{**p, "text": (p["text"][0] + "*" * (len(p["text"]) - 1)) if p["kind"] == "성명" and p["text"] else mask(p["text"])} for p in pii][:50], pii_count=len(pii),
               chars=chars, tables=len(tabs))
    return res


def check(path: str, out: str | None = None, do_mask: bool = False) -> list[dict]:
    from .batch import scan
    root = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    files = scan(path, True)
    rows = []
    for rel in files:
        p = os.path.join(root, rel)
        r = check_doc(p)
        r["file"] = rel
        rows.append(r)
        if out and do_mask:
            from . import read
            from .render import to_chunks, to_markdown
            try:
                d = read(p)
                base = os.path.join(out, os.path.splitext(rel)[0])
                os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
                whole = to_markdown(d)
                names = doc_names(whole)
                with open(base + ".가림.md", "w", encoding="utf-8") as f:
                    f.write(mask(whole, names))
                with open(base + ".가림.chunks.jsonl", "w", encoding="utf-8") as f:
                    for c in to_chunks(d):
                        c["text"] = mask(c["text"], names)
                        c.pop("records", None)
                        f.write(json.dumps(c, ensure_ascii=False) + "\n")
            except Exception:
                pass
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "AI투입점검.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        from .xlsx import write_xlsx
        head = ["파일", "판정", "이유", "AI 가독성", "공개 구분", "공문서", "개인정보 수", "글자 수", "표 수"]
        data = [head] + [[r["file"], r["verdict"], " / ".join(r.get("reasons", [])), r.get("score"), r.get("disclosure", ""),
                          "예" if r.get("official") else "", r.get("pii_count", 0), r.get("chars", 0), r.get("tables", 0)] for r in rows]
        st = ["HEAD"] + [{"투입 가능": "PASS", "검토 필요": "WARN", "투입 불가": "FAIL"}[r["verdict"]] for r in rows]
        write_xlsx(os.path.join(out, "AI투입점검.xlsx"), [("AI투입점검", data, st, [40, 10, 60, 10, 14, 8, 10, 10, 8])])
    return rows
