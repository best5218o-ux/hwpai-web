"""AI 앱에 hwpai MCP 서버를 승인 후 등록·해제한다.

대상
- claude  : Claude 데스크톱 설정 (claude_desktop_config.json, JSON)
- chatgpt : ChatGPT 데스크톱 설정 (~/.codex/config.toml, TOML의 [mcp_servers.hwpai])

원칙
- 등록·해제 전에 반드시 사용자 승인을 받는다 (--yes 없이는 질문을 띄운다).
- 기존 설정 파일은 .bak 으로 보관한다. hwpai 항목 외의 설정은 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
import sys

NAME = "hwpai"


def _codex_config() -> str:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, ".codex", "config.toml")


def _env_and_cmd() -> tuple[str, list[str], dict]:
    from .mcp import server_entry
    e = server_entry()
    return e["command"], e["args"], e.get("env", {})


def _toml_lit(s: str) -> str:
    # TOML 리터럴 문자열(작은따옴표): 백슬래시를 그대로 둔다 (Windows 경로)
    return "'" + s.replace("'", "") + "'"


def _toml_block(command: str, args: list[str], env: dict) -> str:
    lines = [f"[mcp_servers.{NAME}]", f"command = {_toml_lit(command)}",
             "args = [" + ", ".join(_toml_lit(a) for a in args) + "]", "",
             f"[mcp_servers.{NAME}.env]"]
    for k, v in env.items():
        lines.append(f"{k} = {_toml_lit(str(v))}")
    return "\n".join(lines) + "\n"


def _strip_toml_block(text: str) -> str:
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        st = line.strip()
        if st.startswith("["):
            skip = st == f"[mcp_servers.{NAME}]" or st.startswith(f"[mcp_servers.{NAME}.")
        if not skip:
            out.append(line)
    return "".join(out).rstrip() + "\n" if out else ""


def target_path(target: str) -> str:
    if target == "claude":
        from .mcp import config_path
        return config_path()
    if target == "chatgpt":
        return _codex_config()
    raise SystemExit(f"알 수 없는 대상: {target} (claude | chatgpt)")


def status(target: str) -> str:
    p = target_path(target)
    if not os.path.exists(p):
        return f"{target}: 설정 파일 없음 ({p}) — 등록 안 됨"
    txt = open(p, encoding="utf-8").read()
    if target == "claude":
        cfg = json.loads(txt) if txt.strip() else {}
        on = NAME in cfg.get("mcpServers", {})
    else:
        on = f"[mcp_servers.{NAME}]" in txt
    return f"{target}: {'등록됨' if on else '등록 안 됨'} ({p})"


def install(target: str, yes: bool = False) -> str:
    p = target_path(target)
    cmd, args, env = _env_and_cmd()
    if not yes and not _ask(f"{target} 설정에 hwpai를 등록합니다 ({p}). 승인하시겠습니까?"):
        return "취소했습니다. 아무것도 바꾸지 않았습니다."
    old = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    if old:
        open(p + ".bak", "w", encoding="utf-8").write(old)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if target == "claude":
        cfg = json.loads(old) if old.strip() else {}
        cfg.setdefault("mcpServers", {})[NAME] = {"command": cmd, "args": args, "env": env}
        new = json.dumps(cfg, ensure_ascii=False, indent=2)
    else:
        base = _strip_toml_block(old)
        new = (base + "\n" if base.strip() else "") + _toml_block(cmd, args, env)
    open(p + ".part", "w", encoding="utf-8").write(new)
    os.replace(p + ".part", p)
    return f"등록했습니다: {p} (기존 설정은 .bak 로 보관). {target} 앱을 다시 시작하세요."


def remove(target: str, yes: bool = False) -> str:
    p = target_path(target)
    if not os.path.exists(p):
        return "설정 파일이 없어 할 일이 없습니다."
    if not yes and not _ask(f"{target} 설정에서 hwpai를 해제합니다 ({p}). 승인하시겠습니까?"):
        return "취소했습니다. 아무것도 바꾸지 않았습니다."
    old = open(p, encoding="utf-8").read()
    open(p + ".bak", "w", encoding="utf-8").write(old)
    if target == "claude":
        cfg = json.loads(old) if old.strip() else {}
        cfg.get("mcpServers", {}).pop(NAME, None)
        new = json.dumps(cfg, ensure_ascii=False, indent=2)
    else:
        new = _strip_toml_block(old)
    open(p + ".part", "w", encoding="utf-8").write(new)
    os.replace(p + ".part", p)
    return f"해제했습니다: {p} (기존 설정은 .bak 로 보관)."


def _ask(msg: str) -> bool:
    if not sys.stdin.isatty():
        return False
    ans = input(msg + " [y/N] ").strip().lower()
    return ans in ("y", "yes", "예", "네")
