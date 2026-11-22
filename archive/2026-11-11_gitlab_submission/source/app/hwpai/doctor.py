"""hwpai doctor — 설치 상태를 하나씩 점검하고, 막히면 한국어로 원인과 해결 방법을 알려 준다.

  python -m hwpai doctor
마지막 단계에서 실제로 문서를 만들어 → HWPX 로 변환하고 → 검증서를 돌려 PASS 인지 본다.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import platform
import sys
import tempfile
import time

# 동봉 엔진 파일 지문 (rhwp 로컬 빌드 0.9.0-local.c100: 변경 추적 숨김 반영, 그림 사각형 가드, 묶음 안 OLE 보존). 빌드 도구가 vendor 파일과 대조해 다르면 빌드를 멈춘다(C108)
ENGINE_SHA256 = {
    "rhwp_bg.wasm": "58cda4b49984c3d2b7b486167c162fa05930fa13be997e2eaeb71f5d3340677c",
    "rhwp.js": "02dcb4a17782f65814129c7971c81c05237e93e67327b205cfdb00b3a3ac0568",
}

OK, WARN, FAIL = "통과", "주의", "실패"


class Report:
    def __init__(self, out=print):
        self.items = []
        self.out = out

    def add(self, name, state, detail="", fix=""):
        self.items.append({"점검": name, "결과": state, "내용": detail, "해결": fix})
        mark = {OK: "[통과]", WARN: "[주의]", FAIL: "[실패]"}[state]
        self.out(f"{mark} {name}" + (f" — {detail}" if detail else ""))
        if fix and state != OK:
            self.out(f"        해결: {fix}")

    @property
    def failed(self):
        return any(i["결과"] == FAIL for i in self.items)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(out=print, sample: bool = True) -> Report:
    from . import engines as E
    R = Report(out)
    out(f"HWP AI 어댑터(hwpai) 점검 — {platform.system()} {platform.release()} · Python {platform.python_version()}")

    # 1 파이썬
    if sys.version_info >= (3, 10):
        R.add("파이썬 3.10 이상", OK, sys.executable)
    else:
        R.add("파이썬 3.10 이상", FAIL, platform.python_version(), "휴대용 폴더의 hwpai.bat 으로 실행하거나 Python 3.10 이상을 설치하세요.")

    # 2 파이썬 부품
    for mod, why in (("olefile", "HWP 5.0 읽기"), ("cryptography", "배포용 문서 풀기")):
        try:
            m = importlib.import_module(mod)
            R.add(f"부품 {mod} ({why})", OK, getattr(m, "__version__", ""))
        except Exception as e:
            st = FAIL if mod == "olefile" else WARN
            R.add(f"부품 {mod} ({why})", st, f"{type(e).__name__}",
                  f"휴대용 폴더라면 폴더째 다시 풀어 주세요. 일반 설치라면: python -m pip install {mod}"
                  + ("" if mod == "olefile" else " (없으면 배포용 문서만 못 읽고 나머지는 동작)"))

    # 3 Node
    node = E.find_node()
    if not node:
        R.add("Node.js (변환 엔진 실행기)", FAIL, "찾지 못함",
              "휴대용 폴더에는 node\\node.exe 가 들어 있어야 합니다. 일반 설치라면 https://nodejs.org 에서 LTS 설치. "
              "다른 위치라면 환경변수 HWPAI_NODE 에 node 실행 파일 경로를 지정. (읽기·검증서는 Node 없이도 됩니다)")
    else:
        major = E._node_major(node)
        if major >= 18:
            R.add("Node.js (변환 엔진 실행기)", OK, f"v{major} · {node}")
        else:
            R.add("Node.js (변환 엔진 실행기)", FAIL, f"v{major} · {node}", "Node.js 18 이상이 필요합니다. 최신 LTS 로 바꾸거나 휴대용 폴더의 node 를 쓰세요.")

    # 4 엔진 파일
    core = E.find_core()
    if not core:
        R.add("변환 엔진 rhwp(@rhwp/core)", FAIL, "찾지 못함",
              "vendor\\rhwp-core 폴더가 있어야 합니다. 폴더째 다시 풀거나 HWPAI_RHWP_CORE 로 위치를 지정하세요.")
    else:
        bad = [n for n, h in ENGINE_SHA256.items()
               if not os.path.isfile(os.path.join(core, n)) or _sha(os.path.join(core, n)) != h]
        if bad:
            R.add("변환 엔진 rhwp(@rhwp/core)", WARN, f"{core} — 동봉판과 지문 다름: {', '.join(bad)}",
                  "다른 판의 엔진입니다. 동작은 할 수 있으나 측정 수치는 동봉판 기준입니다.")
        else:
            R.add("변환 엔진 rhwp(@rhwp/core)", OK, f"동봉판 · 지문 일치 · {core}")

    # 5 쓰기 권한·한글 경로
    try:
        with tempfile.TemporaryDirectory(prefix="hwpai_점검_", ignore_cleanup_errors=True) as d:
            p = os.path.join(d, "한글 이름 폴더", "시험.txt")
            os.makedirs(os.path.dirname(p))
            with open(p, "w", encoding="utf-8") as f:
                f.write("가")
            R.add("임시 폴더 쓰기·한글 경로", OK, tempfile.gettempdir())
    except Exception as e:
        R.add("임시 폴더 쓰기·한글 경로", FAIL, f"{type(e).__name__}: {e}",
              "임시 폴더에 쓸 수 없습니다. 환경변수 TEMP 를 쓰기 가능한 폴더로 바꾸세요.")

    # 6 실제 변환·검증
    if sample and node and core and not R.failed:
        from .audit import audit
        from . import read
        try:
            with tempfile.TemporaryDirectory(prefix="hwpai_점검_", ignore_cleanup_errors=True) as d:
                src, dst = os.path.join(d, "점검 문서.hwp"), os.path.join(d, "점검 문서.hwpx")
                t0 = time.perf_counter()
                with E.RhwpWasmEngine() as eng:
                    r1 = eng.selftest(src, text="HWP AI 어댑터 점검 문서 — 한글 없이 변환합니다.")
                    r2 = eng.convert(src, dst, timeout=60) if r1.get("ok") else r1
                if not r2.get("ok"):
                    R.add("시험 변환(HWP→HWPX)", FAIL, r2.get("error", "")[:200],
                          "엔진이 시작되지만 변환에 실패했습니다. 보안 프로그램이 node.exe 실행을 막는지 확인하세요.")
                else:
                    R.add("시험 변환(HWP→HWPX)", OK, f"{(time.perf_counter() - t0) * 1000:.0f}ms")
                    a = audit(src, dst)
                    txt = "".join(getattr(b, "text", "") for b in read(dst).blocks)
                    if a.verdict == "PASS" and "점검 문서" in txt:
                        R.add("시험 검증서·AI 판독", OK, f"검증서 {a.verdict} · 변환본 글 판독 확인")
                    else:
                        R.add("시험 검증서·AI 판독", FAIL, f"검증서 {a.verdict}: {a.reasons[:1]}",
                              "설치 파일이 손상되었을 수 있습니다. 폴더째 다시 풀어 주세요.")
        except E.EngineMissing as e:
            R.add("시험 변환(HWP→HWPX)", FAIL, str(e).splitlines()[0],
                  "Node.js 가 엔진을 띄우지 못했습니다. 위 Node.js·엔진 점검 결과를 확인하세요.")
    elif sample:
        R.add("시험 변환(HWP→HWPX)", WARN, "앞 단계 실패로 건너뜀", "위의 [실패] 항목을 먼저 해결하세요.")

    out("")
    out("결론: " + ("사용할 수 없습니다 — 위 [실패] 항목의 해결 방법을 따르세요." if R.failed else
                    "사용할 수 있습니다." + (" ([주의] 항목은 일부 기능 제한)" if any(i["결과"] == WARN for i in R.items) else "")))
    return R
