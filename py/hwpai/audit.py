"""변환 검증서 — 원본 HWP(또는 HWPX)와 변환 HWPX 를 같은 문서 모델로 읽어 대조한다.

어떤 변환기(한컴·rhwp·그 밖)의 결과든 받는다. 변환 엔진 자신의 재검사(같은 파서로 다시
읽기)와 달리, 원본 쪽은 hwpai 의 HWP5 레코드 판독기, 변환본 쪽은 hwpai 의 HWPX 판독기로
읽으므로 엔진의 해석 오류가 그대로 통과하지 않는다.

검사 항목
  1 글     전체 글(공백 제거) 일치 여부, 4-gram 재현율·정밀도, 차이 위치(문단·글상자·각주 단위)
  2 표     개수, 표마다 격자 크기·병합 구조(행,열,행병합,열병합)·칸 글 차이(위치와 내용)
  3 그림   개수, 그림 데이터 해시(원본에 있는데 변환본에 없는 것)
  4 각주·미주·수식 개수, 수식 스크립트
  5 미리보기 원본 PrvText(한글이 저장한 첫 쪽 글)가 변환본 글에 들어 있는 비율 — 제3의 정답
  6 판독 경고·엔진 손실 보고

판정
  FAIL  내용 손실: 변환본 판독 불가 / 표 개수·병합 구조·칸 글 차이 / 그림 감소 /
        각주·미주·수식 개수 차이 / 원본 글이 빠지거나 바뀐 곳(문단 단위) / 글 재현율 < 0.98
  WARN  손실은 못 찾았지만 사람이 볼 것: 글 미세 차이 / 그림 데이터 해시 불일치 /
        미리보기 대조 낮음 / 판독 경고 / 엔진 손실 보고 / 원본을 독립 판독할 수 없음(HWP3·암호)
  PASS  위 항목 모두 일치
"""
from __future__ import annotations

import collections
import difflib
import hashlib
import json
import os
import re
import struct
import unicodedata
import zipfile
from dataclasses import dataclass, field

from .model import Equation, HeaderFooter, Image, Note, Paragraph, Table, TextBox, walk_tables
from .render import grid_of, plain_text, squash_latent_rows as _squash_latent_rows

AUDIT_VERSION = "1.1"
TEXT_RECALL_FAIL = 0.98
PRV_RECALL_WARN = 0.80

_WS = re.compile(r"\s+")
_MARK = re.compile(r"\[\^미?\d+\]|\[표\d+ 참조\]|\[그림:[^\]]*\]")


_AUTONUM = re.compile("\u2063(\\d*)\u2063")


def norm(s: str) -> str:
    """비교용 글: 공백·본문 표지 제거, 자동 번호 표지는 지우고 숫자는 남긴다."""
    return _WS.sub("", _MARK.sub("", (s or "").replace("\u2063", "").replace("\ufffd", "\u25a1")))   # C91: 읽을 수 없는 글자(U+FFFD)는 한컴 한글이 □ 로 저장한다


def _num_free(s: str) -> str:
    """자동 번호(캐시값)를 #으로 바꾼 글."""
    return _WS.sub("", _MARK.sub("", _AUTONUM.sub("#", s or "")))


def loose(s: str) -> str:
    """기호·사용자 정의 문자를 뺀 글. 변환기가 한컴 기호 글꼴 문자(사용자 정의 영역 등)를
    다른 코드로 옮기는 경우를 「내용 손실」과 가르기 위해 쓴다."""
    return "".join(c for c in _num_free(s)
                   if c != "\ufffd" and unicodedata.category(c) not in ("Co", "So", "Cn", "Cs", "Cf"))


def _covered(s: str, pool: collections.Counter) -> float:
    """s 의 4-gram 이 pool(변환본 전체)에 있는 비율(개수 무시)."""
    g = grams(s)
    if not g:
        return 1.0 if not s else 0.0
    return sum(1 for k in g if pool.get(k)) / len(g)


def grams(s: str, n: int = 4) -> collections.Counter:
    return collections.Counter(s[i:i + n] for i in range(max(len(s) - n + 1, 0)))


def recall_precision(ref: str, got: str) -> tuple[float, float]:
    if not ref and not got:
        return 1.0, 1.0
    if len(ref) < 4 or len(got) < 4:
        r = 1.0 if ref in got else 0.0
        p = 1.0 if got in ref else 0.0
        return r, p
    ga, gb = grams(ref), grams(got)
    inter = sum((ga & gb).values())
    return inter / max(sum(ga.values()), 1), inter / max(sum(gb.values()), 1)


# ---------------------------------------------------------------- 문서 → 대조 단위
def _units(doc) -> list[tuple[str, str]]:
    """표 밖의 글 단위(위치 이름, 글). 표 칸 글은 표 대조에서 따로 본다."""
    out: list[tuple[str, str]] = []
    cnt = collections.Counter()

    def emit(blocks, where):
        for b in blocks:
            if isinstance(b, Paragraph):
                cnt[where] += 1
                out.append((f"{where} {cnt[where]}번째 문단", b.text))
            elif isinstance(b, Table):
                if b.caption:
                    out.append((f"표{b.id} 캡션", b.caption))
                for c in b.cells:
                    emit([x for x in c.blocks if isinstance(x, (Note, TextBox))], f"표{b.id} 칸 안")
                    for x in c.blocks:
                        if isinstance(x, Table):
                            emit([x], where)
            elif isinstance(b, Note):
                nm = ("각주" if b.kind == "footnote" else "미주") + str(b.number)
                emit(b.blocks, nm)
            elif isinstance(b, TextBox):
                emit(b.blocks, f"{where}·글상자")
            elif isinstance(b, Equation):
                out.append((f"{where} 수식", b.script))
            elif isinstance(b, Image) and b.caption:
                out.append((f"{where} 그림 캡션", b.caption))
            elif isinstance(b, HeaderFooter):
                emit(b.blocks, "머리말" if b.role == "header" else "꼬리말")

    emit(doc.blocks, "본문")
    return out


def _count(doc, kind, pred=None) -> int:
    n = 0

    def walk(bs):
        nonlocal n
        for b in bs:
            if isinstance(b, kind) and (pred is None or pred(b)):
                n += 1
            if hasattr(b, "blocks"):
                walk(b.blocks)
            if hasattr(b, "cells"):
                for c in b.cells:
                    walk(c.blocks)
    walk(doc.blocks)
    return n


def _iter(doc, kind):
    def walk(bs):
        for b in bs:
            if isinstance(b, kind):
                yield b
            if hasattr(b, "blocks"):
                yield from walk(b.blocks)
            if hasattr(b, "cells"):
                for c in b.cells:
                    yield from walk(c.blocks)
    yield from walk(doc.blocks)


def _digests(data: bytes | None) -> set[str]:
    """그림 데이터 지문. OLE 는 HWP 쪽에 길이 머리(4바이트)가 붙는 경우가 있어 두 가지로 잰다."""
    if not data:
        return set()
    out = {hashlib.sha256(data).hexdigest()[:16]}
    if len(data) > 4:
        out.add(hashlib.sha256(data[4:]).hexdigest()[:16])
    ole = _ole_print(data)
    if ole:
        out.add(ole)
    return out


_CFB = bytes.fromhex("d0cf11e0a1b11ae1")


def _ole_print(data: bytes) -> str | None:
    """OLE 개체(차트·한셀 등)는 한글이 저장할 때마다 내부 스트림을 다시 쓴다(바이트가 달라짐).
    그래서 바이트 해시와 별도로 스트림 구성(이름 목록) 지문을 둔다. 'ole:' 로 시작한다."""
    off = 0 if data[:8] == _CFB else (4 if data[4:12] == _CFB else -1)
    if off < 0:
        return None
    try:
        import io
        import olefile
        o = olefile.OleFileIO(io.BytesIO(data[off:]))
        try:
            # OlePres* 는 표시용 그림 캐시 — 한글이 저장할 때 새로 만들거나 늘린다. 구성 비교에서 뺀다
            names = sorted("/".join(e) for e in o.listdir() if not e[-1].lstrip("\x01\x02\x05").startswith("OlePres"))
        finally:
            o.close()
        return "ole:" + hashlib.sha256("|".join(names).encode()).hexdigest()[:16]
    except Exception:
        return None


def _image_prints(doc) -> list[tuple[str, set[str]]]:
    res = []
    cache: dict[str, set[str]] = {}
    for im in _iter(doc, Image):
        if im.name not in cache:
            try:
                cache[im.name] = _digests(doc.image_bytes(im.name)) if im.name else set()
            except Exception:
                cache[im.name] = set()
        res.append((im.name, cache[im.name]))
    return res


# ---------------------------------------------------------------- 미리보기
def read_prvtext(path: str) -> str | None:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                if "Preview/PrvText.txt" in z.namelist():
                    return z.read("Preview/PrvText.txt").decode("utf-8", "replace")
            return None
        import olefile
        if not olefile.isOleFile(path):
            return None
        o = olefile.OleFileIO(path)
        try:
            if o.exists("PrvText"):
                return o.openstream("PrvText").read().decode("utf-16-le", "replace")
        finally:
            o.close()
    except Exception:
        return None
    return None


def _prv_norm(s: str) -> str:
    # PrvText 는 표 칸을 <...> 로 감싸고, 길면 잘린다 — 꺾쇠를 지우고 끝 64자는 버린다(잘림 대비)
    s = norm(s.replace("<", "").replace(">", ""))
    return s[:-64] if len(s) > 200 else s


def _prv_recall(prv_raw: str, conv_text: str) -> float:
    """미리보기 글이 변환본 글에 들어 있는 비율 — 줄(구분자) 단위, 순서와 무관.

    PrvText 는 표 칸을 행 순서대로 이어 붙이고 길이가 잘리므로, 4글자 짝 대조는
    칸 순서 차이만으로 점수가 떨어진다. 그래서 줄·표 칸(<…>) 구분자로 나눈 조각마다
    변환본 글에 그대로 들어 있는지 보고, 글자 수로 가중 평균한다.
    마지막 조각은 잘린 것일 수 있어 끝 64자를 뺀다(긴 경우).
    """
    segs = [x for x in re.split(r"[\r\n\x00\u000b<>]+", prv_raw or "") if x.strip()]
    tot = found = 0
    for i, seg in enumerate(segs):
        t = norm(seg.replace("<", "").replace(">", ""))
        if i == len(segs) - 1 and len(t) > 200:
            t = t[:-64]
        if len(t) < 2:
            continue
        tot += len(t)
        if t in conv_text:
            found += len(t)
    if tot == 0:
        return 1.0
    return found / tot


# ---------------------------------------------------------------- 형식 판별
def sniff(path: str) -> dict:
    """파일 형식·특성(암호·DRM·배포용·HWP3)을 본문을 풀지 않고 가린다."""
    info = {"format": "unknown"}
    try:
        size = os.path.getsize(path)
        info["size"] = size
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError as e:
        info["error"] = str(e)
        return info
    if size == 0:
        info["format"] = "empty"
        return info
    if head.startswith(b"PK"):
        info["format"] = "hwpx" if zipfile.is_zipfile(path) else "zip-broken"
        if info["format"] == "hwpx":
            try:
                with zipfile.ZipFile(path) as z:
                    nm = z.namelist()
                    info["encrypted"] = "META-INF/manifest.xml" in nm and b"encryption-data" in z.read("META-INF/manifest.xml")
                if "Contents/header.xml" not in nm:
                    info["format"] = "zip-not-hwpx"
            except Exception as e:
                info["format"] = "zip-broken"
                info["error"] = str(e)
        return info
    if head.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        try:
            import olefile
            o = olefile.OleFileIO(path)
            try:
                fh = o.openstream("FileHeader").read() if o.exists("FileHeader") else b""
            finally:
                o.close()
        except Exception as e:
            info["format"] = "ole-broken"
            info["error"] = str(e)
            return info
        if not fh.startswith(b"HWP Document File"):
            info["format"] = "ole-not-hwp"
            return info
        flags = struct.unpack_from("<I", fh, 36)[0] if len(fh) >= 40 else 0
        info.update(format="hwp5", version=".".join(str(b) for b in reversed(fh[32:36])),
                    encrypted=bool(flags & 2), distribute=bool(flags & 4), drm=bool(flags & 16))
        return info
    if head.startswith(b"HWP Document File V3") or head.startswith(b"HWP Document File V2"):
        info["format"] = "hwp3"
        return info
    if head.lstrip().startswith(b"<?xml") or b"<HWPML" in head:
        info["format"] = "hml"
        return info
    return info


# ---------------------------------------------------------------- 표 대조
def _table_sig(t: Table) -> str:
    g = grid_of(t, " ")
    first = norm(" ".join(g[0])) if g else ""
    return f"{len(g)}x{len(g[0]) if g else 0}:{first[:40]}"


def _compare_table(a: Table, b: Table, limit: int = 20) -> dict:
    a, na = _squash_latent_rows(a)
    b, nb = _squash_latent_rows(b)
    ga, gb = grid_of(a, " "), grid_of(b, " ")
    sa = sorted((c.row, c.col, c.rowspan, c.colspan) for c in a.cells)
    sb = sorted((c.row, c.col, c.rowspan, c.colspan) for c in b.cells)
    res = {"orig_id": a.id, "conv_id": b.id,
           "shape": [len(ga), len(ga[0]) if ga else 0], "shape_conv": [len(gb), len(gb[0]) if gb else 0],
           "cells": sum(len(r) for r in ga)}
    if na or nb:
        res["latent_rows"] = [na, nb]
    span_missing = sorted(set(sa) - set(sb))
    span_extra = sorted(set(sb) - set(sa))
    res["span_ok"] = not span_missing and not span_extra and len(sa) == len(sb)
    if not res["span_ok"]:
        res["span_missing"] = [list(x) for x in span_missing[:limit]]
        res["span_extra"] = [list(x) for x in span_extra[:limit]]
    diffs = []
    nbad = nsym = 0
    for r in range(max(len(ga), len(gb))):
        for c in range(max(len(ga[r]) if r < len(ga) else 0, len(gb[r]) if r < len(gb) else 0)):
            va = ga[r][c] if r < len(ga) and c < len(ga[r]) else None
            vb = gb[r][c] if r < len(gb) and c < len(gb[r]) else None
            if norm(va or "") != norm(vb or "") or (va is None) != (vb is None):
                if va is not None and vb is not None and loose(va) == loose(vb):
                    nsym += 1
                    continue
                nbad += 1
                if len(diffs) < limit:
                    diffs.append({"row": r + 1, "col": c + 1, "orig": (va or "").replace("\u2063", "")[:80], "conv": (vb or "").replace("\u2063", "")[:80],
                                  "kind": "칸 없음" if vb is None else ("칸 추가" if va is None else "글 다름")})
    res["cells_bad"] = nbad
    res["cells_symbol_mapped"] = nsym
    res["cell_diffs"] = diffs
    return res


# ---------------------------------------------------------------- 검증서
@dataclass
class Audit:
    original: str
    converted: str
    verdict: str = "FAIL"
    score: float | None = 0.0
    reasons: list = field(default_factory=list)       # 판정 이유 (FAIL·WARN)
    checks: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    visible_reference: dict | None = None  # 가시 글 기준 참고 판정 (공식 판정에 쓰지 않음)

    def to_dict(self):
        return {"audit_version": AUDIT_VERSION, "original": self.original, "converted": self.converted,
                "verdict": self.verdict, "score": None if self.score is None else round(self.score, 2),
                "reasons": self.reasons,
                "checks": self.checks, "details": self.details,
                "visible_reference": self.visible_reference}


def audit(original: str, converted: str, engine_report: dict | None = None, read=None, _nested: bool = False) -> Audit:
    """원본과 변환본을 대조해 검증서(Audit)를 만든다. 예외를 밖으로 내지 않는다."""
    from . import api
    read = read or (lambda p: api.read(p, autonum_mark=True))
    A = Audit(os.path.basename(original), os.path.basename(converted))
    fails, warns = [], []
    ck = A.checks

    def fail(code, msg):
        fails.append({"level": "FAIL", "code": code, "msg": msg})

    def warn(code, msg):
        warns.append({"level": "WARN", "code": code, "msg": msg})

    # ---- 변환본 읽기 (HWPX 여야 함)
    sc = sniff(converted)
    ck["converted_format"] = sc.get("format")
    if sc.get("format") != "hwpx":
        fail("CONV_NOT_HWPX", f"변환본이 HWPX 가 아님({sc.get('format')})")
        A.verdict, A.reasons = "FAIL", fails
        return A
    try:
        conv = read(converted)
    except Exception as e:
        fail("CONV_UNREADABLE", f"변환본 판독 실패: {type(e).__name__}: {e}")
        A.verdict, A.reasons = "FAIL", fails
        return A

    # ---- 원본 읽기
    so = sniff(original)
    ck["original_format"] = so.get("format")
    orig = None
    try:
        orig = read(original)
    except Exception as e:
        reason = {"hwp3": "HWP 3.0 문서", "hml": "HML 문서"}.get(so.get("format"))
        if so.get("encrypted"):
            reason = "열기 암호 문서"
        elif so.get("drm"):
            reason = "DRM 문서"
        warn("ORIG_UNVERIFIABLE", f"원본을 독립 판독할 수 없음({reason or type(e).__name__}) — "
                                  f"변환본 판독만 확인, 내용 대조 못 함")
    prv_o = read_prvtext(original)

    if engine_report and engine_report.get("count"):
        kinds = collections.Counter(x.get("kind") or x.get("code") or "?" for x in engine_report.get("losses", []))
        warn("ENGINE_LOSS", "변환 엔진이 손실을 보고함: " + ", ".join(f"{k}×{v}" for k, v in kinds.most_common(6)))

    conv_raw = plain_text(conv)
    conv_text = norm(conv_raw)
    ck["conv_chars"] = len(conv_text)
    if conv.warnings:
        warn("CONV_READ_WARN", f"변환본 판독 경고 {len(conv.warnings)}건: {conv.warnings[0][:120]}")

    sub = {}
    if orig is None:
        # 원본을 못 읽으면 미리보기로만 확인
        if prv_o:
            r = _prv_recall(prv_o, conv_text)
            ck["prv_recall"] = round(r, 4)
            if r < PRV_RECALL_WARN:
                fail("PRV_MISSING", f"원본 미리보기 글이 변환본에 {r:.0%}만 있음")
        if not conv_text:
            fail("CONV_EMPTY", "변환본에 글이 없음")
        A.verdict = "FAIL" if fails else "WARN"
        A.reasons = fails + warns
        A.score = None  # 원본 대조를 못 했으므로 점수를 매기지 않는다
        return A

    if orig.warnings:
        warn("ORIG_READ_WARN", f"원본 판독 경고 {len(orig.warnings)}건: {orig.warnings[0][:120]}")

    # ---- 1 글
    orig_raw = plain_text(orig)
    orig_text = norm(orig_raw)
    r, p = recall_precision(orig_text, conv_text)
    exact = orig_text == conv_text
    ck.update(text_chars=len(orig_text), text_exact=exact, text_recall=round(r, 4), text_precision=round(p, 4))
    ua, ub = _units(orig), _units(conv)
    sm = difflib.SequenceMatcher(None, [norm(t) for _, t in ua], [norm(t) for _, t in ub], autojunk=False)
    conv_loose = loose(conv_raw)
    orig_loose = loose(orig_raw)
    conv_grams = grams(conv_loose)
    tdiff = []
    sym_spots = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a_txt = "".join(t for _, t in ua[i1:i2])
        b_txt = "".join(t for _, t in ub[j1:j2])
        if norm(a_txt) == norm(b_txt):  # 문단 나뉨만 다름
            continue
        na, nb = loose(a_txt), loose(b_txt)
        if na == nb:  # 자동 번호 캐시값 또는 기호 문자 코드만 다름
            kind = "autonum" if _num_free(a_txt) == _num_free(b_txt) else "symbol"
            sym_spots.append({"kind": kind, "where_orig": ua[i1][0] if i1 < i2 else "",
                              "orig": a_txt.replace("\u2063", "")[:80], "conv": b_txt.replace("\u2063", "")[:80]})
            continue
        # 빠짐 판단은 자리 맞춘 쪽만이 아니라 변환본 전체에서 찾는다 — 자리만 옮겨졌거나(캡션·머리말 위치)
        # 판독 모델 차이로 반복된 글(묶음 캡션)은 손실이 아니다
        # 같은 글이 문서에 여러 번 나오면 개수로 본다(반복 문구 하나가 빠진 것도 잡는다)
        lost = bool(na) and na not in nb and (
            conv_loose.count(na) < orig_loose.count(na) if na in conv_loose else _covered(na, conv_grams) < 0.9)
        tdiff.append({"op": {"replace": "바뀜", "delete": "빠짐", "insert": "더해짐"}[op], "lost": bool(lost and na),
                      "where_orig": ua[i1][0] if i1 < i2 else (ua[i1 - 1][0] + " 뒤" if i1 else "처음"),
                      "where_conv": ub[j1][0] if j1 < j2 else (ub[j1 - 1][0] + " 뒤" if j1 else "처음"),
                      "orig": a_txt.replace("\u2063", "")[:120], "conv": b_txt.replace("\u2063", "")[:120]})
    ck["text_diff_spots"] = len(tdiff)
    A.details["text_diffs"] = tdiff[:30]
    lost_spots = [x for x in tdiff if x["lost"]]
    ck["text_lost_spots"] = len(lost_spots)
    lr, _ = recall_precision(loose(orig_raw), conv_loose)
    ck["text_recall_loose"] = round(lr, 4)
    auto = [x for x in sym_spots if x["kind"] == "autonum"]
    sym = [x for x in sym_spots if x["kind"] == "symbol"]
    if sym_spots:
        ck["symbol_mapped_spots"], ck["autonum_diff_spots"] = len(sym), len(auto)
        A.details["soft_diffs"] = sym_spots[:30]
    if sym:
        warn("SYMBOL_MAPPED", f"기호·사용자 정의 문자 코드만 바뀐 곳 {len(sym)}곳 — 예: {sym[0]['where_orig']} "
                              f"「{sym[0]['orig'][:20]}」→「{sym[0]['conv'][:20]}」 (글꼴에 따라 모양 확인)")
    if auto:
        warn("AUTONUM_DIFF", f"자동 번호(캡션·각주 번호)의 저장값만 다른 곳 {len(auto)}곳 — 예: {auto[0]['where_orig']} "
                             f"「{auto[0]['orig'][:20]}」→「{auto[0]['conv'][:20]}」 (한글은 열 때 다시 매기지만, "
                             f"변환본을 그대로 읽는 AI·검색에는 틀린 번호가 들어감)")
    if lr < TEXT_RECALL_FAIL or lost_spots:
        x = (lost_spots or tdiff or [None])[0]
        where = (f"표 밖 문단 {len(lost_spots)}곳" if lost_spots
                 else "표 밖 문단은 0곳, 차이는 표 칸 안(TABLE_CELL 참조)")
        fail("TEXT_LOSS", f"원본 글 재현율 {lr:.3f}{' (기준 ' + format(TEXT_RECALL_FAIL, '.2f') + ' 미달)' if lr < TEXT_RECALL_FAIL else ''} — {where}" +
             (f" — {x['where_orig']}: 「{x['orig'][:40]}」" if x else ""))
    elif not exact:
        # 표 칸·순서 차이가 아닌, 표 밖 글이 다를 때만 경고(표는 아래에서 따로 판정)
        if tdiff:
            warn("TEXT_DIFF", f"글 미세 차이 {len(tdiff)}곳 (재현율 {r:.3f}) — 첫 차이: {tdiff[0]['where_orig']}")

    # ---- 2 표
    ta, tb = list(walk_tables(orig.blocks)), list(walk_tables(conv.blocks))
    ck["tables"] = [len(ta), len(tb)]
    if len(ta) != len(tb):
        fail("TABLE_COUNT", f"표 개수 다름: 원본 {len(ta)} / 변환 {len(tb)}")
    sm2 = difflib.SequenceMatcher(None, [_table_sig(t) for t in ta], [_table_sig(t) for t in tb], autojunk=False)
    pairs = []
    for op, i1, i2, j1, j2 in sm2.get_opcodes():
        if op in ("equal", "replace"):
            pairs.extend(zip(ta[i1:i2], tb[j1:j2]))
    tres = [_compare_table(a, b) for a, b in pairs]
    tot_cells = sum(x["cells"] for x in tres) or 0
    bad_cells = sum(x["cells_bad"] for x in tres)
    span_bad = [x for x in tres if not x["span_ok"]]
    sym_cells = sum(x.get("cells_symbol_mapped", 0) for x in tres)
    ck.update(table_cells=tot_cells, table_cells_bad=bad_cells, table_span_bad=len(span_bad),
              table_cells_symbol_mapped=sym_cells)
    if sym_cells:
        warn("CELL_SOFT_DIFF", f"표 칸 {sym_cells}곳에서 기호 문자 코드·자동 번호 저장값만 다름")
    A.details["tables"] = [x for x in tres if x["cells_bad"] or not x["span_ok"]][:30]
    if span_bad:
        x = span_bad[0]
        fail("TABLE_SPAN", f"표 병합 구조 다름 {len(span_bad)}개 — 표{x['orig_id']} 원본 격자 {x['shape']} / 변환 {x['shape_conv']}")
    if bad_cells:
        x = next(t for t in tres if t["cells_bad"])
        d = x["cell_diffs"][0] if x["cell_diffs"] else {}
        fail("TABLE_CELL", f"표 칸 글 다름 {bad_cells}칸 — 표{x['orig_id']} {d.get('row')}행 {d.get('col')}열 "
                           f"「{d.get('orig', '')[:30]}」→「{d.get('conv', '')[:30]}」")

    # ---- 3 그림
    ia, ib = _image_prints(orig), _image_prints(conv)
    ck["images"] = [len(ia), len(ib)]
    pool = collections.Counter()
    for _, d in ib:
        for x in d:
            pool[x] += 1
    lost = []
    nodata = ole_rewritten = 0
    for nm, d in ia:
        if not d:
            nodata += 1
            continue
        # 바이트 해시 먼저, 없으면 OLE 구성 지문
        hit = next((x for x in sorted(d) if not x.startswith("ole:") and pool[x] > 0), None) or \
            next((x for x in d if x.startswith("ole:") and pool[x] > 0), None)
        if hit:
            pool[hit] -= 1
            ole_rewritten += hit.startswith("ole:")
        else:
            lost.append(nm)
    ck.update(images_hash_unmatched=len(lost), images_no_data=nodata, images_ole_rewritten=ole_rewritten)
    with_data = len(ia) - nodata
    if len(ib) < len(ia):
        if not lost and len(ib) >= with_data:
            # 원본에서도 데이터가 없는 그림 참조(잘린 문서 등)만 빠짐 — 데이터 있는 그림은 모두 짝이 맞음
            warn("IMAGE_REF_NO_DATA", f"원본에서 데이터 없는 그림 참조 {len(ia) - len(ib)}개가 변환본에서 빠짐")
        else:
            fail("IMAGE_MISSING", f"그림 개수 감소: 원본 {len(ia)} / 변환 {len(ib)}" +
                 (f" — 짝 없는 원본 그림 예: {lost[0]}" if lost else ""))
    elif len(ib) > len(ia):
        warn("IMAGE_EXTRA", f"그림 개수 증가: 원본 {len(ia)} / 변환 {len(ib)}")
    if lost:
        A.details["images_unmatched"] = lost[:30]
        if len(ib) >= len(ia):
            warn("IMAGE_HASH", f"그림 데이터 불일치 {len(lost)}개(개수는 같음) — 예: {lost[0]}")

    # ---- 4 각주·미주·수식
    fa, fb = _count(orig, Note, lambda n: n.kind == "footnote"), _count(conv, Note, lambda n: n.kind == "footnote")
    ea, eb = _count(orig, Note, lambda n: n.kind == "endnote"), _count(conv, Note, lambda n: n.kind == "endnote")
    qa = sorted(norm(e.script) for e in _iter(orig, Equation))
    qb = sorted(norm(e.script) for e in _iter(conv, Equation))
    ck.update(footnotes=[fa, fb], endnotes=[ea, eb], equations=[len(qa), len(qb)])
    if fa != fb:
        fail("FOOTNOTE_COUNT", f"각주 개수 다름: 원본 {fa} / 변환 {fb}")
    if ea != eb:
        fail("ENDNOTE_COUNT", f"미주 개수 다름: 원본 {ea} / 변환 {eb}")
    if len(qa) != len(qb):
        fail("EQUATION_COUNT", f"수식 개수 다름: 원본 {len(qa)} / 변환 {len(qb)}")
    elif qa != qb:
        warn("EQUATION_SCRIPT", "수식 스크립트 내용이 다름")

    # ---- 5 미리보기(PrvText)
    prv_score = 1.0
    if prv_o:
        pr = _prv_recall(prv_o, conv_text)
        ck["prv_recall"] = round(pr, 4)
        prv_score = pr
        if pr < PRV_RECALL_WARN:
            # 원본 판독 글로도 낮으면 미리보기 자체의 특성(자동번호 등) — 변환 탓이 아님
            po = _prv_recall(prv_o, orig_text)
            ck["prv_recall_orig"] = round(po, 4)
            if po - pr > 0.05:
                warn("PRV_LOW", f"원본 미리보기 글이 변환본에 {pr:.0%}만 있음(원본 판독은 {po:.0%})")
    ck["prv_conv_present"] = read_prvtext(converted) is not None

    # ---- 점수(0~100)와 판정
    cell_acc = 1.0 - (bad_cells / tot_cells) if tot_cells else (0.0 if len(ta) != len(tb) else 1.0)
    if len(ta) != len(tb):
        cell_acc *= min(len(ta), len(tb)) / max(len(ta), len(tb), 1)
    img = (len(ia) - len(lost) - max(len(ia) - len(ib), 0)) / len(ia) if ia else 1.0
    cnt = sum([fa == fb, ea == eb, len(qa) == len(qb)]) / 3
    f1 = 2 * r * p / (r + p) if r + p else 0.0
    A.score = 100 * (0.40 * f1 + 0.30 * cell_acc + 0.10 * max(img, 0) + 0.10 * cnt + 0.10 * min(prv_score, 1.0))
    A.verdict = "FAIL" if fails else ("WARN" if warns else "PASS")
    A.reasons = fails + warns
    # ---- 가시 글 기준 참고: 변경 추적으로 숨겨진 글(삭제 구간)을 뺀 원본과 비교한다.
    # 공식 판정은 바꾸지 않는다. 두 기준이 다르면 한글 화면 대조 전까지 둘 다 보여 준다.
    if not _nested and so.get("format") == "hwp5":
        try:
            from . import api as _api
            vis_read = lambda p: _api.read(p, autonum_mark=True, visible=True)
            vis_doc = vis_read(original)
            if norm(plain_text(vis_doc)) != norm(plain_text(orig)):
                A2 = audit(original, converted, engine_report, read=vis_read, _nested=True)
                A.visible_reference = {"verdict": A2.verdict, "score": None if A2.score is None else round(A2.score, 2),
                                       "reasons": [r for r in A2.reasons if r["level"] == "FAIL"],
                                       "raw_chars": len(norm(plain_text(orig))),
                                       "visible_chars": len(norm(plain_text(vis_doc))),
                                       "note": "변경 추적으로 숨겨진 글을 뺀 원본 기준. 공식 판정 아님. 한글 화면 대조로 확정."}
        except Exception as e:  # 참고 판정이 실패해도 공식 판정은 그대로 둔다
            A.visible_reference = {"error": f"{type(e).__name__}: {e}"}
    return A


# ---------------------------------------------------------------- 사람용 검증서
def to_markdown(a: Audit) -> str:
    d = a.to_dict()
    ck = d["checks"]
    L = [f"# 변환 검증서 — {d['original']}", "",
         f"- 판정: **{d['verdict']}**  ·  점수 {'(원본 대조 불가)' if d['score'] is None else '%.1f/100' % d['score']}  ·  검증서 판 {AUDIT_VERSION}",
         f"- 원본: `{d['original']}` ({ck.get('original_format')})  →  변환본: `{d['converted']}` ({ck.get('converted_format')})", ""]
    if d["reasons"]:
        L += ["## 판정 이유", ""] + [f"- [{x['level']}] {x['code']}: {x['msg']}" for x in d["reasons"]] + [""]
    vr = d.get("visible_reference")
    if vr:
        L += ["## 가시 글 기준 참고 (공식 판정 아님)", ""]
        if "error" in vr:
            L += [f"- 참고 판정 실패: {vr['error']}", ""]
        else:
            L += [f"- 원본 글 {vr['raw_chars']}자 중 변경 추적으로 숨겨진 글을 뺀 가시 글 {vr['visible_chars']}자 기준으로 다시 비교했다.",
                  f"- 가시 글 기준 판정: **{vr['verdict']}**" + (f" · 점수 {vr['score']:.1f}/100" if vr.get('score') is not None else ""),
                  f"- {vr['note']}"]
            L += [f"- [{x['level']}] {x['code']}: {x['msg']}" for x in vr.get('reasons', [])] + [""]
    L += ["## 항목별 결과", "", "| 항목 | 원본 | 변환본 | 결과 |", "|---|---|---|---|"]
    if "text_chars" in ck:
        L.append(f"| 글(공백 제외 글자) | {ck['text_chars']} | {ck.get('conv_chars')} | "
                 f"{'일치' if ck['text_exact'] else '재현율 %.3f · 정밀도 %.3f' % (ck['text_recall'], ck['text_precision'])} |")
    if "tables" in ck:
        L.append(f"| 표 | {ck['tables'][0]} | {ck['tables'][1]} | 칸 {ck.get('table_cells', 0)}개 중 다른 칸 "
                 f"{ck.get('table_cells_bad', 0)} · 병합 구조 다른 표 {ck.get('table_span_bad', 0)} |")
    if "images" in ck:
        L.append(f"| 그림 | {ck['images'][0]} | {ck['images'][1]} | 데이터 불일치 {ck.get('images_hash_unmatched', 0)} |")
    for k, nm in (("footnotes", "각주"), ("endnotes", "미주"), ("equations", "수식")):
        if k in ck:
            L.append(f"| {nm} | {ck[k][0]} | {ck[k][1]} | {'일치' if ck[k][0] == ck[k][1] else '다름'} |")
    if "prv_recall" in ck:
        L.append(f"| 미리보기(PrvText) 대조 | 한글 저장 미리보기 | 변환본 글 | 포함률 {ck['prv_recall']:.1%} |")
    L.append("")
    if d["details"].get("text_diffs"):
        L += ["## 글 차이 위치 (최대 30곳)", "", "| 종류 | 원본 위치 | 변환본 위치 | 원본 | 변환본 |", "|---|---|---|---|---|"]
        for x in d["details"]["text_diffs"]:
            L.append(f"| {x['op']} | {x['where_orig']} | {x['where_conv']} | {_md(x['orig'])} | {_md(x['conv'])} |")
        L.append("")
    if d["details"].get("tables"):
        L += ["## 표 차이", ""]
        for t in d["details"]["tables"]:
            L.append(f"### 표{t['orig_id']} (원본 격자 {t['shape'][0]}×{t['shape'][1]}, 변환 {t['shape_conv'][0]}×{t['shape_conv'][1]})")
            if not t["span_ok"]:
                L.append(f"- 병합 구조 다름 — 원본에만: {t.get('span_missing')} / 변환에만: {t.get('span_extra')} "
                         "(행,열,행병합,열병합; 0부터)")
            for c in t["cell_diffs"]:
                L.append(f"- {c['row']}행 {c['col']}열 [{c['kind']}] 「{_md(c['orig'])}」 → 「{_md(c['conv'])}」")
            L.append("")
    if d["details"].get("images_unmatched"):
        L += ["## 데이터가 맞지 않는 그림", "", ", ".join(d["details"]["images_unmatched"]), ""]
    return "\n".join(L)


def _md(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def write_audit(a: Audit, out_base: str) -> tuple[str, str]:
    os.makedirs(os.path.dirname(os.path.abspath(out_base)), exist_ok=True)
    jp, mp = out_base + ".json", out_base + ".md"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(a.to_dict(), f, ensure_ascii=False, indent=1)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(to_markdown(a) + "\n")
    return jp, mp
