"""HWPX (OWPML, KS X 6101) 판독기 — HWP5 판독기와 같은 문서 모델로 올린다.

이름공간 판본(2011/2016 …)이 섞여 있어 접두어가 아닌 로컬 이름으로 요소를 가린다.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET

from .hwp5 import AUTONUM_MARK
from .model import (Cell, Document, Equation, HeaderFooter, Image, Note, Paragraph, Table, TextBox)

_SHAPES = {"rect", "ellipse", "arc", "polygon", "curve", "line", "connectLine", "textart", "container", "ole", "pic",
           "video", "chart"}


def _ln(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _ln(c.tag) == name:
            return c
    return None


def _children(el, name):
    return [c for c in el if _ln(c.tag) == name]


def _switch_pick(sw, prefer="case"):
    """hp:switch 의 한 갈래(자식 목록). Element 의 참/거짓은 자식 유무라 `or` 로 고르지 않는다."""
    cases = [c for c in sw if _ln(c.tag) == "case"]
    dflt = _child(sw, "default")
    order = ([cases[0]] if cases else []) + ([dflt] if dflt is not None else [])
    if prefer == "default":
        order.reverse()
    for g in order:
        if len(g):
            return list(g)
    return []


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


class _Header:
    """header.xml — 스타일 이름과 개요 수준."""

    def __init__(self, xml: bytes | None):
        self.styles: dict[str, str] = {}
        self.outline: dict[str, int] = {}
        self.hidden_tc: set[str] = set()     # 숨김 처리된 삭제(변경 추적 hide=1)의 TcId — 이 구간 글은 화면에 없다(C95)
        if not xml:
            return
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return
        for el in root.iter():
            n = _ln(el.tag)
            if n == "trackChange":
                if el.get("type") == "Delete" and el.get("hide") == "1":
                    self.hidden_tc.add(el.get("id", ""))
            elif n == "style":
                self.styles[el.get("id", "")] = el.get("name", "")
            elif n == "paraPr":
                h = _child(el, "heading")
                if h is None:  # switch/case 로 감싼 판본
                    for d in el.iter():
                        if _ln(d.tag) == "heading":
                            h = d
                            break
                if h is not None and h.get("type", "").upper() == "OUTLINE":
                    self.outline[el.get("id", "")] = _int(h.get("level"), 0) + 1


class HwpxParser:
    def __init__(self, z: zipfile.ZipFile, autonum_mark: bool = False):
        self.z = z
        self.autonum_mark = autonum_mark
        self.warnings: list[str] = []
        self._indel = False
        self._delopen = set()
        self.table_no = 0
        self.fn_no = 0
        self.en_no = 0
        names = z.namelist()
        hpf = z.read("Contents/content.hpf") if "Contents/content.hpf" in names else b""
        self.manifest: dict[str, str] = {}
        spine: list[str] = []
        if hpf:
            s = hpf.decode("utf-8", "replace")
            for m in re.finditer(r"<[\w:]*item\b([^>]*)/?>", s):
                a = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))
                if "id" in a and "href" in a:
                    self.manifest[a["id"]] = a["href"]
            for m in re.finditer(r'<[\w:]*itemref\b[^>]*idref="([^"]*)"', s):
                spine.append(m.group(1))
        secs = [self.manifest[i] for i in spine if re.search(r"section\d+\.xml$", self.manifest.get(i, ""))]
        secs = [s if s in names else "Contents/" + s.split("/")[-1] for s in secs]
        if not secs or any(s not in names for s in secs):
            secs = sorted((n for n in names if re.match(r"Contents/section\d+\.xml$", n)),
                          key=lambda n: int(re.findall(r"\d+", n.rsplit("/", 1)[-1])[0]))
        self.sections = secs
        self.header = _Header(z.read("Contents/header.xml") if "Contents/header.xml" in names else None)
        self.bin_files = [n for n in names if n.startswith("BinData/") and not n.endswith("/")]

    # ---------- 그림 이름 ----------
    def image_name(self, ref: str) -> str:
        href = self.manifest.get(ref, "")
        if href:
            return href.rsplit("/", 1)[-1]
        for n in self.bin_files:  # 매니페스트가 없으면 파일명으로 추정
            base = n.rsplit("/", 1)[-1]
            if base.split(".")[0] == ref:
                return base
        return ref

    # ---------- 문단 목록 (subList 등) ----------
    def plist(self, el, where: str | None = None) -> list:
        out: list = []
        prev_tail_para = False   # 바로 앞 hp:p 가 글 문단으로 끝났나
        for p in el:
            if _ln(p.tag) == "p":
                if where is None:
                    blocks = self.para(p)
                else:   # 구역 최상위: 문단 하나가 깨져도 나머지는 읽는다
                    try:
                        blocks = self.para(p)
                    except Exception as e:
                        self.warnings.append(f"{where} 문단 해석 실패: {type(e).__name__}: {e}")
                        blocks = []
                # C95 2단계: 변경 추적에서 문단 나눔을 지운 문단은 한글이 앞 문단과 붙여 보여 준다(hp:p@merged="1", 한컴 표기).
                # 숨김 삭제가 있는 문서에서만, 바로 앞 hp:p 가 글 문단으로 끝났을 때 이어 붙인다.
                if (self.header.hidden_tc and p.get("merged") == "1" and prev_tail_para and blocks
                        and isinstance(blocks[0], Paragraph) and out and isinstance(out[-1], Paragraph)):
                    out[-1] = Paragraph(out[-1].text + blocks[0].text, out[-1].style, out[-1].outline)
                    blocks = blocks[1:]
                out.extend(blocks)
                prev_tail_para = bool(blocks) and isinstance(blocks[-1], Paragraph) or (not blocks and prev_tail_para and p.get("merged") == "1")
        return out

    def sublist_blocks(self, el) -> list:
        sl = _child(el, "subList")
        return self.plist(sl) if sl is not None else []

    # ---------- 문단 ----------
    def para(self, p) -> list:
        style = self.header.styles.get(p.get("styleIDRef", ""), "")
        outline = self.header.outline.get(p.get("paraPrIDRef", ""), 0)
        if not outline and style:
            m = re.match(r"^개요\s*(\d)$", style)
            if m:
                outline = int(m.group(1))
        out: list = []
        buf: list[str] = []
        trailing: list = []

        def flush():
            t = "".join(buf)
            buf.clear()
            t = re.sub(r"[ \t]+\n", "\n", t).strip("\n")
            if t.strip():
                out.append(Paragraph(t.strip() if "\n" not in t else t, style, outline))

        def text_el(t):
            if t.text and not self._indel:
                buf.append(t.text)
            for c in t:
                n = _ln(c.tag)
                if n == "deleteBegin":   # 숨김 삭제 구간은 겹치거나 중첩될 수 있다 — 열린 구간 Id 집합으로 센다(C95 보강)
                    if c.get("TcId", "") in self.header.hidden_tc:
                        self._delopen.add(c.get("Id", ""))
                    self._indel = bool(self._delopen)
                elif n == "deleteEnd":
                    self._delopen.discard(c.get("Id", ""))
                    self._indel = bool(self._delopen)
                elif self._indel:
                    if c.tail:
                        pass
                    continue
                if n == "tab":
                    buf.append("\t")
                elif n == "lineBreak":
                    buf.append("\n")
                elif n in ("fwSpace", "nbSpace"):
                    buf.append(" ")
                elif n == "hyphen":
                    pass  # 줄 끝 하이픈(HWP5 제어문자 24) — HWP5 판독기와 같이 글로 내지 않는다
                # markpen·titleMark 등은 글이 없음
                if c.tail and not self._indel:
                    buf.append(c.tail)

        def obj(c):
            """run 속 요소 하나 → 본문 처리."""
            n = _ln(c.tag)
            if n == "t":
                text_el(c)
            elif self._indel:
                return   # 숨김 삭제 구간 안의 표·그림·컨트롤은 한글 화면에 없다(C95 2단계)
            elif n == "tbl":
                flush()
                out.append(self.table(c))
            elif n in _SHAPES:
                flush()
                out.extend(self.shape(c))
            elif n == "equation":
                flush()
                sc = _child(c, "script")
                out.append(Equation((sc.text or "").strip() if sc is not None else ""))
            elif n == "ctrl":
                for d in c:
                    ctrl(d)
            elif n in ("footNote", "endNote", "header", "footer", "autoNum"):
                ctrl(c)
            elif n == "switch":
                # run 안 호환 블록 — 예: <switch><case 2016/ooxmlchart><chart/></case>
                # <default><ole/></default></switch>. HWP5 원본은 차트·OLE 를 OLE 개체 1개로
                # 저장하므로, 원본과 같은 모양인 default 를 먼저 쓰고 비었으면 case 를 쓴다.
                for c2 in _switch_pick(c, prefer="default"):
                    obj(c2)

        def ctrl(d):
            n = _ln(d.tag)
            if n in ("footNote", "endNote"):
                if n == "footNote":
                    self.fn_no += 1
                    no = self.fn_no
                    buf.append(f"[^{no}]")
                    trailing.append(Note("footnote", no, self.sublist_blocks(d)))
                else:
                    self.en_no += 1
                    no = self.en_no
                    buf.append(f"[^미{no}]")
                    trailing.append(Note("endnote", no, self.sublist_blocks(d)))
            elif n in ("header", "footer"):
                trailing.append(HeaderFooter(n, self.sublist_blocks(d)))
            elif n == "autoNum":
                # 쪽 번호는 조판 캐시(쪽마다 달라짐) — HWP5 판독기와 같이 글로 내지 않는다
                if d.get("numType", "").upper() in ("PAGE", "TOTAL_PAGE"):
                    return
                if d.get("num") is not None:
                    n = str(d.get("num"))
                    buf.append(AUTONUM_MARK + n + AUTONUM_MARK if self.autonum_mark else n)

        for run in p:
            rn = _ln(run.tag)
            if rn == "run":
                for c in run:
                    obj(c)
            elif rn in ("switch",):  # 호환 블록: case 우선, 없으면 default
                for r in _switch_pick(run, prefer="case"):
                    if _ln(r.tag) == "run":
                        for c in r:
                            obj(c)
        flush()
        out.extend(trailing)
        return out

    # ---------- 표 ----------
    def table(self, tbl) -> Table:
        self.table_no += 1
        t = Table(_int(tbl.get("rowCnt")), _int(tbl.get("colCnt")), id=self.table_no)
        cap = _child(tbl, "caption")
        if cap is not None:
            t.caption = " ".join(b.text for b in self.sublist_blocks(cap) if isinstance(b, Paragraph)).strip()
        r_auto = 0
        for tr in _children(tbl, "tr"):
            c_auto = 0
            for tc in _children(tr, "tc"):
                addr = _child(tc, "cellAddr")
                span = _child(tc, "cellSpan")
                col = _int(addr.get("colAddr") if addr is not None else tc.get("colAddr"), c_auto)
                row = _int(addr.get("rowAddr") if addr is not None else tc.get("rowAddr"), r_auto)
                cs = _int(span.get("colSpan") if span is not None else tc.get("colSpan"), 1)
                rs = _int(span.get("rowSpan") if span is not None else tc.get("rowSpan"), 1)
                cell = Cell(row, col, max(rs, 1), max(cs, 1), self.sublist_blocks(tc),
                            is_header=tc.get("header") in ("1", "true"))
                t.cells.append(cell)
                c_auto = col + max(cs, 1)
            r_auto += 1
        return t

    # ---------- 도형 ----------
    def shape(self, el) -> list:
        n = _ln(el.tag)
        out: list = []
        cap = _child(el, "caption")
        caption = ""
        if cap is not None:
            caption = " ".join(b.text for b in self.sublist_blocks(cap) if isinstance(b, Paragraph)).strip()
        if n == "pic":
            img = None
            for d in el.iter():
                if _ln(d.tag) == "img" and d.get("binaryItemIDRef"):
                    img = d.get("binaryItemIDRef")
                    break
            out.append(Image(self.image_name(img) if img else "", caption))
        elif n in ("ole", "chart"):  # OLE 개체·차트 — HWP 쪽 OLE 와 같이 그림 1개로 센다
            ref = el.get("binaryItemIDRef") or el.get("chartIDRef")
            out.append(Image(self.image_name(ref) if ref else "", caption))
        elif n == "container":
            for c in el:
                if _ln(c.tag) in _SHAPES:
                    out.extend(self.shape(c))
            # 묶음 개체의 캡션 — HWP5 판독기와 같이 안의 그림마다 붙인다(그림이 없으면 문단)
            ims = [b for b in out if isinstance(b, Image)]
            if caption and ims:
                for im in ims:
                    im.caption = caption
            elif caption:
                out.append(Paragraph(caption))
        else:
            if n == "rect":
                # 사각형의 그림 채우기(imgBrush) — HWP5 판독기가 사각형 이미지 채우기를 그림으로 세는 것과 맞춘다
                for d in el.iter():
                    if _ln(d.tag) == "imgBrush":
                        ref = next((x.get("binaryItemIDRef") for x in d.iter()
                                    if _ln(x.tag) == "img" and x.get("binaryItemIDRef")), None)
                        if ref:
                            out.append(Image(self.image_name(ref), ""))
                        break
            dt = _child(el, "drawText")
            if caption:
                out.append(Paragraph(caption))
            if dt is not None:
                out.append(TextBox(self.sublist_blocks(dt)))
        return out

    def parse(self) -> list:
        blocks: list = []
        for s in self.sections:
            try:
                root = ET.fromstring(self.z.read(s))
            except ET.ParseError as e:
                self.warnings.append(f"{s} XML 오류: {e}")
                continue
            blocks.extend(self.plist(root, s))
        return blocks


def _zip_read(path: str, name: str) -> bytes:
    # Windows 에서는 열어 둔 ZIP 이 파일을 잠가 임시 폴더 삭제가 막힌다 — 읽고 바로 닫는다
    with zipfile.ZipFile(path) as zz:
        return zz.read(name)


def read_hwpx(path: str, autonum_mark: bool = False) -> Document:
    with zipfile.ZipFile(path) as z:
        p = HwpxParser(z, autonum_mark)
        blocks = p.parse()
        prv = ""
        if "Preview/PrvText.txt" in z.namelist():
            prv = z.read("Preview/PrvText.txt").decode("utf-8", "replace")
    images = {}
    for n in p.bin_files:
        images[n.rsplit("/", 1)[-1]] = (lambda name=n: _zip_read(path, name))
    meta = {"format": "hwpx", "sections": len(p.sections), "preview": prv[:500]}
    return Document(blocks, meta, images, p.warnings)
