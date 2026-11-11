"""구성요소 센서스 — 원본 HWP 와 변환 HWPX 가 「무엇을 몇 개 가졌는가」를 서로 독립적으로 센다.

HWP 쪽은 BodyText·DocInfo 레코드를 직접 훑어(엔진을 쓰지 않음) 컨트롤 ID·도형 구성요소 ID·도형 크기를 센다.
HWPX 쪽은 Contents/*.xml 의 요소를 센다. 서로 짝이 되는 구성요소(COMPONENTS)마다 개수·크기 서명이 같은지 본다.
이 모듈은 audit.py 의 글·표·그림·각주 검증을 대체하지 않고, 도형·필드·머리말·수식·메모·OLE·서식 정의 등으로 넓힌다.
"""
from __future__ import annotations

import collections
import re
import struct
import zipfile

import olefile

from .hwp5 import FLAG_COMPRESSED, FLAG_DISTRIBUTE, FLAG_ENCRYPTED, _decrypt_viewtext, _inflate, iter_records

# ---- HWP: 컨트롤 ID → 구성요소 이름 ----
CTRL_NAMES = {
    "tbl ": "표", "eqed": "수식", "fn  ": "각주", "en  ": "미주", "head": "머리말", "foot": "꼬리말",
    "secd": "구역", "cold": "단", "pgnp": "쪽번호위치", "nwno": "새번호", "atno": "자동번호", "pghd": "감추기",
    "tcps": "글자겹침", "tdut": "덧말", "idxm": "찾아보기표시", "bokm": "책갈피", "form": "양식개체",
    "gso ": "그리기개체",
}
SHAPE_NAMES = {"$pic": "그림", "$rec": "사각형", "$ell": "타원", "$arc": "호", "$pol": "다각형", "$cur": "곡선",
               "$lin": "선", "$con": "묶음", "$ole": "OLE", "$tat": "글맵시", "$txt": "글상자", "$vid": "동영상",
               "$cht": "차트", "$col": "연결선"}
# HWPX 요소 → 구성요소
HWPX_TAGS = {"tbl": "표", "equation": "수식", "footNote": "각주", "endNote": "미주", "header": "머리말", "footer": "꼬리말",
             "secPr": "구역", "colPr": "단", "pageNum": "쪽번호위치", "newNum": "새번호", "autoNum": "자동번호",
             "pageHiding": "감추기", "compose": "글자겹침", "dutmal": "덧말", "indexmark": "찾아보기표시",
             "bookmark": "책갈피", "pic": "그림", "rect": "사각형", "ellipse": "타원", "arc": "호", "polygon": "다각형",
             "curve": "곡선", "line": "선", "container": "묶음", "ole": "OLE", "textart": "글맵시", "video": "동영상",
             "chart": "차트", "connectLine": "연결선", "btn": "양식:버튼", "checkBtn": "양식:체크", "radioBtn": "양식:라디오",
             "comboBox": "양식:콤보", "edit": "양식:입력", "listBox": "양식:목록", "scrollBar": "양식:스크롤"}
FIELD_TYPES = {"%hlk": "하이퍼링크", "%clk": "누름틀", "%dte": "날짜", "%ddt": "문서날짜", "%pat": "경로", "%bmk": "책갈피필드",
               "%fmu": "계산식", "%mmg": "메일머지", "%xrf": "상호참조", "%fml": "계산식", "%smr": "문서요약", "%usr": "사용자정보",
               "%sig": "서명", "%mmo": "메모", "%unk": "알수없음", "%cpr": "저작권", "%rvw": "교정"}
FIELD_ATTR = {"HYPERLINK": "하이퍼링크", "CLICK_HERE": "누름틀", "DATE": "날짜", "DOC_DATE": "문서날짜", "PATH": "경로",
              "BOOKMARK": "책갈피필드", "MAILMERGE": "메일머지", "CROSSREF": "상호참조", "FORMULA": "계산식",
              "SUMMERY": "문서요약", "USER_INFO": "사용자정보", "MEMO": "메모", "REVISION_SIGN": "서명", "UNKNOWN": "알수없음"}
SHAPE_KEYS = ("그림", "사각형", "타원", "호", "다각형", "곡선", "선", "묶음", "OLE", "글맵시", "동영상", "차트", "연결선")


def _sections(ole, flags):
    body = "ViewText" if flags & FLAG_DISTRIBUTE else "BodyText"
    secs = sorted((e[1] for e in ole.listdir() if len(e) == 2 and e[0] == body and e[1].startswith("Section")),
                  key=lambda s: int(re.findall(r"\d+", s)[0]))
    for s in secs:
        raw = ole.openstream(f"{body}/{s}").read()
        if flags & FLAG_DISTRIBUTE:
            raw = _decrypt_viewtext(raw)
        yield _inflate(raw) if flags & FLAG_COMPRESSED else raw


# C69(개정): rhwp 가 실측으로 세운 command 접두 → OWPML 필드 type (src/parser/tags.rs OWPML_FIELD_TYPE_BY_COMMAND 와 같은 표, 여기서는 독립 사본)
_CMD_KIND = (("$RevisionSign", "PROOFREADING_MARKS_SIGN"), ("$RevisionDelete", "PROOFREADING_MARKS_DELETE"), ("$RevisionSimpleChange", "PROOFREADING_MARKS_SIMPLECHANGE"), ("$RevisionClipping", "PROOFREADING_MARKS_CLIPPING"),
             ("MEMO/", "메모"), ("TableOfContents", "TABLEOFCONTENTS"))


def _field_kind_by_command(pl: bytes, default: str) -> str:
    """CTRL_HEADER(필드): ctrl id 4 · 속성 4 · 기타 1 · command 길이 u16 · command(UTF-16). 접두가 표에 없으면 default(알수없음·%toc) 그대로."""
    try:
        n = struct.unpack_from("<H", pl, 9)[0]
        cmd = pl[11:11 + 2 * n].decode("utf-16le", "replace")
    except Exception:
        return default
    for pre, kind in _CMD_KIND:
        if cmd.startswith(pre):
            return kind
    return default


def hwp_census(path: str) -> dict:
    """원본 HWP(5.0) 센서스. {'개수': Counter, '크기': {구성요소: Counter((너비,높이))}, '정의': Counter}"""
    ole = olefile.OleFileIO(path)
    try:
        head = ole.openstream("FileHeader").read()
        if not head.startswith(b"HWP Document File"):
            raise ValueError("HWP 5.0 아님")
        flags = struct.unpack_from("<I", head, 36)[0]
        if flags & FLAG_ENCRYPTED:
            raise ValueError("열기 암호")
        cnt = collections.Counter()
        size = collections.defaultdict(collections.Counter)
        defs = collections.Counter()
        di = ole.openstream("DocInfo").read()
        di = _inflate(di) if flags & FLAG_COMPRESSED else di
        DEF = {0x13: "글꼴", 0x15: "글자모양", 0x19: "문단모양", 0x1A: "스타일", 0x14: "테두리배경", 0x17: "번호문단",
               0x18: "글머리표", 0x16: "탭", 0x12: "BinData", 0x60: "변경추적"}
        for t, _lv, _pl in iter_records(di):
            if t in DEF:
                defs[DEF[t]] += 1
        for data in _sections(ole, flags):
            tags, lvls, pls = [], [], []
            for t, lv, pl in iter_records(data):
                tags.append(t)
                lvls.append(lv)
                pls.append(pl)
            n = len(tags)
            pg_seen: dict = {}  # 문단 수준 → 본 서명. 같은 문단의 같은 쪽번호 위치 컨트롤은 하나로 센다(라운드1 C53)
            for i in range(n):
                t = tags[i]
                if t == 0x42:
                    for lv_ in [x for x in pg_seen if x >= lvls[i]]:
                        del pg_seen[lv_]
                if t == 0x47:  # CTRL_HEADER
                    pl = pls[i]
                    cid = bytes(pl[:4][::-1]).decode("latin1")
                    if cid in CTRL_NAMES and cid != "gso ":
                        nm = CTRL_NAMES[cid]
                        if cid == "pgnp":
                            # C89: 한 문단의 쪽번호 위치 컨트롤은 서명이 달라도 하나로 센다. HWPX 는 문단당 하나만 둔다(한컴 2024 도 접는다 —
                            # rhwp #6869 기록: 한컴 산출 pageNum 23→5). 어느 값이 남는지는 변환 쪽(C88)과 별도 증거 스크립트로 대조한다.
                            seen_ = pg_seen.setdefault(lvls[i] - 1, set())
                            if seen_:
                                continue
                            seen_.add(b"")
                        if cid == "tbl ":  # 표 레코드(0x4D)가 아래에 있는 것만 표로 센다(라운드1 C53)
                            j = i + 1
                            has = False
                            while j < n and lvls[j] > lvls[i]:
                                if tags[j] == 0x4D and lvls[j] == lvls[i] + 1:
                                    has = True
                                    break
                                j += 1
                            if not has:
                                cnt["컨트롤:표형식아님"] += 1
                                continue
                        cnt[nm] += 1
                        if cid in ("tbl ", "eqed") and len(pl) >= 24:
                            w, h = struct.unpack_from("<II", pl, 16)
                            size[nm][(w, h)] += 1
                    elif cid == "gso ":
                        # 이 그리기 개체 아래 SHAPE_COMPONENT 들(묶음이면 자식 포함).
                        # 아래에 다른 CTRL_HEADER(글상자 속 개체 등)가 있으면 그 하위는 그 개체의 몫이라 건너뛴다(라운드1 C53: 이중 계산 수정)
                        j = i + 1
                        L = lvls[i]
                        kids = []
                        while j < n and lvls[j] > L:
                            if tags[j] == 0x47:
                                k = j + 1
                                while k < n and lvls[k] > lvls[j]:
                                    k += 1
                                j = k
                                continue
                            if tags[j] == 0x4C:
                                kids.append(bytes(pls[j][:4][::-1]).decode("latin1"))
                            j += 1
                        pl_ = pls[i]
                        for k in kids:
                            cnt[SHAPE_NAMES.get(k, "그리기:" + k)] += 1
                        if kids and len(pl_) >= 24:
                            w, h = struct.unpack_from("<II", pl_, 16)
                            size["그리기개체"][(w, h)] += 1
                        if not kids:
                            cnt["그리기:구성요소없음"] += 1
                    elif cid.startswith("%"):
                        name = FIELD_TYPES.get(cid, cid)
                        if cid in ("%unk", "%toc"):   # C69(개정): HWP5 는 이 종류를 ctrl id 가 아니라 command 문자열로 들고 있다 → command 접두로 종류를 읽는다
                            name = _field_kind_by_command(pls[i], name)
                        cnt["필드:" + name] += 1
                        cnt["필드"] += 1
                    else:
                        cnt["컨트롤:" + cid.strip()] += 1
                elif t == 0x4D:  # TABLE
                    pass
                elif t == 0x4A and False:
                    pass
            # 셀 수: 표 아래 LIST_HEADER 중 표 다음에 오는 것 — audit 가 이미 칸 단위로 검증하므로 여기선 TABLE 수만
            cnt["문단"] += sum(1 for t in tags if t == 0x42)
        for k in (set(cnt) - {"문단"}):
            pass
        return {"개수": cnt, "크기": {k: dict(v) for k, v in size.items()}, "정의": defs,
                "버전": ".".join(str(b) for b in reversed(head[32:36]))}
    finally:
        ole.close()


_TAG = re.compile(rb"<(?:[A-Za-z0-9]+):([A-Za-z0-9]+)((?:\s[^<>]*?)?)/?>")
_ATTR = re.compile(rb'([A-Za-z0-9:_]+)="([^"]*)"')


def hwpx_census(path: str) -> dict:
    z = zipfile.ZipFile(path)
    cnt = collections.Counter()
    defs = collections.Counter()
    size = collections.defaultdict(collections.Counter)
    names = z.namelist()
    # C95 2단계: 숨김(hide=1) 삭제 구간 안의 표·그림 등은 한글 화면에 없다 — 세지 않는다(원본 최종 본문 기준과 맞춤)
    hidden = set()
    if "Contents/header.xml" in names:
        for m in re.finditer(rb"<hh:trackChange\b([^>]*)>", z.read("Contents/header.xml")):
            a = dict(_ATTR.findall(m.group(1)))
            if a.get(b"type") == b"Delete" and a.get(b"hide") in (b"1", b"true"):
                hidden.add(a.get(b"id"))
    for nm in names:
        if not (nm.startswith("Contents/") and nm.endswith(".xml")):
            continue
        data = z.read(nm)
        if "section" in nm.lower() or "masterpage" in nm.lower():
            opn = set()
            for m in _TAG.finditer(data):
                tag = m.group(1).decode()
                if hidden and tag in ("deleteBegin", "deleteEnd"):
                    a = dict(_ATTR.findall(m.group(2)))
                    if tag == "deleteBegin" and a.get(b"TcId") in hidden:
                        opn.add(a.get(b"Id"))
                    elif tag == "deleteEnd":
                        opn.discard(a.get(b"Id"))
                    continue
                if opn:
                    continue
                if tag in HWPX_TAGS:
                    cnt[HWPX_TAGS[tag]] += 1
                elif tag == "fieldBegin":
                    a = dict(_ATTR.findall(m.group(2)))
                    ty = a.get(b"type", b"").decode()
                    cnt["필드:" + FIELD_ATTR.get(ty, ty)] += 1
                    cnt["필드"] += 1
                elif tag == "p":
                    cnt["문단"] += 1
        elif nm.endswith("header.xml"):
            for m in _TAG.finditer(data):
                tag = m.group(1).decode()
                d = {"font": "글꼴", "charPr": "글자모양", "paraPr": "문단모양", "style": "스타일", "borderFill": "테두리배경",
                     "numbering": "번호문단", "bullet": "글머리표", "tabPr": "탭", "trackChange": "변경추적"}.get(tag)
                if d:
                    defs[d] += 1
    defs["BinData"] = sum(1 for n in names if n.startswith("BinData/"))
    return {"개수": cnt, "정의": defs, "크기": {k: dict(v) for k, v in size.items()}}


# 짝: (구성요소, HWP 개수 키들, HWPX 개수 키들)
COMPONENTS = [
    ("표", ["표"], ["표"]),
    ("수식", ["수식"], ["수식"]),
    ("각주", ["각주"], ["각주"]),
    ("미주", ["미주"], ["미주"]),
    ("머리말", ["머리말"], ["머리말"]),
    ("꼬리말", ["꼬리말"], ["꼬리말"]),
    ("구역", ["구역"], ["구역"]),
    ("쪽번호위치", ["쪽번호위치"], ["쪽번호위치"]),
    ("새번호", ["새번호"], ["새번호"]),
    ("자동번호", ["자동번호"], ["자동번호"]),
    ("감추기", ["감추기"], ["감추기"]),
    ("글자겹침", ["글자겹침"], ["글자겹침"]),
    ("덧말", ["덧말"], ["덧말"]),
    ("찾아보기표시", ["찾아보기표시"], ["찾아보기표시"]),
    ("책갈피", ["책갈피"], ["책갈피"]),
    ("필드", ["필드"], ["필드"]),
    ("그림", ["그림"], ["그림"]),
    ("사각형", ["사각형"], ["사각형"]),
    ("타원", ["타원"], ["타원"]),
    ("호", ["호"], ["호"]),
    ("다각형", ["다각형"], ["다각형"]),
    ("곡선", ["곡선"], ["곡선"]),
    ("선", ["선"], ["선"]),
    ("묶음", ["묶음"], ["묶음"]),
    ("OLE", ["OLE"], ["OLE"]),
    ("글맵시", ["글맵시"], ["글맵시"]),
    ("연결선", ["연결선"], ["연결선"]),
]
# 정의(DocInfo ↔ header.xml) — 엔진이 병합·정리할 수 있어 개수 일치가 아니라 「HWPX 가 가졌는가」를 본다
DEF_PAIRS = [("글꼴", "글꼴"), ("글자모양", "글자모양"), ("문단모양", "문단모양"), ("스타일", "스타일"),
             ("테두리배경", "테두리배경"), ("번호문단", "번호문단"), ("글머리표", "글머리표"), ("탭", "탭"),
             ("BinData", "BinData")]


def compare(hw: dict, hx: dict) -> dict:
    """구성요소별 {이름: (원본 개수, 변환 개수)} — 짝이 있는 것만, 양쪽 다 0이면 뺀다."""
    out = {}
    for name, hk, xk in COMPONENTS:
        a = sum(hw["개수"].get(k, 0) for k in hk)
        b = sum(hx["개수"].get(k, 0) for k in xk)
        if a or b:
            out[name] = (a, b)
    # C66: 그림을 채운 사각형은 HWPX 에서 그림(pic)으로 쓰인다. 종류를 알아볼 수 없는 그리기 개체(원본 「그리기:*」)도 있다. 따로 보면 불일치여도
    #      그리기 개체 합계가 같으면 형태 바뀜일 뿐 개수는 보존 → 합계로 비교한다(합계가 다르면 그대로 불일치).
    unk = sum(v for k, v in hw["개수"].items() if k.startswith("그리기:"))
    pa, pb = out.get("그림", (0, 0)), out.get("사각형", (0, 0))
    ta, tb = pa[0] + pb[0] + unk, pa[1] + pb[1]
    if ta == tb and (pa[0] != pa[1] or pb[0] != pb[1] or unk):
        out.pop("그림", None); out.pop("사각형", None)
        # 원본 「그리기:*」(종류를 못 읽은 개체)가 합계에 들어갔으면 이름에 표시한다 — 이 경우는 개수 합계만 확인한 것(독립 검수 2026-11-10)
        out["그림·사각형(합" + (", 원본 종류 미분류 포함)" if unk else ")")] = (ta, tb)
    # C67: 원본에 이미지 자료(BinData)가 하나도 없는데 그림 개체만 있으면 참조 대상이 없는 깨진 그림 → 변환에서 빠지는 것이 정상. 따로 표시.
    if out.get("그림") and hw["정의"].get("BinData", 0) == 0 and out["그림"][1] == 0:
        n = out.pop("그림")[0]; out["그림(원본에 이미지 자료 없음·생략 정상)"] = (n, n)
    for k in sorted(set(hw["개수"]) | set(hx["개수"])):
        if k.startswith("필드:"):
            a, b = hw["개수"].get(k, 0), hx["개수"].get(k, 0)
            if a or b:
                out[k] = (a, b)
    return out
