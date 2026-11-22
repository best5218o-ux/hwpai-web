"""hwpai gui — 내 컴퓨터 안(127.0.0.1)에서만 열리는 화면.

  python -m hwpai gui [--port 8765] [--no-browser]

처음 화면 전체가 끌어놓기 자리다. 폴더(하위 폴더 포함)·여러 파일을 놓거나 「폴더 선택」으로 고른다.
브라우저는 실제 경로를 알려 주지 않으므로, 받은 .hwp/.hwpx 만 이 컴퓨터의 작업 폴더
(HWPAI_WORKDIR, 기본 문서\\hwpai_work\\〈폴더 이름〉)에 상대 경로 그대로 복사한 뒤 일괄 변환한다.
결과는 〈작업 폴더〉\\〈폴더 이름〉_hwpx변환. 사용자의 원본 파일은 읽기만 한다.
같은 폴더를 다시 놓으면 크기·수정 시각이 같은 파일은 다시 옮기지 않고, 이관대장으로 이어서 한다.
경로를 직접 고르는 방식(「경로로 고르기」)은 복사 없이 원본 옆 〈원본〉_hwpx변환 에 쓴다.

보안: 127.0.0.1 에만 열고, 접속 열쇠(token)·Host·Origin 이 맞지 않으면 응답하지 않는다.
올리는 경로는 상대 경로만 받고(../·절대 경로·드라이브 문자 거부), 파일 크기·개수·디스크 여유를 먼저 본다.
외부 라이브러리·인터넷 없이 파이썬 표준 http.server 로 돈다.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import string
import subprocess
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .batch import SRC_EXT, BatchConverter, OUT_SUFFIX, default_out

STATE = {"job": None, "uploads": {}}
LOCK = threading.Lock()
MAX_FILE_MB = int(os.environ.get("HWPAI_UPLOAD_MAX_MB", "200"))      # 파일 하나 상한
MAX_FILES = int(os.environ.get("HWPAI_UPLOAD_MAX_FILES", "20000"))    # 한 번에 받는 파일 수 상한
POLICY_UI = {"기본": ("review", None), "공개": ("review", "공개"), "엄격": ("pii-strict", None)}
_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')


def work_root() -> str:
    w = os.environ.get("HWPAI_WORKDIR")
    if not w:
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        w = os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"), "hwpai_work")
    return os.path.abspath(w)


def show(p: str) -> str:
    """화면에 보일 경로 — 사용자 폴더 앞부분은 「내 폴더」로 줄인다(캡처·화면 공유 때 계정 이름이 덜 드러나게)."""
    h = os.path.expanduser("~")
    return ("내 폴더" + p[len(h):]) if p and h and h != os.sep and p.startswith(h) else p


def safe_name(name: str) -> str:
    """작업 폴더 이름(한 단계) — 위험한 글자는 _ 로."""
    n = _BAD.sub("_", (name or "").replace("/", "_").replace("\\", "_")).strip(" .")
    return n[:80] or "끌어놓은_파일"


def safe_rel(rel: str) -> str | None:
    """브라우저가 준 상대 경로 → 안전한 상대 경로. 탈출(../)·절대 경로·드라이브·예약 글자·HWP 아님이면 None."""
    if not rel or len(rel) > 400:
        return None
    r = rel.replace("\\", "/")
    if r.startswith("/") or re.match(r"^[A-Za-z]:", r):
        return None
    parts = r.split("/")
    if any(p in ("", ".", "..") or _BAD.search(p) or p != p.rstrip(" .") for p in parts):
        return None
    if not parts[-1].lower().endswith(SRC_EXT):
        return None
    return os.path.join(*parts)


def inside(root: str, path: str) -> bool:
    root, path = os.path.realpath(root), os.path.realpath(path)
    return path.startswith(root + os.sep)


class Upload:
    """끌어놓은 파일을 작업 폴더로 옮기는 한 번의 묶음."""

    def __init__(self, name: str, files: list):
        self.id = uuid.uuid4().hex
        self.name = safe_name(name)
        self.stage = os.path.join(work_root(), self.name)
        self.out = self.stage + OUT_SUFFIX
        self.man_path = os.path.join(self.stage, ".hwpai_upload.json")
        self.files = {}   # rel → (size, mtime)
        for f in files:
            rel = safe_rel(str(f.get("rel", "")))
            if rel is None:
                raise ValueError(f"받을 수 없는 경로: {f.get('rel')!r}")
            size = int(f.get("size", -1))
            if size < 0 or size > MAX_FILE_MB * 1024 * 1024:
                raise ValueError(f"파일 크기 상한({MAX_FILE_MB}MB) 초과: {f.get('rel')}")
            self.files[rel] = (size, int(f.get("mtime", 0)))
        if not self.files:
            raise ValueError("HWP·HWPX 파일이 없습니다")
        if len(self.files) > MAX_FILES:
            raise ValueError(f"한 번에 {MAX_FILES}개까지 받습니다")
        os.makedirs(self.stage, exist_ok=True)
        need = sum(s for s, _ in self.files.values()) * 3  # 사본 + 변환본 + 여유
        if shutil.disk_usage(self.stage).free < need + 200 * 1024 * 1024:
            raise ValueError("작업 폴더 디스크 여유 공간이 부족합니다")
        try:
            with open(self.man_path, encoding="utf-8") as fh:
                self.manifest = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self.manifest = {}
        self.received = set()

    def have(self) -> list[str]:
        """이미 같은 크기·수정 시각으로 받아 둔 파일(다시 옮기지 않는다)."""
        out = []
        for rel, (size, mt) in self.files.items():
            p = os.path.join(self.stage, rel)
            key = rel.replace(os.sep, "/")
            if os.path.isfile(p) and os.path.getsize(p) == size and self.manifest.get(key) == [size, mt]:
                out.append(key)
                self.received.add(rel)
        return out

    def put(self, rel_raw: str, stream, length: int):
        rel = safe_rel(rel_raw)
        if rel is None or rel not in self.files:
            raise ValueError("이 묶음에 없는 파일입니다")
        size, mt = self.files[rel]
        if length != size:
            raise ValueError("크기가 알린 값과 다릅니다")
        dst = os.path.join(self.stage, rel)
        if not inside(self.stage, dst):
            raise ValueError("작업 폴더 밖으로 쓸 수 없습니다")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".part"
        left = length
        with open(tmp, "wb") as fh:
            while left > 0:
                b = stream.read(min(left, 1 << 20))
                if not b:
                    break
                fh.write(b)
                left -= len(b)
        if left:
            os.remove(tmp)
            raise ValueError("전송이 끊겼습니다")
        os.replace(tmp, dst)
        with LOCK:
            self.received.add(rel)
            self.manifest[rel.replace(os.sep, "/")] = [size, mt]
            with open(self.man_path, "w", encoding="utf-8") as fh:
                json.dump(self.manifest, fh, ensure_ascii=False)


class Job:
    def __init__(self, src, out, jobs, policy="기본", only=None, dropped=False):
        self.src, self.out, self.jobs, self.only, self.dropped = src, out, jobs, only, dropped
        self.policy = policy if policy in POLICY_UI else "기본"
        self.done = self.total = 0
        self.rows: list[dict] = []
        self.status = "실행 중"
        self.stats = None
        self.error = ""
        self.started = time.time()
        threading.Thread(target=self.run, daemon=True).start()

    def on_row(self, done, total, row):
        with LOCK:
            if done is not None:
                self.done = done
            self.total = total
            self.rows.append({k: row.get(k, "") for k in ("원본", "상태", "판정", "검증점수", "판정_이유", "검증서", "변환_소요ms")})

    def run(self):
        try:
            # 화면에서도 명령줄과 같은 개인정보 게이트를 쓴다. 화면의 보안등급 선택이 정책을 정한다
            # (기본=pii · 공개=모든 파일 「공개」 지정 · 엄격=pii-strict). 등급 파일: HWPAI_GRADE_FILE
            from . import grade as _grade
            pol, default = POLICY_UI[self.policy]
            pol = os.environ.get("HWPAI_GRADE_POLICY", pol) if self.policy == "기본" else pol
            gf = os.environ.get("HWPAI_GRADE_FILE")
            gate = _grade.Gate(grades=_grade.load_grades(gf), default=default, exception=None, mode="gui",
                               logdir=self.out, policy=pol)
            _grade.set_active(gate, tool="gui")
            bc = BatchConverter(self.src, self.out, jobs=self.jobs, log=lambda *a, **k: None, on_row=self.on_row,
                                gate=gate, only=self.only)
            self.stats = bc.run()
            self.status = "완료"
        except Exception as e:
            self.status, self.error = "오류", f"{type(e).__name__}: {e}"


def _drives():
    if os.name == "nt":
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    return ["/"]


def _scan_preview(p: str) -> dict:
    n = size = skip = 0
    dirs = set()
    for dp, dns, fns in os.walk(p):
        dns[:] = [d for d in dns if not d.startswith(".")]
        for f in fns:
            if f.lower().endswith(SRC_EXT):
                n += 1
                size += os.path.getsize(os.path.join(dp, f))
                dirs.add(os.path.relpath(dp, p))
            elif not f.startswith("."):
                skip += 1
    dirs.discard(".")
    return {"hwp": n, "bytes": size, "subdirs": len(dirs), "skipped": skip}


def _open_path(path: str) -> bool:
    if os.environ.get("HWPAI_NO_OPEN"):
        return False
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 — 이번 작업의 결과 폴더·대장만 연다
            return True
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        pass
    return False


class Handler(BaseHTTPRequestHandler):
    token = ""
    port = 0

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(b)

    def _ok(self, q):
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if self.headers.get("Host") not in hosts:
            return False
        org = self.headers.get("Origin")
        if org and org not in {"http://" + h for h in hosts}:
            return False
        return secrets.compare_digest(q.get("t", [""])[0], self.token)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self._ok(q):
            return self._send(403, {"오류": "접속 열쇠가 맞지 않습니다. 명령창에 나온 주소로 여세요."})
        if u.path == "/":
            return self._send(200, PAGE.replace("__TOKEN__", self.token).replace("__WORK__", show(work_root())),
                              "text/html; charset=utf-8")
        if u.path == "/api/ls":
            p = q.get("p", [""])[0]
            if not p:
                return self._send(200, {"path": "", "dirs": _drives(), "hwp": 0})
            try:
                ents = sorted(os.scandir(p), key=lambda e: e.name)
                dirs = [e.name for e in ents if e.is_dir() and not e.name.startswith(".")]
                files = [e.name for e in ents if e.is_file() and e.name.lower().endswith(SRC_EXT)]
                return self._send(200, {"path": os.path.abspath(p), "parent": os.path.dirname(os.path.abspath(p)),
                                        "dirs": dirs[:500], "hwp": len(files), "files": files[:500]})
            except OSError as e:
                return self._send(400, {"오류": str(e)})
        if u.path == "/api/preview":
            p = q.get("p", [""])[0]
            if not os.path.isdir(p):
                return self._send(400, {"오류": "폴더가 없습니다"})
            return self._send(200, {**_scan_preview(p), "out": default_out(p)})
        if u.path == "/api/status":
            j = STATE["job"]
            if not j:
                return self._send(200, {"status": "대기"})
            since = int(q.get("since", ["0"])[0] or 0)
            with LOCK:
                return self._send(200, {"status": j.status, "done": j.done, "total": j.total, "rows": j.rows[since:],
                                        "nrows": len(j.rows), "out": j.out, "out_show": show(j.out), "stats": j.stats, "error": j.error,
                                        "elapsed": round(time.time() - j.started, 1), "policy": j.policy,
                                        "dropped": j.dropped})
        if u.path == "/sens":
            j = STATE["job"]
            if not j:
                return self._send(404, {"오류": "작업이 없습니다"})
            from . import sens
            from .sens_view import render_review_html
            store = sens.Store(j.out)
            files = [os.path.join(j.src, r) for r in j.only] if j.only else sens._files(j.src)
            docs = []
            for f in files:
                st = sens.scan_file(f, store)
                if st["state"] is None or not st["items"]:
                    continue
                rec = store.load(st["sha256"]) or {}
                decs = {r["key"]: r["decision"] for r in rec.get("items", []) if r.get("decision")}
                docs.append({"name": os.path.relpath(f, j.src) if os.path.isdir(j.src) else os.path.basename(f), "sha256": st["sha256"],
                             "text": st["text"], "items": st["items"], "decisions": decs, "policy": rec.get("policy")})
            return self._send(200, render_review_html(docs, reviewer=sens._whoami(), api=f"/api/sens/save?t={self.token}"),
                              "text/html; charset=utf-8")
        if u.path == "/api/review":
            from . import review as rv
            try:
                return self._send(200, rv._load(q.get("p", [""])[0]))
            except Exception as e:
                return self._send(400, {"오류": str(e)})
        if u.path == "/api/audit":
            j = STATE["job"]
            rel = q.get("p", [""])[0]
            if not j or not rel:
                return self._send(404, {"오류": "없음"})
            full = os.path.abspath(os.path.join(j.out, rel))
            if not full.startswith(os.path.abspath(j.out) + os.sep) or not full.endswith(".md") or not os.path.isfile(full):
                return self._send(404, {"오류": "검증서가 없습니다"})
            with open(full, encoding="utf-8") as f:
                return self._send(200, {"md": f.read()})
        return self._send(404, {"오류": "없음"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self._ok(q):
            return self._send(403, {"오류": "접속 열쇠 불일치"})
        n = int(self.headers.get("Content-Length") or 0)
        if u.path == "/api/upload/file":   # 본문은 파일 바이트 그대로
            up = STATE["uploads"].get(q.get("id", [""])[0])
            if not up:
                return self._send(404, {"오류": "올리기 묶음이 없습니다"})
            try:
                up.put(q.get("rel", [""])[0], self.rfile, n)
            except ValueError as e:
                self.close_connection = True
                return self._send(400, {"오류": str(e)})
            return self._send(200, {"ok": True, "received": len(up.received)})
        if n > 8 * 1024 * 1024:
            return self._send(413, {"오류": "요청이 너무 큽니다"})
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"오류": "요청 형식"})
        if u.path == "/api/upload/begin":
            j = STATE["job"]
            if j and j.status == "실행 중":
                return self._send(409, {"오류": "이미 변환 중입니다"})
            try:
                up = Upload(data.get("name", ""), data.get("files") or [])
            except (ValueError, OSError) as e:
                return self._send(400, {"오류": str(e)})
            STATE["uploads"] = {up.id: up}
            return self._send(200, {"id": up.id, "have": up.have(), "stage": up.stage, "out": up.out, "out_show": show(up.out)})
        if u.path == "/api/open":
            j = STATE["job"]
            if not j:
                return self._send(404, {"오류": "작업이 없습니다"})
            what = data.get("what")
            target = {"out": j.out, "ledger": os.path.join(j.out, "이관대장.xlsx"),
                      "summary": os.path.join(j.out, "요약.md")}.get(what)
            if not target or not os.path.exists(target):
                return self._send(404, {"오류": "아직 만들어지지 않았습니다"})
            return self._send(200, {"path": show(target), "opened": _open_path(target)})
        if u.path == "/api/export":
            j = STATE["job"]
            if not j:
                return self._send(404, {"오류": "작업이 없습니다"})
            from . import grade
            from .export import export_many
            ai = bool(data.get("ai"))
            outd = os.path.join(j.out, "내보내기_AI폴더" if ai else "내보내기")
            saved = grade.active()
            grade.set_active(grade.Gate(default=None, mode="cli", policy="review", logdir=j.out), tool="export")
            try:
                srcs = [os.path.join(j.src, r) for r in j.only] if j.only else [j.src]
                r = export_many(srcs, outd, ("md", "json", "chunks"), ai, log=lambda *a, **k: None)
            finally:
                grade.set_active(saved, tool="export")
            msg = f"{r['written']}개 문서를 Markdown·JSON·청크로 내보냈습니다." + (f" 확인 대기 {r['waiting']}개는 쓰지 않았습니다(민감정보 확인 후 다시 내보내세요)." if r["waiting"] else "")
            return self._send(200, {"msg": msg, "out": outd, "written": r["written"], "waiting": r["waiting"], "failed": r["failed"], "opened": _open_path(outd)})
        if u.path == "/api/sens/save":
            j = STATE["job"]
            if not j:
                return self._send(404, {"오류": "작업이 없습니다"})
            from . import sens
            store = sens.Store(j.out)
            files = [os.path.join(j.src, r) for r in j.only] if j.only else sens._files(j.src)
            n = sens.apply_decisions(store, data, {sens.sha256_file(f): f for f in files})
            return self._send(200, {"msg": f"{n}개 문서의 확인 결과를 저장했습니다. 이 문서들은 AI 질의에 쓸 수 있는지 다시 판정됩니다."})
        if u.path.startswith("/api/review/"):
            from . import review as rv
            try:
                pth = data.get("path", "")
                if u.path == "/api/review/make":
                    msg = rv.make(data.get("doc", ""))
                    base = os.path.splitext(os.path.basename(data.get("doc", "")))[0]
                    rpath = os.path.join(os.path.dirname(os.path.abspath(data.get("doc", ""))) + "_가림검토", base, "검토.json")
                    return self._send(200, {"msg": msg, "path": rpath})
                elif u.path == "/api/review/decide":
                    msg = rv.decide(pth, data.get("ids"), data.get("decision"), data.get("all"))
                elif u.path == "/api/review/add":
                    msg = rv.add(pth, data.get("text", ""), data.get("kind", "기타"))
                elif u.path == "/api/review/apply":
                    msg = rv.apply(pth, data.get("by", ""))
                else:
                    return self._send(404, {"오류": "없음"})
                return self._send(200, {"msg": msg})
            except SystemExit as e:
                return self._send(400, {"오류": str(e)})
            except Exception as e:
                return self._send(400, {"오류": f"{type(e).__name__}: {e}"})
        if u.path == "/api/start":
            j = STATE["job"]
            if j and j.status == "실행 중":
                return self._send(409, {"오류": "이미 변환 중입니다"})
            jobs = max(1, min(8, int(data.get("jobs", 2) or 2)))
            policy = data.get("policy", "기본")
            if data.get("upload"):   # 끌어놓기: 작업 폴더로 받은 파일만 변환
                up = STATE["uploads"].get(data["upload"])
                if not up:
                    return self._send(404, {"오류": "올리기 묶음이 없습니다"})
                missing = [r for r in up.files if r not in up.received]
                if missing:
                    return self._send(400, {"오류": f"아직 받지 못한 파일 {len(missing)}개"})
                STATE["job"] = Job(up.stage, up.out, jobs, policy, only=list(up.files), dropped=True)
                return self._send(200, {"out": up.out, "out_show": show(up.out)})
            src = os.path.abspath(data.get("src", ""))
            if not os.path.isdir(src):
                return self._send(400, {"오류": "원본 폴더가 없습니다"})
            out = os.path.abspath(data.get("out") or default_out(src))
            if out == src or out.startswith(src + os.sep):
                return self._send(400, {"오류": "결과 폴더는 원본 폴더 밖이어야 합니다(원본 불변)"})
            STATE["job"] = Job(src, out, jobs, policy)
            return self._send(200, {"out": out})
        return self._send(404, {"오류": "없음"})


def serve(port: int = 8765, open_browser: bool = True):
    Handler.token = secrets.token_urlsafe(16)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:   # 그 번호를 다른 프로그램(또는 이미 열린 화면)이 쓰면 빈 번호로 연다
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Handler.port = srv.server_address[1]
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={Handler.token}"
    print(f"HWP AI 어댑터 화면: {url}\n(이 컴퓨터에서만 열립니다. 끝내려면 이 창에서 Ctrl+C)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return srv


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HWP AI 어댑터</title><style>
:root{--bg:#fff;--fg:#1f2328;--mut:#6b7280;--line:#e6e8ec;--acc:#03c75a;--acc2:#02b150;--soft:#f4f6f8;
--pass:#dff5e6;--pass-f:#17794a;--warn:#fff1c7;--warn-f:#8a5b00;--fail:#fde0e0;--fail-f:#b42318;--gray:#eceef2;--gray-f:#475467}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{font:14px/1.5 "Malgun Gothic","맑은 고딕",system-ui,sans-serif;background:var(--bg);color:var(--fg);overflow:hidden}
.screen{display:none;height:100vh;flex-direction:column}
.screen.on{display:flex}
/* top bar */
.top{display:flex;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid var(--line);min-height:56px}
.top .back{background:none;color:var(--fg);border:0;font-size:22px;padding:2px 8px;border-radius:8px;cursor:pointer;line-height:1}
.top .back:hover{background:var(--soft)}
.top .ttl{font-weight:800;font-size:17px}
.top .logo{font-weight:900;color:var(--acc);margin-right:2px}
.top .sp{flex:1}
/* home */
#home{align-items:center;justify-content:center;padding:24px;gap:0}
.hero{text-align:center;margin-bottom:26px}
.hero .big{font-size:44px;font-weight:900;letter-spacing:-1px;color:var(--fg)}
.hero .big b{color:var(--acc)}
.hero p{margin:8px 0 0;color:var(--mut);font-size:15px}
.start{display:flex;align-items:center;justify-content:space-between;width:min(560px,92vw);padding:18px 22px;border:1px solid var(--line);border-radius:999px;box-shadow:0 1px 6px rgba(0,0,0,.08);cursor:pointer;background:#fff;font-size:16px;color:var(--mut);font-family:inherit;text-align:left}
.start:hover{box-shadow:0 2px 12px rgba(0,0,0,.14)}
.start b{color:var(--acc);font-weight:800}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;width:min(640px,92vw);margin-top:34px}
.tile{border:0;background:none;cursor:pointer;text-align:center;font-family:inherit;color:var(--fg);padding:14px 6px;border-radius:16px}
.tile:hover{background:var(--soft)}
.tile .ic{width:64px;height:64px;margin:0 auto 10px;border-radius:20px;display:grid;place-items:center;font-size:28px;background:#eefbf3}
.tile .nm{font-weight:800;font-size:15px}
.tile .st{font-size:12px;color:var(--mut);margin-top:3px;min-height:18px}
.tile .st.hot{color:var(--acc2);font-weight:700}
.foot{position:absolute;bottom:14px;left:0;right:0;text-align:center;color:var(--mut);font-size:12px}
/* work area */
.work{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;padding:16px 20px;overflow:hidden}
.pane{min-height:0;display:flex;flex-direction:column;border:1px solid var(--line);border-radius:14px;overflow:hidden}
.pane .h{padding:12px 16px;border-bottom:1px solid var(--line);font-weight:800;display:flex;align-items:center;gap:8px}
.pane .b{padding:14px 16px;flex:1;min-height:0;display:flex;flex-direction:column;gap:10px;overflow:hidden}
.num{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--acc);color:#fff;font-size:12px;font-weight:800}
.path{display:flex;gap:8px;align-items:center}
input[type=text],select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font:inherit;background:#fbfcfe;min-width:0}
input[type=text]:focus,select:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px #d9f7e5}
button{white-space:nowrap;background:var(--acc);color:#fff;border:0;border-radius:10px;padding:10px 16px;font:inherit;font-weight:700;cursor:pointer}
button:hover{background:var(--acc2)}
button.sub{background:#fff;color:#02823b;border:1px solid #cfeee0}button.sub:hover{background:#f1faf5}
button.big{padding:14px 20px;font-size:15px;border-radius:14px}
.mut{color:var(--mut);font-size:12.5px}
.list{flex:1;min-height:0;overflow:auto;border:1px solid var(--line);border-radius:10px}
.list .it{padding:9px 12px;cursor:pointer;border-bottom:1px solid #f1f3f6;display:flex;gap:8px;align-items:center}
.list .it:last-child{border-bottom:0}
.list .it:hover{background:#f1faf5}
.list .it.sel{background:#e3f7ec;font-weight:700}
.list .empty{padding:24px;text-align:center;color:var(--mut)}
.bar{height:10px;background:var(--gray);border-radius:999px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--acc2),var(--acc));width:0;transition:width .3s}
.chips{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.chips span{display:block;padding:12px 8px;border-radius:12px;text-align:center;font-weight:800;font-size:22px}
.chips span::before{content:attr(data-k);display:block;font-size:12px;font-weight:600;opacity:.85;margin-bottom:2px}
.chips .pass{background:var(--pass);color:var(--pass-f)}.chips .warn{background:var(--warn);color:var(--warn-f)}.chips .fail{background:var(--fail);color:var(--fail-f)}.chips .gray{background:var(--gray);color:var(--gray-f)}
.filters{display:flex;gap:8px;flex-wrap:wrap}
.filters button{background:#fff;color:var(--fg);border:1px solid var(--line)}
.filters button.on{background:var(--fg);color:#fff;border-color:var(--fg)}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
th,td{border-bottom:1px solid #eef1f6;padding:9px 10px;text-align:left;vertical-align:top}
th{background:#fafbfc;position:sticky;top:0;color:var(--mut);font-weight:700;font-size:12.5px;z-index:1}
td.v{font-weight:800}
tr.PASS td.v{color:var(--pass-f)}tr.WARN td.v{color:var(--warn-f)}tr.FAIL td.v{color:var(--fail-f)}tr.GRAY td.v{color:var(--gray-f)}
tbody tr{cursor:pointer}tbody tr:hover{background:#f8fdf9}
.tbox{flex:1;min-height:0;overflow:auto;border:1px solid var(--line);border-radius:12px}
pre{flex:1;min-height:0;margin:0;white-space:pre-wrap;font:13px/1.65 Consolas,"Malgun Gothic",monospace;background:#fbfcfe;border:1px solid var(--line);padding:16px;border-radius:12px;overflow:auto}
.steps{display:flex;gap:8px;flex-wrap:wrap}
.steps span{padding:6px 12px;border-radius:999px;background:var(--soft);font-size:12.5px;color:var(--mut);font-weight:700}
.steps span.on{background:#e3f7ec;color:#02823b}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.guide{display:grid;gap:12px;overflow:auto}
.guide div{border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.guide h3{margin:0 0 6px;font-size:15px}
.guide p{margin:0;color:#374151}
.msg{font-size:13px;min-height:18px}
.ok{color:#02823b}.bad{color:#b42318}
.dropwrap{flex:1;overflow:auto;display:flex;flex-direction:column;align-items:center;padding:18px 20px 28px;gap:16px}
.drop{width:min(860px,94vw);min-height:230px;border:3px dashed #9fdcb9;border-radius:24px;background:#f6fdf9;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;text-align:center;padding:24px;cursor:pointer;transition:background .15s,border-color .15s}
.drop:hover{background:#eefbf3}
.drop .dz-ic{font-size:54px;line-height:1}
.drop .dz-t{font-size:26px;font-weight:900;letter-spacing:-.5px}
.drop .dz-s{font-size:15px;color:var(--mut)}
body.dragging .drop{background:#dff5e8;border-color:var(--acc)}
#overlay{display:none;position:fixed;inset:0;background:rgba(3,199,90,.12);border:6px solid var(--acc);z-index:50;align-items:center;justify-content:center;font-size:30px;font-weight:900;color:#02823b;pointer-events:none}
body.dragging #overlay{display:flex}
#overlay span{background:#fff;padding:20px 34px;border-radius:20px;box-shadow:0 6px 30px rgba(0,0,0,.15)}
.panel{width:min(860px,94vw);display:flex;flex-direction:column;gap:12px}
.seg{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:15px}
.seg label{display:flex;align-items:center;gap:6px;padding:9px 14px;border:1px solid var(--line);border-radius:999px;cursor:pointer;font-weight:700}
.seg input{accent-color:var(--acc);width:18px;height:18px}
.seg label:has(input:checked){background:#e3f7ec;border-color:#8fdcae;color:#02823b}
.pv{font-size:17px;padding:14px 18px;border-radius:14px;background:var(--soft);display:none}
.pv b{font-size:20px}
.acts{display:flex;gap:12px;flex-wrap:wrap}
.acts button{font-size:18px;padding:16px 26px;border-radius:14px}
.acts button:disabled{background:#c9d2cc;cursor:not-allowed}
#lprog{font-size:16px;font-weight:700}
.live{max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:12px;display:none}
.live td{font-size:14px}
.links{display:flex;gap:16px;font-size:14px}
.links a{color:var(--mut);text-decoration:none;font-weight:700;cursor:pointer}.links a:hover{color:var(--acc2)}
.big-note{font-size:14px;color:var(--mut)}
@media(max-width:820px){body{overflow:auto}.screen{height:auto;min-height:100vh}.work{grid-template-columns:1fr;overflow:visible}.pane{min-height:340px}.tiles{grid-template-columns:repeat(2,1fr)}.hero .big{font-size:34px}.chips{grid-template-columns:repeat(2,1fr)}.foot{position:static;padding:20px}}
</style></head><body>

<!-- 처음 화면 = 끌어놓기 -->
<div id="overlay"><span>놓으면 HWP 목록을 만듭니다</span></div>
<div class="screen on" id="home">
  <div class="top"><span class="ttl"><span class="logo">HWP</span> AI 어댑터</span><span class="sp"></span>
    <nav class="links"><a onclick="go('results')">결과 표</a><a onclick="go('convert')">경로로 고르기</a><a onclick="go('review')">가림 검토</a><a onclick="go('help')">사용법</a></nav></div>
  <div class="dropwrap">
    <div class="drop" id="drop" onclick="document.getElementById('pick').click()">
      <div class="dz-ic">📂</div>
      <div class="dz-t">HWP 폴더를 여기에 끌어다 놓으세요</div>
      <div class="dz-s">하위 폴더까지 · 폴더·파일 여러 개 한꺼번에 · .hwp/.hwpx 만 변환 · 원본은 바뀌지 않습니다</div>
    </div>
    <input type="file" id="pick" webkitdirectory directory multiple style="display:none">
    <div class="panel">
      <div class="seg"><b>보안등급</b>
        <label><input type="radio" name="pol" value="기본" checked>기본</label>
        <label><input type="radio" name="pol" value="공개">공개 자료</label>
        <label><input type="radio" name="pol" value="엄격">엄격</label>
        <span class="big-note" id="polnote"></span></div>
      <div class="pv" id="pv"></div>
      <div class="acts" id="acts1"><button class="sub" onclick="document.getElementById('pick').click()">폴더 선택</button><button id="go" onclick="dropStart()" disabled>변환 시작</button></div>
      <div class="acts" id="acts2" style="display:none"><button onclick="openIt('out')">결과 폴더 열기</button><button class="sub" onclick="openIt('ledger')">이관대장 열기</button><button class="sub" id="failbtn" onclick="toggleFail()">FAIL만 보기</button><button class="sub" id="sensbtn" onclick="window.open('/sens?t='+T,'_blank')">민감정보 확인</button><button class="sub" onclick="exportIt(false)">Markdown·JSON 내보내기</button><button class="sub" onclick="exportIt(true)">AI 폴더용 내보내기(확인 끝난 것만)</button></div>
      <div class="bar"><i id="lbar"></i></div>
      <div id="lprog" class="mut">폴더를 놓거나 「폴더 선택」을 누르세요. 결과는 __WORK__ 안 「〈폴더〉_hwpx변환」에 생깁니다.</div>
      <div class="chips" id="lchips"></div>
      <div class="live" id="live"><table><thead><tr><th>원본</th><th>판정</th><th>점수</th><th>이유</th></tr></thead><tbody id="ltb"></tbody></table></div>
      <div class="big-note" id="lout"></div>
    </div>
  </div>
</div>

<!-- 변환 -->
<div class="screen" id="convert">
  <div class="top"><button class="back" onclick="go('home')" aria-label="처음으로">‹</button><span class="ttl"><span class="logo">HWP</span>변환</span><span class="sp"></span><span class="mut">원본은 바꾸지 않습니다</span></div>
  <div class="work">
    <div class="pane">
      <div class="h"><span class="num">1</span>원본 폴더 고르기</div>
      <div class="b">
        <div class="path"><input id="src" type="text" placeholder="폴더를 누르거나 경로를 적으세요"><button class="sub" onclick="ls('cv', document.getElementById('src').value)">열기</button></div>
        <div class="row"><button class="sub" onclick="up('cv')">위 폴더</button><button class="sub" onclick="useHere()">이 폴더 선택</button><span class="mut" id="cv-n"></span></div>
        <div class="list" id="cv-list"></div>
      </div>
    </div>
    <div class="pane">
      <div class="h"><span class="num">2</span>변환 시작</div>
      <div class="b">
        <div class="mut">결과 폴더 (비우면 「원본폴더_hwpx변환」)</div><div class="mut" id="cv-pv"></div>
        <input id="out" type="text">
        <div class="seg"><b>보안등급</b><label><input type="radio" name="pol2" value="기본" checked>기본</label><label><input type="radio" name="pol2" value="공개">공개 자료</label><label><input type="radio" name="pol2" value="엄격">엄격</label></div>
        <div class="row"><span class="mut">동시 변환 수</span><input id="jobs" type="text" value="2" style="width:70px"><button class="big" onclick="start()">변환 시작</button></div>
        <div class="bar"><i id="bar"></i></div>
        <div class="row"><span id="prog" class="mut">대기</span></div>
        <div class="chips" id="chips"></div>
        <div class="mut" id="outs"></div>
        <div class="row"><button class="sub" onclick="go('results')">결과 자세히 보기 →</button></div>
      </div>
    </div>
  </div>
</div>

<!-- 결과 -->
<div class="screen" id="results">
  <div class="top"><button class="back" onclick="go('home')" aria-label="처음으로">‹</button><span class="ttl">결과</span><span class="sp"></span><span class="mut" id="rs-sum"></span></div>
  <div class="work" style="grid-template-columns:minmax(0,1fr)">
    <div class="pane">
      <div class="b" style="flex:1">
        <div class="filters" id="filters">
          <button class="on" data-f="전체">전체</button><button data-f="PASS">통과 PASS</button><button data-f="WARN">확인 WARN</button><button data-f="FAIL">불일치 FAIL</button><button data-f="실패">실패·격리</button>
        </div>
        <div class="tbox"><table><thead><tr><th>원본</th><th>상태</th><th>판정</th><th>점수</th><th>이유</th></tr></thead><tbody id="tb"><tr><td colspan="5" class="mut" style="text-align:center;padding:30px">아직 변환 결과가 없습니다. 변환을 먼저 시작하세요.</td></tr></tbody></table></div>
        <div class="mut">행을 누르면 검증서가 열립니다.</div>
      </div>
    </div>
  </div>
</div>

<!-- 검증서 -->
<div class="screen" id="audit">
  <div class="top"><button class="back" onclick="back()" aria-label="뒤로">‹</button><span class="ttl">검증서</span><span class="sp"></span><span class="mut" id="au-name"></span></div>
  <div class="work" style="grid-template-columns:minmax(0,1fr)"><pre id="auditbox">검증서를 불러오는 중…</pre></div>
</div>

<!-- 가림 검토 -->
<div class="screen" id="review">
  <div class="top"><button class="back" onclick="go('home')" aria-label="처음으로">‹</button><span class="ttl">개인정보 가림 검토</span><span class="sp"></span><span class="mut">사람이 확인해야 확정본이 만들어집니다</span></div>
  <div class="work">
    <div class="pane">
      <div class="h"><span class="num">1</span>문서 고르기</div>
      <div class="b">
        <div class="path"><input id="rsrc" type="text" placeholder="폴더를 누르거나 경로를 적으세요"><button class="sub" onclick="ls('rv', document.getElementById('rsrc').value)">열기</button></div>
        <div class="row"><button class="sub" onclick="up('rv')">위 폴더</button><span class="mut" id="rv-n"></span></div>
        <div class="list" id="rv-list"></div>
        <div class="row"><span class="mut">검토할 문서:</span><b id="rdoc">아직 없음</b></div>
        <div class="row"><button class="big" onclick="rMake()">검토 목록 만들기</button><span class="msg" id="rmsg"></span></div>
      </div>
    </div>
    <div class="pane">
      <div class="h"><span class="num">2</span>후보 확인 · 확정<span class="mut" id="rcount" style="margin-left:auto;font-weight:600"></span></div>
      <div class="b">
        <div class="row"><button class="sub" onclick="rAll('가림')">모두 가림</button><button class="sub" onclick="rAll('남김')">모두 남김</button></div>
        <div class="tbox"><table><thead><tr><th style="width:44px">번호</th><th>종류</th><th>글자</th><th>횟수</th><th>주변 글</th><th style="width:150px">결정</th></tr></thead><tbody id="rtb"><tr><td colspan="6" class="mut" style="text-align:center;padding:24px">검토 목록이 여기에 나옵니다</td></tr></tbody></table></div>
        <div class="row"><span class="mut">놓친 항목 추가:</span><input id="addtext" type="text" placeholder="원문 글자 그대로" style="flex:2;min-width:160px"><select id="addkind" style="width:auto"><option>성명</option><option>전화</option><option>이메일</option><option>주소</option><option>주민등록번호</option><option>계좌번호</option><option>기타</option></select><button onclick="rAdd()">추가</button></div>
        <div class="row" style="padding-top:10px;border-top:1px solid var(--line)"><span class="mut">확정자 이름:</span><input id="by" type="text" style="width:160px"><button onclick="rApply()">확정본 만들기</button><span class="msg" id="rmsg2"></span></div>
      </div>
    </div>
  </div>
</div>

<!-- 사용법 -->
<div class="screen" id="help">
  <div class="top"><button class="back" onclick="go('home')" aria-label="처음으로">‹</button><span class="ttl">사용법</span></div>
  <div class="work" style="grid-template-columns:minmax(0,1fr)">
    <div class="guide" style="overflow:auto">
      <div><h3>① 끌어놓기</h3><p>처음 화면에 HWP 폴더(하위 폴더 포함)나 파일 여러 개를 끌어다 놓고 「변환 시작」. 끌어놓기가 안 되는 브라우저는 「폴더 선택」. 받은 HWP·HWPX만 작업 폴더로 복사해 변환하고, 결과는 「〈폴더〉_hwpx변환」에 생깁니다. 같은 폴더를 다시 놓으면 끝난 파일은 건너뛰고 이어서 합니다.</p></div><div><h3>보안등급</h3><p>기본: 등급이 없는 문서에서 휴대전화·주민번호·계좌·이메일·성명 표기가 나오면 변환은 하고 이관대장에 「확인 필요」로 적습니다. 사람이 「가림 검토」에서 확인하기 전에는 AI(질의·MCP·AI용 내보내기)로 보내지 않습니다. 공개 자료: 사람이 공개 자료라고 판단한 묶음 — 개인정보 점검을 하지 않습니다. 엄격: 개인정보 꼴(유선·070 번호 포함)이 나오면 변환하지 않습니다.</p></div><div><h3>경로로 고르기</h3><p>복사 없이 원본 옆 「원본폴더_hwpx변환」에 쓰려면 위쪽 「경로로 고르기」에서 폴더를 골라 「이 폴더 선택」 → 「변환 시작」.</p></div>
      <div><h3>② 결과</h3><p>PASS는 검증을 통과, WARN은 사람이 확인, FAIL은 원본과 차이가 있습니다. 행을 누르면 검증서가 열립니다.</p></div>
      <div><h3>③ 가림 검토</h3><p>주민번호·전화·이메일 등 후보를 사람이 「가림/남김」으로 정합니다. 놓친 글자는 직접 추가할 수 있고, 확정본은 확정자 이름을 적어야 만들어집니다.</p></div>
      <div><h3>탐색기에서 바로</h3><p>폴더나 파일을 hwpai.bat 아이콘 위에 놓으면 화면 없이 바로 변환하고, 끝나면 결과 폴더와 요약을 엽니다.</p></div>
    </div>
  </div>
</div>

<script>
const T="__TOKEN__";
const api=(p,o)=>fetch(p+(p.includes("?")?"&":"?")+"t="+T,o).then(r=>r.json());
const enc=encodeURIComponent;
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
const SCREENS=["home","convert","results","audit","review","help"];
let hist=["home"];
function go(s,push=true){SCREENS.forEach(x=>document.getElementById(x).classList.toggle("on",x===s));
 if(push&&hist[hist.length-1]!==s)hist.push(s);
 if(s==="results")drawResults();
 if(s==="convert"&&!cur.cv)ls("cv","");
 if(s==="review"&&!cur.rv)ls("rv","");
 
 window.scrollTo(0,0)}
function back(){hist.pop();const prev=hist[hist.length-1]||"home";hist.pop();go(prev)}

/* 폴더 탐색 (변환·가림 검토 두 곳에서 같이 쓴다) */
const cur={cv:"",rv:""},par={cv:"",rv:""};
const SEP=p=>p.includes("\\")?"\\":"/";
function join(d,n){if(!d)return n;return d.replace(/[\\/]$/,"")+SEP(d)+n}
function ls(pre,p){api("/api/ls?p="+enc(p||"")).then(d=>{
 if(d["오류"]){alert(d["오류"]);return}
 cur[pre]=d.path||"";par[pre]=d.parent||"";
 const inp=document.getElementById(pre==="cv"?"src":"rsrc");inp.value=cur[pre];
 document.getElementById(pre+"-n").textContent=cur[pre]?("HWP·HWPX "+d.hwp+"개"):"드라이브";
 const list=document.getElementById(pre+"-list");
 const dirs=(d.dirs||[]).map(n=>`<div class="it" data-d="${esc(n)}">📁 ${esc(n)}</div>`).join("");
 const files=pre==="rv"?(d.files||[]).map(n=>`<div class="it" data-f="${esc(n)}">📄 ${esc(n)}</div>`).join(""):"";
 list.innerHTML=(dirs+files)||'<div class="empty">폴더가 비어 있습니다</div>';
});}
function up(pre){if(par[pre]&&par[pre]!==cur[pre])ls(pre,par[pre]);else ls(pre,"")}
function clickList(e,pre){const t=e.target.closest(".it");if(!t)return;
 if(t.dataset.d!==undefined)return ls(pre,join(cur[pre],t.dataset.d));
 if(t.dataset.f!==undefined){document.querySelectorAll("#rv-list .it").forEach(x=>x.classList.remove("sel"));t.classList.add("sel");
  rDoc=join(cur.rv,t.dataset.f);document.getElementById("rdoc").textContent=t.dataset.f;rShow("「검토 목록 만들기」를 누르세요",true)}}
document.getElementById("cv-list").onclick=e=>clickList(e,"cv");
document.getElementById("rv-list").onclick=e=>clickList(e,"rv");
function useHere(){document.getElementById("src").value=cur.cv;api("/api/preview?p="+enc(cur.cv)).then(d=>{document.getElementById("cv-pv").textContent=d["오류"]?"":`HWP·HWPX ${d.hwp}개 · ${mb(d.bytes)} · 하위 폴더 ${d.subdirs}개 · 건너뜀 ${d.skipped}개 → ${d.out}`})}
const pol=n=>(document.querySelector(`input[name=${n}]:checked`)||{}).value||"기본";
function mb(b){return b>=1048576?(b/1048576).toFixed(1)+"MB":Math.max(1,Math.round(b/1024))+"KB"}

/* 변환 */
function start(){api("/api/start",{method:"POST",body:JSON.stringify({src:document.getElementById("src").value,out:document.getElementById("out").value,jobs:+document.getElementById("jobs").value||2,policy:pol("pol2")})})
 .then(d=>{if(d["오류"]){alert(d["오류"]);return}document.getElementById("outs").textContent="결과 폴더: "+d.out;rows=[];poll()})}
function cls(r){return ["변환실패","격리","건너뜀","등급차단"].includes(r["상태"])&&!r["판정"]?"GRAY":(r["판정"]||"GRAY")}
let rows=[],filt="전체",poller=null;
function rowsFiltered(){return rows.filter(r=>{
 if(filt==="전체")return true;
 if(filt==="실패")return ["변환실패","격리"].includes(r["상태"]);
 return r["판정"]===filt})}
function drawResults(){
 const body=rowsFiltered();
 document.getElementById("rs-sum").textContent=rows.length?`전체 ${rows.length}개`:"";
 document.getElementById("tb").innerHTML=body.length?body.map(r=>`<tr class="${cls(r)}" data-a="${esc(r["검증서"])}"><td>${esc(r["원본"])}</td><td>${esc(r["상태"])}</td><td class="v">${esc(r["판정"])}</td><td>${esc(r["검증점수"])}</td><td>${esc((r["판정_이유"]||"").slice(0,160))}</td></tr>`).join("")
  :'<tr><td colspan="5" class="mut" style="text-align:center;padding:30px">해당하는 결과가 없습니다</td></tr>';
}
document.getElementById("filters").onclick=e=>{const b=e.target.closest("button");if(!b)return;filt=b.dataset.f;
 document.querySelectorAll("#filters button").forEach(x=>x.classList.toggle("on",x===b));drawResults()};
document.getElementById("tb").onclick=e=>{const tr=e.target.closest("tr");if(!tr||!tr.dataset.a)return;
 const a=tr.dataset.a;document.getElementById("au-name").textContent=tr.cells[0].textContent;
 if(!a.endsWith(".md")){document.getElementById("auditbox").textContent="검증서가 없습니다(변환하지 않았거나 격리된 파일)";go("audit");return}
 go("audit");
 api("/api/audit?p="+enc(a)).then(d=>document.getElementById("auditbox").textContent=d.md||d["오류"])};
function counts(){const c={PASS:0,WARN:0,FAIL:0,"실패·격리":0,"등급차단":0};
 rows.forEach(r=>{if(r["상태"]==="변환완료"&&r["판정"]in c)c[r["판정"]]++;else if(["변환실패","격리"].includes(r["상태"]))c["실패·격리"]++;else if(r["상태"]==="등급차단")c["등급차단"]++});return c}
function chipsHTML(c){return `<span class="pass" data-k="통과 PASS">${c.PASS}</span><span class="warn" data-k="확인 WARN">${c.WARN}</span><span class="fail" data-k="불일치 FAIL">${c.FAIL}</span><span class="gray" data-k="차단·실패">${c["등급차단"]+c["실패·격리"]}</span>`}
function eta(d){if(!d.total||!d.done||d.status!=="실행 중")return "";const rem=d.elapsed/d.done*(d.total-d.done);return " · 남은 시간 약 "+(rem<60?Math.ceil(rem)+"초":Math.ceil(rem/60)+"분")}
let pollT=null;
function poll(){clearTimeout(pollT);api("/api/status?since="+rows.length).then(d=>{if(d.status==="대기")return;rows=rows.concat(d.rows||[]);const pc=d.total?Math.round(100*d.done/d.total):(d.status==="완료"?100:0);
 for(const id of ["bar","lbar"])document.getElementById(id).style.width=pc+"%";
 const txt=(d.status==="실행 중"?"변환 중":d.status)+" · "+(d.done||0)+"/"+(d.total||0)+eta(d)+(d.error?" · "+d.error:"");
 document.getElementById("prog").textContent=txt;
 const c=counts();document.getElementById("chips").innerHTML=chipsHTML(c);
 if(d.status==="완료")document.getElementById("outs").textContent="결과 폴더: "+d.out+" · 엑셀 보고서: 이관대장.xlsx · 요약: 요약.md";
 if(d.dropped||document.getElementById("home").classList.contains("on")){
  document.getElementById("lprog").textContent=txt+(d.status==="완료"?` · ${d.elapsed}초`:"");
  document.getElementById("lchips").innerHTML=chipsHTML(c);drawLive();
  if(d.status==="완료"){document.getElementById("acts1").style.display="none";document.getElementById("acts2").style.display="flex";
   document.getElementById("lout").textContent="결과 폴더: "+(d.out_show||d.out)+" · 이관대장.xlsx 「사람확인목록」 시트에 WARN·FAIL이 모입니다. 다른 폴더를 놓으면 새로 시작합니다."}}
 drawResults();refreshHome(d);
 if(d.status==="실행 중")pollT=setTimeout(poll,700)})}

/* 끌어놓기 */
let picked=[],pickName="",failOnly=false,busy=false;
const isHwp=n=>/\.(hwp|hwpx)$/i.test(n);
async function walk(entry,prefix,out){
 if(entry.isFile){const f=await new Promise((res,rej)=>entry.file(res,rej));out.push({file:f,rel:prefix+entry.name});return}
 if(entry.isDirectory){const rd=entry.createReader();let b;do{b=await new Promise((res,rej)=>rd.readEntries(res,rej));for(const c of b)await walk(c,prefix+entry.name+"/",out)}while(b.length)}}
async function fromDrop(dt){
 const items=[...(dt.items||[])].filter(i=>i.kind==="file");
 const ents=items.map(i=>i.webkitGetAsEntry?i.webkitGetAsEntry():null);   // 비동기 전에 먼저 받아 둔다
 const out=[];
 if(!ents.length||ents.every(e=>!e)){for(const f of dt.files)out.push({file:f,rel:f.name});return {list:out,tops:[...dt.files].map(f=>({name:f.name,dir:false}))}}
 for(const e of ents)if(e)await walk(e,"",out);
 return {list:out,tops:ents.filter(Boolean).map(e=>({name:e.name,dir:e.isDirectory}))};
}
function setPicked(list,tops){
 if(busy)return;
 let name="끌어놓은_파일",strip="";
 if(tops.length===1&&tops[0].dir){name=tops[0].name;strip=name+"/"}
 const hw=list.filter(x=>isHwp(x.rel)),skip=list.length-hw.length;
 picked=hw.map(x=>({file:x.file,rel:strip&&x.rel.startsWith(strip)?x.rel.slice(strip.length):x.rel}));pickName=name;
 const dirs=new Set(picked.map(x=>x.rel.includes("/")?x.rel.slice(0,x.rel.lastIndexOf("/")):"").filter(Boolean));
 const bytes=picked.reduce((a,x)=>a+x.file.size,0);
 const pv=document.getElementById("pv");pv.style.display="block";
 pv.innerHTML=`<b>${esc(name)}</b> · HWP·HWPX <b>${picked.length}</b>개 · ${mb(bytes)} · 하위 폴더 ${dirs.size}개 · 건너뜀 ${skip}개 (HWP 아님)`;
 document.getElementById("go").disabled=!picked.length;
 document.getElementById("acts1").style.display="flex";document.getElementById("acts2").style.display="none";
 document.getElementById("lprog").textContent=picked.length?"「변환 시작」을 누르세요":"HWP·HWPX 파일이 없습니다";
 document.getElementById("lchips").innerHTML="";document.getElementById("ltb").innerHTML="";document.getElementById("live").style.display="none";document.getElementById("lout").textContent="";
 for(const id of ["lbar"])document.getElementById(id).style.width="0";
}
let dragDepth=0;
addEventListener("dragenter",e=>{if([...(e.dataTransfer?.types||[])].includes("Files")){e.preventDefault();dragDepth++;document.body.classList.add("dragging")}});
addEventListener("dragover",e=>{e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect="copy"});
addEventListener("dragleave",e=>{if(--dragDepth<=0){dragDepth=0;document.body.classList.remove("dragging")}});
addEventListener("drop",async e=>{e.preventDefault();dragDepth=0;document.body.classList.remove("dragging");
 if(!e.dataTransfer)return;go("home");const r=await fromDrop(e.dataTransfer);setPicked(r.list,r.tops)});
document.getElementById("pick").onchange=e=>{const fs=[...e.target.files];if(!fs.length)return;
 const top=(fs[0].webkitRelativePath||"").split("/")[0];
 setPicked(fs.map(f=>({file:f,rel:f.webkitRelativePath||f.name})),top?[{name:top,dir:true}]:fs.map(f=>({name:f.name,dir:false})));e.target.value=""};
async function dropStart(){
 if(!picked.length||busy)return;busy=true;document.getElementById("go").disabled=true;
 const P=document.getElementById("lprog");
 try{
  const b=await api("/api/upload/begin",{method:"POST",body:JSON.stringify({name:pickName,files:picked.map(x=>({rel:x.rel,size:x.file.size,mtime:x.file.lastModified}))})});
  if(b["오류"])throw new Error(b["오류"]);
  const have=new Set(b.have),todo=picked.filter(x=>!have.has(x.rel));let i=0;
  for(const x of todo){i++;P.textContent=`작업 폴더로 옮기는 중 ${i}/${todo.length}`+(have.size?` (이미 받은 ${have.size}개 건너뜀)`:"");
   document.getElementById("lbar").style.width=Math.round(100*i/todo.length)+"%";
   const r=await fetch(`/api/upload/file?t=${T}&id=${b.id}&rel=${enc(x.rel)}`,{method:"POST",body:x.file}).then(r=>r.json());
   if(r["오류"])throw new Error(x.rel+": "+r["오류"])}
  const s=await api("/api/start",{method:"POST",body:JSON.stringify({upload:b.id,policy:pol("pol"),jobs:2})});
  if(s["오류"])throw new Error(s["오류"]);
  rows=[];failOnly=false;document.getElementById("failbtn").textContent="FAIL만 보기";
  document.getElementById("live").style.display="block";document.getElementById("lout").textContent="결과 폴더: "+(s.out_show||s.out);
  poll();
 }catch(err){P.textContent="오류: "+err.message;document.getElementById("go").disabled=false}
 busy=false}
function liveRows(){return failOnly?rows.filter(r=>r["판정"]==="FAIL"||["변환실패","격리"].includes(r["상태"])):rows}
function drawLive(){const rs=liveRows();document.getElementById("live").style.display="block";
 document.getElementById("ltb").innerHTML=rs.length?rs.map(r=>`<tr class="${cls(r)}" data-a="${esc(r["검증서"])}"><td>${esc(r["원본"])}</td><td class="v">${esc(r["판정"]||r["상태"])}</td><td>${esc(r["검증점수"])}</td><td>${esc((r["판정_이유"]||"").slice(0,120))}</td></tr>`).join("")
  :`<tr><td colspan="4" class="mut" style="text-align:center;padding:18px">${failOnly?"FAIL이 없습니다":"아직 없음"}</td></tr>`}
function toggleFail(){failOnly=!failOnly;document.getElementById("failbtn").textContent=failOnly?"전체 보기":"FAIL만 보기";drawLive()}
document.getElementById("ltb").onclick=e=>document.getElementById("tb").onclick(e);
function exportIt(ai){api("/api/export",{method:"POST",body:JSON.stringify({ai:ai})}).then(d=>alert(d["오류"]||d.msg))}
function openIt(w){api("/api/open",{method:"POST",body:JSON.stringify({what:w})}).then(d=>{if(d["오류"]){alert(d["오류"]);return}
 if(!d.opened)document.getElementById("lout").textContent="열 위치: "+d.path})}
const POLN={"기본":"개인정보 꼴이 나오면 변환은 하고 「확인 필요」로 표시 — 확인 전에는 AI로 안 보냄","공개":"공개 자료로 지정 — 개인정보 점검 안 함","엄격":"개인정보 꼴(유선·070 포함)이 나오면 변환하지 않음"};
document.querySelectorAll("input[name=pol]").forEach(x=>x.onchange=()=>document.getElementById("polnote").textContent=POLN[pol("pol")]);
document.getElementById("polnote").textContent=POLN["기본"];

/* 처음 화면의 타일 상태 */
function refreshHome(d){}

/* 가림 검토 */
let rDoc="",rFile="";
function rShow(m,ok){const e=document.getElementById("rmsg");e.textContent=m;e.className="msg "+(ok?"ok":"bad")}
function rShow2(m,ok){const e=document.getElementById("rmsg2");e.textContent=m;e.className="msg "+(ok?"ok":"bad")}
function rLoad(){if(!rFile)return;api("/api/review?p="+enc(rFile)).then(d=>{if(d["오류"]){rShow2(d["오류"],false);return}drawR(d)})}
function drawR(d){const items=d.items||[];
 document.getElementById("rcount").textContent=`후보 ${items.length}개 · 정한 항목 ${items.filter(x=>x.decision).length}개`;
 document.getElementById("rtb").innerHTML=items.length?items.map(x=>`<tr class="${x.decision==="가림"?"FAIL":x.decision==="남김"?"PASS":"GRAY"}"><td>${x.id}</td><td>${esc(x.kind)}${x.source?' <span class="mut">('+esc(x.source)+')</span>':''}</td><td><b>${esc(x.text)}</b></td><td>${x.count}</td><td class="mut">…${esc(x.context)}…</td><td><button class="sub" style="${x.decision==="가림"?"background:#fde0e0;color:#b42318;border-color:#f5b5b5":""}" onclick="rOne(${x.id},'가림')">가림</button> <button class="sub" style="${x.decision==="남김"?"background:#eefbf3;color:#02823b;border-color:#8fdcae":""}" onclick="rOne(${x.id},'남김')">남김</button></td></tr>`).join(""):'<tr><td colspan="6" class="mut" style="text-align:center;padding:24px">후보가 없습니다. 아래에서 직접 추가할 수 있습니다.</td></tr>'}
function rOne(id,dec){api("/api/review/decide",{method:"POST",body:JSON.stringify({path:rFile,ids:[id],decision:dec})}).then(d=>{d["오류"]?rShow2(d["오류"],false):rLoad()})}
function rAll(dec){if(!rFile){rShow2("먼저 검토 목록을 만드세요",false);return}api("/api/review/decide",{method:"POST",body:JSON.stringify({path:rFile,all:dec})}).then(d=>{d["오류"]?rShow2(d["오류"],false):rLoad()})}
function rMake(){if(!rDoc){rShow("먼저 왼쪽 목록에서 HWP 파일을 고르세요",false);return}
 api("/api/review/make",{method:"POST",body:JSON.stringify({doc:rDoc})}).then(d=>{if(d["오류"]){rShow(d["오류"],false);return}
 rFile=d.path;rShow(d.msg.split("\n")[0],true);rLoad()})}
function rAdd(){const t=document.getElementById("addtext").value;if(!rFile){rShow2("먼저 검토 목록을 만드세요",false);return}
 api("/api/review/add",{method:"POST",body:JSON.stringify({path:rFile,text:t,kind:document.getElementById("addkind").value})}).then(d=>{if(d["오류"]){rShow2(d["오류"],false);return}
 document.getElementById("addtext").value="";rShow2(d.msg,true);rLoad()})}
function rApply(){const by=document.getElementById("by").value.trim();if(!by){rShow2("확정자 이름을 적으세요",false);return}
 api("/api/review/apply",{method:"POST",body:JSON.stringify({path:rFile,by:by})}).then(d=>{d["오류"]?rShow2(d["오류"],false):rShow2(d.msg.replace(/\n/g," · "),true)})}

poll();
</script></body></html>
"""
