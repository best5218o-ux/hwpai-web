"""비배포 HWP 의 ViewText 숨김 — 엔진이 한글 화면에 없는 ViewText 글을 HWPX 에 넣는 문제 우회.

원인(2026-11-09 확인): 비배포 문서(FileHeader 플래그 0x04 꺼짐)는 한글 화면 본문이 BodyText 인데,
rhwp 엔진이 ViewText 스트림을 함께 읽어 한글에 없는 글이 HWPX 에 들어간다 (0195.hwp: 특허심판원 기사 +~1,800자).

처리: 엔진에 넘길 임시 사본에서 디렉터리 항목 이름 「ViewText」를 같은 길이의 「ZZZZZZZZ」로 바꾼다.
  - 같은 길이라 CFB 구조·크기 변화 없음. 대문자 기준 정렬 위치도 그대로(같은 길이 형제 중 마지막)라 트리가 깨지지 않는다.
  - 원본 파일은 건드리지 않는다. 검증(audit)은 원본을 BodyText 로 읽는다.
배포용 문서(플래그 0x04)는 ViewText 가 본문이므로 손대지 않는다.
"""
from __future__ import annotations

import os
import shutil
import struct
import tempfile

FLAG_DISTRIBUTE = 4
_OLD = "ViewText".encode("utf-16-le")
_NEW = "ZZZZZZZZ".encode("utf-16-le")


def hidden_copy(src: str, workdir: str | None = None) -> str | None:
    """ViewText 를 숨긴 임시 사본 경로를 돌려준다. 해당 없으면 None (원본을 그대로 쓴다)."""
    try:
        import olefile
        ole = olefile.OleFileIO(src)
        try:
            if not ole.exists("ViewText/Section0") or not ole.exists("FileHeader"):
                return None
            head = ole.openstream("FileHeader").read()
        finally:
            ole.close()
    except Exception:
        return None
    if len(head) < 40 or not head.startswith(b"HWP Document File"):
        return None
    if struct.unpack_from("<I", head, 36)[0] & FLAG_DISTRIBUTE:
        return None  # 배포용: ViewText 가 본문
    eng = engine_copy_unhidden(src, workdir)
    if eng:
        return eng
    data = bytearray(open(src, "rb").read())
    if data.count(_OLD) == 1:
        data = bytearray(bytes(data).replace(_OLD, _NEW))
    else:
        # C85: 옛 저장본은 같은 이름의 디렉터리 항목이 더 남아 있는 경우가 있다(실문서 a2afde11f4eceb89). 트리에 실제로 매달린 항목 하나만 찾아 바꾼다.
        off = _tree_entry_offset(src, "ViewText")
        if off is None or bytes(data[off:off + len(_OLD)]) != _OLD:
            return None  # 애매하면 건드리지 않는다
        data[off:off + len(_OLD)] = _NEW
    d = tempfile.mkdtemp(prefix="hwpai_vt_", dir=workdir)
    dst = os.path.join(d, "engine_input.hwp")
    with open(dst, "wb") as f:
        f.write(bytes(data))
    return dst


def _tree_entry_offset(src: str, name: str) -> int | None:
    """CFB 디렉터리 트리에 실제로 있는 항목 한 개(저장소)의 파일 안 바이트 위치. 못 찾거나 둘 이상이면 None."""
    try:
        import olefile
        ole = olefile.OleFileIO(src)
        try:
            ss = ole.sector_size
            sids = [i for i, e in enumerate(ole.direntries) if e is not None and e.name == name and e.entry_type == olefile.STGTY_STORAGE]
            if len(sids) != 1:
                return None
            chain = []
            sect = ole.first_dir_sector
            while sect != olefile.ENDOFCHAIN and sect >= 0 and len(chain) < 100000:
                chain.append(sect)
                sect = ole.fat[sect]
            per = ss // 128
            sid = sids[0]
            if sid // per >= len(chain):
                return None
            return (chain[sid // per] + 1) * ss + (sid % per) * 128
        finally:
            ole.close()
    except Exception:
        return None


def cleanup(path: str | None) -> None:
    if path:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def engine_copy_unhidden(src: str, workdir: str | None = None) -> str | None:
    """C95 2단계: 변경 추적에 숨김(hide=1) 삽입·삭제가 있는 비배포 문서는 ViewText 를 숨기지 않고, 대신 엔진 입력 사본의 DocInfo 에서
    그 정의들의 hide 만 0 으로 바꾼다. 엔진(rhwp)은 숨김 구간을 미리 지운 뒤(투영) 변환하므로, 이렇게 해야 지운 글·지운 표·지운 문단 나눔이
    변환본에 자리로 남고 뒤처리(tracked.apply_full)가 그 자리에 한컴 표기의 삭제·삽입 표식을 건다. 원본 파일은 건드리지 않는다.
    DocInfo 를 다시 압축한 길이가 원래보다 길면(드묾) 하지 않고 None. 해당 없으면 None."""
    try:
        import olefile
        import zlib
        ole = olefile.OleFileIO(src)
        try:
            if not ole.exists("ViewText/Section0") or not ole.exists("DocInfo"):
                return None
            head = ole.openstream("FileHeader").read()
            flags = struct.unpack_from("<I", head, 36)[0]
            if flags & (FLAG_DISTRIBUTE | 2 | 16):
                return None
            comp = bool(flags & 1)
            raw = ole.openstream("DocInfo").read()
        finally:
            ole.close()
        d = bytearray(zlib.decompress(raw, -15) if comp else raw)
        p = k = tc_no = 0
        hidden_ids = []
        while p + 4 <= len(d):
            h = struct.unpack_from("<I", d, p)[0]
            tag, sz = h & 0x3FF, h >> 20
            p += 4
            if sz == 0xFFF:
                sz = struct.unpack_from("<I", d, p)[0]
                p += 4
            if tag == 0x60:
                if sz >= 26 and struct.unpack_from("<I", d, p)[0] in (0x10, 0x11) and struct.unpack_from("<I", d, p + 22)[0] == 1:
                    struct.pack_into("<I", d, p + 22, 0)
                    hidden_ids.append(tc_no + 1)
                    k += 1
                tc_no += 1
            p += sz
        if not k:
            return None
        if comp:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            new = c.compress(bytes(d)) + c.flush()
        else:
            new = bytes(d)
        if len(new) > len(raw):
            return None
        new += b"\0" * (len(raw) - len(new))   # 같은 길이로(압축 끝 뒤 0 채움 — 풀 때 무시됨)
        dd = tempfile.mkdtemp(prefix="hwpai_vt_", dir=workdir)
        dst = os.path.join(dd, "engine_input.hwp")
        shutil.copyfile(src, dst)
        o = olefile.OleFileIO(dst, write_mode=True)
        try:
            o.write_stream("DocInfo", new)
        finally:
            o.close()
        # 뒤처리(tracked)는 엔진 입력 사본을 읽는다 — 원래 숨김 값을 옆 파일로 남겨 header 에 원본 그대로 쓰게 한다
        with open(dst + ".hidden_tc", "w", encoding="ascii") as f:
            f.write(",".join(map(str, hidden_ids)))
        return dst
    except Exception:
        return None


def _rename_viewtext(path: str, workdir: str | None = None) -> str | None:
    """ViewText 를 ZZZZZZZZ 로 숨긴 사본(이전 방식, 엔진이 최종 본문 BodyText 를 읽게)."""
    data = bytearray(open(path, "rb").read())
    if data.count(_OLD) == 1:
        data = bytearray(bytes(data).replace(_OLD, _NEW))
    else:
        off = _tree_entry_offset(path, "ViewText")
        if off is None or bytes(data[off:off + len(_OLD)]) != _OLD:
            return None
        data[off:off + len(_OLD)] = _NEW
    d = tempfile.mkdtemp(prefix="hwpai_vt_", dir=workdir)
    dst = os.path.join(d, "engine_input.hwp")
    with open(dst, "wb") as f:
        f.write(bytes(data))
    return dst


def convert_hwp(eng, src: str, dst: str, workdir: str | None = None, **kw) -> dict:
    """제품 변환 경로 한 곳: 엔진 입력 사본 고르기 → 변환(뒤처리 포함) → 변경 추적 전체 구조 모드가 안 되면 최종 본문으로 다시 변환.
    batch.py(데스크톱·웹 공통)와 시험 도구가 같은 함수를 쓴다."""
    from . import tracked as _tr
    vt = hidden_copy(src, workdir)
    try:
        del _tr.NEED_FALLBACK[:]
        r = eng.convert(vt or src, dst, **kw)
        if r.get("ok") and vt and os.path.exists(vt + ".hidden_tc") and dst in _tr.NEED_FALLBACK:
            del _tr.NEED_FALLBACK[:]
            vt2 = _rename_viewtext(vt, workdir)
            if vt2:
                try:
                    shutil.copyfile(vt + ".hidden_tc", vt2 + ".hidden_tc.legacy")
                    r2 = eng.convert(vt2, dst, **kw)
                finally:
                    cleanup(vt2)
                r2["notes"] = list(r2.get("notes") or []) + ["변경 추적: 지운 문단·표까지 실을 수 없는 구조라 최종 본문 기준으로 변환(이력은 일부만)"]
                return r2
        return r
    finally:
        cleanup(vt)
