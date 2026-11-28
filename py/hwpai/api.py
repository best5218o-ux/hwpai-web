from __future__ import annotations
import os, zipfile
from .model import Document
from .hwp5 import read_hwp5, _is_ole, HwpError, EncryptedDocument  # noqa: F401


def read(path: str, autonum_mark: bool = False, visible: bool = False) -> Document:
    """형식을 가려(HWPX=ZIP, HWP5=OLE, HWP3=머리글) 문서 모델로 읽는다.
    autonum_mark=True 면 자동 번호(캡션·각주 번호) 앞뒤에 보이지 않는 표지(U+2063)를 붙인다(검증서용)."""
    from .grade import guard
    dec = guard(path)  # 보안등급 게이트 — 설정이 없으면 통과
    if zipfile.is_zipfile(path):
        from .hwpx import read_hwpx
        doc = read_hwpx(path, autonum_mark)
    elif _is_ole(path):
        doc = read_hwp5(path, autonum_mark, visible)
    else:
        from .hwp3 import is_hwp3, read_hwp3, Hwp3Error
        from .hml import is_hml, read_hml
        if is_hml(path):                                   # 0.9.2: XML 로 쓴 한글 문서(HML)도 독립 판독
            doc = read_hml(path, autonum_mark)
            doc.meta["source"] = os.path.basename(path)
            if dec and dec.get("mask_values"):
                from .sens import mask_doc
                mask_doc(doc, dec["mask_values"])
                doc.meta["masked"] = True
            return doc
        if not is_hwp3(path):
            raise HwpError("HWP 5.x(OLE)·HWP 3.0·2.x·1.x·HML·HWPX(ZIP) 형식이 아닙니다")
        try:
            doc = read_hwp3(path, autonum_mark, visible)      # 0.9.2: 옛 형식 원본도 독립 판독(검증서 대조용)
        except Hwp3Error as e:
            raise HwpError(f"HWP 3.0·2.x 문서를 읽지 못했습니다: {e}")
    doc.meta["source"] = os.path.basename(path)
    if dec and dec.get("mask_values"):
        from .sens import mask_doc
        mask_doc(doc, dec["mask_values"])
        doc.meta["masked"] = True
    return doc


def convert(path: str, outdir: str) -> dict:
    from .render import write_outputs
    return write_outputs(read(path, visible=True), outdir)   # C77: 화면에 보이는 글만
