"""내 컴퓨터 전체 변환(선택 기능) — 기본은 꺼짐. 사용자가 명령으로 켜고, 동의하고, 미리보기를 확인한 뒤에만 변환한다.

  python -m hwpai scan-all [--roots C:\\ D:\\] [--out 결과폴더] [--preview-only] [--yes]
                           [--beside] [--window 22:00-06:00] [--jobs 1] [--max-files N]
  python -m hwpai install --scan-all        (동의 문구를 보여 주고 이 옵션을 켠다. 아무 변환도 하지 않는다)

원칙
  1. 설치만으로는 아무것도 변환하지 않는다. 이 명령을 직접 실행해야 한다.
  2. 먼저 미리보기(찾은 개수·총 용량·예상 시간·폴더별 분포·제외 폴더·접근 불가 폴더)를 보이고, 사람이 「예」라고
     확인한 뒤에만 변환한다. 확인 없는 실행은 --yes 를 직접 준 때만.
  3. 원본은 읽기만 한다. 결과는 기본으로 별도 폴더(원본 폴더 구조 그대로). --beside 를 주면 원본 옆
     〈같은 이름〉.hwpx 로 두되 이미 있으면 「 (2)」를 붙이고 절대 덮어쓰지 않는다.
  4. 시스템·설치·캐시 폴더, 심볼릭 링크·정션은 건너뛴다. 접근 불가 폴더는 건너뛰고 목록에 남긴다.
  5. 보안등급 게이트(기본 review 정책)가 적용된다 — 민감정보 꼴은 차단이 아니라 「확인 대기」. 이관대장·이어하기·중단(중지 파일·Ctrl-C)·낮은 우선순위·
     작업 시간대 지원. 네트워크 호출은 없다(이 모듈은 소켓을 열지 않는다).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sys
import time

from .batch import SRC_EXT, BatchConverter

CONSENT = """[내 컴퓨터 전체 변환 — 동의 확인]
 - 이 컴퓨터의 고정 드라이브를 훑어 .hwp 파일을 찾습니다(.hwpx 는 건드리지 않습니다).
 - 원본은 읽기만 합니다. 수정·삭제·덮어쓰기를 하지 않습니다.
 - 결과는 별도 폴더에 원본 폴더 구조 그대로 만듭니다(--beside 를 주면 원본 옆, 덮어쓰기 없이).
 - Windows·Program Files·ProgramData·AppData·휴지통·시스템 볼륨 정보·.git·node_modules 는 제외합니다.
 - 이 컴퓨터 안의 어떤 파일도 외부로 나가지 않습니다(네트워크 호출 0건, 모든 처리는 이 컴퓨터 안).
 - 개인정보 꼴이 있는 문서도 변환은 합니다(이 컴퓨터 안). 대신 「확인 대기」로 세고, 확인하기 전에는 AI 에 보내지 않습니다.
 - 먼저 미리보기를 보여 드리고, 확인하신 뒤에만 변환합니다. 언제든 중지할 수 있습니다(Ctrl-C 또는 결과 폴더에 「중지」 파일)."""

# 이름만으로 제외하는 폴더(소문자). 어느 깊이에서든 적용한다.
EXCLUDE_NAMES = {
    "windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin", "recycler",
    "$recycle.bin.old", "system volume information", ".git", ".svn", "node_modules", "$windows.~bt",
    "$windows.~ws", "recovery", "msocache", "config.msi", "__pycache__", "site-packages", "휴지통",
    "hwpai_전체변환", "hwpai_등급기록",
}
# 유닉스 쪽 시험·운영에서 훑지 않는 가상·시스템 경로
EXCLUDE_ABS_POSIX = ("/proc", "/sys", "/dev", "/run", "/snap", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/boot")
_REPARSE = 0x400
MAX_PATH_SAFE = 240


def _lp(p: str) -> str:
    """Windows 긴 경로(260자 초과)는 \\\\?\\ 접두어로 연다."""
    if os.name == "nt" and len(p) > MAX_PATH_SAFE and not p.startswith("\\\\?\\"):
        import ntpath
        ap = ntpath.abspath(p)
        return "\\\\?\\UNC\\" + ap[2:] if ap.startswith("\\\\") else "\\\\?\\" + ap
    return p


def fixed_drives() -> list[str]:
    """고정 드라이브(C:\\ D:\\ …). Windows 가 아니면 파일 시스템 루트 하나."""
    if os.name != "nt":
        return ["/"]
    import ctypes
    out = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED  # type: ignore[attr-defined]
                out.append(root)
    return out


def _is_link(entry: "os.DirEntry") -> bool:
    try:
        if entry.is_symlink():
            return True
        if os.name == "nt":
            st = entry.stat(follow_symlinks=False)
            return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)  # 정션·마운트 지점
    except OSError:
        return True
    return False


def default_out() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, "hwpai_전체변환")


def _under(p: str, base: str) -> bool:
    p, base = os.path.normcase(os.path.abspath(p)), os.path.normcase(os.path.abspath(base))
    return p == base or p.startswith(base.rstrip("\\/") + os.sep)


def walk_hwp(root: str, out_dir: str, extra_exclude: list[str] | None = None, max_files: int | None = None,
             on_dir=None) -> dict:
    """root 아래의 .hwp 를 모은다. 심볼릭 링크·정션을 따라가지 않고, 제외 폴더와 접근 불가 폴더를 기록한다."""
    skip_abs = [os.path.abspath(out_dir)] + [os.path.abspath(x) for x in (extra_exclude or [])]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hwpai 설치 폴더(app 의 상위)
    skip_abs.append(os.path.dirname(here))
    files, excluded, denied, links = [], [], [], []
    dirs = 0
    stack = [root]
    while stack:
        d = stack.pop()
        dirs += 1
        if on_dir:
            on_dir(d)
        try:
            it = list(os.scandir(_lp(d)))
        except OSError as e:
            denied.append({"경로": d, "사유": type(e).__name__})
            continue
        subs = []
        for e in it:
            try:
                name = e.name
                if _is_link(e):
                    links.append(os.path.join(d, name))
                    continue
                if e.is_dir(follow_symlinks=False):
                    full = os.path.join(d, name)
                    low = name.lower()
                    if low in EXCLUDE_NAMES or low.startswith("hwpai-portable") or (os.name != "nt" and full in EXCLUDE_ABS_POSIX) \
                            or any(_under(full, s) for s in skip_abs):
                        excluded.append(full)
                        continue
                    subs.append(full)
                elif e.is_file(follow_symlinks=False) and name.lower().endswith(".hwp"):
                    st = e.stat(follow_symlinks=False)
                    files.append((os.path.join(d, name), st.st_size))
                    if max_files and len(files) >= max_files:
                        stack.clear()
                        subs = []
                        break
            except OSError as ex:
                denied.append({"경로": os.path.join(d, e.name), "사유": type(ex).__name__})
        stack.extend(sorted(subs, reverse=True))
    return {"root": root, "files": files, "excluded": excluded, "denied": denied, "links": links, "dirs": dirs}


def estimate_seconds(nfiles: int, nbytes: int) -> float:
    """측정치(약 1,000건·494MB·45초, 일꾼 1~2개) 기반 거친 추정 — 검증까지 포함. 실제는 PC 사양에 따라 다르다."""
    return nfiles * 0.03 + (nbytes / 1048576) * 0.03


def build_preview(roots: list[str], out_dir: str, max_files: int | None = None, log=print) -> dict:
    scans = []
    for r in roots:
        log(f"[훑기] {r}")
        scans.append(walk_hwp(r, out_dir, max_files=max_files))
    nfiles = sum(len(s["files"]) for s in scans)
    nbytes = sum(sz for s in scans for _, sz in s["files"])
    by_top: dict = {}
    for s in scans:
        for p, sz in s["files"]:
            rel = os.path.relpath(p, s["root"])
            top = rel.split(os.sep)[0] if os.sep in rel else "(루트)"
            k = os.path.join(s["root"], top) if top != "(루트)" else s["root"]
            c = by_top.setdefault(k, [0, 0])
            c[0] += 1
            c[1] += sz
    return {"roots": roots, "out_dir": out_dir, "files": nfiles, "bytes": nbytes,
            "est_seconds": round(estimate_seconds(nfiles, nbytes)),
            "by_folder": sorted(([k, v[0], v[1]] for k, v in by_top.items()), key=lambda x: -x[1]),
            "excluded": [x for s in scans for x in s["excluded"]],
            "denied": [x for s in scans for x in s["denied"]],
            "links_skipped": [x for s in scans for x in s["links"]],
            "scans": scans}


def preview_text(pv: dict, top: int = 15) -> str:
    mb = pv["bytes"] / 1048576
    m, s = divmod(pv["est_seconds"], 60)
    h, m = divmod(m, 60)
    L = ["[미리보기 — 아직 아무것도 변환하지 않았습니다]",
         f" 훑은 곳: {', '.join(pv['roots'])}",
         f" 찾은 HWP: {pv['files']:,}개 · 총 {mb:,.1f} MB · 예상 시간(거친 추정) {h}시간 {m}분 {s}초",
         f" 결과 위치: {pv['out_dir']}",
         " 폴더별 분포(상위):"]
    for k, n, sz in pv["by_folder"][:top]:
        L.append(f"   {n:>7,}개  {sz / 1048576:>9,.1f} MB  {k}")
    L.append(f" 제외한 폴더 {len(pv['excluded']):,}곳(시스템·설치·캐시) · 따라가지 않은 링크 {len(pv['links_skipped']):,}개 · "
             f"접근 불가 {len(pv['denied']):,}곳")
    return "\n".join(L)


def write_preview(pv: dict, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    slim = {k: v for k, v in pv.items() if k != "scans"}
    slim["files_list_count"] = pv["files"]
    with open(os.path.join(out_dir, "미리보기.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "미리보기.md"), "w", encoding="utf-8") as f:
        f.write(preview_text(pv, top=50) + "\n\n## 제외한 폴더\n" +
                "\n".join(f"- {x}" for x in pv["excluded"][:2000]) + "\n\n## 접근 불가\n" +
                "\n".join(f"- {x['경로']} ({x['사유']})" for x in pv["denied"][:2000]) + "\n")


# ---- 낮은 우선순위 ----
def lower_priority():
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32  # type: ignore[attr-defined]
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
        else:
            os.nice(10)
    except Exception:
        pass


def parse_window(s: str | None):
    if not s:
        return None
    a, b = s.split("-")
    f = lambda t: _dt.time(int(t.split(":")[0]), int(t.split(":")[1]))  # noqa: E731
    return f(a), f(b)


def in_window(win, now: _dt.time | None = None) -> bool:
    if not win:
        return True
    now = now or _dt.datetime.now().time()
    a, b = win
    return (a <= now <= b) if a <= b else (now >= a or now <= b)


class _Batch(BatchConverter):
    """작업 시간대·중지·일시정지를 파일 사이에서 확인한다."""
    window = None
    stop_path = ""
    sleep = staticmethod(time.sleep)

    def process(self, rel, ledger):
        while not in_window(self.window):
            if os.path.exists(self.stop_path):
                break
            self.sleep(30)
        if os.path.exists(self.stop_path):
            return {"원본": rel, "상태": "중지", "_resumed": True}
        return super().process(rel, ledger)


def beside_copy(rows: list[dict], root: str, outdir: str, log=print) -> int:
    """결과를 원본 옆 〈같은 이름〉.hwpx 로 복사한다. 같은 이름이 있으면 번호를 붙이고 절대 덮어쓰지 않는다."""
    n = 0
    for r in rows:
        if r.get("상태") != "변환완료" or not r.get("변환본"):
            continue
        src = os.path.join(outdir, r["변환본"])
        dst = os.path.join(root, os.path.splitext(r["원본"])[0] + ".hwpx")
        k = 2
        base = os.path.splitext(dst)[0]
        while os.path.exists(dst):
            dst = f"{base} ({k}).hwpx"
            k += 1
        try:
            shutil.copyfile(src, dst)
            n += 1
        except OSError as e:
            log(f"  원본 옆 복사 실패 {dst}: {e}")
    return n


def run_scan_all(roots: list[str] | None, out_dir: str | None, yes: bool = False, preview_only: bool = False,
                 beside: bool = False, window: str | None = None, jobs: int = 1, max_files: int | None = None,
                 gate=None, log=print, ask=input, low_priority: bool = True) -> dict:
    out_dir = os.path.abspath(out_dir or default_out())
    roots = [os.path.abspath(r) if os.name != "nt" else r for r in (roots or fixed_drives())]
    if low_priority:
        lower_priority()
    log(CONSENT)
    pv = build_preview(roots, out_dir, max_files=max_files, log=log)
    write_preview(pv, out_dir)
    log(preview_text(pv))
    log(f" (미리보기 파일: {os.path.join(out_dir, '미리보기.md')})")
    res = {"preview": {k: v for k, v in pv.items() if k != "scans"}, "ran": False}
    if preview_only or pv["files"] == 0:
        log("미리보기만 했습니다." if preview_only else "변환할 HWP 가 없습니다.")
        return res
    if not yes:
        ans = ask("이 내용으로 변환을 시작할까요? 시작하려면 「예」 를 입력하세요 [예/아니오]: ").strip()
        if ans not in ("예", "y", "Y", "yes", "YES"):
            log("취소했습니다. 아무것도 변환하지 않았습니다.")
            return res
    with open(os.path.join(out_dir, "동의기록.json"), "w", encoding="utf-8") as f:
        json.dump({"시각": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "확인방식": "--yes" if yes else "대화 입력", "roots": roots, "beside": beside,
                   "files": pv["files"]}, f, ensure_ascii=False, indent=1)
    win = parse_window(window)
    stats_all = []
    for i, sc in enumerate(pv["scans"]):
        if not sc["files"]:
            continue
        tag = (sc["root"].rstrip("\\/").replace(":", "").replace("\\", "_").replace("/", "_") or "root")
        sub = os.path.join(out_dir, tag)
        rels = [os.path.relpath(p, sc["root"]) for p, _ in sc["files"]]
        log(f"\n[변환] {sc['root']} — {len(rels):,}개 → {sub}")
        bc = _Batch(sc["root"], sub, jobs=jobs, gate=gate, files=rels, log=log)
        bc.window = win
        bc.stop_path = os.path.join(out_dir, "중지")
        try:
            stats = bc.run()
        except KeyboardInterrupt:
            log("중지했습니다. 같은 명령을 다시 실행하면 이어서 합니다(끝난 파일은 건너뜀).")
            res["interrupted"] = True
            break
        stats_all.append({"root": sc["root"], "out": sub, **{k: stats.get(k) for k in ("files", "status", "verdict", "wall_seconds", "sensitive")}})
        sv = (stats.get("sensitive") or {})
        if sv.get("확인 필요"):
            log(f"  민감정보 확인 대기 {sv['확인 필요']}건 — 변환은 끝났고, 확인 전에는 AI 에 보내지 않습니다. 확인: python -m hwpai sens review \"{sc['root']}\"")
        if beside:
            try:
                import csv
                with open(os.path.join(sub, "이관대장.csv"), encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.DictReader(f))
                log(f"  원본 옆 복사 {beside_copy(rows, sc['root'], sub, log)}개")
            except OSError as e:
                log(f"  원본 옆 복사 생략: {e}")
        if os.path.exists(bc.stop_path):
            log("「중지」 파일이 있어 멈췄습니다. 지운 뒤 다시 실행하면 이어서 합니다.")
            res["interrupted"] = True
            break
    res["ran"] = True
    res["stats"] = stats_all
    log("\n끝. 원본은 바뀌지 않았습니다. 이관대장·요약은 각 결과 폴더에 있습니다.")
    return res


def cmd_scan_all(a):
    r = run_scan_all(a.roots, a.out, yes=a.yes, preview_only=a.preview_only, beside=a.beside, window=a.window,
                     jobs=a.jobs, max_files=a.max_files, gate=getattr(a, "gate", None))
    return 0 if (r["ran"] or a.preview_only) else 2


def settings_path() -> str:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base or os.path.expanduser("~"), "hwpai", "settings.json")


def cmd_install(a):
    """설치 단계 옵션. 아무 플래그가 없으면 아무것도 하지 않는다(기본 꺼짐)."""
    sp_ = settings_path()
    if not a.scan_all:
        print("설치만으로는 아무것도 변환하지 않습니다. 「내 컴퓨터 전체 변환」은 기본 꺼짐입니다.\n"
              "켜려면: python -m hwpai install --scan-all  (동의 확인 후 설정에 기록, 변환은 하지 않음)")
        return 0
    print(CONSENT)
    if not a.yes and input("이 옵션을 켤까요? [예/아니오]: ").strip() not in ("예", "y", "Y", "yes"):
        print("켜지 않았습니다.")
        return 0
    os.makedirs(os.path.dirname(sp_), exist_ok=True)
    with open(sp_, "w", encoding="utf-8") as f:
        json.dump({"scan_all_enabled": True, "시각": _dt.datetime.now().astimezone().isoformat(timespec="seconds")}, f)
    print(f"켰습니다(설정: {sp_}). 변환은 아직 하지 않았습니다. 실행: python -m hwpai scan-all")
    return 0


if __name__ == "__main__":
    sys.exit(0)
