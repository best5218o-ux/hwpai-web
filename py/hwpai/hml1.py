"""HWPML 1.x(한글 97 시절 HML, 루트 <HWPML VER="HWPML1.1" CODE="KS">)를 HWPML 2.9 로 옮긴다.

엔진과 검증서는 HWPML 2.x 만 읽는다. 1.x 는 닫는 태그가 없는 요소(PSTYLE·TR·BOX·FONTID 등)가 섞인 SGML 꼴이고
글은 완성형(KS, EUC-KR) 또는 조합형(KSSM)이다. 근거: kldp 「HWPML 1.1」 문서(루트 VERSION/CODE, HEAD 의
INFORMATION·PAPERMARGIN·SUMMATION·FONTLIST·STYLELIST, CSTYLE SIZE 250=10pt(hunit), PSTYLE ALIGN 0~7·LMARGIN·
RMARGIN·INDENT·LSPACE(%)·PSPACE(hunit)) + 행정망 실문서 1건의 태그 목록(이름·횟수·속성 이름만, 2026-11-28).

옮기는 것: 쪽 크기·여백, 글꼴 이름(7개 언어), 글자 크기·장평·자간·색, 문단 정렬·여백·들여쓰기·줄 간격·아래 간격,
표(BOX + CELL 의 HPOSX·HPOSY·HWIDTH·HHEIGHT 로 칸 격자를 다시 짬, 선이 있는 칸은 실선), 캡션·글상자 안 글.
옮기지 못하는 것(검증서가 알림): 그림 자료(DATA), 그리기 개체의 모양, 진하게·밑줄 같은 글자 속성.
"""
from __future__ import annotations

import html as _html
import re
from xml.sax.saxutils import escape as _esc

_VOID = {"PSTYLE", "BOX", "TR", "MARGIN", "DATA", "DRAWHEADER", "DRAWROTATION", "TAB", "INFORMATION", "BORDER",
         "PAPERMARGIN", "BACKGROUND", "FONTID", "LINEBREAK", "BR"}
_LANG = (("KORFONT", "Hangul"), ("ENGFONT", "Latin"), ("HANJAFONT", "Hanja"), ("JAPANFONT", "Japanese"),
         ("ETCFONT", "Other"), ("SPECIALFONT", "Symbol"), ("USERFONT", "User"))
_FONTID_KEY = {"KOR": "Hangul", "ENG": "Latin", "HANJA": "Hanja", "JAPAN": "Japanese", "ETC": "Other",
               "SPECIAL": "Symbol", "USER": "User"}
_ALIGN = {"0": "Justify", "NOALIGN": "Justify", "1": "Left", "LEFT": "Left", "2": "Right", "RIGHT": "Right",
          "3": "Center", "CENTER": "Center", "4": "Justify", "WORD": "Justify", "5": "Justify", "CHAR": "Justify",
          "6": "Justify", "JUSTIFIED": "Justify", "7": "Distribute", "DISTRIBUTED": "Distribute"}
# HWP 글자 색 정수는 0x00BBGGRR
_COLOR = {"BLACK": 0x000000, "BLUE": 0xFF0000, "GREEN": 0x008000, "AQUA": 0xFFFF00, "RED": 0x0000FF,
          "PURPLE": 0x800080, "YELLOW": 0x00FFFF, "WHITE": 0xFFFFFF}
_PAPER = {"A4": (2100, 2970), "LETTER": (2159, 2794), "B5": (1820, 2570), "B4": (2570, 3640), "LEGAL": (2159, 3556),
          "A3": (2970, 4200), "80": (2159, 2794), "132": (3780, 2794)}          # 0.1mm


def is_hml1(head: bytes) -> bool:
    """머리 4KB 로 HWPML 1.x 인지 본다(2.x 의 Version="2.x" 가 없고 VER="HWPML1." 이 있음)."""
    m = re.search(rb"<HWPML\b([^>]*)>", head, re.I)
    if not m:
        return False
    a = m.group(1)
    return bool(re.search(rb'\bVER(?:SION)?\s*=\s*"?HWPML\s*1\.', a, re.I)) and not re.search(rb'\bVersion\s*=\s*"2\.', a)


class _N:
    __slots__ = ("name", "a", "kids")

    def __init__(self, name, a):
        self.name, self.a, self.kids = name, a, []

    def find(self, name):
        for k in self.kids:
            if isinstance(k, _N) and k.name == name:
                return k
        return None

    def all(self, name):
        return [k for k in self.kids if isinstance(k, _N) and k.name == name]

    def text(self):
        out = []
        for k in self.kids:
            out.append(k if isinstance(k, str) else k.text())
        return "".join(out)


_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)((?:\s+[^<>]*?)?)\s*(/?)>|<!--.*?-->|<![^>]*>|<\?[^>]*\?>", re.S)
_ATTR = re.compile(r'([A-Za-z_][\w.-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+))')


def _attrs(s):
    return {m.group(1).upper(): (m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else m.group(4))
            for m in _ATTR.finditer(s or "")}


def _decode(data: bytes) -> str:
    m = re.search(rb'\bCODE\s*=\s*"?([A-Za-z]+)', data[:4096])
    code = (m.group(1).decode("ascii").upper() if m else "KS")
    enc = "johab" if code == "KSSM" else "cp949"
    return data.decode(enc, "replace")


def _tree(text: str) -> _N:
    root = _N("#root", {})
    stack = [root]
    pos = 0
    for m in _TAG.finditer(text):
        if m.start() > pos:
            stack[-1].kids.append(_html.unescape(text[pos:m.start()]))
        pos = m.end()
        if m.group(2) is None:            # 주석·선언
            continue
        close, name, attr, selfclose = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
        if close:
            for i in range(len(stack) - 1, 0, -1):
                if stack[i].name == name:
                    del stack[i:]
                    break
            continue
        node = _N(name, _attrs(attr))
        stack[-1].kids.append(node)
        if not selfclose and name not in _VOID:
            stack.append(node)
    if pos < len(text):
        stack[-1].kids.append(_html.unescape(text[pos:]))
    return root


def _int(v, d=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return d


class _Conv:
    def __init__(self, root: _N):
        self.root = root
        self.fonts = {lang: [] for _t, lang in _LANG}
        self.cshapes, self.pshapes = {}, {}
        self.n_lost = 0

    # ---- 모양 표
    def cshape(self, size=1000, ratio=100, space=0, color=0, fid=None):
        key = (size, ratio, space, color, tuple(sorted((fid or {}).items())))
        if key not in self.cshapes:
            self.cshapes[key] = len(self.cshapes)
        return self.cshapes[key]

    def pshape(self, ps: _N | None):
        a = ps.a if ps is not None else {}
        align = _ALIGN.get(str(a.get("ALIGN", "6")).upper(), "Justify")
        left = _int(a.get("LMARGIN")) * 4
        right = _int(a.get("RMARGIN")) * 4
        indent = _int(a.get("INDENT")) * 4
        ls = _int(a.get("LSPACE"), 160) or 160
        nxt = _int(a.get("PSPACE")) * 4
        prev = _int(a.get("TMARGIN")) * 4
        key = (align, left, right, indent, ls, prev, nxt)
        if key not in self.pshapes:
            self.pshapes[key] = len(self.pshapes)
        return self.pshapes[key]

    # ---- 문단
    def para(self, p: _N) -> str:
        """한 문단 → 2.9 <P>…</P>. 글상자·캡션 안 문단은 뒤따르는 문단으로 덧붙인다."""
        ps = None
        runs = []          # (charshape, xml)
        extra = []         # 뒤에 덧붙일 문단 XML

        def emit(cs, s):
            if runs and runs[-1][0] == cs and runs[-1][2]:
                runs[-1] = (cs, runs[-1][1] + s, True)
            else:
                runs.append((cs, s, True))

        def walk(n: _N, cattr):
            nonlocal ps
            for k in n.kids:
                if isinstance(k, str):
                    t = k.replace("\r", "").replace("\n", "")
                    if t:
                        emit(self.cshape(**cattr), _esc(t))
                    continue
                if k.name == "PSTYLE" and ps is None:
                    ps = k
                elif k.name == "CHAR" or k.name == "CSTYLE":
                    c = dict(cattr)
                    if "SIZE" in k.a:
                        c["size"] = max(_int(k.a["SIZE"], 250), 1) * 4
                    if "RATIO" in k.a:
                        c["ratio"] = max(50, min(200, _int(k.a["RATIO"], 100)))
                    if "SPACE" in k.a:
                        c["space"] = max(-50, min(50, _int(k.a["SPACE"])))
                    if "COLOR" in k.a:
                        v = str(k.a["COLOR"]).upper()
                        c["color"] = _COLOR.get(v, _int(v, 0))
                    f = k.find("FONTID")
                    if f is not None:
                        c["fid"] = {_FONTID_KEY[x]: _int(y) for x, y in f.a.items() if x in _FONTID_KEY}
                    walk(k, c)
                elif k.name in ("TAB",):
                    emit(self.cshape(**cattr), "<TAB/>")
                elif k.name in ("LINEBREAK", "BR"):
                    emit(self.cshape(**cattr), "<LINEBREAK/>")
                elif k.name == "CTRLCODE":
                    ctl, after = self.control(k)
                    if ctl:
                        runs.append((self.cshape(**cattr), ctl, False))
                    extra.extend(after)
                elif k.name in ("P",):
                    extra.append(self.para(k))
                else:
                    walk(k, cattr)

        walk(p, {})
        pid = self.pshape(ps)
        body = "".join(f'<TEXT CharShape="{cs}">' + (_wrap_char(x) if txt else x) + "</TEXT>" for cs, x, txt in runs) \
            or f'<TEXT CharShape="{self.cshape()}"/>'
        return f'<P ParaShape="{pid}" Style="0">{body}</P>' + "".join(extra)

    def paras(self, n: _N) -> str:
        ps = [k for k in n.kids if isinstance(k, _N) and k.name == "P"]
        if not ps:
            inner = [x for k in n.kids if isinstance(k, _N) for x in (k.all("P") or [])]
            ps = inner
        out = "".join(self.para(p) for p in ps)
        return out or f'<P ParaShape="{self.pshape(None)}" Style="0"><TEXT CharShape="{self.cshape()}"/></P>'

    # ---- 개체
    def control(self, c: _N):
        """CTRLCODE → (TEXT 안에 넣을 개체 XML, 뒤에 덧붙일 문단들)."""
        after = []
        cells = _collect(c, "CELL")
        box = _collect(c, "BOX")
        for cap in _collect(c, "CAPTION") + _collect(c, "DRAWTEXTBOX"):
            if cap.text().strip():
                after.append(self.paras(cap))
        if not cells:
            if _collect(c, "DATA") or _collect(c, "DRAWOBJECT"):
                self.n_lost += 1
            return "", after
        return self.table(cells, box[0] if box else None), after

    def table(self, cells, box):
        geo = []
        for cell in cells:
            x, y = _int(cell.a.get("HPOSX")) * 4, _int(cell.a.get("HPOSY")) * 4
            w, h = max(_int(cell.a.get("HWIDTH")) * 4, 1), max(_int(cell.a.get("HHEIGHT")) * 4, 1)
            geo.append((x, y, w, h, cell))

        def edges(vals):
            out = []
            for v in sorted(vals):
                if not out or abs(v - out[-1]) >= 40:
                    out.append(v)
            return out

        def idx(es, v):
            return min(range(len(es)), key=lambda i: abs(es[i] - v))
        xs = edges([g[0] for g in geo] + [g[0] + g[2] for g in geo])
        ys = edges([g[1] for g in geo] + [g[1] + g[3] for g in geo])
        nc, nr = max(len(xs) - 1, 1), max(len(ys) - 1, 1)
        rows = {}
        for x, y, w, h, cell in geo:
            c0, r0 = idx(xs, x), idx(ys, y)
            c1, r1 = max(idx(xs, x + w), c0 + 1), max(idx(ys, y + h), r0 + 1)
            line = any(_int(cell.a.get(k)) for k in ("LLINE", "RLINE", "TLINE", "BLINE"))
            rows.setdefault(r0, []).append(
                f'<CELL ColAddr="{c0}" RowAddr="{r0}" ColSpan="{c1 - c0}" RowSpan="{r1 - r0}" Width="{w}" Height="{h}"'
                f' BorderFill="{2 if line else 1}"><PARALIST>{self.paras(cell)}</PARALIST></CELL>')
        tw, th = (xs[-1] - xs[0]) if len(xs) > 1 else 0, (ys[-1] - ys[0]) if len(ys) > 1 else 0
        body = "".join("<ROW>" + "".join(v) + "</ROW>" for _k, v in sorted(rows.items()))
        return (f'<TABLE RowCount="{nr}" ColCount="{nc}" BorderFill="1"><SHAPEOBJECT TreatAsChar="true">'
                f'<SIZE Width="{tw}" Height="{th}"/><POSITION TreatAsChar="true"/></SHAPEOBJECT>{body}</TABLE>')

    # ---- 문서
    def convert(self) -> str:
        hw = self.root.find("HWPML") or self.root
        head = hw.find("HEAD") or _N("HEAD", {})
        body = hw.find("BODY") or _N("BODY", {})
        fl = head.find("FONTLIST")
        for tag, lang in _LANG:
            node = fl.find(tag) if fl is not None else None
            names = []
            if node is not None:
                for f in node.all("FONT"):
                    names.append(re.sub(r"\s+", " ", f.text()).strip() or "명조")
            self.fonts[lang] = names or ["명조"]
        info = head.find("INFORMATION")
        pw, ph = _PAPER["A4"]
        land = 0
        if info is not None:
            pw, ph = _PAPER.get(str(info.a.get("PAPER", "A4")).upper(), (pw, ph))
            if str(info.a.get("PAPER", "")).upper() == "USER":
                pw = _int(info.a.get("PAGEWID"), 0) * 10 / 72 or pw          # hunit(1800dpi) → 0.1mm 근사
                ph = _int(info.a.get("PAGELEN"), 0) * 10 / 72 or ph
            land = 1 if _int(info.a.get("LANDSCAPE")) else 0
        to_hu = lambda tenth_mm: int(round(tenth_mm * 7200 / 254))
        pm = head.find("PAPERMARGIN")
        mg = {k: _int(pm.a.get(k)) * 4 for k in ("TOP", "BOTTOM", "LEFT", "RIGHT", "HEADER", "FOOTER", "GUTTER")} if pm is not None else {}
        paras = [k for k in body.kids if isinstance(k, _N) and k.name == "P"]
        pxml = [self.para(p) for p in paras] or [f'<P ParaShape="{self.pshape(None)}" Style="0"><TEXT CharShape="{self.cshape()}"/></P>']
        secdef = (f'<SECDEF><PAGEDEF Width="{to_hu(pw)}" Height="{to_hu(ph)}" Landscape="{land}">'
                  + (f'<PAGEMARGIN Left="{mg["LEFT"]}" Right="{mg["RIGHT"]}" Top="{mg["TOP"]}" Bottom="{mg["BOTTOM"]}"'
                     f' Header="{mg["HEADER"]}" Footer="{mg["FOOTER"]}" Gutter="{mg["GUTTER"]}"/>' if mg else "")
                  + '</PAGEDEF></SECDEF>')
        pxml[0] = re.sub(r'(<TEXT CharShape="\d+")(/?)>', lambda m: m.group(1) + ">" + secdef + ("</TEXT>" if m.group(2) else ""), pxml[0], count=1)
        faces = "".join(f'<FONTFACE Count="{len(v)}" Lang="{lang}">' + "".join(
            f'<FONT Id="{i}" Name="{_esc(n, {chr(34): "&quot;"})}" Type="ttf"/>' for i, n in enumerate(v)) + "</FONTFACE>"
                        for lang, v in self.fonts.items())
        langs = ("Hangul", "Latin", "Hanja", "Japanese", "Other", "Symbol", "User")
        cs = []
        for (size, ratio, space, color, fid), i in sorted(self.cshapes.items(), key=lambda x: x[1]):
            fd = dict(fid)
            ids = " ".join(f'{l}="{min(fd.get(l, 0), max(len(self.fonts[l]) - 1, 0))}"' for l in langs)
            arr = lambda v: " ".join(f'{l}="{v}"' for l in langs)
            cs.append(f'<CHARSHAPE Id="{i}" Height="{size}" TextColor="{color}" ShadeColor="4294967295" BorderFillId="1">'
                      f'<FONTID {ids}/><RATIO {arr(ratio)}/><CHARSPACING {arr(space)}/><RELSIZE {arr(100)}/><CHAROFFSET {arr(0)}/></CHARSHAPE>')
        ps = []
        for (align, left, right, indent, ls, prev, nxt), i in sorted(self.pshapes.items(), key=lambda x: x[1]):
            ps.append(f'<PARASHAPE Id="{i}" Align="{align}"><PARAMARGIN Left="{left}" Right="{right}" Indent="{indent}"'
                      f' Prev="{prev}" Next="{nxt}" LineSpacing="{ls}" LineSpacingType="Percent"/></PARASHAPE>')
        bf = ('<BORDERFILLLIST Count="2"><BORDERFILL Id="1"/><BORDERFILL Id="2">'
              '<LEFTBORDER Type="Solid" Width="0.12mm"/><RIGHTBORDER Type="Solid" Width="0.12mm"/>'
              '<TOPBORDER Type="Solid" Width="0.12mm"/><BOTTOMBORDER Type="Solid" Width="0.12mm"/></BORDERFILL></BORDERFILLLIST>')
        title = ""
        sm = head.find("SUMMATION")
        if sm is not None and sm.find("TITLE") is not None:
            title = f'<DOCSUMMARY><TITLE>{_esc(sm.find("TITLE").text().strip())}</TITLE></DOCSUMMARY>'
        return ('<?xml version="1.0" encoding="UTF-8"?><HWPML Style="embed" SubVersion="9.0.0.0" Version="2.9">'
                f'<HEAD SecCnt="1">{title}<DOCSETTING><BEGINNUMBER Page="1"/></DOCSETTING><MAPPINGTABLE>'
                f'<FACENAMELIST>{faces}</FACENAMELIST>{bf}<CHARSHAPELIST Count="{len(cs)}">{"".join(cs)}</CHARSHAPELIST>'
                f'<PARASHAPELIST Count="{len(ps)}">{"".join(ps)}</PARASHAPELIST>'
                '<STYLELIST Count="1"><STYLE CharShape="0" EngName="Normal" Id="0" Name="바탕글" NextStyle="0" ParaShape="0" Type="Para"/></STYLELIST>'
                f'</MAPPINGTABLE></HEAD><BODY><SECTION Id="0">{"".join(pxml)}</SECTION></BODY><TAIL></TAIL></HWPML>')


def _collect(n: _N, name: str):
    out = []
    for k in n.kids:
        if isinstance(k, _N):
            if k.name == name:
                out.append(k)
            if k.name not in ("CELL",) or name != "CELL":
                out.extend(_collect(k, name))
    return out


def _wrap_char(x: str) -> str:
    """TEXT 안의 글은 <CHAR> 로 감싸고, 개체·탭·줄바꿈은 그대로 둔다."""
    parts = re.split(r"(<TAB/>|<LINEBREAK/>)", x)
    return "".join(f"<CHAR>{p}</CHAR>" for p in parts if p)


def to_hml29(data: bytes) -> tuple[bytes, int]:
    """HWPML 1.x 바이트 → (HWPML 2.9 UTF-8 바이트, 옮기지 못한 그림·그리기 개체 수)."""
    conv = _Conv(_tree(_decode(data)))
    xml = conv.convert()
    return xml.encode("utf-8"), conv.n_lost
