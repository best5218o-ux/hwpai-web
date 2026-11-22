"""파일 열기 연결 — .hwp 를 더블클릭하면 HWPX 로 변환·검증한 뒤 연다. 원본은 건드리지 않는다.

- 변환본: 원본 옆 「<이름>_hwpx」 폴더 (원본 폴더 밖에 쓰지 않는다)
- 검증 PASS → HWPX 를 연다. 그 밖(WARN·FAIL·변환 실패) → 원본 HWP 를 연다 (사유를 「열기_안내.txt」에 남김)
"""
import os
import shutil
import sys
import tempfile


def _open(path: str) -> None:
    os.startfile(path)  # Windows 기본 연결 프로그램으로 연다


def _card(path: str, ok: bool, title: str, detail: str, hwpx: str = "") -> None:
    """열기 안내를 카드 형태의 HTML 로 남긴다 (텍스트 안내는 그대로 함께 남긴다)."""
    import html as _h
    color, label = (("#02823b", "검증 통과 · HWPX 로 열었습니다") if ok
                    else ("#8a5b00", "원본 HWP 로 열었습니다"))
    bg = "#eefbf3" if ok else "#fff7e6"
    body = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>hwpai 열기 안내</title>
<style>
body{{margin:0;background:#f5f6f8;font:14px/1.6 "Malgun Gothic","맑은 고딕",system-ui,sans-serif;color:#17202f}}
.card{{max-width:560px;margin:40px auto;background:#fff;border:1px solid #e3e7ee;border-radius:16px;overflow:hidden;box-shadow:none}}
.top{{background:#fff;color:#1e1e1e;border-bottom:1px solid #e5e7eb;padding:18px 22px}}
.top h1{{margin:0;font-size:17px;color:#03c75a;font-weight:800}}.top p{{margin:4px 0 0;color:#6b7280;font-size:12.5px}}
.pill{{display:inline-block;margin:16px 22px 0;padding:6px 12px;border-radius:999px;background:{bg};color:{color};font-weight:700;font-size:13px}}
dl{{margin:12px 22px 4px;display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:13px}}
dt{{color:#667085}}dd{{margin:0;word-break:break-all}}
.note{{margin:12px 22px 20px;color:#667085;font-size:12.5px}}
</style></head><body><div class="card">
<div class="top"><h1>hwpai · HWP 열기 안내</h1><p>{_h.escape(title)}</p></div>
<div class="pill">{_h.escape(label)}</div>
<dl><dt>원본</dt><dd>{_h.escape(path)}</dd>{('<dt>변환본</dt><dd>' + _h.escape(hwpx) + '</dd>') if hwpx else ''}
<dt>판정</dt><dd>{_h.escape(detail)}</dd></dl>
<div class="note">원본 파일은 바뀌지 않았습니다. 변환본을 편집해도 원본 HWP에는 반영되지 않습니다.</div>
</div></body></html>"""
    with open(_card_path(path), "w", encoding="utf-8") as f:
        f.write(body)


def _card_path(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(os.path.dirname(path), base + "_hwpx", "열기_안내.html")


def open_hwp(path: str) -> int:
    src = os.path.abspath(path)
    if not os.path.isfile(src):
        print(f"파일이 없습니다: {src}", file=sys.stderr)
        return 2
    ext = os.path.splitext(src)[1].lower()
    if ext == ".hwpx":
        _open(src)
        return 0
    if ext != ".hwp":
        _open(src)
        return 0

    from .batch import BatchConverter

    base = os.path.splitext(os.path.basename(src))[0]
    folder = os.path.dirname(src)
    out = os.path.join(folder, base + "_hwpx")
    os.makedirs(out, exist_ok=True)
    note = os.path.join(out, "열기_안내.txt")

    tmp = tempfile.mkdtemp(prefix="hwpai_open_")
    try:
        shutil.copy2(src, os.path.join(tmp, os.path.basename(src)))  # 원본은 복사해서만 읽는다
        summary = BatchConverter(tmp, out, verify=True).run()
        v = summary.get("verdict", {})
        verdict = str(v) if not isinstance(v, dict) else ", ".join(f"{k} {n}" for k, n in v.items())
        only_pass = isinstance(v, dict) and v.get("PASS", 0) > 0 and not v.get("WARN") and not v.get("FAIL")
        hwpx = os.path.join(out, base + ".hwpx")
        if not os.path.isfile(hwpx):
            cands = [f for f in os.listdir(out) if f.lower().endswith(".hwpx")]
            hwpx = os.path.join(out, cands[0]) if cands else ""
    except Exception as e:  # 변환 실패 → 원본 열기
        verdict, hwpx, only_pass = f"변환 실패 {type(e).__name__}: {e}", "", False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if only_pass and hwpx:
        _open(hwpx)
        with open(note, "w", encoding="utf-8") as f:
            f.write(f"HWPX로 열었습니다 (검증 PASS).\n원본: {src}\n변환본: {hwpx}\n")
        _card(src, True, os.path.basename(src), "PASS", hwpx)
        return 0

    _open(src)
    with open(note, "w", encoding="utf-8") as f:
        f.write(f"원본 HWP로 열었습니다. 변환 판정: {verdict or '미확인'}\n원본: {src}\n")
    _card(src, False, os.path.basename(src), verdict or "미확인", "")
    return 0
