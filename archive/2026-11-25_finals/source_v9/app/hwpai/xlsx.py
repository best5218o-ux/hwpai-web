"""외부 라이브러리 없이 엑셀(.xlsx) 보고서를 쓴다 — 이관대장·판정 색·요약 시트.

OOXML 최소 구성(workbook·sheet·styles·sharedStrings 없이 inlineStr)만 쓴다.
"""
from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

# 판정별 칸 색 (PASS 연두, WARN 노랑, FAIL 빨강, 실패·격리 회색)
FILLS = {"PASS": "FFC6EFCE", "WARN": "FFFFEB9C", "FAIL": "FFFFC7CE", "GRAY": "FFD9D9D9", "HEAD": "FF1F3864"}
_STYLE_IDX = {"": 0, "HEAD": 1, "PASS": 2, "WARN": 3, "FAIL": 4, "GRAY": 5}


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v, style: int) -> str:
    st = f' s="{style}"' if style else ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    txt = escape("" if v is None else str(v)).replace("\x00", "")
    txt = "".join(ch for ch in txt if ch in "\t\n\r" or ord(ch) >= 0x20)
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{txt}</t></is></c>'


def _sheet(rows: list[list], styles: list[str], widths: list[int]) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = []
    for r, (row, st) in enumerate(zip(rows, styles), 1):
        sidx = _STYLE_IDX.get(st, 0)
        body.append(f'<row r="{r}">' + "".join(_cell(f"{_col(c)}{r}", v, sidx) for c, v in enumerate(row)) + "</row>")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>'
            + (f'<autoFilter ref="A1:{_col(len(rows[0]) - 1)}{len(rows)}"/>' if rows and len(rows) > 1 else "")
            + '</worksheet>')


def _styles() -> str:
    fills = '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    for k in ("HEAD", "PASS", "WARN", "FAIL", "GRAY"):
        fills += f'<fill><patternFill patternType="solid"><fgColor rgb="{FILLS[k]}"/><bgColor indexed="64"/></patternFill></fill>'
    xfs = '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
    xfs += '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyFill="1" applyFont="1"/>'
    for i in range(4):
        xfs += f'<xf numFmtId="0" fontId="0" fillId="{3 + i}" borderId="0" applyFill="1"/>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="10"/><name val="맑은 고딕"/></font>'
            '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="맑은 고딕"/></font></fonts>'
            f'<fills count="7">{fills}</fills><borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="6">{xfs}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def write_xlsx(path: str, sheets: list[tuple[str, list[list], list[str], list[int]]]):
    """sheets: [(시트 이름, 행들, 행별 스타일 키, 열 너비)]"""
    wb_sheets = "".join(f'<sheet name="{escape(n[:31])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, *_) in enumerate(sheets))
    rels = "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                   f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
    rels += (f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
             'Target="styles.xml"/>')
    ct = "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   f'{ct}</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets>{wb_sheets}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        z.writestr("xl/styles.xml", _styles())
        for i, (_n, rows, styles, widths) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet(rows, styles, widths))
    import os
    os.replace(tmp, path)
    return path


def ledger_xlsx(path: str, columns: list[str], rows: list[dict], summary: dict) -> str:
    def st(r):
        if r.get("상태") in ("변환실패", "격리"):
            return "FAIL" if r.get("상태") == "변환실패" else "GRAY"
        return r.get("판정") or ("GRAY" if r.get("상태") == "건너뜀" else "")
    data = [columns] + [[(i if c == "순번" else _num(r.get(c, ""))) for c in columns] for i, r in enumerate(rows, 1)]
    styles = ["HEAD"] + [st(r) for r in rows]
    widths = [6 if c == "순번" else 40 if c in ("원본", "변환본", "판정_이유", "검증서") else 14 for c in columns]
    need = [r for r in rows if r.get("판정") in ("FAIL", "WARN") or r.get("상태") in ("변환실패", "격리")]
    s2 = [["원본", "상태", "판정", "이유", "검증서"]] + [[r.get("원본"), r.get("상태"), r.get("판정"), r.get("판정_이유"), r.get("검증서")] for r in need]
    s3 = [["항목", "값"]] + [[k, v if isinstance(v, (int, float)) else str(v)] for k, v in summary.items()]
    return write_xlsx(path, [
        ("이관대장", data, styles, widths),
        ("사람확인목록", s2, ["HEAD"] + [st(r) for r in need], [50, 10, 8, 80, 50]),
        ("요약", s3, ["HEAD"] + [""] * (len(s3) - 1), [24, 80]),
    ])


def _num(v):
    if isinstance(v, (int, float)):
        return v
    try:
        return int(v) if str(v).isdigit() else float(v) if str(v).replace(".", "", 1).isdigit() else v
    except ValueError:
        return v
