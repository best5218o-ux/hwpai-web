"""공통 문서 모델 — HWP(5.0)와 HWPX가 같은 모양으로 올라온다.

블록 종류
  Paragraph  글 한 덩어리 (style/outline 은 알 수 있을 때만)
  Table      표. 셀마다 (행, 열, 행병합, 열병합)과 안쪽 블록을 가진다 (표 속 표 가능)
  Image      그림·OLE (원본 바이트는 Document.images 에서 이름으로 찾는다)
  Equation   수식 스크립트
  Note       각주·미주 (본문에는 [^n] 표시만 남고 내용은 여기에)
  TextBox    글상자·도형 속 글
  HeaderFooter 머리말·꼬리말 (쪽마다 반복되므로 한 번만)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Paragraph:
    text: str
    style: str = ""          # 스타일 이름(예: "개요 1") — 알 수 있을 때만
    outline: int = 0         # 개요 수준 1..7, 0이면 없음
    kind: str = "p"

    def to_dict(self):
        d = {"type": "p", "text": self.text}
        if self.style:
            d["style"] = self.style
        if self.outline:
            d["outline"] = self.outline
        return d


@dataclass
class Cell:
    row: int
    col: int
    rowspan: int
    colspan: int
    blocks: list = field(default_factory=list)
    is_header: bool = False

    def to_dict(self):
        return {"row": self.row, "col": self.col, "rowspan": self.rowspan, "colspan": self.colspan,
                "blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Table:
    nrows: int
    ncols: int
    cells: list = field(default_factory=list)
    caption: str = ""
    id: int = 0              # 문서 안 번호(1부터, 표 속 표 포함, 등장 순)
    kind: str = "table"

    def to_dict(self):
        return {"type": "table", "id": self.id, "caption": self.caption,
                "nrows": self.nrows, "ncols": self.ncols,
                "cells": [c.to_dict() for c in self.cells]}


@dataclass
class Image:
    name: str                # BinData 안 파일명 (예: BIN0002.jpg)
    caption: str = ""
    kind: str = "image"

    def to_dict(self):
        return {"type": "image", "name": self.name, "caption": self.caption}


@dataclass
class Equation:
    script: str
    kind: str = "equation"

    def to_dict(self):
        return {"type": "equation", "script": self.script}


@dataclass
class Note:
    kind: str                # 'footnote' | 'endnote'
    number: int
    blocks: list = field(default_factory=list)

    def to_dict(self):
        return {"type": self.kind, "number": self.number, "blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class TextBox:
    blocks: list = field(default_factory=list)
    kind: str = "textbox"

    def to_dict(self):
        return {"type": "textbox", "blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class HeaderFooter:
    role: str                # 'header' | 'footer'
    blocks: list = field(default_factory=list)
    kind: str = "headerfooter"

    def to_dict(self):
        return {"type": self.role, "blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Document:
    blocks: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)       # 형식, 버전, 플래그, 원본 이름 …
    images: dict = field(default_factory=dict)     # 이름 -> 바이트를 돌려주는 함수 또는 바이트
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return {"meta": self.meta, "warnings": self.warnings, "blocks": [b.to_dict() for b in self.blocks]}

    def image_bytes(self, name: str) -> bytes | None:
        v = self.images.get(name)
        if v is None:  # HWP5: DocInfo 이름(BIN0001.png)과 스트림 이름(Bin0001.png)의 대소문자가 다르다
            low = name.lower()
            v = next((x for k, x in self.images.items() if k.lower() == low), None)
        return v() if callable(v) else v


# ---------- 표 → 격자 ----------
def table_grid(t: Table, cell_text: Callable[[Cell], str], fill_cols: bool = True, fill_rows: bool = True) -> list[list[str]]:
    """병합 셀을 펼친 격자.

    세로 병합(행병합)은 항상 아래 칸까지 같은 값을 채운다 — 행마다 '구분'이 살아 있어야
    한 줄씩 떼어도 뜻이 통하기 때문. 가로 병합은 fill_cols=True 일 때만 채운다
    (CSV·레코드용). 마크다운은 False 로 두어 제목줄이 칸마다 반복되지 않게 한다.
    """
    nr, nc = max(t.nrows, 1), max(t.ncols, 1)
    for c in t.cells:  # 선언된 크기보다 큰 주소가 있으면 늘린다
        nr = max(nr, c.row + max(c.rowspan, 1))
        nc = max(nc, c.col + max(c.colspan, 1))
    g: list[list[str | None]] = [[None] * nc for _ in range(nr)]
    for c in t.cells:
        txt = cell_text(c)
        for i in range(max(c.rowspan, 1)):
            for j in range(max(c.colspan, 1)):
                r, k = c.row + i, c.col + j
                if r < nr and k < nc and g[r][k] is None:
                    g[r][k] = txt if ((fill_rows or i == 0) and (fill_cols or j == 0)) else ""
    return [[(x if x is not None else "") for x in row] for row in g]


def walk_tables(blocks):
    """블록 트리 속 모든 표를 등장 순서대로 (표 속 표 포함)."""
    for b in blocks:
        if isinstance(b, Table):
            yield b
            for c in b.cells:
                yield from walk_tables(c.blocks)
        elif isinstance(b, (TextBox, Note, HeaderFooter)):
            yield from walk_tables(b.blocks)
