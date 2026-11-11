from __future__ import annotations
import os, zipfile
from .model import Document
from .hwp5 import read_hwp5, _is_ole, HwpError, EncryptedDocument  # noqa: F401


def read(path: str, autonum_mark: bool = False, visible: bool = False) -> Document:
    """형식을 가려(HWPX=ZIP, HWP5=OLE) 문서 모델로 읽는다.
    autonum_mark=True 면 자동 번호(캡션·각주 번호) 앞뒤에 보이지 않는 표지(U+2063)를 붙인다(검증서용)."""
    from .grade import guard
    dec = guard(path)  # 보안등급 게이트 — 설정이 없으면 통과
    if zipfile.is_zipfile(path):
        from .hwpx import read_hwpx
        doc = read_hwpx(path, autonum_mark)
    elif _is_ole(path):
        doc = read_hwp5(path, autonum_mark, visible)
    else:
        raise HwpError("HWP 5.0(OLE)·HWPX(ZIP) 형식이 아닙니다")
    doc.meta["source"] = os.path.basename(path)
    if dec and dec.get("mask_values"):
        from .sens import mask_doc
        mask_doc(doc, dec["mask_values"])
        doc.meta["masked"] = True
    return doc


def convert(path: str, outdir: str) -> dict:
    from .render import write_outputs
    return write_outputs(read(path, visible=True), outdir)   # C77: 화면에 보이는 글만
