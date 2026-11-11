"""HWP 5.0 (OLE 복합 파일) 직접 판독기.

pyhwp 같은 객체 모델을 만들지 않고 BodyText 레코드를 한 번 훑으며
필요한 것(문단 글, 표 셀 주소·병합, 각주, 글상자, 수식, 그림)만 꺼낸다.
레코드 규격은 한컴이 공개한 「한글 문서 파일 형식 5.0」을 따른다.

레코드 머리 : 32비트 = 태그(10) | 수준(10) | 크기(12, 0xFFF면 뒤 4바이트가 크기)
문단        : PARA_HEADER(수준 L) 아래 PARA_TEXT·CTRL_HEADER … (수준 L+1)
표 셀       : CTRL_HEADER('tbl ') 아래 TABLE, 그리고 LIST_HEADER + 형제 PARA_HEADER 들
"""
from __future__ import annotations

import re
import struct
import zlib

import olefile

from .model import (Cell, Document, Equation, HeaderFooter, Image, Note, Paragraph, Table, TextBox)

# ---- 태그 ----
T_DOC_BIN_DATA = 0x12
T_DOC_PARA_SHAPE = 0x19
T_DOC_STYLE = 0x1A
T_DOC_TRACK_CHANGE = 0x60  # HWPTAG_BEGIN+80: 변경 추적 (삽입·삭제, 숨김 여부)
T_PARA_RANGE_TAG = 0x46   # HWPTAG_BEGIN+54: 문단 범위 태그 (변경 추적 구간)
T_DISTRIBUTE = 0x1C
T_PARA_HEADER = 0x42
T_PARA_TEXT = 0x43
T_CTRL_HEADER = 0x47
T_LIST_HEADER = 0x48
T_TABLE = 0x4D
T_PICTURE = 0x55
T_OLE = 0x54  # SHAPE_COMPONENT_OLE (HWPTAG_BEGIN+68)
T_SHAPE_COMP = 0x4C  # SHAPE_COMPONENT (HWPTAG_BEGIN+60): 채우기(fill) 정보 포함
T_SHAPE_RECT = 0x4F  # SHAPE_COMPONENT_RECTANGLE (HWPTAG_BEGIN+63)
T_EQEDIT = 0x58

AUTONUM_MARK = "\u2063"  # 보이지 않는 구분자 — read(..., autonum_mark=True) 일 때만 쓴다

FLAG_COMPRESSED = 1
FLAG_ENCRYPTED = 2
FLAG_DISTRIBUTE = 4
FLAG_DRM = 16

_CTRL_RE = re.compile(r"[\x00-\x1f]")
# 8 wchar(16바이트)를 차지하는 제어문자 — 확장(뒤따르는 CTRL_HEADER 가 있음)과 인라인
_EXTENDED = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
_INLINE = {4, 5, 6, 7, 8, 9, 19, 20}


class HwpError(Exception):
    pass


class EncryptedDocument(HwpError):
    """열기 암호가 걸린 문서 — 본문은 열 수 없고 미리보기 텍스트만 있다."""

    def __init__(self, msg, preview=""):
        super().__init__(msg)
        self.preview = preview


# ======================================================================
# 바이트 → 레코드
# ======================================================================
def iter_records(data: bytes):
    i, n = 0, len(data)
    unpack = struct.unpack_from
    while i + 4 <= n:
        h = unpack("<I", data, i)[0]
        i += 4
        size = h >> 20
        if size == 0xFFF:
            if i + 4 > n:
                return
            size = unpack("<I", data, i)[0]
            i += 4
        yield h & 0x3FF, (h >> 10) & 0x3FF, data[i:i + size]
        i += size


def _inflate(raw: bytes) -> bytes:
    for wbits in (-15, 15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            continue
    # 끝이 잘린 스트림 — 풀 수 있는 데까지 푼다
    d = zlib.decompressobj(-15)
    try:
        return d.decompress(raw)
    except zlib.error as e:
        raise HwpError(f"압축 해제 실패: {e}")


# ======================================================================
# 배포용 문서(ViewText) 복호화 — AES-128 ECB, 키는 문서 안 256바이트에서 유도
# ======================================================================
def _msvc_rand(seed):
    state = seed & 0xFFFFFFFF
    while True:
        state = (state * 214013 + 2531011) & 0xFFFFFFFF
        yield (state >> 16) & 0x7FFF


def _distribute_key(blob: bytes) -> bytes:
    data = bytearray(blob[:256])
    seed = struct.unpack_from("<I", data, 0)[0]
    rnd = _msvc_rand(seed)
    n, key = 0, 0
    for i in range(256):
        if n == 0:
            key = next(rnd) & 0xFF
            n = (next(rnd) & 0xF) + 1
        if i >= 4:
            data[i] ^= key
        n -= 1
    off = (seed & 0xF) + 4
    return bytes(data[off:off + 16])


def _decrypt_viewtext(stream: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    tag = struct.unpack_from("<I", stream, 0)[0]
    if (tag & 0x3FF) != T_DISTRIBUTE:
        raise HwpError("배포용 문서의 첫 레코드가 아닙니다")
    key = _distribute_key(stream[4:4 + 256])
    enc = stream[4 + 256:]
    enc = enc[: len(enc) // 16 * 16]
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(enc) + dec.finalize()


# ======================================================================
# DocInfo — 그림 이름, 스타일 이름, 개요 수준
# ======================================================================
class DocInfo:
    def __init__(self, data: bytes):
        self.bin_names: dict[int, str] = {}
        self.styles: list[tuple[str, int]] = []   # (이름, 문단모양 id)
        self.para_outline: list[int] = []         # 문단모양 id → 개요 수준(0=없음)
        self.track_changes: list[tuple[int, int]] = []  # 변경 추적 레코드 순서대로 (종류 0x10 삽입·0x11 삭제, 숨김 1/0)
        bin_seq = 0
        for tag, _lv, pl in iter_records(data):
            try:
                if tag == T_DOC_BIN_DATA:
                    bin_seq += 1
                    attr = struct.unpack_from("<H", pl, 0)[0]
                    if (attr & 0xF) in (1, 2) and len(pl) >= 6:  # 임베딩/스토리지
                        bid = struct.unpack_from("<H", pl, 2)[0]
                        ln = struct.unpack_from("<H", pl, 4)[0]
                        ext = pl[6:6 + ln * 2].decode("utf-16-le", "replace")
                        # 그림 레코드가 가리키는 번호는 BIN_DATA 의 순번(1부터)이다
                        self.bin_names[bin_seq] = f"BIN{bid:04X}.{ext}" if ext else f"BIN{bid:04X}"
                elif tag == T_DOC_STYLE:
                    ln = struct.unpack_from("<H", pl, 0)[0]
                    name = pl[2:2 + ln * 2].decode("utf-16-le", "replace")
                    ln2 = struct.unpack_from("<H", pl, 2 + ln * 2)[0]
                    off = 2 + ln * 2 + 2 + ln2 * 2
                    pshape = struct.unpack_from("<H", pl, off + 2)[0] if len(pl) >= off + 4 else 0
                    self.styles.append((name, pshape))
                elif tag == T_DOC_PARA_SHAPE:
                    attr = struct.unpack_from("<I", pl, 0)[0]
                    kind = (attr >> 23) & 0x3         # 0 없음 1 개요 2 번호 3 글머리
                    level = ((attr >> 25) & 0x7) + 1  # 1..7
                    self.para_outline.append(level if kind == 1 else 0)
                elif tag == T_DOC_TRACK_CHANGE:
                    kind = struct.unpack_from("<I", pl, 0)[0]
                    hide = struct.unpack_from("<I", pl, 22)[0] if len(pl) >= 26 else 0
                    self.track_changes.append((kind, 1 if hide == 1 else 0))
            except struct.error:
                continue

    def style_name(self, sid: int) -> str:
        return self.styles[sid][0] if 0 <= sid < len(self.styles) else ""

    def outline_of(self, shape_id: int) -> int:
        return self.para_outline[shape_id] if 0 <= shape_id < len(self.para_outline) else 0


# ======================================================================
# 구역(Section) 해석
# ======================================================================
class SectionParser:
    def __init__(self, data: bytes, info: DocInfo, state: dict):
        tags, lvls, pls = [], [], []
        for t, lv, pl in iter_records(data):
            tags.append(t)
            lvls.append(lv)
            pls.append(pl)
        self.tag, self.lv, self.pl = tags, lvls, pls
        self.n = len(tags)
        self.info = info
        self.st = state  # 문서 전체에서 공유: table_no, fn_no, en_no, warnings
        # 하위 트리의 끝(다음에 수준이 같거나 낮은 레코드의 위치)
        end = [self.n] * self.n
        stack: list[int] = []
        for i, lv in enumerate(lvls):
            while stack and lvls[stack[-1]] >= lv:
                end[stack.pop()] = i
            stack.append(i)
        self.end = end

    # ---- 구역 전체 ----
    def parse(self) -> list:
        blocks: list = []
        i = 0
        while i < self.n:
            if self.tag[i] == T_PARA_HEADER and self.lv[i] == 0:
                try:
                    blocks.extend(self.para(i))
                except Exception as e:  # 한 문단이 깨져도 나머지는 살린다
                    self.st["warnings"].append(f"문단 해석 실패(레코드 {i}): {type(e).__name__}: {e}")
                i = self.end[i]
            else:
                i += 1
        return blocks

    # ---- 같은 수준의 PARA_HEADER 들을 모은다 (표 셀·글상자·각주 안) ----
    def paras_from(self, start: int, stop: int, level: int):
        blocks: list = []
        m = start
        while m < stop and self.lv[m] == level and self.tag[m] == T_PARA_HEADER:
            try:
                blocks.extend(self.para(m))
            except Exception as e:
                self.st["warnings"].append(f"문단 해석 실패(레코드 {m}): {type(e).__name__}: {e}")
            m = self.end[m]
        return blocks, m

    # ---- 변경 추적: 숨김 구간(삭제됐거나 숨김 처리된 글) 제거 — 한글 화면에 보이는 글 ----
    def _visible_text(self, text: bytes, ranges: bytes):
        """(보이는 글 바이트, 숨겨진 컨트롤 순번 집합). 컨트롤(그림·표 등)이 숨김 구간에 통째로 들어 있으면 그 컨트롤도 뺀다(C87)."""
        n = len(text) // 2
        hid = [False] * n
        for off in range(0, len(ranges) - 11, 12):
            s, e, tg = struct.unpack_from("<III", ranges, off)
            kind, ident = tg >> 24, tg & 0xFFFFFF
            if 1 <= ident <= len(self.info.track_changes):
                k_, hide = self.info.track_changes[ident - 1]
                if k_ == kind and hide == 1:
                    for u in range(s, min(e, n)):
                        hid[u] = True
        if not any(hid):
            return text, set()
        units = [struct.unpack_from("<H", text, 2 * u)[0] for u in range(n)]
        keep = [True] * n
        dropped: set = set()
        x = 0
        nctrl = 0
        while x < n:
            c = units[x]
            if c in _EXTENDED or c in _INLINE:
                w = min(8, n - x)
                idx = None
                if c in _EXTENDED:
                    idx = nctrl
                    nctrl += 1
                if all(hid[x:x + w]):
                    for u in range(x, x + w):
                        keep[u] = False
                    if idx is not None:
                        dropped.add(idx)
                elif any(hid[x:x + w]):
                    self.st["warnings"].append("가시 글: 컨트롤이 숨김 구간에 걸쳐 있어 건너뜀")
                x += w
                continue
            if hid[x] and c < 32:
                # 문단 끝·줄바꿈 같은 한 글자 제어가 숨김 구간에 있으면 구조를 깨지 않도록 그대로 둔다
                self.st["warnings"].append("가시 글: 제어 문자가 든 숨김 구간은 건너뜀")
                x += 1
                continue
            if hid[x]:
                keep[x] = False
            x += 1
        return b"".join(struct.pack("<H", units[u]) for u in range(n) if keep[u]), dropped

    # ---- 문단 하나 ----
    def para(self, i: int) -> list:
        L = self.lv[i]
        j = self.end[i]
        hdr = self.pl[i]
        shape_id = struct.unpack_from("<H", hdr, 8)[0] if len(hdr) >= 10 else -1
        style_id = hdr[10] if len(hdr) >= 11 else -1
        text = b""
        ranges = b""
        ctrls: list[tuple[int, int]] = []
        k = i + 1
        while k < j:
            if self.lv[k] == L + 1:
                tg = self.tag[k]
                if tg == T_PARA_TEXT:
                    text = self.pl[k]
                elif tg == T_PARA_RANGE_TAG:
                    ranges = self.pl[k]
                elif tg == T_CTRL_HEADER:
                    ctrls.append((k, self.end[k]))
                    k = self.end[k]
                    continue
            k += 1

        if self.st.get("visible") and text and ranges:
            text, _hidden_ctrl = self._visible_text(text, ranges)
            if _hidden_ctrl:
                ctrls = [c for i2, c in enumerate(ctrls) if i2 not in _hidden_ctrl]   # C87: 숨김 구간 안의 컨트롤(삭제된 그림 등)은 건너뛴다

        style = self.info.style_name(style_id)
        outline = self.info.outline_of(shape_id)
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

        s = text.decode("utf-16-le", "replace") if text else ""
        pos, nctrl = 0, 0
        while pos < len(s):
            m = _CTRL_RE.search(s, pos)
            if not m:
                buf.append(s[pos:])
                break
            if m.start() > pos:
                buf.append(s[pos:m.start()])
            c = ord(s[m.start()])
            pos = m.start() + 1
            if c in _EXTENDED:
                pos = m.start() + 8
                if nctrl < len(ctrls):
                    k, ke = ctrls[nctrl]
                    nctrl += 1
                    inline, blocks, splits = self.ctrl(k, ke)
                    if inline:
                        buf.append(inline)
                    if splits:          # 표·도형은 블록 단위 — 내용이 비어도 문단을 끊는다
                        flush()
                        out.extend(blocks)
                    elif blocks:
                        trailing.extend(blocks)
            elif c in _INLINE:
                pos = m.start() + 8
                if c == 9:
                    buf.append("\t")
            elif c == 10:
                buf.append("\n")
            elif c in (25, 30, 31):
                buf.append(" ")
            # 0, 13(문단 끝), 24(하이픈 — 한컴도 글로 내보내지 않음), 26~29 는 버린다
        flush()
        # 문단에 글이 없고 표지·제어만 있으면 out 은 그 블록들뿐 — 그대로 둔다
        out.extend(trailing)
        return out

    # ---- 컨트롤 하나 → (본문에 끼울 글, 블록들, 문단을 끊는가) ----
    def ctrl(self, k: int, ke: int):
        cid = bytes(self.pl[k][:4][::-1]).decode("latin1")
        if cid == "tbl ":
            return "", [self.table(k, ke)], True
        if cid == "gso ":
            return "", self.shape(k, ke), True
        if cid == "eqed":
            for m in range(k + 1, ke):
                if self.tag[m] == T_EQEDIT:
                    pl = self.pl[m]
                    if len(pl) >= 6:
                        ln = struct.unpack_from("<H", pl, 4)[0]
                        script = pl[6:6 + ln * 2].decode("utf-16-le", "replace").strip()
                        return "", [Equation(script)], True
            return "", [], False
        if cid in ("fn  ", "en  "):
            kind = "footnote" if cid == "fn  " else "endnote"
            key = "fn_no" if cid == "fn  " else "en_no"
            self.st[key] += 1
            no = self.st[key]
            blocks = self.list_blocks(k, ke)
            mark = f"[^{no}]" if kind == "footnote" else f"[^미{no}]"
            return mark, [Note(kind, no, blocks)], False
        if cid == "atno":  # 자동 번호(캡션의 "표 3" 같은 번호) — 저장된 값을 그대로 쓴다
            pl = self.pl[k]
            if len(pl) >= 10:
                # 번호 종류(속성 하위 4비트) 0 = 쪽 번호, 6 = 전체 쪽 수: 저장값은 조판 캐시라 글로 내지 않는다
                if struct.unpack_from("<I", pl, 4)[0] & 0xF in (0, 6):
                    return "", [], False
                n = str(struct.unpack_from("<H", pl, 8)[0])
                # 검증서용 표지: 자동 번호는 저장된 캐시값이라 변환기마다 다를 수 있다 — 구간을 표시해 둔다
                return (AUTONUM_MARK + n + AUTONUM_MARK if self.st.get("autonum_mark") else n), [], False
            return "", [], False
        if cid in ("head", "foot"):
            return "", [HeaderFooter("header" if cid == "head" else "footer", self.list_blocks(k, ke))], False
        return "", [], False

    def list_blocks(self, k: int, ke: int) -> list:
        """CTRL_HEADER 아래 LIST_HEADER 뒤의 문단들."""
        out: list = []
        m = k + 1
        while m < ke:
            if self.tag[m] == T_LIST_HEADER:
                b, m = self.paras_from(m + 1, ke, self.lv[m])
                out.extend(b)
            else:
                m += 1
        return out

    # ---- 표 ----
    def table(self, k: int, ke: int) -> Table:
        L1 = self.lv[k] + 1
        self.st["table_no"] += 1
        t = Table(0, 0, id=self.st["table_no"])
        seen_table = False
        cap: list[str] = []
        m = k + 1
        while m < ke:
            tg = self.tag[m]
            if self.lv[m] == L1 and tg == T_TABLE:
                pl = self.pl[m]
                t.nrows, t.ncols = struct.unpack_from("<HH", pl, 4)
                seen_table = True
                m += 1
            elif self.lv[m] == L1 and tg == T_LIST_HEADER:
                hdr = self.pl[m]
                blocks, m2 = self.paras_from(m + 1, ke, L1)
                if seen_table and len(hdr) >= 16:
                    col, row, cs, rs = struct.unpack_from("<HHHH", hdr, 8)
                    # C76: 제목 셀 — 셀 LIST_HEADER 6~7바이트(확장 속성)의 bit2 (rhwp CELL_FLAG_HEADER 0x0004, hwplib 「제목 셀」)
                    t.cells.append(Cell(row, col, max(rs, 1), max(cs, 1), blocks,
                                        is_header=bool(struct.unpack_from("<H", hdr, 6)[0] & 0x0004)))
                elif not seen_table:
                    cap.extend(b.text for b in blocks if isinstance(b, Paragraph))
                m = m2
            else:
                m += 1
        t.caption = " ".join(cap).strip()
        return t

    # ---- 도형(그림·글상자·묶음) ----
    def shape(self, k: int, ke: int) -> list:
        L1 = self.lv[k] + 1
        out: list = []
        caption = ""
        m = k + 1
        images: list[Image] = []
        texts: list = []
        fill_bids: list[int] = []   # 사각형의 이미지 채우기 (rhwp 는 hp:pic 으로 변환)
        saw_rect = False
        saw_pic = False
        while m < ke:
            tg = self.tag[m]
            if tg == T_SHAPE_COMP:
                bid = _fill_image_bin_id(self.pl[m])
                if bid is not None:
                    fill_bids.append(bid)
                m += 1
            elif tg == T_SHAPE_RECT:
                saw_rect = True
                m += 1
            elif tg == T_LIST_HEADER:
                blocks, m2 = self.paras_from(m + 1, ke, self.lv[m])
                if self.lv[m] == L1:   # 도형 바로 아래 = 캡션
                    caption = " ".join(b.text for b in blocks if isinstance(b, Paragraph)).strip()
                else:                  # 도형 안쪽 = 글상자 내용
                    texts.append(TextBox(blocks))
                m = m2
            elif tg == T_PICTURE:
                saw_pic = True
                pl = self.pl[m]
                if len(pl) >= 73:
                    bid = struct.unpack_from("<H", pl, 71)[0]
                    images.append(Image(self.st["bin_names"].get(bid, f"BIN{bid:04X}")))
                m += 1
            elif tg == T_OLE:  # 속성(4) extentX(4) extentY(4) BinData ID(2)
                pl = self.pl[m]
                if len(pl) >= 14:
                    bid = struct.unpack_from("<H", pl, 12)[0]
                    images.append(Image(self.st["bin_names"].get(bid, f"BIN{bid:04X}")))
                m += 1
            else:
                m += 1
        # 사각형에 이미지 채우기가 있고 별도 그림 개체가 없으면 그 채우기 이미지를 그림으로 센다
        if fill_bids and saw_rect and not saw_pic and not images:
            for bid in fill_bids:
                images.append(Image(self.st["bin_names"].get(bid, f"BIN{bid:04X}")))
        for im in images:
            im.caption = caption
        out.extend(images)
        if caption and not images:
            out.append(Paragraph(caption))
        out.extend(texts)
        return out


def _fill_image_bin_id(pl: bytes):
    """SHAPE_COMPONENT 레코드의 채우기 블록에서 이미지 채우기 BinData ID 를 읽는다.
    rhwp parse_shape_component_full 과 같은 순서: ctrl id(4|8) → 속성 42 → 렌더 행렬(cnt·96+48)
    → 테두리 13 → 채우기(u32 종류 비트, bit1=이미지 → mode·밝기·대비·효과 u8×4, BinData u16).
    이미지 채우기가 아니면 None."""
    n = len(pl)
    base = 8 if n >= 8 and pl[0:4] == pl[4:8] else 4
    p = base + 42
    if p + 2 > n:
        return None
    cnt = struct.unpack_from("<H", pl, p)[0]
    p += 2 + 48 + cnt * 96
    p += 13
    if p + 4 > n:
        return None
    if not struct.unpack_from("<I", pl, p)[0] & 0x02:
        return None
    # C73: rhwp parse_fill 과 같은 순서 — 종류 u32 → (bit0) 단색 12바이트 → (bit2) 그라데이션 → (bit1) 이미지.
    # 이전 판은 단색 블록(12바이트)을 건너뛰지 않아 단색 비트가 함께 켜진 이미지 채우기의 BinData ID 를 패턴색에서 읽어 0 으로 봤다.
    kind = struct.unpack_from("<I", pl, p)[0]
    p += 4
    if kind & 0x01:
        p += 12
    if kind & 0x04:
        if p + 21 > n:
            return None
        cnt2 = struct.unpack_from("<I", pl, p + 17)[0]
        cnt2 = min(cnt2, 64)
        p += 21 + (cnt2 * 4 if cnt2 > 2 else 0) + cnt2 * 4
    # 이미지: mode u8, 밝기 i8, 대비 i8, 효과 u8, BinData ID u16
    if p + 6 > n:
        return None
    bid = struct.unpack_from("<H", pl, p + 4)[0]
    return bid if bid != 0 else None


# ======================================================================
# 파일 하나
# ======================================================================
def _is_ole(path) -> bool:
    with open(path, "rb") as f:
        return f.read(8) == bytes.fromhex("d0cf11e0a1b11ae1")


def read_hwp5(path: str, autonum_mark: bool = False, visible: bool = False) -> Document:
    ole = olefile.OleFileIO(path)
    try:
        head = ole.openstream("FileHeader").read()
        if not head.startswith(b"HWP Document File"):
            raise HwpError("HWP 5.0 문서가 아닙니다")
        flags = struct.unpack_from("<I", head, 36)[0]
        ver = ".".join(str(b) for b in reversed(head[32:36]))
        compressed = bool(flags & FLAG_COMPRESSED)
        prv = ""
        if ole.exists("PrvText"):
            prv = ole.openstream("PrvText").read().decode("utf-16-le", "replace")
        if flags & FLAG_ENCRYPTED:
            raise EncryptedDocument("열기 암호가 걸린 문서입니다(한글에서 암호를 풀어 저장해야 판독 가능).", prv)
        if flags & FLAG_DRM:
            raise EncryptedDocument("DRM이 적용된 문서입니다.", prv)

        di = ole.openstream("DocInfo").read()
        info = DocInfo(_inflate(di) if compressed else di)

        body = "ViewText" if flags & FLAG_DISTRIBUTE else "BodyText"
        secs = sorted((e[1] for e in ole.listdir() if len(e) == 2 and e[0] == body and e[1].startswith("Section")),
                      key=lambda s: int(re.findall(r"\d+", s)[0]))
        images = {}
        for e in ole.listdir():
            if e[0] == "BinData" and len(e) == 2:
                name = e[1]
                reader = (lambda p=tuple(e): _read_bin(path, p, compressed))
                images[name] = reader


        state = {"table_no": 0, "fn_no": 0, "en_no": 0, "warnings": [], "bin_names": info.bin_names,
                 "autonum_mark": autonum_mark, "visible": visible}
        blocks: list = []
        for s in secs:
            raw = ole.openstream(f"{body}/{s}").read()
            if flags & FLAG_DISTRIBUTE:
                raw = _decrypt_viewtext(raw)
            data = _inflate(raw) if compressed else raw
            blocks.extend(SectionParser(data, info, state).parse())
        meta = {"format": "hwp5", "version": ver, "compressed": compressed,
                "distribute": bool(flags & FLAG_DISTRIBUTE), "sections": len(secs), "preview": prv[:500]}
        return Document(blocks, meta, images, state["warnings"])
    finally:
        ole.close()


def _read_bin(path, entry, compressed):
    ole = olefile.OleFileIO(path)
    try:
        raw = ole.openstream(list(entry)).read()
    finally:
        ole.close()
    if compressed:  # 문서가 압축 저장이면 BinData 도 압축된 것이 일반적
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            pass
    return raw
