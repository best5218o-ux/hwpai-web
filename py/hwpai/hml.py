"""HML(HWPML, XML 로 쓴 한글 문서) 독립 판독기 — 검증서가 HML 원본도 직접 읽어 변환본과 대조하도록 한다.

변환 엔진(rhwp)과 별개 코드다. 요소 이름은 한글과컴퓨터 공개 문서 「한글 문서 파일 형식 3.0 / HWPML」을 따랐고,
블록을 만드는 규칙(각주 표시, 머리말·꼬리말, 글상자, 캡션, 묶음 개체)은 HWPX 판독기(hwpx.py)와 같게 맞췄다.
읽는 것: 글, 표(칸 주소·병합), 그림, 수식, 글상자, 각주·미주, 머리말·꼬리말, 캡션, 자동 번호.
읽지 않는 것: 글자·문단 모양, 숨은 설명, 글자 겹침·덧말(다른 판독기와 대조 범위를 맞춤).
"""
from __future__ import annotations

import base64
import os
import re
import zlib
import xml.etree.ElementTree as ET

from .hwp5 import AUTONUM_MARK, HwpError
from .model import Document, Paragraph, Table, Cell, Image, Equation, Note, TextBox, HeaderFooter

_SHAPES = {"RECTANGLE", "ELLIPSE", "ARC", "POLYGON", "CURVE", "LINE", "CONNECTLINE", "TEXTART", "CONTAINER",
           "PICTURE", "OLE", "UNKNOWNOBJECT", "BUTTON", "RADIOBUTTON", "CHECKBUTTON", "COMBOBOX", "EDIT", "LISTBOX",
           "SCROLLBAR", "FORMOBJECT"}
MAX_BYTES = 256 * 1024 * 1024


def is_hml(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    head = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            head = head.decode("utf-16", "replace").encode("utf-8")
        except Exception:
            return False
    return b"<HWPML" in head and head.startswith((b"<?xml", b"<HWPML", b"<!DOCTYPE"))


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


class _Hml:
    def __init__(self, root, autonum_mark: bool):
        self.root, self.autonum_mark = root, autonum_mark
        self.table_no = self.fn_no = self.en_no = 0
        self.warnings: list = []
        self.bin_names: dict = {}
        self.styles: dict = {}
        head = root.find("HEAD")
        if head is not None:
            for it in head.iter("BINITEM"):
                i = len(self.bin_names) + 1
                fmt = (it.get("Format") or "").lower()
                name = it.get("BinData")
                if name is not None and name.isdigit():
                    self.bin_names[str(i)] = f"BIN{int(name):04X}.{fmt}" if fmt else f"BIN{int(name):04X}"
                else:
                    self.bin_names[str(i)] = os.path.basename((it.get("APath") or it.get("RPath") or "").replace("\\", "/")) or f"BIN{i:04X}"
            for st in head.iter("STYLE"):
                self.styles[st.get("Id", "")] = st.get("Name", "")

    # ---------- 문단 목록 ----------
    def plist(self, el, top: bool = False) -> list:
        out: list = []
        for p in el:
            if p.tag != "P":
                continue
            if not top:
                out.extend(self.para(p))
                continue
            try:
                out.extend(self.para(p))
            except Exception as e:                      # 구역 최상위: 문단 하나가 깨져도 나머지는 읽는다
                self.warnings.append(f"문단 해석 실패: {type(e).__name__}: {e}")
        return out

    def sub(self, el) -> list:
        pl = el.find("PARALIST") if el is not None else None
        return self.plist(pl) if pl is not None else []

    def caption(self, el) -> str:
        so = el.find("SHAPEOBJECT")
        cap = so.find("CAPTION") if so is not None else None
        if cap is None:
            cap = el.find("CAPTION")
        if cap is None:
            return ""
        return " ".join(b.text for b in self.sub(cap) if isinstance(b, Paragraph)).strip()

    # ---------- 문단 ----------
    def para(self, p) -> list:
        style = self.styles.get(p.get("Style", ""), "")
        m = re.match(r"^개요\s*(\d)$", style or "")
        outline = int(m.group(1)) if m else 0
        out: list = []
        buf: list = []
        trailing: list = []

        def flush():
            t = "".join(buf)
            buf.clear()
            t = re.sub(r"[ \t]+\n", "\n", t).strip("\n")
            if t.strip():
                out.append(Paragraph(t.strip() if "\n" not in t else t, style, outline))

        def char(c):
            if c.text:
                buf.append(c.text)
            for d in c:
                n = d.tag
                if n == "TAB":
                    buf.append("\t")
                elif n == "LINEBREAK":
                    buf.append("\n")
                elif n in ("NBSPACE", "FWSPACE"):
                    buf.append(" ")

                if d.tail:
                    buf.append(d.tail)

        def obj(c):
            n = c.tag
            if n == "CHAR":
                char(c)
            elif n == "TABLE":
                flush()
                out.append(self.table(c))
            elif n == "EQUATION":
                flush()
                sc = c.find("SCRIPT")
                out.append(Equation((sc.text or "").strip() if sc is not None else "", caption=self.caption(c)))
            elif n in _SHAPES:
                flush()
                out.extend(self.shape(c))
            elif n in ("FOOTNOTE", "ENDNOTE"):
                if n == "FOOTNOTE":
                    self.fn_no += 1
                    buf.append(f"[^{self.fn_no}]")
                    trailing.append(Note("footnote", self.fn_no, self.sub(c)))
                else:
                    self.en_no += 1
                    buf.append(f"[^미{self.en_no}]")
                    trailing.append(Note("endnote", self.en_no, self.sub(c)))
            elif n in ("HEADER", "FOOTER"):
                trailing.append(HeaderFooter(n.lower(), self.sub(c)))
            elif n == "AUTONUM":
                if (c.get("NumberType") or "").lower() in ("page", "totalpage"):
                    return                              # 쪽 번호는 조판 값 — 다른 판독기와 같이 글로 내지 않는다
                num = c.get("Number")
                if num is not None:
                    buf.append(AUTONUM_MARK + num + AUTONUM_MARK if self.autonum_mark else num)

        for t in p:
            if t.tag != "TEXT":
                continue
            for c in t:
                obj(c)
        flush()
        out.extend(trailing)
        return out

    # ---------- 표 ----------
    def table(self, tbl) -> Table:
        self.table_no += 1
        t = Table(_int(tbl.get("RowCount")), _int(tbl.get("ColCount")), id=self.table_no)
        t.caption = self.caption(tbl)
        r_auto = 0
        for tr in tbl.findall("ROW"):
            c_auto = 0
            for tc in tr.findall("CELL"):
                col, row = _int(tc.get("ColAddr"), c_auto), _int(tc.get("RowAddr"), r_auto)
                cs, rs = max(_int(tc.get("ColSpan"), 1), 1), max(_int(tc.get("RowSpan"), 1), 1)
                t.cells.append(Cell(row, col, rs, cs, self.sub(tc), is_header=(tc.get("Header") or "").lower() in ("1", "true")))
                c_auto = col + cs
            r_auto += 1
        if t.cells:
            t.nrows = max(t.nrows, max(c.row + c.rowspan for c in t.cells))
            t.ncols = max(t.ncols, max(c.col + c.colspan for c in t.cells))
        return t

    # ---------- 도형 ----------
    def image_name(self, ref) -> str:
        return self.bin_names.get(str(ref), "") if ref is not None else ""

    def shape(self, el) -> list:
        n = el.tag
        out: list = []
        cap = self.caption(el)
        if n == "PICTURE":
            img = el.find("IMAGE")
            out.append(Image(self.image_name(img.get("BinItem")) if img is not None else "", cap))
        elif n == "OLE":
            out.append(Image(self.image_name(el.get("BinItem")), cap))
        elif n == "CONTAINER":
            for c in el:
                if c.tag in _SHAPES:
                    out.extend(self.shape(c))
            ims = [b for b in out if isinstance(b, Image)]
            if cap and ims:
                for im in ims:
                    im.caption = cap
            elif cap:
                out.append(Paragraph(cap))
        else:
            do = el.find("DRAWINGOBJECT")
            if n == "RECTANGLE" and do is not None:     # 사각형의 그림 채우기는 그림으로 센다(다른 판독기와 같게)
                fb = do.find("FILLBRUSH")
                ib = fb.find("IMAGEBRUSH") if fb is not None else None
                im = ib.find("IMAGE") if ib is not None else None
                if im is not None and im.get("BinItem"):
                    out.append(Image(self.image_name(im.get("BinItem")), ""))
            if cap:
                out.append(Paragraph(cap))
            dt = do.find("DRAWTEXT") if do is not None else None
            if dt is not None:
                out.append(TextBox(self.sub(dt)))
        return out

    def parse(self) -> list:
        blocks: list = []
        body = self.root.find("BODY")
        for sec in (body.findall("SECTION") if body is not None else []):
            blocks.extend(self.plist(sec, top=True))
        return blocks


def _images(root, names: dict) -> dict:
    out: dict = {}
    tail = root.find("TAIL")
    store = tail.find("BINDATASTORAGE") if tail is not None else None
    for i, bd in enumerate(store.findall("BINDATA") if store is not None else [], 1):
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", bd.text or ""))
            if (bd.get("Compress") or "").lower() == "true":
                raw = zlib.decompress(raw, -15)
        except Exception:
            continue
        name = names.get(bd.get("Id", str(i))) or names.get(str(i))
        if name:
            out[name] = raw
    return out


_ENT_DECL = re.compile(rb"<!ENTITY\s+([A-Za-z_][\w.-]{0,40})\s+(\"|')(.{0,256}?)\2\s*>", re.S)
_ENT_SAFE = re.compile(rb"(?:[^&%<]|&#\d{1,7};|&#x[0-9A-Fa-f]{1,6};|&(?:amp|lt|gt|quot|apos);)*")
_XML_NAMES = (b"amp", b"lt", b"gt", b"quot", b"apos")


def _strip_doctype(data: bytes) -> bytes:
    """<!DOCTYPE …> 선언을 떼어 낸다. 외부 정의는 불러오지 않는다.

    법제처 배포본 등은 선언 안에 글자 개체(&nbsp; 따위)를 직접 정의해 쓴다. 값이 글자 그대로이거나 글자 번호(&#160;)인
    단순 정의만 받아 본문에 풀어 넣는다. 다른 개체를 다시 부르는 정의·외부(SYSTEM·PUBLIC)·매개변수 개체는 읽지 않는다."""
    head = data[:262144]
    i = head.find(b"<!DOCTYPE")
    if i < 0:
        if b"<!ENTITY" in head:
            raise HwpError("HML 문서에 개체 정의(ENTITY)가 선언 밖에 있어 읽지 않습니다")
        return data
    m = re.compile(rb"<!DOCTYPE\s+[^>\[]{0,300}?(?:\[(.*?)\]\s*)?>", re.S).match(head, i)
    if not m:
        raise HwpError("HML 문서의 DOCTYPE 선언을 읽을 수 없습니다")
    ents = {}
    sub = m.group(1)
    if sub:
        sub = re.sub(rb"<!--.*?-->", b"", sub, flags=re.S)
        for em in _ENT_DECL.finditer(sub):
            name, val = em.group(1), em.group(3)
            if not _ENT_SAFE.fullmatch(val):
                raise HwpError("HML 문서의 개체 정의가 다른 개체를 부르고 있어 읽지 않습니다")
            if name not in _XML_NAMES:
                ents[name] = val
        rest = _ENT_DECL.sub(b"", sub)
        rest = re.sub(rb"<!(?:ELEMENT|ATTLIST|NOTATION)\s[^>]{0,4000}>", b"", rest)
        if rest.strip() or len(ents) > 2000:
            raise HwpError("HML 문서의 DOCTYPE 안에 읽지 않는 정의가 들어 있습니다")
    data = data[:m.start()] + data[m.end():]
    if ents:
        data = re.sub(rb"&([A-Za-z_][\w.-]{0,40});", lambda x: ents.get(x.group(1), x.group(0)), data)
    return data



def read_hml(path: str, autonum_mark: bool = False) -> Document:
    if os.path.getsize(path) > MAX_BYTES:
        raise HwpError("HML 문서가 너무 큽니다")
    with open(path, "rb") as f:
        data = f.read()
    from .hml1 import is_hml1, to_hml29
    hml1_lost = None
    if is_hml1(data[:4096]):
        data, hml1_lost = to_hml29(data)                # HWPML 1.x(한글 97) → 2.9 꼴로 옮겨 같은 판독기로 읽는다
    data = _strip_doctype(data)
    m = re.match(rb'\s*(?:\xef\xbb\xbf)?\s*<\?xml[^>]*?encoding="([^"]+)"[^>]*\?>', data[:300])
    if m and m.group(1).lower().startswith(b"utf-16") and b"\x00" not in data[:200]:
        data = data[m.end():]                           # 선언은 UTF-16 인데 실제 바이트는 UTF-8 로 다시 저장된 문서
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise HwpError(f"HML 문서의 XML 이 깨져 있습니다: {e}")
    if root.tag != "HWPML":
        raise HwpError("HML(HWPML) 문서가 아닙니다")
    h = _Hml(root, autonum_mark)
    blocks = h.parse()
    if hml1_lost is not None:
        h.warnings.append("HWPML 1.x(한글 97) 원본은 2.9 꼴로 옮겨 읽음 — 변환과 같은 옮김 코드를 거치므로 원본과의 독립 대조가 아님"
                          + (f", 그림·그리기 개체 {hml1_lost}개는 모양을 읽지 못함" if hml1_lost else ""))
    title = ""
    ds = root.find("HEAD/DOCSUMMARY/TITLE")
    if ds is not None and ds.text:
        title = ds.text.strip()
    doc = Document(blocks, {"format": "hml", "version": root.get("Version", ""), "sections": len(root.findall("BODY/SECTION")),
                            "preview": "", "title": title}, _images(root, h.bin_names), h.warnings)
    doc.meta["source"] = os.path.basename(path)
    return doc


def masterpage_texts(path: str) -> list:
    """바탕쪽마다 그 안의 글(빈칸 뺀 것). 검증서가 변환본의 바탕쪽과 견줄 때 쓴다."""
    with open(path, "rb") as f:
        data = f.read()
    from .hml1 import is_hml1, to_hml29
    if is_hml1(data[:4096]):
        data = to_hml29(data)[0]
    data = _strip_doctype(data)
    m = re.match(rb'\s*(?:\xef\xbb\xbf)?\s*<\?xml[^>]*?encoding="([^"]+)"[^>]*\?>', data[:300])
    if m and m.group(1).lower().startswith(b"utf-16") and b"\x00" not in data[:200]:
        data = data[m.end():]
    root = ET.fromstring(data)
    out = []
    for mp in root.iter("MASTERPAGE"):
        out.append(re.sub(r"\s+", "", "".join((c.text or "") + "".join(d.tail or "" for d in c) for c in mp.iter("CHAR"))))
    return sorted(out)
