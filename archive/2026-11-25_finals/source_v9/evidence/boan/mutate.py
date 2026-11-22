"""검증기 변이 시험 — 정상 변환본(HWPX)에서 요소 하나를 지우거나 바꾼 「일부러 망가뜨린 변환본」을 만들어
hwpai 검증기(audit)가 잡는지 본다. 원본은 읽기만 한다. 변이본은 임시 파일로 만들고 바로 지운다.

사용: python3 -I mutate.py <hwpai 코드 폴더> <census.json> <결과.jsonl> [문서수/요소=6] [seed]
"""
import io, json, os, random, re, sys, tempfile, time, zipfile
import xml.etree.ElementTree as ET

CODE, CENSUS, OUTP = sys.argv[1], sys.argv[2], sys.argv[3]
NDOC = int(sys.argv[4]) if len(sys.argv) > 4 else 6
SEED = int(sys.argv[5]) if len(sys.argv) > 5 else 20261120
ONLY = set(sys.argv[6].split(",")) if len(sys.argv) > 6 and sys.argv[6] else None
sys.path.insert(0, os.path.join(CODE, "app"))
from hwpai.audit import audit  # noqa: E402

IN = os.environ.get("MUT_IN", "/home/claude/v8in")     # 3차: 보류 표본(변경 추적 문서)도 돌릴 수 있게 환경 변수로 바꿀 수 있다
OUT = os.environ.get("MUT_OUT", "/home/claude/v8out")
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
TMP = os.environ.get("MUT_TMP", "/dev/shm/v9w/tmp")
os.makedirs(TMP, exist_ok=True)


def ln(t):
    return t.rsplit("}", 1)[-1]


def load(path):
    z = zipfile.ZipFile(path)
    secs, nss = {}, {}
    for n in z.namelist():
        if n.startswith("Contents/section") and n.endswith(".xml"):
            data = z.read(n)
            for ev, (pfx, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
                nss.setdefault(pfx, uri)
            secs[n] = ET.fromstring(data)
    z.close()
    return secs, nss


def save(src, dst, secs, nss, bin_mut=None):
    for p, u in nss.items():
        ET.register_namespace(p, u)
    zin = zipfile.ZipFile(src)
    with zipfile.ZipFile(dst, "w") as zout:
        for zi in zin.infolist():
            if zi.filename in secs:
                data = ET.tostring(secs[zi.filename], encoding="utf-8", xml_declaration=True)
            elif bin_mut and zi.filename == bin_mut:
                d = bytearray(zin.read(zi.filename))
                for k in range(16, min(len(d), 4096), 97):
                    d[k] ^= 0x5A
                data = bytes(d)
            else:
                data = zin.read(zi.filename)
            zout.writestr(zi, data, compress_type=zi.compress_type)
    zin.close()


def parents(secs):
    pm = {}
    for root in secs.values():
        for p in root.iter():
            for c in p:
                pm[c] = p
    return pm


def all_el(secs, name):
    return [e for r in secs.values() for e in r.iter() if ln(e.tag) == name]


def text_of(e):
    return "".join(t.text or "" for t in e.iter() if ln(t.tag) == "t") + "".join(
        (t.tail or "") for t in e.iter() if ln(t.tag) in ("tab", "lineBreak") and False)


def inside(e, pm, names):
    p = pm.get(e)
    while p is not None:
        if ln(p.tag) in names:
            return True
        p = pm.get(p)
    return False


def remove(e, pm):
    pm[e].remove(e)


def alter_text(e, rnd):
    """요소 안 글 하나에서 가운데 글자 하나를 다른 글자로 바꾼다(숫자면 다른 숫자)."""
    ts = [t for t in e.iter() if ln(t.tag) == "t" and t.text and len(t.text.strip()) >= 2]
    if not ts:
        return False
    t = rnd.choice(ts)
    s = t.text
    idx = [i for i, c in enumerate(s) if not c.isspace()]
    i = idx[len(idx) // 2]
    c = s[i]
    if c.isdigit():
        n = str((int(c) + 5) % 10)
    elif "가" <= c <= "힣":
        n = "가" if c != "가" else "나"
    else:
        n = "Q" if c != "Q" else "Z"
    t.text = s[:i] + n + s[i + 1:]
    return True


def blank_text(e):
    ts = [t for t in e.iter() if ln(t.tag) == "t" and (t.text or "").strip()]
    if not ts:
        return False
    for t in ts:
        t.text = ""
        for c in list(t):     # t 안 tab 등 하위 요소의 tail 글도 지운다
            c.tail = ""
    return True


# ---------------------------------------------------------------- 변이 정의 — (요소, 방식) → 함수(secs, pm, rnd) → 설명 or None
def m_para_del(secs, pm, rnd):
    cand = [p for r in secs.values() for p in r if ln(p.tag) == "p" and len(text_of(p).strip()) >= 4
            and not any(ln(x.tag) in ("tbl", "pic", "container", "rect", "equation", "ctrl", "ole") for x in p.iter())]
    if not cand:
        return None
    p = rnd.choice(cand)
    d = text_of(p)[:30]
    remove(p, pm)
    return f"본문 문단 삭제 「{d}」"


def m_para_mod(secs, pm, rnd):
    cand = [p for r in secs.values() for p in r if ln(p.tag) == "p" and len(text_of(p).strip()) >= 4
            and not any(ln(x.tag) in ("tbl", "pic", "container", "rect", "equation") for x in p.iter())]
    if not cand:
        return None
    p = rnd.choice(cand)
    return "본문 문단 한 글자 바꿈" if alter_text(p, rnd) else None


def _cells(secs, pm):
    return [c for c in all_el(secs, "tc") if (text_of(c).strip()) and len(text_of(c).strip()) >= 2
            and not any(ln(x.tag) == "tbl" for x in c.iter() if x is not c)]


def m_cell_blank(secs, pm, rnd):
    c = _cells(secs, pm)
    if not c:
        return None
    t = rnd.choice(c)
    d = text_of(t)[:20]
    return f"표 칸 글 지움 「{d}」" if blank_text(t) else None


def m_cell_mod(secs, pm, rnd):
    c = _cells(secs, pm)
    if not c:
        return None
    return "표 칸 한 글자 바꿈" if alter_text(rnd.choice(c), rnd) else None


def m_row_del(secs, pm, rnd):
    rows = [r for r in all_el(secs, "tr") if text_of(r).strip() and len(list(pm[r])) >= 2
            and all(int((x.get("rowSpan") or "1")) == 1 for x in r.iter() if ln(x.tag) == "cellSpan")]
    if not rows:
        return None
    r = rnd.choice(rows)
    remove(r, pm)
    return "표 행 삭제(rowCnt 그대로)"


def m_row_del_fix(secs, pm, rnd):
    rows = [r for r in all_el(secs, "tr") if text_of(r).strip() and len(list(pm[r])) >= 2
            and all(int((x.get("rowSpan") or "1")) == 1 for x in r.iter() if ln(x.tag) == "cellSpan")]
    if not rows:
        return None
    r = rnd.choice(rows)
    tbl = pm[r]
    ri = list(tbl).index(r)
    remove(r, pm)
    # 행 번호·rowCnt 를 맞춰 「깔끔하게」 지운 것처럼 만든다
    tbl.set("rowCnt", str(max(int(tbl.get("rowCnt") or "1") - 1, 1)))
    k = 0
    for tr in tbl:
        if ln(tr.tag) != "tr":
            continue
        for a in tr.iter():
            if ln(a.tag) == "cellAddr":
                a.set("rowAddr", str(k))
        k += 1
    return "표 행 삭제(rowCnt·행 주소까지 맞춤)"


def _rm_obj(secs, pm, rnd, name, pred=lambda e: True):
    c = [e for e in all_el(secs, name) if pred(e)]
    if not c:
        return None
    e = rnd.choice(c)
    remove(e, pm)
    return True


def m_pic_del(secs, pm, rnd):
    return "그림 삭제" if _rm_obj(secs, pm, rnd, "pic") else None


def m_note_del(kind):
    def f(secs, pm, rnd):
        return f"{kind} 삭제" if _rm_obj(secs, pm, rnd, kind) else None
    return f


def m_inner_blank(kind, label):
    def f(secs, pm, rnd):
        c = [e for e in all_el(secs, kind) if text_of(e).strip()]
        if not c:
            return None
        return f"{label} 안 글 지움" if blank_text(rnd.choice(c)) else None
    return f


def m_inner_mod(kind, label):
    def f(secs, pm, rnd):
        c = [e for e in all_el(secs, kind) if len(text_of(e).strip()) >= 2]
        if not c:
            return None
        return f"{label} 안 한 글자 바꿈" if alter_text(rnd.choice(c), rnd) else None
    return f


def m_hf_del(kind):
    def f(secs, pm, rnd):
        c = [e for e in all_el(secs, kind)]
        if not c:
            return None
        e = rnd.choice(c)
        # header 는 ctrl 안에 있다 — ctrl 째 지운다
        p = pm[e]
        if ln(p.tag) == "ctrl" and len(list(p)) == 1:
            remove(p, pm)
        else:
            remove(e, pm)
        return f"{kind} 컨트롤 삭제"
    return f


def m_eq_del(secs, pm, rnd):
    return "수식 삭제" if _rm_obj(secs, pm, rnd, "equation") else None


def m_eq_mod(secs, pm, rnd):
    c = [s for s in all_el(secs, "script") if (s.text or "").strip()]
    if not c:
        return None
    s = rnd.choice(c)
    s.text = (s.text or "") + " + 1"
    return "수식 스크립트 바꿈"


def m_eqcap_del(secs, pm, rnd):
    c = [cap for e in all_el(secs, "equation") for cap in e if ln(cap.tag) == "caption"]
    if not c:
        return None
    cap = rnd.choice(c)
    remove(cap, pm)
    return "수식 캡션 삭제"


def m_cap_del(owner):
    def f(secs, pm, rnd):
        c = [cap for e in all_el(secs, owner) for cap in e if ln(cap.tag) == "caption" and text_of(cap).strip()]
        if not c:
            return None
        cap = rnd.choice(c)
        d = text_of(cap)[:20]
        remove(cap, pm)
        return f"{owner} 캡션 삭제 「{d}」"
    return f


def _field_pairs(secs, pm, ftype):
    out = []
    for fb in all_el(secs, "fieldBegin"):
        if fb.get("type") == ftype:
            out.append(fb)
    return out


def m_field_del(ftype):
    def f(secs, pm, rnd):
        c = _field_pairs(secs, pm, ftype)
        if not c:
            return None
        fb = rnd.choice(c)
        fid = fb.get("id")
        p = pm[fb]
        if ln(p.tag) == "ctrl":
            remove(p, pm)
        else:
            remove(fb, pm)
        for fe in all_el(secs, "fieldEnd"):
            if fe.get("beginIDRef") == fid:
                q = pm[fe]
                if ln(q.tag) == "ctrl":
                    remove(q, pm)
                else:
                    remove(fe, pm)
        return f"{ftype} 필드 삭제(글은 남김)"
    return f


def m_field_mod(ftype):
    def f(secs, pm, rnd):
        c = _field_pairs(secs, pm, ftype)
        if not c:
            return None
        fb = rnd.choice(c)
        changed = False
        for sp in fb.iter():
            if ln(sp.tag) == "stringParam" and (sp.text or "").strip():
                sp.text = "http://changed.invalid/" if ftype == "HYPERLINK" else (sp.text + "_바뀜")
                changed = True
                break
        if fb.get("name") and not changed:
            fb.set("name", fb.get("name") + "_바뀜")
            changed = True
        return f"{ftype} 필드 값(주소·이름) 바꿈" if changed else None
    return f


def m_simple_del(kind, label):
    def f(secs, pm, rnd):
        c = all_el(secs, kind)
        if not c:
            return None
        e = rnd.choice(c)
        p = pm[e]
        if ln(p.tag) == "ctrl" and len(list(p)) == 1:
            remove(p, pm)
        else:
            remove(e, pm)
        return f"{label} 삭제"
    return f


def m_shapecmt_mod(secs, pm, rnd):
    c = [e for e in all_el(secs, "shapeComment") if (e.text or "").strip() and (e.text or "").strip() not in ("그림입니다.",)]
    if not c:
        return None
    e = rnd.choice(c)
    e.text = "바뀐 설명"
    return "개체 설명(대체 텍스트) 바꿈"


MUTS = [
    ("본문 문단", "삭제", "para", m_para_del),
    ("본문 문단", "한 글자", "para", m_para_mod),
    ("표 칸 글", "지움", "cell", m_cell_blank),
    ("표 칸 글", "한 글자", "cell", m_cell_mod),
    ("표 행", "삭제", "cell", m_row_del),
    ("표 행", "삭제+주소 맞춤", "cell", m_row_del_fix),
    ("그림", "삭제", "pic", m_pic_del),
    ("그림", "데이터 변조", "pic", None),
    ("각주", "삭제", "footnote", m_note_del("footNote")),
    ("각주", "글 지움", "footnote", m_inner_blank("footNote", "각주")),
    ("미주", "삭제", "endnote", m_note_del("endNote")),
    ("미주", "글 지움", "endnote", m_inner_blank("endNote", "미주")),
    ("머리말", "삭제", "header", m_hf_del("header")),
    ("머리말", "글 지움", "header", m_inner_blank("header", "머리말")),
    ("꼬리말", "삭제", "footer", m_hf_del("footer")),
    ("꼬리말", "글 지움", "footer", m_inner_blank("footer", "꼬리말")),
    ("글상자 안 글", "지움", "drawtext", m_inner_blank("drawText", "글상자")),
    ("글상자 안 글", "한 글자", "drawtext", m_inner_mod("drawText", "글상자")),
    ("수식", "삭제", "equation", m_eq_del),
    ("수식", "스크립트 바꿈", "equation", m_eq_mod),
    ("표 캡션", "삭제", "tblcap", m_cap_del("tbl")),
    ("그림 캡션", "삭제", "piccap", m_cap_del("pic")),
    ("하이퍼링크", "필드 삭제", "hyperlink", m_field_del("HYPERLINK")),
    ("하이퍼링크", "주소 바꿈", "hyperlink", m_field_mod("HYPERLINK")),
    ("누름틀", "필드 삭제", "clickhere", m_field_del("CLICK_HERE")),
    ("누름틀", "이름 바꿈", "clickhere", m_field_mod("CLICK_HERE")),
    ("쪽 번호", "삭제", "pagenum", m_simple_del("pageNum", "쪽 번호")),
    ("숨은 설명", "삭제", "hiddencmt", m_simple_del("hiddenComment", "숨은 설명")),
    ("책갈피", "삭제", "bookmark", m_simple_del("bookmark", "책갈피")),
    ("개체 설명", "바꿈", "shapecmt", m_shapecmt_mod),
]


# ---------------------------------------------------------------- 3차 보완(C3-2) 변이 — 변경 추적 이력·도형 종류
def _marker_pairs(secs, pm, begin, end):
    """같은 hp:t 안에서 begin 바로 다음 형제가 같은 Id 의 end 인 짝(사이 글 = begin.tail)."""
    out = []
    for b in all_el(secs, begin):
        t = pm.get(b)
        if t is None:
            continue
        kids = list(t)
        i = kids.index(b)
        if i + 1 < len(kids) and ln(kids[i + 1].tag) == end and kids[i + 1].get("Id") == b.get("Id"):
            out.append((t, b, kids[i + 1]))
    return out


def _drop_keep_tail(t, el, keep_tail=True):
    """hp:t 안 표식 el 을 지우고, keep_tail 이면 el 뒤 글(tail)은 앞 글에 붙여 남긴다."""
    kids = list(t)
    i = kids.index(el)
    tail = (el.tail or "") if keep_tail else ""
    if i == 0:
        t.text = (t.text or "") + tail
    else:
        kids[i - 1].tail = (kids[i - 1].tail or "") + tail
    t.remove(el)


def m_trk_del_seg(secs, pm, rnd):
    c = [x for x in _marker_pairs(secs, pm, "deleteBegin", "deleteEnd") if (x[1].tail or "").strip()]
    if not c:
        return None
    t, b, e = rnd.choice(c)
    d = b.tail
    _drop_keep_tail(t, b, keep_tail=False)
    _drop_keep_tail(t, e, keep_tail=True)
    return f"지운 글 이력 구간 삭제(표식과 글) 「{d[:20]}」"


def m_trk_del_unmark(secs, pm, rnd):
    c = [x for x in _marker_pairs(secs, pm, "deleteBegin", "deleteEnd") if (x[1].tail or "").strip()]
    if not c:
        return None
    t, b, e = rnd.choice(c)
    d = b.tail
    _drop_keep_tail(t, b)
    _drop_keep_tail(t, e)
    return f"지운 글 표식만 삭제(글은 보이는 글로 남음) 「{d[:20]}」"


def m_trk_ins_unmark(secs, pm, rnd):
    c = [x for x in _marker_pairs(secs, pm, "insertBegin", "insertEnd") if (x[1].tail or "").strip()]
    if not c:
        return None
    t, b, e = rnd.choice(c)
    d = b.tail
    _drop_keep_tail(t, b)
    _drop_keep_tail(t, e)
    return f"삽입 표식 삭제(글은 남김) 「{d[:20]}」"


def m_shape_del(kind, label):
    def f(secs, pm, rnd):
        c = all_el(secs, kind)
        if not c:
            return None
        e = rnd.choice(c)
        has_txt = bool(text_of(e).strip())
        remove(e, pm)
        return f"{label} 삭제({'안에 글 있음' if has_txt else '글 없음'})"
    return f


def m_rect_to_ellipse(secs, pm, rnd):
    c = [e for e in all_el(secs, "rect")]
    if not c:
        return None
    e = rnd.choice(c)
    e.tag = e.tag[:-len("rect")] + "ellipse"
    return "사각형을 타원으로 종류 바꿈(개수 같음)"


MUTS3 = [
    ("변경 추적", "지운 글 구간 삭제", "trk", m_trk_del_seg),
    ("변경 추적", "지운 글 표식만 삭제", "trk", m_trk_del_unmark),
    ("변경 추적", "삽입 표식 삭제", "trk", m_trk_ins_unmark),
    ("사각형", "삭제", "rect", m_shape_del("rect", "사각형")),
    ("선", "삭제", "line", m_shape_del("line", "선")),
    ("연결선", "삭제", "connectLine", m_shape_del("connectLine", "연결선")),
    ("타원", "삭제", "ellipse", m_shape_del("ellipse", "타원")),
    ("다각형", "삭제", "polygon", m_shape_del("polygon", "다각형")),
    ("묶음", "삭제", "container", m_shape_del("container", "묶음")),
    ("OLE", "삭제", "ole", m_shape_del("ole", "OLE")),
    ("사각형", "종류 바꿈(→타원)", "rect", m_rect_to_ellipse),
]
if os.environ.get("MUT_SET") == "3":
    MUTS = MUTS3


def bin_target(path, secs):
    """그림 데이터 변조 대상: 문서 그림이 참조하는 BinData 하나."""
    refs = [d.get("binaryItemIDRef") for r in secs.values() for d in r.iter() if ln(d.tag) == "img" and d.get("binaryItemIDRef")]
    if not refs:
        return None
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if n.startswith("BinData/")]
    z.close()
    for ref in refs:
        for n in names:
            if n.rsplit("/", 1)[-1].rsplit(".", 1)[0] == ref:
                return n
    return None


def main():
    census = json.load(open(CENSUS))
    rnd0 = random.Random(SEED)
    base_cache = {}
    done = set()
    if os.path.exists(OUTP):
        for line in open(OUTP):
            r = json.loads(line)
            done.add((r["el"], r["how"], r["doc"]))
    fo = open(OUTP, "a")
    for el, how, key, fn in MUTS:
        if ONLY and key not in ONLY:
            continue
        docs = sorted(d for d, v in census.items() if v.get(key) and v["size"] < 3_000_000)
        rnd0 = random.Random(f"{SEED}:{el}:{how}")
        rnd0.shuffle(docs)
        n = 0
        for doc in docs:
            if n >= NDOC:
                break
            if (el, how, doc) in done:
                n += 1
                continue
            src, conv = os.path.join(IN, doc + ".hwp"), os.path.join(OUT, doc + ".hwpx")
            if doc not in base_cache:
                a0 = audit(src, conv)
                base_cache[doc] = (a0.verdict, {x["code"] for x in a0.reasons})
            bv, bcodes = base_cache[doc]
            if bv == "FAIL" or "ORIG_UNVERIFIABLE" in bcodes:   # HWP3·암호 원본은 대조 자체가 불가(늘 WARN) — 표본에서 뺀다
                continue
            secs, nss = load(conv)
            pm = parents(secs)
            rnd = random.Random(f"{SEED}:{doc}:{el}:{how}")
            binm = None
            if fn is None:
                binm = bin_target(conv, secs)
                desc = "그림 데이터 바이트 변조" if binm else None
            else:
                desc = fn(secs, pm, rnd)
            if not desc:
                continue
            fd, dst = tempfile.mkstemp(suffix=".hwpx", dir=TMP)
            os.close(fd)
            try:
                save(conv, dst, secs, nss, bin_mut=binm)
                t0 = time.time()
                a = audit(src, dst)
                dt = time.time() - t0
            finally:
                os.remove(dst)
            new = [x for x in a.reasons if x["code"] not in bcodes]
            newf = [x for x in new if x["level"] == "FAIL"]
            neww = [x for x in new if x["level"] == "WARN"]
            res = "FAIL" if newf else ("WARN" if neww else "놓침")
            rec = {"el": el, "how": how, "doc": doc, "desc": desc, "base": bv, "verdict": a.verdict, "result": res,
                   "new_codes": sorted({x["code"] for x in new}), "msg": (new[0]["msg"][:120] if new else ""), "sec": round(dt, 2)}
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fo.flush()
            print(el, how, doc, res, rec["new_codes"], flush=True)
            n += 1
    fo.close()


if __name__ == "__main__":
    main()
