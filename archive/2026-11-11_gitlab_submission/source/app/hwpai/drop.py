"""끌어놓기 일괄 변환 — 탐색기에서 폴더·파일 여러 개를 hwpai.bat 아이콘 위에 놓으면 이 명령이 돈다.

  python -m hwpai drop 〈폴더|파일〉 [〈폴더|파일〉 …] [--grade 공개 | --grade-policy pii-strict] [--no-open]

- 폴더: 하위 폴더까지 .hwp/.hwpx 를 모두 변환 → 〈폴더〉_hwpx변환 (상대 경로 유지)
- 파일: 같은 폴더에 있는 파일끼리 묶어 → 〈그 폴더〉_hwpx변환 (놓은 파일만)
- .hwp/.hwpx 가 아닌 파일은 「건너뜀 n개」로 센다. 원본은 읽기만 한다.
- 같은 폴더를 다시 놓으면 이관대장으로 이어하기(끝난 파일은 건너뜀).
- 끝나면(Windows) 결과 폴더와 요약.md 를 연다. --no-open 이면 열지 않는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from .batch import SRC_EXT, BatchConverter, default_out


def plan(paths: list[str]) -> dict:
    """놓은 경로들 → 변환 묶음 [(원본 폴더, 결과 폴더, only 또는 None)] + 건너뛴 것."""
    groups, files_by_dir, skipped, missing = [], {}, [], []
    for raw in paths:
        p = os.path.abspath(raw.strip().strip('"'))
        if os.path.isdir(p):
            groups.append((p, default_out(p), None))
            for dp_, dns, fns in os.walk(p):
                dns[:] = [d for d in dns if not d.startswith(".")]
                skipped += [os.path.join(dp_, f) for f in fns if not f.lower().endswith(SRC_EXT) and not f.startswith(".")]
        elif os.path.isfile(p):
            if p.lower().endswith(SRC_EXT):
                files_by_dir.setdefault(os.path.dirname(p), []).append(os.path.basename(p))
            else:
                skipped.append(p)
        else:
            missing.append(p)
    for d, names in files_by_dir.items():
        groups.append((d, default_out(d), sorted(set(names))))
    return {"groups": groups, "skipped": skipped, "missing": missing}


def _open(path: str):
    try:
        if os.name == "nt":
            if path.lower().endswith(".md"):
                subprocess.Popen(["notepad.exe", path])
            else:
                os.startfile(path)  # noqa: S606 — 사용자가 놓은 폴더의 결과만 연다
    except Exception:
        pass


def run(paths: list[str], gate=None, jobs: int = 2, open_result: bool = True, log=print) -> list[dict]:
    pl = plan(paths)
    for m in pl["missing"]:
        log(f"[없음] {m}")
    if pl["skipped"]:
        log(f"[건너뜀] HWP·HWPX 가 아닌 파일 {len(pl['skipped'])}개")
    results = []
    for src, out, only in pl["groups"]:
        if os.path.normcase(out).startswith(os.path.normcase(src) + os.sep):
            log(f"[중단] 결과 폴더가 원본 안에 있습니다: {out}")
            continue
        log(f"\n[변환] {src}" + (f" (파일 {len(only)}개)" if only else "") + f"\n   → {out}")
        bc = BatchConverter(src, out, jobs=jobs, gate=gate, only=only,
                            log=lambda *a, **k: log(*a, **k))
        s = bc.run()
        v = s.get("verdict", {})
        st = s.get("status", {})
        line = (f"   PASS {v.get('PASS', 0)} · WARN {v.get('WARN', 0)} · FAIL {v.get('FAIL', 0)} · "
                f"등급차단 {st.get('등급차단', 0)} · 실패·격리 {st.get('변환실패', 0) + st.get('격리', 0)} · "
                f"이어하기로 건너뜀 {s.get('resumed', 0)} · {s.get('wall_seconds')}초")
        log(line)
        results.append({"src": src, "out": out, "only": only, "stats": s})
    if open_result and results:
        for r in results[:3]:
            _open(r["out"])
            _open(os.path.join(r["out"], "요약.md"))
    log(f"\n끝. 결과 폴더 {len(results)}곳 · 건너뜀 {len(pl['skipped'])}개 · 원본은 바뀌지 않았습니다.")
    return results


def cmd_drop(a):
    rs = run(a.paths, gate=getattr(a, "gate", None), jobs=a.jobs, open_result=not a.no_open)
    if a.json:
        print(json.dumps([{"src": r["src"], "out": r["out"], "verdict": r["stats"].get("verdict"),
                           "status": r["stats"].get("status")} for r in rs], ensure_ascii=False))
    return 0 if rs else 2


if __name__ == "__main__":
    sys.exit(0)
