"""C95 변경 추적 삭제 이력 싣기 — 원본 HWP 의 변경 추적(삽입·삭제)을 변환본 HWPX 에 한컴 한글이 저장하는 모양으로 되살린다.
엔진(rhwp)은 숨김 처리된 삭제 글을 HWPX 에 싣지 않고 변경 추적 정의(hh:trackChanges)도 쓰지 않는다. 한컴 한글은 삭제된 글을
<hp:deleteBegin Id TcId/>…<hp:deleteEnd Id TcId paraend="0"/>, 삽입된 글을 insertBegin/insertEnd 로 감싸 본문에 두고,
header.xml 의 refList 끝에 trackChanges·trackChangeAuthors 를 둔다(한컴 한글 13 출력 구조 대조로 확인).
안전 장치: 원본 문단과 변환본 문단을 글로 맞춰 보아 한 글자도 어긋나지 않는 문단만 고친다. 컨트롤(탭·표·그림 등)이 낀 문단,
문단 끝에 걸친 구간은 고치지 않고 건너뛰며 건너뛴 개수를 notes 로 알린다. 원본 파일은 바꾸지 않는다."""
from __future__ import annotations

import difflib
import re
import struct
import zipfile
import zlib
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

_T_PARA_HEADER, _T_PARA_TEXT, _T_RANGE = 0x42, 0x43, 0x46
_T_TRACK, _T_TRACK_AUTHOR = 0x60, 0x61
_EXT = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}   # 8 유닛 컨트롤
_INL = {4, 5, 6, 7, 8, 9, 19, 20}


def _records(data: bytes):
    p = 0
    while p + 4 <= len(data):
        h = struct.unpack_from("<I", data, p)[0]
        p += 4
        tag, lv, sz = h & 0x3FF, (h >> 10) & 0x3FF, h >> 20
        if sz == 0xFFF:
            sz = struct.unpack_from("<I", data, p)[0]
            p += 4
        yield tag, lv, data[p:p + sz]
        p += sz


def _inflate(b: bytes) -> bytes:
    return zlib.decompress(b, -15)


def read_tracked(src: str):
    """(변경 추적 정의 목록, 작성자 목록, 문단 목록) — 정의가 없으면 None.
    정의: dict(kind 'Insert'|'Delete', date, author, hide). 문단: dict(text 보이는 글, full 전체 글(컨트롤 없을 때만), ranges, plain)"""
    import olefile
    ole = olefile.OleFileIO(src)
    try:
        fh = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", fh, 36)[0]
        if flags & 2 or flags & 16:
            return None
        comp = bool(flags & 1)
        di = ole.openstream("DocInfo").read()
        di = _inflate(di) if comp else di
        defs, authors = [], []
        for tag, _lv, pl in _records(di):
            if tag == _T_TRACK and len(pl) >= 26:
                kind = struct.unpack_from("<I", pl, 0)[0]
                y, mo, d, h, mi = struct.unpack_from("<5H", pl, 4)
                author = struct.unpack_from("<H", pl, 14)[0]
                hide = struct.unpack_from("<I", pl, 22)[0]
                try:
                    dt = datetime(y, mo, d, h, mi) - timedelta(hours=9)   # 한글은 현지(KST) 시각을 저장하고 HWPX 는 UTC 로 적는다
                    date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    date = "1970-01-01T00:00:00Z"
                defs.append({"kind": _KIND.get(kind, "Insert"), "raw_kind": kind, "date": date, "author": author or 1, "hide": 1 if hide == 1 else 0})
            elif tag == _T_TRACK_AUTHOR and len(pl) >= 2:
                n = struct.unpack_from("<I", pl, 0)[0]
                name = pl[4:4 + 2 * n].decode("utf-16-le", "replace")
                mark = struct.unpack_from("<I", pl, 4 + 2 * n)[0] if len(pl) >= 8 + 2 * n else 1
                authors.append({"name": name, "mark": mark or 1})
        if not defs:
            return None
        # 엔진 입력 사본(viewtext.engine_copy_unhidden)이면 원래 숨김 값을 되살린다
        side = src + ".hidden_tc"
        if not __import__("os").path.exists(side):
            side = src + ".hidden_tc.legacy"   # 다시 변환(최종 본문) 사본
        try:
            with open(side, encoding="ascii") as f:
                for x in f.read().split(","):
                    if x.strip().isdigit() and 1 <= int(x) <= len(defs):
                        defs[int(x) - 1]["hide"] = 1
        except OSError:
            pass
        # 비배포 문서의 ViewText(엔진 입력 사본에서는 ZZZZZZZZ)가 변경 추적 구간이 든 판이다(한컴 한글 13 출력과 대조해 확인).
        # BodyText 는 삭제가 반영된 최종 글이라 변경 추적 구간이 없다. 배포용(플래그 4)은 암호화 본문이라 다루지 않는다.
        if flags & 4:
            return None
        body = next((nm for nm in ("ViewText", "ZZZZZZZZ") if any(len(e) == 2 and e[0] == nm for e in ole.listdir())), None)
        if body is None:
            return None
        secs = sorted((e[1] for e in ole.listdir() if len(e) == 2 and e[0] == body and e[1].startswith("Section")),
                      key=lambda s: int(re.findall(r"\d+", s)[0]))
        paras = []
        for s in secs:
            raw = ole.openstream(f"{body}/{s}").read()
            data = _inflate(raw) if comp else raw
            recs = list(_records(data))
            n = len(recs)
            memo_lv = None   # 메모 목록(HWPTAG_MEMO_LIST 0x5D) 뒤의 문단은 메모 내용 — HWPX 에서는 필드(MEMO) 안에 들어가 순서가 다르다
            for i, (tag, lv, _pl) in enumerate(recs):
                if tag == 0x5D:
                    memo_lv = lv if memo_lv is None else min(memo_lv, lv)
                    continue
                if tag != _T_PARA_HEADER:
                    continue
                if memo_lv is not None and lv >= memo_lv:
                    continue
                text = b""
                rng = b""
                k = i + 1
                while k < n and recs[k][1] > lv:
                    if recs[k][1] == lv + 1:
                        if recs[k][0] == _T_PARA_TEXT:
                            text = recs[k][2]
                        elif recs[k][0] == _T_RANGE:
                            rng = recs[k][2]
                    k += 1
                if not text and rng:
                    # C105: 빈 문단은 PARA_TEXT 레코드가 없지만 문단 끝(나눔) 글자 하나를 가진다(범위 표식 [0,1)).
                    # 이 글자를 빼면 빈 문단의 나눔 삭제·삽입을 놓쳐 한컴보다 빈 줄이 남는다(한컴 열기 시험 2026-11-10, 쪽 수 증가 원인).
                    text = b"\r\x00"
                pp = _para(text, rng, defs)
                pp["lv"] = lv
                paras.append(pp)
        return defs, authors, paras
    finally:
        ole.close()


# 변경 종류(DocInfo 변경 추적 레코드 첫 u32) → 한컴 HWPX hh:trackChange@type. 한컴 저장본(0195 등)과 대조해 확인:
# 16 Insert·17 Delete 는 본문 insertBegin/deleteBegin 표식, 18 CharShape 는 hp:run@charTcId, 19 ParaShape 는 hp:p@paraTcId 로 쓴다.
# 이전 판은 18·19 를 Insert 로 보고 삽입 표식을 달았다(잘못) — C95 정정.
NEED_FALLBACK: list = []   # 전체 구조 모드가 안 된 변환본(다시 변환해야 함) — viewtext.convert_hwp 가 비운다
_KIND = {0x10: "Insert", 0x11: "Delete", 0x12: "CharShape", 0x13: "ParaShape"}
_MARKED = ("Insert", "Delete")


def _para(text: bytes, rng: bytes, defs):
    n = len(text) // 2
    units = struct.unpack("<%dH" % n, text[:2 * n]) if n else ()
    hid = [False] * n
    marks = []   # (s, e, kind, tc)
    for off in range(0, len(rng) - 11, 12):
        s, e, tg = struct.unpack_from("<III", rng, off)
        kind, ident = tg >> 24, tg & 0xFFFFFF
        if 1 <= ident <= len(defs) and defs[ident - 1]["raw_kind"] == kind:
            if defs[ident - 1]["kind"] not in _MARKED:
                continue   # 글자·문단 모양 변경 이력은 본문 표식이 아니다(한컴은 charTcId/paraTcId) — 싣지 않고 정의만 header 에 둔다
            marks.append((s, min(e, n), ident))
            if defs[ident - 1]["hide"] == 1 and defs[ident - 1]["kind"] == "Delete":
                for u in range(s, min(e, n)):
                    hid[u] = True
    plain = True
    vis = []
    full = []
    toks = []            # (유닛 위치, 종류 c=글자·o=컨트롤, 글자) — 전체 구조 모드(apply_full)에서 변환본 조각과 맞춘다
    u2c = [0] * (n + 1)  # 유닛 위치 → 앞에 있는 글자 수(표식 위치를 글자 위치로)
    x = 0
    while x < n:
        c = units[x]
        step = 1
        ch = None
        if c == 9:   # 탭(인라인 8유닛) — 글자 한 개(\t). HWPX 에서는 hp:t 안 <hp:tab …/> 요소 하나
            ch, step = "\t", min(8, n - x)
        elif c in _SPECIAL:   # 묶음 빈칸(30)·고정폭 빈칸(31)·하이픈(24) — 1유닛, HWPX 에서는 <hp:nbSpace/> 등
            ch = _SPECIAL[c]
        elif c == 10:   # 줄 바꿈 — HWPX 에서는 hp:t 안 <hp:lineBreak/>
            ch = "\n"
            plain = False
        elif c in _EXT or c in _INL:
            plain = False
            step = min(8, n - x)
            toks.append((x, "o", None))
        elif c < 32:
            if not (c == 13 and x == n - 1):
                plain = False
        else:
            ch = chr(c)
        for k in range(x, min(n, x + step)):
            u2c[k] = len(full)
        if ch is not None:
            toks.append((x, "c", ch))
            if ch != "\n":   # 줄 바꿈은 글(full·vis)에 넣지 않는다(이전 판과 같은 글 정의)
                full.append(ch)
                if not hid[x]:
                    vis.append(ch)
        x += step
    u2c[n] = len(full)
    end_del = bool(n and units[n - 1] == 13 and hid[n - 1])   # 문단 끝(나눔)이 숨김 삭제됨 → 최종본에서는 다음 문단과 붙는다
    cmarks = [(u2c[a], u2c[min(b, n)], tc) for (a, b, tc) in marks]
    return {"text": "".join(vis), "full": "".join(full) if plain else None, "marks": cmarks if plain else [], "plain": plain, "n": n,
            "has_marks": bool(marks), "end_del": end_del, "toks": toks, "umarks": marks, "hid": hid,
            "end_unit": n - 1 if n and units[n - 1] == 13 else n}


def _group(hp):
    """C95 보강: 변경 추적에서 문단 나눔을 지우면 ViewText 에는 문단이 둘로 남고 최종 본문(BodyText)·변환본에서는 하나로 붙는다
    (0195: ViewText 138문단 → 변환본 70문단). 문단 끝이 숨김 삭제된 문단을 다음 문단과 묶어 최종 문단 하나에 대응시킨다.
    묶은 문단의 전체 글·표식은 이어 붙이고 표식 위치는 앞 문단 길이만큼 민다."""
    out, cur = [], []
    for p in hp:
        cur.append(p)
        if not p.get("end_del"):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    G = []
    for g in out:
        if len(g) == 1:
            G.append(g[0])
            continue
        plain = all(x["plain"] for x in g)
        full, marks, off = [], [], 0
        for x in g:
            if plain:
                for (a, b, tc) in x["marks"]:
                    marks.append((a + off, b + off, tc))
                full.append(x["full"])
                off += len(x["full"])
        G.append({"text": "".join(x["text"] for x in g), "full": "".join(full) if plain else None, "marks": marks if plain else [],
                  "plain": plain, "n": sum(x["n"] for x in g), "has_marks": any(x["has_marks"] for x in g), "merged": len(g)})
    return G


# ---------------------------------------------------------------- HWPX 쪽
_TOK = re.compile(r"<hp:p\b[^>]*?(?<!/)>|</hp:p>|<hp:t>(?P<in>.*?)</hp:t>|<hp:t\s[^>]*?(?<!/)>.*?</hp:t>", re.S)


def _scan(xml: str):
    """문단(여는 순서) 목록: dict(ts=[(시작, 끝, 안쪽글)], complex). 글 조각은 가장 가까운 바깥 문단에 속한다."""
    paras, stack = [], []
    for m in _TOK.finditer(xml):
        g = m.group(0)
        if g.startswith("<hp:p"):
            d = {"ts": [], "complex": False}
            paras.append(d)
            stack.append(d)
        elif g == "</hp:p>":
            if stack:
                stack.pop()
        elif stack:
            inner = m.group("in")
            if inner is None or not _TABONLY.fullmatch(inner):
                stack[-1]["complex"] = True
            else:
                stack[-1]["ts"].append((m.start("in"), m.end("in"), inner))
    return paras


# 1유닛 특수 글자 ↔ HWPX 요소. 문자 대신 개인 사용 영역 표지 글자를 쓴다(원문 글에 나올 일이 없는 값).
_SPECIAL = {30: "\ue030", 31: "\ue031", 24: "\ue024"}
_SPECIAL_XML = {"\ue030": "<hp:nbSpace/>", "\ue031": "<hp:fwSpace/>", "\ue024": "<hp:hyphen/>"}
_ELEM_CHAR = {"nbSpace": "\ue030", "fwSpace": "\ue031", "hyphen": "\ue024"}
_TABONLY = re.compile(r"(?:[^<]|<hp:(?:tab|nbSpace|fwSpace|hyphen)\b[^>]*/>)*", re.S)
_UNIT = re.compile(r"<hp:(?:tab|nbSpace|fwSpace|hyphen)\b[^>]*/>|&[a-zA-Z#0-9]+;|[^<&]", re.S)
_TABXML = '<hp:tab width="0" leader="0" type="1"/>'


def _units(inner: str):
    """hp:t 안쪽 → 보이는 글자 단위 목록(XML 조각 그대로). 탭 요소는 한 단위."""
    return _UNIT.findall(inner)


def _uchar(u: str) -> str:
    if u.startswith("<hp:"):
        nm = re.match(r"<hp:(\w+)", u).group(1)
        return "\t" if nm == "tab" else _ELEM_CHAR.get(nm, "?")
    return _unesc(u)


def _unesc(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def apply(src: str, dst: str):
    """원본 src(HWP) 의 변경 추적을 dst(HWPX) 에 싣는다. (고친 문단 수, 건너뛴 문단 수, 비고)를 돌려준다. 해당 없으면 (0, 0, '')."""
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return 0, 0, ""
        r = read_tracked(src)
    except Exception:
        return 0, 0, ""
    if not r:
        return 0, 0, ""
    defs, authors, hp = r
    import os as _os
    unhidden_input = _os.path.exists(src + ".hidden_tc")
    if unhidden_input:
        # 엔진은 숨김을 풀고 전체 구조로 변환했다. 전체 구조 모드로 표식을 다 걸지 못하면 지운 글이 보이는 글로 남으므로
        # 이 변환본은 쓰면 안 된다 — 다시 변환(이전 방식: 최종 본문)하라고 알린다(viewtext.convert_hwp 가 처리).
        try:
            full = apply_full(src, dst, defs, authors, hp)
        except Exception:
            full = None
        if full is None:
            NEED_FALLBACK.append(dst)
            return 0, 0, "전체 구조 모드 불가 — 최종 본문으로 다시 변환"
        return full
    hp = _group(hp)
    if not any(p["has_marks"] for p in hp):
        return 0, 0, ""
    zin = zipfile.ZipFile(dst)
    names = zin.namelist()
    secnames = sorted((n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)), key=lambda s: int(re.findall(r"\d+", s)[0]))
    xmls = {n: zin.read(n).decode("utf-8") for n in secnames}
    header = zin.read("Contents/header.xml").decode("utf-8")
    # 변환본 문단 목록(구역 순서대로 이어 붙임)
    xp = []
    for n in secnames:
        for d in _scan(xmls[n]):
            d["sec"] = n
            xp.append(d)
    def xtext(d):
        return "".join(_uchar(u) for (_a, _b, i) in d["ts"] for u in _units(i))
    A = [p["text"] for p in hp]
    B = [xtext(d) for d in xp]
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    pair = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pair[i1 + k] = j1 + k
    done = skipped = 0
    edits = {}   # sec -> [(start, end, newinner)]
    uid = [0]
    used_tc = set()
    for i, p in enumerate(hp):
        if not p["has_marks"]:
            continue
        j = pair.get(i)
        if j is None or not p["plain"] or xp[j]["complex"] or not xp[j]["ts"]:
            skipped += 1
            continue
        full = p["full"]
        marks = [(s, e, tc) for (s, e, tc) in p["marks"] if e > s and e <= len(full)]
        # 같은 변경(TcId)의 구간이 겹치거나 중첩되면(0207 실측) 하나로 합친다 — 시작·끝 표식 짝이 어긋나지 않게
        mm = {}
        for (s0, e0, tc) in sorted(marks, key=lambda x: (x[2], x[0], x[1])):
            L = mm.setdefault(tc, [])
            if L and s0 <= L[-1][1]:
                L[-1][1] = max(L[-1][1], e0)
            else:
                L.append([s0, e0])
        marks = sorted(((a, b, tc) for tc, L in mm.items() for a, b in L), key=lambda x: (x[0], x[1]))
        if any(e > len(full) for (_s, e, _t) in p["marks"]):
            skipped += 1
            continue
        # 전체 글(숨김 포함)의 각 글자 → 보이는지
        hidden = [False] * len(full)
        for (s, e, tc) in marks:
            if defs[tc - 1]["kind"] == "Delete" and defs[tc - 1]["hide"] == 1:
                for u in range(s, e):
                    hidden[u] = True
        # 경계 지점마다 시작·끝 표식
        starts, ends = {}, {}
        for (s, e, tc) in marks:
            starts.setdefault(s, []).append(tc)
            ends.setdefault(e, []).append(tc)
        ts = xp[j]["ts"]
        units = [_units(i2) for (_a, _b, i2) in ts]
        lens = [len(u) for u in units]
        if sum(lens) != sum(1 for h in hidden if not h):
            skipped += 1
            continue
        out = [[] for _ in ts]
        cur, used = 0, 0
        def emit(piece):
            nonlocal cur
            out[cur].append(piece)
        def advance():
            nonlocal cur, used
            while cur < len(ts) - 1 and used >= lens[cur]:
                cur += 1
                used = 0
        pend = ""
        def flush():
            nonlocal pend, used
            if pend:
                x = escape(pend).replace("\t", _TABXML)
                for k, v in _SPECIAL_XML.items():
                    x = x.replace(k, v)
                emit(x)
                pend = ""

        def emit_visible():
            nonlocal used
            emit(units[cur][used])   # 보이는 글자는 변환본의 원래 조각(탭 요소 포함)을 그대로 쓴다
            used += 1
        open_ids = {}
        bad = False
        for u in range(len(full) + 1):
            for tc in ends.get(u, []):
                flush()
                kind = defs[tc - 1]["kind"]
                emit(f'<hp:{kind.lower()}End Id="{open_ids.pop(tc, 0)}" TcId="{tc}" paraend="0"/>')
            for tc in starts.get(u, []):
                flush()
                if not hidden[u] if u < len(full) else False:
                    advance()
                uid[0] += 1
                open_ids[tc] = uid[0]
                kind = defs[tc - 1]["kind"]
                emit(f'<hp:{kind.lower()}Begin Id="{uid[0]}" TcId="{tc}"/>')
                used_tc.add(tc)
            if u == len(full):
                break
            ch = full[u]
            if hidden[u]:
                pend += ch
            else:
                if pend:
                    flush()
                advance()
                if _uchar(units[cur][used]) != ch:
                    bad = True
                    break
                emit_visible()
        flush()
        if bad:
            skipped += 1
            continue
        fx = edits.setdefault(xp[j]["sec"], [])
        for t, (a, b, _i) in enumerate(ts):
            fx.append((a, b, "".join(out[t])))
        done += 1
    if not done:
        return 0, skipped, ""
    # 구역 XML 에 쓰기
    newx = {}
    for n, lst in edits.items():
        s = xmls[n]
        for a, b, new in sorted(lst, reverse=True):
            s = s[:a] + new + s[b:]
        newx[n] = s
    tcxml = "".join(f'<hh:trackChange type="{d["kind"]}" date="{d["date"]}" authorID="{d["author"]}" hide="{d["hide"]}" id="{k + 1}"/>' for k, d in enumerate(defs))
    authxml = "".join(f'<hh:trackChangeAuthor name="{escape(a["name"])}" mark="{a["mark"]}" id="{k + 1}"/>' for k, a in enumerate(authors or [{"name": "user", "mark": 1}]))
    blk = f'<hh:trackChanges itemCnt="{len(defs)}">{tcxml}</hh:trackChanges><hh:trackChangeAuthors itemCnt="{max(len(authors), 1)}">{authxml}</hh:trackChangeAuthors>'
    if "<hh:trackChanges" not in header and "</hh:refList>" in header:
        header = header.replace("</hh:refList>", blk + "</hh:refList>", 1)
    elif "<hh:trackChanges" not in header:
        return 0, skipped, "header.xml 에 refList 가 없어 변경 추적 정의를 넣지 못함"
    tmp = dst + ".trk"
    with zipfile.ZipFile(tmp, "w") as zo:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in newx:
                data = newx[info.filename].encode("utf-8")
            elif info.filename == "Contents/header.xml":
                data = header.encode("utf-8")
            zo.writestr(info, data, compress_type=info.compress_type)
    zin.close()
    import os
    os.replace(tmp, dst)
    return done, skipped, ""


# ---------------------------------------------------------------- 전체 구조 모드 (C95 2단계)
# 원인: 엔진(rhwp)은 ViewText 를 읽을 때 DocInfo 의 숨김(hide=1) 삭제를 미리 「투영」해 지운 글·지운 표·지운 문단 나눔을 없앤 뒤 HWPX 를
# 만든다(src/parser/tracked_viewtext.rs). 그래서 변환본에는 이력을 걸 자리(문단·표)가 없었다(0195: ViewText 138문단·표 5 → 변환본 70문단·표 3).
# 설계: 엔진에 넘기는 사본에서만 DocInfo 변경 추적 정의의 hide 를 0 으로 바꾼다(viewtext.engine_copy). 엔진은 아무것도 숨기지 않고
# ViewText 구조 그대로(문단·표·글 전부) HWPX 를 만든다. 여기서 원본의 구간 표식(PARA_RANGE_TAG)을 유닛 단위로 변환본 조각에 맞춰
# deleteBegin/End·insertBegin/End 를 넣고, 문단 끝(나눔)까지 덮는 구간은 paraend="1", 지운 나눔 다음 문단은 merged="1" 로 한컴 표기와 같게 쓴다.
# header 의 hide 는 원본 값 그대로이므로 한글은 지운 내용을 숨겨 보여 준다. 줄 배치 캐시는 지운 글까지 넣고 계산된 것이라 이 문서에서만 지운다.

_TAG = re.compile(r"<(/?)([A-Za-z]+:[A-Za-z]+)\b[^>]*?(/?)>", re.S)
_INLINE_CH = {"tab": "\t", "nbSpace": "", "fwSpace": "", "hyphen": "", "lineBreak": "\n"}
_ZERO = {"markpenBegin", "markpenEnd", "titleMark", "insertBegin", "insertEnd", "deleteBegin", "deleteEnd"}


def _slots_with_text(xml: str):
    """_paragraph_slots 에 hp:t 안 글자 조각을 위치 순서대로 끼운다."""
    paras = []
    stack = []      # 요소 이름 스택
    pstack = []     # 열린 문단 dict 스택
    owner = []      # 각 스택 칸의 「이 요소가 속한 문단 dict 또는 None(불투명 내부)」
    pos = 0
    for m in _TAG.finditer(xml):
        # 앞선 글
        if m.start() > pos and stack and stack[-1] == "hp:t" and owner and owner[-1] is not None:
            P = owner[-1]
            seg = xml[pos:m.start()]
            for u in re.finditer(r"&[a-zA-Z#0-9]+;|[^&]", seg, re.S):
                P["slots"].append(("c", _unesc(u.group(0)), pos + u.start(), True))
        pos = m.end()
        close, name, selfclose = m.group(1) == "/", m.group(2), m.group(3) == "/"
        local = name.split(":", 1)[1]
        cur_owner = owner[-1] if owner else None
        parent = stack[-1] if stack else None
        if close:
            if stack:
                stack.pop()
                o = owner.pop()
                if name == "hp:run" and o is not None:
                    o["end"] = m.start()
                    o["runs_end"].append(m.start())
                if name == "hp:linesegarray" and o is not None and o.get("lsa_start") is not None and o.get("lsa") is None:
                    o["lsa"] = (o["lsa_start"], m.end())
                if name == "hp:p" and pstack:
                    pstack.pop()
            continue
        if name == "hp:p":
            d = {"slots": [], "p_start": m.start(), "tag_end": m.end(), "end": None, "runs_end": []}
            if "hp:fieldBegin" not in stack:   # 메모 등 필드 안 문단은 원본에서 다른 자리(메모 목록)에 있다 — 맞춤 대상에서 뺀다
                paras.append(d)
            if not selfclose:
                pstack.append(d)
                stack.append(name)
                owner.append(d)
            continue
        # 이 요소의 소유 문단: 부모가 문단이면 그 문단, 부모가 run 이면 run 의 소유자, 그 밖에는 None(불투명 내부)
        if parent == "hp:p":
            my = cur_owner
            if name == "hp:linesegarray" and cur_owner is not None:
                cur_owner["lsa_start"] = m.start()
        elif parent == "hp:run":
            my = cur_owner
            if cur_owner is not None and name != "hp:t":
                cur_owner["slots"].append(("o", None, m.start(), False))
                my = None   # 표·그림 등 안쪽은 이 문단의 조각이 아니다
        elif parent == "hp:t":
            my = cur_owner
            if cur_owner is not None:
                if local in _INLINE_CH:
                    cur_owner["slots"].append(("c", _INLINE_CH[local], m.start(), True))
        elif parent == "hp:subList" or name == "hp:subList":
            my = None
        else:
            my = None if parent is not None and cur_owner is None else (None if parent not in ("hp:p", "hp:run", "hp:t") else cur_owner)
        if not selfclose:
            stack.append(name)
            owner.append(my)
    return paras


def _bslots_text(P):
    return "".join(ch for k, ch, _p, _t in P["slots"] if k == "c" and ch != "\n")


def _align(A, P):
    """A 문단 유닛 토큰과 변환본 조각을 두 포인터로 맞춘다. 반환: 유닛 위치 → 조각 번호(그 앞에 넣을 자리). 글자가 어긋나면 None."""
    toks = A["toks"]
    S = P["slots"]
    i = j = 0
    at = {}
    while i < len(toks):
        u, kind, ch = toks[i]
        if kind == "c":
            while j < len(S) and S[j][0] == "o":
                j += 1
            if j >= len(S) or S[j][1] != ch:
                return None
            at[u] = j
            i += 1
            j += 1
        else:
            at[u] = j
            if j < len(S) and S[j][0] == "o":
                j += 1
            i += 1
    while j < len(S):
        if S[j][0] == "c" and S[j][1] != "\n":
            return None
        j += 1
    return at


def apply_full(src, dst, defs, authors, hp):
    """전체 구조 모드. 변환본 문단 수·글이 ViewText 와 1:1 로 맞을 때만 쓴다. (실은 문단 수, 못 실은 문단 수, 비고) 또는 None(이 모드 아님)."""
    zin = zipfile.ZipFile(dst)
    names = zin.namelist()
    secnames = sorted((n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)), key=lambda s: int(re.findall(r"\d+", s)[0]))
    xmls = {n: zin.read(n).decode("utf-8") for n in secnames}
    header = zin.read("Contents/header.xml").decode("utf-8")
    BP = []
    for n in secnames:
        for d in _slots_with_text(xmls[n]):
            d["sec"] = n
            BP.append(d)
    if len(BP) != len(hp):
        zin.close()
        return None
    same = sum(1 for a, b in zip(hp, BP) if a["full"] is not None and a["full"] == _bslots_text(b))
    plain = sum(1 for a in hp if a["full"] is not None)
    if plain == 0 or same < 0.9 * plain:
        zin.close()
        return None
    edits = {n: [] for n in secnames}   # (위치, 순서, 넣을 XML)
    changed_p = []   # 표식을 넣었거나 이어 붙인 문단 — 그 문단의 줄 배치 캐시만 지운다(지운 글까지 넣고 잰 값이라)
    uid = 0
    done = skipped = 0
    seq = 0
    prev_end_del = {}
    for i, (A, P) in enumerate(zip(hp, BP)):
        # 지운 나눔 다음 문단(같은 목록·같은 깊이의 바로 다음 문단) → merged="1"
        lv = A.get("lv")
        if i > 0 and hp[i - 1].get("end_del") and hp[i - 1].get("lv") == lv and 'merged="0"' in xmls[P["sec"]][P["p_start"]:P["tag_end"]]:
            tag = xmls[P["sec"]][P["p_start"]:P["tag_end"]]
            k = tag.index('merged="0"')
            edits[P["sec"]].append((P["p_start"] + k, -1, 'merged="1"', len('merged="0"')))
            changed_p.append(P)
        um = A.get("umarks") or []
        if not um:
            continue
        at = _align(A, P)
        if at is None or P["end"] is None:
            if any(defs[tc - 1]["hide"] == 1 for (_a, _b, tc) in um):
                zin.close()
                return None   # 숨김 구간을 못 거는 문단이 있으면 이 모드는 쓰지 않는다(지운 글이 보이게 됨)
            skipped += 1
            continue
        endu = A["end_unit"]
        # 같은 변경의 겹침·중첩 구간 합치기
        mm = {}
        for (a, b, tc) in sorted(um, key=lambda x: (x[2], x[0], x[1])):
            L = mm.setdefault(tc, [])
            if L and a <= L[-1][1]:
                L[-1][1] = max(L[-1][1], b)
            else:
                L.append([a, b])
        marks = sorted(((a, b, tc) for tc, L in mm.items() for a, b in L if b > a), key=lambda x: (x[0], x[1]))
        upos = sorted(at)

        def slot_for(u):
            """유닛 경계 u 앞에 넣을 자리: u 이상인 첫 토큰의 조각. 없으면 문단 끝."""
            for x in upos:
                if x >= u:
                    return at[x]
            return None

        ins = []   # (조각 번호 또는 None=문단 끝, 순서, XML)
        for (a, b, tc) in marks:
            kind = defs[tc - 1]["kind"].lower()
            uid += 1
            sa = slot_for(a)
            ins.append((sa, seq, 1, f'<hp:{kind}Begin Id="{uid}" TcId="{tc}"/>'))
            seq += 1
            # C105: 한컴 표기 — 나눔만 덮는 구간(a == endu)은 paraend="0", 글과 나눔을 함께 덮거나 빈 문단의 나눔이면 paraend="1".
            pe = "1" if b > endu and (a < endu or endu == 0) else "0"
            sb = None if b > endu else slot_for(b)
            # 같은 자리 순서: 앞에서 시작한 구간의 끝(0) → 시작(1) → 이 자리에서 시작한 구간의 끝(2)
            ins.append((sb, seq, 2 if sb == sa else 0, f'<hp:{kind}End Id="{uid}" TcId="{tc}" paraend="{pe}"/>'))
            seq += 1
        S = P["slots"]
        groups = {}
        for (sl, sq, isend, x) in ins:
            groups.setdefault(sl, []).append((sq, isend, x))
        for sl, lst in groups.items():
            # 같은 자리: 끝 표식 먼저, 그다음 시작 표식(각각 생긴 순서)
            lst.sort(key=lambda t: (t[1], t[0]))
            xml = "".join(t[2] for t in lst)
            if sl is None:
                pos = P["end"]
                edits[P["sec"]].append((pos, 0, f"<hp:t>{xml}</hp:t>", 0))
            else:
                k, _ch, pos, int_ = S[sl]
                edits[P["sec"]].append((pos, 0, xml if int_ else f"<hp:t>{xml}</hp:t>", 0))
        done += 1
        changed_p.append(P)
    import os as _os
    if _os.environ.get("HWPAI_TRK_LINESEG", "keep") == "changed":
        seen = set()
        for P in changed_p:
            if P.get("lsa") and id(P) not in seen:
                seen.add(id(P))
                a, b = P["lsa"]
                edits[P["sec"]].append((a, -2, "", b - a))
    newx = {}
    for n, lst in edits.items():
        if not lst:
            continue
        s = xmls[n]
        for pos, _o, new, rm in sorted(lst, key=lambda t: (t[0], t[1]), reverse=True):
            s = s[:pos] + new + s[pos + rm:]
        newx[n] = s
    if _os.environ.get("HWPAI_TRK_LINESEG", "keep") == "all":
        for n in secnames:
            newx[n] = re.sub(r"<hp:linesegarray>.*?</hp:linesegarray>", "", newx.get(n, xmls[n]), flags=re.S)
    tcxml = "".join(f'<hh:trackChange type="{d["kind"]}" date="{d["date"]}" authorID="{d["author"]}" hide="{d["hide"]}" id="{k + 1}"/>' for k, d in enumerate(defs))
    authxml = "".join(f'<hh:trackChangeAuthor name="{escape(a["name"])}" mark="{a["mark"]}" id="{k + 1}"/>' for k, a in enumerate(authors or [{"name": "user", "mark": 1}]))
    blk = f'<hh:trackChanges itemCnt="{len(defs)}">{tcxml}</hh:trackChanges><hh:trackChangeAuthors itemCnt="{max(len(authors), 1)}">{authxml}</hh:trackChangeAuthors>'
    if "<hh:trackChanges" not in header:
        if "</hh:refList>" not in header:
            zin.close()
            return 0, skipped, "header.xml 에 refList 가 없어 변경 추적 정의를 넣지 못함"
        header = header.replace("</hh:refList>", blk + "</hh:refList>", 1)
    tmp = dst + ".trk"
    with zipfile.ZipFile(tmp, "w") as zo:
        for zi in zin.infolist():
            if zi.filename in newx:
                data = newx[zi.filename].encode("utf-8")
            elif zi.filename == "Contents/header.xml":
                data = header.encode("utf-8")
            else:
                data = zin.read(zi.filename)
            zo.writestr(zi, data, compress_type=zi.compress_type)
    zin.close()
    import os
    os.replace(tmp, dst)
    return done, skipped, "전체 구조 모드(지운 문단·표 포함)"
