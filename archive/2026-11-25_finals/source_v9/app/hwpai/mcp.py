"""hwpai MCP 서버 — 표준입출력(JSON-RPC 2.0, 한 줄에 메시지 하나). 외부 라이브러리 없음.

  python -m hwpai mcp                 MCP 호스트(Claude 데스크톱 등)가 띄운다
  python -m hwpai mcp-install         Claude 데스크톱 설정에 자동 등록(기존 설정은 .bak 로 보관)

도구
  read_hwp        HWP·HWPX → 마크다운(또는 순수 글·JSON). 변환 없이 바로 읽는다
  get_tables      문서 속 표 → CSV 또는 행 레코드(병합 칸 펼침)
  search_chunks   문서를 제목 경로가 붙은 조각으로 나눠 질의와 가까운 조각을 돌려준다
  convert_to_hwpx 파일·폴더 → HWPX 일괄 변환 + 이관대장 + 검증서(원본 불변, 결과는 새 폴더)
  audit           원본과 변환 HWPX 대조 검증서(PASS/WARN/FAIL, 차이 위치)
  export_doc      Markdown·구조화 JSON·RAG 청크 파일 출력(확인 전 문서는 AI 폴더에 쓰지 않음)
  replace_text    서식을 보존한 글 치환 → 새 HWPX + 변경 보고서(원본 불변, 되읽기 검증)
  fill_form       양식 칸 채우기({{키}} 자리표시·이름표 칸) → 새 HWPX + 되읽기 검증

접근 범위: 환경변수 HWPAI_MCP_ROOTS(경로; 구분은 os.pathsep)를 주면 그 아래 파일만 다룬다.
보안등급: 등급은 사람이 만든 등급 파일(HWPAI_GRADE_FILE, CSV: 경로,등급)에서만 읽고 AI 가 인자로 바꿀 수 없다.
  「공개」는 처리, 「민감」·「기밀」은 AI 노출 제한(AI 도구 호출은 예외 없음). 파일에 없는(등급 미표기) 문서는
  명령줄·화면과 같은 정책(HWPAI_GRADE_POLICY, 기본 review 「확인 요청」)을 따른다 — 변환·검증·화면 열람은 막지 않고,
  민감정보 꼴이 있는 문서는 「확인 대기」로 두어 사람이 확인(hwpai sens review)하기 전에는 AI 도구로 내용을 주지 않는다.
  사람이 「민감정보 아님」으로 확인하면 AI 도구도 허용, 「민감정보 있음」이면 가림(mask)본으로만 허용하거나 AI 노출을 막는다.
  pii/pii-strict 는 예전의 즉시 차단 정책, deny 는 등급 없는 문서를 모두 AI 에 주지 않는다. 결정은 등급_기록.jsonl 에 남는다.
종류: [조회형] read_hwp·get_tables·search_chunks·audit  [처리형] convert_to_hwpx·export_doc·replace_text·fill_form(새 파일을 만든다, 원본 불변)
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback

PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")


def _gate_setup():
    """HWPAI_GRADE_FILE 로 MCP 등급 게이트를 켠다. 등급 미표기 문서는 개인정보 미검출이면 허용(정책 pii), HWPAI_GRADE_POLICY=deny 면 차단."""
    from . import grade
    gf = os.environ.get("HWPAI_GRADE_FILE")
    logdir = os.environ.get("HWPAI_GRADE_LOG") or (os.path.dirname(os.path.abspath(gf)) if gf else os.getcwd())
    gate = grade.Gate(grades=grade.load_grades(gf), default=None, exception=None, mode="mcp",
                      logdir=os.path.join(logdir, "hwpai_등급기록"),
                      policy=os.environ.get("HWPAI_GRADE_POLICY", "review"))
    grade.set_active(gate)
    return gate


_DATA_TOOLS = ("read_hwp", "get_tables", "search_chunks")


def _roots():
    v = os.environ.get("HWPAI_MCP_ROOTS")
    return [os.path.abspath(x) for x in v.split(os.pathsep) if x] if v else None


def _check(path: str) -> str:
    p = os.path.abspath(os.path.expanduser(path))
    roots = _roots()
    if roots and not any(p == r or p.startswith(r + os.sep) for r in roots):
        raise PermissionError(f"허용된 폴더 밖입니다: {p} (HWPAI_MCP_ROOTS)")
    if not os.path.exists(p):
        raise FileNotFoundError(f"파일·폴더가 없습니다: {p}")
    return p


# ---------------------------------------------------------------- 도구 구현
def t_read_hwp(path: str, format: str = "markdown", max_chars: int = 60000):
    from . import read
    from .render import plain_text, to_markdown
    doc = read(_check(path), visible=True)   # C77: AI 가 읽는 길은 화면에 보이는 글만
    if format == "json":
        txt = json.dumps(doc.to_dict(), ensure_ascii=False)
    elif format == "text":
        txt = plain_text(doc)
    else:
        txt = to_markdown(doc)
    cut = len(txt) > max_chars
    return txt[:max_chars] + (f"\n\n[… {len(txt) - max_chars}자 생략 — max_chars 를 늘리거나 search_chunks 를 쓰세요]" if cut else "")


def t_get_tables(path: str, table_id: int | None = None, as_: str = "records", max_rows: int = 200):
    import csv
    import io
    from . import read
    from .model import walk_tables
    from .render import grid_of, table_records
    doc = read(_check(path), visible=True)   # C77: AI 가 읽는 길은 화면에 보이는 글만
    out = []
    for t in walk_tables(doc.blocks):
        if table_id and t.id != table_id:
            continue
        item = {"table_id": t.id, "caption": t.caption, "rows": t.nrows, "cols": t.ncols}
        if as_ == "csv":
            s = io.StringIO()
            csv.writer(s).writerows(grid_of(t, " ")[:max_rows])
            item["csv"] = s.getvalue()
        else:
            item["records"] = table_records(t)[:max_rows]
        out.append(item)
    return json.dumps({"tables": out, "count": len(out)}, ensure_ascii=False)


def _grams(s: str) -> list:
    s = re.sub(r"\s+", "", s.lower())
    return [s[i:i + 2] for i in range(len(s) - 1)] if len(s) > 1 else ([s] if s else [])


def t_search_chunks(path: str, query: str, top_k: int = 5):
    """글자 2-gram BM25 — 한국어 띄어쓰기·조사에 덜 민감하고 외부 모델이 필요 없다."""
    import collections
    import math
    from . import read
    from .render import to_chunks
    chunks = to_chunks(read(_check(path), visible=True))
    docs = [collections.Counter(_grams(" ".join(c.get("heading_path", [])) + " " + c["text"])) for c in chunks]
    n = len(docs) or 1
    df = collections.Counter(g for d in docs for g in d)
    avg = sum(sum(d.values()) for d in docs) / n or 1
    q = set(_grams(query))
    k1, b = 1.2, 0.75
    scored = []
    for c, d in zip(chunks, docs):
        ln = sum(d.values()) or 1
        sc = 0.0
        for g in q:
            tf = d.get(g, 0)
            if tf:
                idf = math.log(1 + (n - df[g] + 0.5) / (df[g] + 0.5))
                sc += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * ln / avg))
        scored.append((sc, c))
    scored.sort(key=lambda x: -x[0])
    res = [{"score": round(s, 3), "id": c["id"], "type": c["type"], "heading_path": c.get("heading_path", []),
            "text": c["text"][:3000]} for s, c in scored[:max(1, top_k)] if s > 0]
    return json.dumps({"query": query, "results": res, "total_chunks": len(chunks)}, ensure_ascii=False)


def t_convert_to_hwpx(path: str, out: str | None = None, jobs: int = 1):
    from .batch import BatchConverter
    p = _check(path)
    from .batch import default_out
    o = os.path.abspath(out) if out else default_out(p)
    if o == p or o.startswith(p + os.sep):
        raise ValueError("결과 폴더는 원본 폴더 밖이어야 합니다(원본 불변)")
    from . import grade
    s = BatchConverter(p, o, jobs=jobs, log=lambda *a, **k: None, gate=grade.active()).run()
    return json.dumps({"out": o, "ledger_csv": os.path.join(o, "이관대장.csv"), "ledger_xlsx": os.path.join(o, "이관대장.xlsx"),
                       "summary_md": os.path.join(o, "요약.md"),
                       **{k: s[k] for k in ("files", "status", "verdict", "reason_codes", "wall_seconds")}}, ensure_ascii=False)


def t_audit(original: str, converted: str):
    from .audit import audit, to_markdown
    from .grade import guard
    o, c = _check(original), _check(converted)
    guard(o, tool="audit")  # audit() 은 예외를 삼키므로 먼저 확인
    guard(c, tool="audit")
    a = audit(o, c)
    return to_markdown(a)


def _out_for(p: str, out: str | None, suffix: str) -> str | None:
    if not out:
        return None
    o = _check(os.path.dirname(os.path.abspath(os.path.expanduser(out))) or ".")  # 결과 폴더도 허용 범위 안
    return os.path.join(o, os.path.basename(out))


def t_replace_text(path: str, replacements: dict, out: str | None = None):
    from .edit import replace_text
    p = _check(path)
    from .grade import guard
    guard(p, tool="replace_text")
    if not isinstance(replacements, dict) or not replacements:
        raise ValueError("replacements 는 {찾는 글: 바꿀 글} 객체여야 합니다")
    return json.dumps(replace_text(p, {str(k): str(v) for k, v in replacements.items()}, _out_for(p, out, "_수정")), ensure_ascii=False)


def t_fill_form(path: str, values: dict, out: str | None = None):
    from .fill import fill
    p = _check(path)
    from .grade import guard
    guard(p, tool="fill_form")
    if not isinstance(values, dict) or not values:
        raise ValueError("values 는 {키: 값} 객체여야 합니다")
    return json.dumps(fill(p, {str(k): str(v) for k, v in values.items()}, _out_for(p, out, "_채움")), ensure_ascii=False)


def t_export_doc(path: str, out: str, formats: str = "md,json,chunks", ai_folder: bool = True):
    from .export import export_many
    p = _check(path)
    o = _check(os.path.dirname(os.path.abspath(os.path.expanduser(out))) or ".")
    o = os.path.join(o, os.path.basename(out))
    r = export_many([p], o, tuple(x.strip() for x in formats.split(",") if x.strip()), bool(ai_folder), log=lambda *a, **k: None)
    return json.dumps({k: r[k] for k in ("files", "written", "waiting", "failed", "out")}
                      | {"rows": [{k: x.get(k) for k in ("file", "status", "dir", "reason")} for x in r["rows"]]}, ensure_ascii=False)


TOOLS = [
    {"name": "read_hwp", "fn": t_read_hwp,
     "description": "[조회형] HWP·HWPX 문서를 한글 프로그램 없이 읽어 마크다운(표 포함)으로 돌려준다. 변환하지 않고 원본을 바로 읽는다.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "문서 경로(.hwp/.hwpx)"},
         "format": {"type": "string", "enum": ["markdown", "text", "json"], "default": "markdown"},
         "max_chars": {"type": "integer", "default": 60000}}, "required": ["path"]}},
    {"name": "get_tables", "fn": t_get_tables,
     "description": "[조회형] 문서 속 표를 병합 칸을 펼친 행 레코드(첫 행=머리글) 또는 CSV 로 돌려준다.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "table_id": {"type": "integer", "description": "특정 표 번호(1부터). 비우면 전체"},
         "as": {"type": "string", "enum": ["records", "csv"], "default": "records"},
         "max_rows": {"type": "integer", "default": 200}}, "required": ["path"]}},
    {"name": "search_chunks", "fn": t_search_chunks,
     "description": "[조회형] 문서를 제목 경로가 붙은 조각으로 나눠 질의와 글자 겹침이 큰 조각을 찾는다(긴 문서에서 근거 찾기).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}},
         "required": ["path", "query"]}},
    {"name": "convert_to_hwpx", "fn": t_convert_to_hwpx,
     "description": "[처리형] HWP 파일 또는 폴더를 한글 없이 HWPX 로 일괄 변환하고, 파일별 검증서와 이관대장(CSV·엑셀)을 만든다. 원본은 바꾸지 않는다.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "out": {"type": "string", "description": "결과 폴더(비우면 원본_hwpx변환)"},
         "jobs": {"type": "integer", "default": 1}}, "required": ["path"]}},
    {"name": "audit", "fn": t_audit,
     "description": "[조회형] 원본 HWP 와 변환 HWPX 를 같은 문서 모델로 대조해 검증서(PASS/WARN/FAIL, 글·표 칸·그림·각주·수식 차이 위치)를 만든다.",
     "inputSchema": {"type": "object", "properties": {
         "original": {"type": "string"}, "converted": {"type": "string"}}, "required": ["original", "converted"]}},
    {"name": "export_doc", "fn": t_export_doc,
     "description": "[처리형] 문서(또는 폴더)를 Markdown(본문.md)·구조화 JSON(구조.json: 표 격자·병합·그림 해시)·RAG 청크(chunks.jsonl) 파일로 내보낸다. ai_folder=true(기본)면 민감정보 확인이 끝나지 않은 문서는 쓰지 않고 확인 대기 목록에 올린다.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "out": {"type": "string", "description": "결과 폴더"},
         "formats": {"type": "string", "default": "md,json,chunks"}, "ai_folder": {"type": "boolean", "default": True}}, "required": ["path", "out"]}},
    {"name": "replace_text", "fn": t_replace_text,
     "description": "[처리형] HWPX(또는 HWP)에서 글을 찾아 바꾼 새 HWPX 를 만든다. 글자 모양·표·그림은 그대로 두고, 위치·이전·이후를 적은 변경 보고서(.md)를 함께 만든다. audit 검증서 수정안의 replace_text 값을 그대로 넣을 수 있다(바꿀 글을 「찾는 글 + 줄바꿈 + 더할 글」로 쓰면 그 문단 뒤에 새 문단을 넣는다). 고친 뒤에는 audit 로 다시 검증한다. 원본은 바꾸지 않는다.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "replacements": {"type": "object", "description": "{찾는 글: 바꿀 글}"},
         "out": {"type": "string", "description": "결과 파일(비우면 〈이름〉_수정.hwpx)"}}, "required": ["path", "replacements"]}},
    {"name": "fill_form", "fn": t_fill_form,
     "description": "[처리형] 양식(HWPX·HWP)의 {{키}} 자리표시와 표의 이름표 칸 옆 빈 칸에 값을 서식 유지한 채 넣은 새 HWPX 를 만들고, 되읽기로 검증한다. 원본은 바꾸지 않는다.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "values": {"type": "object", "description": "{키: 값}"},
         "out": {"type": "string"}}, "required": ["path", "values"]}},
]


def _call(name, args):
    from . import grade
    t = next((x for x in TOOLS if x["name"] == name), None)
    if not t:
        raise KeyError(f"없는 도구: {name}")
    args = dict(args or {})
    if name == "get_tables" and "as" in args:
        args["as_"] = args.pop("as")
    if grade.active() is None:  # serve() 를 거치지 않은 호출도 게이트를 반드시 건다
        _gate_setup()
    grade.set_active(grade.active(), tool=name)  # 이 호출의 이름을 등급 기록에 남긴다
    import inspect
    params = inspect.signature(t["fn"]).parameters
    bad = [k for k in args if k not in params]
    if bad:
        if any(k in ("grade", "등급", "policy", "exception", "예외") for k in bad):
            raise ValueError("등급·예외는 AI 도구 호출 인자로 지정할 수 없습니다. 사람이 등급 파일(HWPAI_GRADE_FILE)에 적습니다.")
        raise ValueError(f"알 수 없는 인자: {', '.join(bad)}. 이 도구의 인자는 {', '.join(params) or '없음'} 입니다.")
    out = t["fn"](**args)
    if name in _DATA_TOOLS:
        out = grade.DATA_NOTICE + "\n\n" + out
    return out


def handle(msg: dict) -> dict | None:
    if not isinstance(msg, dict):  # 6차: 객체가 아닌 JSON(숫자·문자열·null)이 오면 서버가 죽던 오류 — JSON-RPC 「잘못된 요청」으로 답한다
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request: JSON-RPC 메시지는 객체여야 합니다"}}
    mid = msg.get("id")
    method = msg.get("method")
    if method is None or (mid is None and isinstance(method, str) and method.startswith("notifications/")):
        return None
    if not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "invalid request: method 는 문자열이어야 합니다"}}
    try:
        if method == "initialize":
            v = (msg.get("params") or {}).get("protocolVersion")
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": v if v in SUPPORTED else PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "hwpai", "title": "HWP AI 어댑터", "version": "0.9.0"},
                "instructions": "HWP·HWPX 문서는 read_hwp 로 바로 읽고, 표는 get_tables, 긴 문서는 search_chunks 로 근거를 찾는다. "
                                "HWPX 이관은 convert_to_hwpx, 변환 품질 확인은 audit."}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {k: v for k, v in t.items() if k != "fn"} for t in TOOLS]}}
        if method == "tools/call":
            p = msg.get("params") or {}
            try:
                text = _call(p.get("name"), p.get("arguments"))
                return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": False}}
            except Exception as e:  # 도구 오류는 결과로 돌려준다(모델이 읽고 고칠 수 있게)
                return {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": f"오류: {type(e).__name__}: {e}"}], "isError": True}}
        if mid is None:
            return None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"지원하지 않는 메서드: {method}"}}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}


def _utf8_stdio():
    """MCP 표준입출력 전송은 UTF-8 이다. 파이썬을 UTF-8 모드 없이 띄우면(윈도 기본 cp949 등) 한글 경로를 읽다 서버가 죽거나
    출력이 깨지므로(6차 시험에서 재현) 표준입출력을 UTF-8 로 맞춘다. 줄바꿈도 \n 하나로 고정(윈도 \r\n 방지)."""
    for st, kw in ((sys.stdin, {"errors": "replace"}), (sys.stdout, {"newline": "\n"})):
        try:
            st.reconfigure(encoding="utf-8", **kw)
        except Exception:
            pass


def serve(stdin=None, stdout=None):
    if stdin is None and stdout is None:
        _utf8_stdio()
    _gate_setup()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            stdout.flush()
            continue
        batch = msg if isinstance(msg, list) else [msg]
        if not batch:  # 빈 배치는 잘못된 요청
            batch = [None]
        outs = [r for r in (handle(m) for m in batch) if r is not None]
        for r in outs:
            stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
        stdout.flush()


# ---------------------------------------------------------------- 설치
def config_path() -> str:
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Claude", "claude_desktop_config.json")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    return os.path.expanduser("~/.config/Claude/claude_desktop_config.json")


def server_entry() -> dict:
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    e = {"command": sys.executable, "args": ["-m", "hwpai", "mcp"], "env": {"PYTHONPATH": pkg_parent, "PYTHONUTF8": "1"}}
    from .engines import find_node
    n = find_node()
    if n:
        e["env"]["HWPAI_NODE"] = n
    return e


def install(path: str | None = None, name: str = "hwpai", dry: bool = False) -> str:
    p = path or config_path()
    cfg = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            txt = f.read()
        cfg = json.loads(txt) if txt.strip() else {}
        if not dry:
            with open(p + ".bak", "w", encoding="utf-8") as f:
                f.write(txt)
    cfg.setdefault("mcpServers", {})[name] = server_entry()
    out = json.dumps(cfg, ensure_ascii=False, indent=2)
    if not dry:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".part", "w", encoding="utf-8") as f:
            f.write(out)
        os.replace(p + ".part", p)
    return p if not dry else out


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
