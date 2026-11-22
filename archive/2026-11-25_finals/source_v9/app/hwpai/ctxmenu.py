"""탐색기 우클릭 「HWPX로 변환」 메뉴 — 첨부 전에 HWP 를 바로 HWPX 로 바꾸는 길(선택 기능, 기본 꺼짐).

  python -m hwpai ctxmenu --root 〈hwpai 폴더〉 [--out 폴더]          .reg 파일 두 개(설치·해제)를 만든다 — 아무것도 바꾸지 않는다
  python -m hwpai ctxmenu --root 〈hwpai 폴더〉 --apply|--remove      (Windows) 현재 사용자(HKCU)에만 바로 등록·해제

동작: .hwp 파일과 폴더의 우클릭 메뉴에 「HWPX로 변환 (hwpai)」 한 줄을 넣고, 누르면 hwpai.bat 〈선택한 경로〉 가 돌아
      〈원본〉_hwpx변환 폴더에 변환본·검증서가 생긴다(원본은 그대로).
범위: 현재 사용자(HKCU)만 — 관리자 권한이 필요 없고, 해제 .reg 로 완전히 되돌린다. 컴퓨터 전체(HKLM)는 건드리지 않는다.
한계: 한 번에 여러 파일을 고르면 Windows 가 파일마다 따로 실행한다(Windows 의 「고정 동사」 동작, 실기 미확인) —
      많은 파일은 폴더를 우클릭하거나 hwpai.bat 아이콘에 끌어놓는다. Windows 11 은 「추가 옵션 표시」 안에 나타난다.
"""
from __future__ import annotations

import os

LABEL = "HWPX로 변환 (hwpai)"
KEYS = (r"Software\Classes\SystemFileAssociations\.hwp\shell\hwpai",
        r"Software\Classes\Directory\shell\hwpai")


def reg_texts(root: str) -> tuple[str, str]:
    """(설치 .reg, 해제 .reg) 내용. root 는 hwpai.bat 이 있는 폴더(윈도 경로)."""
    bat = root.rstrip("\\/") + "\\hwpai.bat"
    cmd = '\\"' + bat.replace("\\", "\\\\") + '\\" \\"%1\\"'
    inst = ["Windows Registry Editor Version 5.00", ""]
    rem = ["Windows Registry Editor Version 5.00", ""]
    for k in KEYS:
        inst += [f"[HKEY_CURRENT_USER\\{k}]", f'@="{LABEL}"', "", f"[HKEY_CURRENT_USER\\{k}\\command]", f'@="{cmd}"', ""]
        rem += [f"[-HKEY_CURRENT_USER\\{k}]", ""]
    return "\r\n".join(inst), "\r\n".join(rem)


def write_reg(root: str, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    inst, rem = reg_texts(root)
    paths = {}
    for name, txt in (("우클릭메뉴_설치.reg", inst), ("우클릭메뉴_해제.reg", rem)):
        p = os.path.join(out_dir, name)
        with open(p, "wb") as f:
            f.write(b"\xff\xfe" + txt.encode("utf-16-le"))  # 한글 Windows 의 regedit 가 읽는 UTF-16 LE(BOM)
        paths[name] = p
    return paths


def apply_registry(root: str, remove: bool = False, winreg=None) -> list:
    """winreg 를 주입할 수 있다(시험용 모의). HKCU 아래 두 키만 쓴다/지운다."""
    if winreg is None:
        import winreg  # Windows 에서만
    bat = root.rstrip("\\/") + "\\hwpai.bat"
    done = []
    for k in KEYS:
        if remove:
            for sub in (k + r"\command", k):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except FileNotFoundError:
                    pass
            done.append(("제거", k))
        else:
            h = winreg.CreateKey(winreg.HKEY_CURRENT_USER, k)
            winreg.SetValueEx(h, "", 0, winreg.REG_SZ, LABEL)
            h2 = winreg.CreateKey(winreg.HKEY_CURRENT_USER, k + r"\command")
            winreg.SetValueEx(h2, "", 0, winreg.REG_SZ, f'"{bat}" "%1"')
            done.append(("등록", k))
    return done


def cmd_ctxmenu(a):
    root = a.root
    if not root:   # 휴대용 폴더 안에서 실행하면 hwpai.bat 이 있는 그 폴더를 쓴다
        cand = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        if os.path.isfile(os.path.join(cand, "hwpai.bat")):
            root = cand
    if not root:
        raise SystemExit("--root 에 hwpai.bat 이 있는 폴더를 적어 주세요. 예: --root C:\\Tools\\hwpai-portable-win64")
    if a.apply or a.remove:
        if os.name != "nt":
            raise SystemExit("--apply/--remove 는 Windows 에서만 됩니다. .reg 파일을 만들려면 옵션 없이 실행하세요.")
        for act, k in apply_registry(root, remove=a.remove):
            print(f"{act}: HKCU\\{k}")
        return 0
    paths = write_reg(root, a.out or os.getcwd())
    for n, p in paths.items():
        print(f"{n}: {p}")
    print("두 파일은 만들기만 했습니다. 메뉴를 넣으려면 「우클릭메뉴_설치.reg」 를 더블클릭하세요(현재 사용자만, 해제 .reg 로 되돌림).")
    return 0
