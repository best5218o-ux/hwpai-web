"""HWP→HWPX 변환 엔진 어댑터.

hwpai 는 변환 엔진을 새로 만들지 않는다. 검증된 공개 엔진을 부품으로 끼우고,
우리가 만드는 것은 그 앞뒤 — 일괄 운영(batch.py)과 파일별 검증서(audit.py) — 이다.

엔진(우선순위 순)
  rhwp-wasm  @rhwp/core(MIT, Edward Kim) 의 WebAssembly 판을 Node.js 로 돌린다.
             설치: Node.js 18 이상 하나. 엔진 파일은 vendor/rhwp-core/ 에 동봉(rhwp 소스 빌드 0.9.0-local, 약 34MB).
  rhwp-cli   rhwp 네이티브 실행 파일(`rhwp export-hwpx`). 직접 빌드했거나 내려받은 경우.

찾는 순서(앞이 우선)
  rhwp-wasm : 환경변수 HWPAI_RHWP_CORE → <저장소>/vendor/rhwp-core → ./node_modules/@rhwp/core
              Node 실행 파일: 환경변수 HWPAI_NODE → PATH 의 node
  rhwp-cli  : 환경변수 HWPAI_RHWP_BIN → PATH 의 rhwp
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))


class EngineMissing(RuntimeError):
    """쓸 수 있는 변환 엔진이 없다 — 메시지에 설치 안내를 담는다."""


GUIDE = """HWP→HWPX 변환 엔진을 찾지 못했습니다.

  [가장 간단한 방법 — Node.js 하나만 설치]
   1) Node.js 18 이상 설치 (https://nodejs.org , Windows 는 LTS 설치 파일 실행)
   2) app/vendor/rhwp-core/ 폴더가 있는지 확인 (rhwp 소스 빌드 0.9.0-local, MIT — 휴대용 폴더에 동봉)
      없으면 zip 을 새 폴더에 다시 풀어 쓴다. npm 배포본 0.8.7 은 변경 추적으로 지운 글을 옮기므로 쓰지 않는다.
   3) 다시 실행:  python -m hwpai convert <폴더> --to hwpx

  [다른 방법]
   - 엔진 폴더를 직접 지정:  HWPAI_RHWP_CORE=<@rhwp/core 폴더>
   - Node 위치를 직접 지정:  HWPAI_NODE=<node 실행 파일>
   - rhwp 네이티브 실행 파일: HWPAI_RHWP_BIN=<rhwp 실행 파일>  (cargo build --release 로 빌드)

  확인:  python -m hwpai engines
"""


def _core_candidates():
    env = os.environ.get("HWPAI_RHWP_CORE")
    if env:
        yield env
    yield os.path.join(REPO, "vendor", "rhwp-core")
    yield os.path.join(os.getcwd(), "node_modules", "@rhwp", "core")
    yield os.path.join(REPO, "node_modules", "@rhwp", "core")


def find_core() -> str | None:
    for d in _core_candidates():
        if os.path.isfile(os.path.join(d, "rhwp.js")) and os.path.isfile(os.path.join(d, "rhwp_bg.wasm")):
            return os.path.abspath(d)
    return None


def find_node() -> str | None:
    """HWPAI_NODE → 휴대용 폴더의 node/ → PATH 의 node."""
    env = os.environ.get("HWPAI_NODE")
    if env and os.path.isfile(env):
        return env
    for d in (os.path.join(REPO, "node"), os.path.join(os.path.dirname(REPO), "node")):
        for exe in (("node.exe",) if os.name == "nt" else ("node",)):
            p = os.path.join(d, exe)
            if os.path.isfile(p):
                return p
    return shutil.which("node")


def _node_major(node: str) -> int:
    try:
        v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(v.lstrip("v").split(".")[0])
    except Exception:
        return 0


class Engine:
    name = "?"
    version = "?"

    def convert(self, src: str, dst: str, timeout: float = 120.0, password: str | None = None) -> dict:
        raise NotImplementedError

    def close(self):
        pass

    def describe(self) -> dict:
        return {"engine": self.name, "version": self.version}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class RhwpWasmEngine(Engine):
    """상주 Node 일꾼 하나에 파일을 차례로 보낸다(파일마다 WASM 을 다시 올리지 않음).

    실패 격리: 파일 하나가 시간 한도를 넘기거나 일꾼이 죽으면 그 일꾼을 끊고 새로 띄운다.
    다음 파일은 깨끗한 일꾼에서 처리된다.
    """
    name = "rhwp-wasm"

    def __init__(self, core: str | None = None, node: str | None = None, start_timeout: float = 60.0):
        self.core = core or find_core()
        self.node = node or find_node()
        if not self.core or not self.node:
            raise EngineMissing(GUIDE)
        if _node_major(self.node) < 18:
            raise EngineMissing("Node.js 18 이상이 필요합니다(현재 " + self.node + ").\n\n" + GUIDE)
        try:
            self.version = json.load(open(os.path.join(self.core, "package.json"), encoding="utf-8"))["version"]
        except Exception:
            self.version = "?"
        self.script = os.path.join(HERE, "rhwp_worker.mjs")
        self.start_timeout = start_timeout
        self.proc = None
        self.restarts = 0
        self._seq = 0
        self._start()

    def _start(self):
        self.proc = subprocess.Popen([self.node, self.script, self.core], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", bufsize=1,
                                     env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))   # 일꾼이 파이썬일 때(경량판) 한글 경로를 UTF-8 로 주고받게
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, args=(self.proc, self.q), daemon=True).start()
        threading.Thread(target=self._drain_err, args=(self.proc,), daemon=True).start()
        try:
            first = self.q.get(timeout=self.start_timeout)
        except queue.Empty:
            self._kill()
            raise EngineMissing("rhwp 엔진(WASM) 시작이 시간 안에 끝나지 않았습니다.\n\n" + GUIDE)
        if not first or not json.loads(first).get("ready"):
            self._kill()
            raise EngineMissing("rhwp 엔진(WASM) 시작 실패: " + str(first) + "\n\n" + GUIDE)

    @staticmethod
    def _pump(proc, q):
        for line in proc.stdout:
            q.put(line)
        q.put(None)

    @staticmethod
    def _drain_err(proc):
        for _ in proc.stderr:
            pass

    def _kill(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(5)
            except Exception:
                pass

    def selftest(self, dst: str, timeout: float = 60.0, text: str = "hwpai 자가 점검 문서") -> dict:
        """엔진 내장 빈 서식으로 문서를 만들어 저장(.hwp 면 HWP 5.0, .hwpx 면 HWPX) — 설치 점검·시험용."""
        return self.convert(None, dst, timeout=timeout, op="empty", text=text)

    def convert(self, src, dst, timeout=120.0, password=None, op=None, text=None):
        up, upnote = (None, None)
        if src and op is None:
            up, upnote = _upconvert_old(src)
            if upnote and not up:
                return {"ok": False, "kind": "engine_error", "error": upnote}
        try:
            r = self._convert_inner(up or src, dst, timeout, password, op, text)
        finally:
            if up:
                _rm(up)
        if not r.get("ok") and src and op is None and not up and r.get("kind") == "engine_error":
            # 0.9.2: 끊기거나 깨진 HWP 3.0 문서 — 온전히 읽히는 문단까지만 살려 다시 변환한다
            up, upnote = _salvage_v3(src)
            if up:
                try:
                    r2 = self._convert_inner(up, dst, timeout, password, op, text)
                finally:
                    _rm(up)
                if r2.get("ok"):
                    r = r2
                else:
                    upnote = None
            else:
                upnote = None
        if r.get("ok") and src and op is None:
            notes = apply_all(src, dst)
            if upnote:
                notes = [upnote] + list(notes or [])
            if notes:
                r["notes"] = list(r.get("notes") or []) + notes
        return r

    def _convert_inner(self, src, dst, timeout=120.0, password=None, op=None, text=None):
        """일꾼이 중간에 죽으면(메모리 압박 등 일시적 원인일 수 있다) 새 일꾼으로 한 번만 다시 시도한다. 시간 초과·엔진 오류는 다시 시도하지 않는다."""
        r = self._convert_once(src, dst, timeout, password, op, text)
        if not r.get("ok") and r.get("kind") == "crash" and src:
            r2 = self._convert_once(src, dst, timeout, password, op, text)
            r2["retried_after_crash"] = True
            if r2.get("ok"):
                return r2
            r["retried_after_crash"] = True
        if not r.get("ok") and r.get("kind") == "timeout" and src and op is None and timeout < 600:
            # C84: 큰 표 하나가 문서를 이루는 등 정상이지만 오래 걸리는 문서가 있다. 시간 초과는 한 번만 3배 시간(최대 900초)으로 다시 한다.
            t2 = min(timeout * 3, 900.0)
            r2 = self._convert_once(src, dst, t2, password, op, text)
            r2["retried_after_timeout"] = f"{timeout:.0f}초 초과 후 {t2:.0f}초로 재시도"
            return r2
        if not r.get("ok") and r.get("kind") == "engine_error" and src and "FORM_ACTION_INVALID" in str(r.get("error")):
            r3 = _retry_without_empty_script(self, src, dst, timeout, password)
            if r3 is not None:
                return r3
        return r

    def _convert_once(self, src, dst, timeout=120.0, password=None, op=None, text=None):
        if self.proc is None or self.proc.poll() is not None:
            self.restarts += 1
            self._start()
        self._seq += 1
        req = {"id": self._seq, "src": os.path.abspath(src) if src else None, "dst": os.path.abspath(dst)}
        if op:
            req["op"] = op
        if text:
            req["text"] = text
        if password:
            req["password"] = password
        t0 = time.perf_counter()
        try:
            self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._kill()
            self.proc = None
            return {"ok": False, "error": "엔진 일꾼이 죽어 있음(재시작 예정)", "kind": "crash"}
        deadline = t0 + timeout
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                self._kill()
                self.proc = None
                _rm(dst + ".part")
                return {"ok": False, "error": f"시간 한도 {timeout:.0f}초 초과", "kind": "timeout",
                        "ms": round((time.perf_counter() - t0) * 1000, 1)}
            try:
                line = self.q.get(timeout=min(left, 1.0))
            except queue.Empty:
                continue
            if line is None:  # 일꾼이 죽음(메모리 초과·WASM 패닉 등)
                self._kill()
                self.proc = None
                _rm(dst + ".part")
                return {"ok": False, "error": "엔진 일꾼 비정상 종료", "kind": "crash",
                        "ms": round((time.perf_counter() - t0) * 1000, 1)}
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("id") != self._seq:
                continue
            if not r.get("ok"):
                r["kind"] = "engine_error"
            return r

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(5)
            except Exception:
                self._kill()


class RhwpCliEngine(Engine):
    """rhwp 네이티브 실행 파일. 파일마다 프로세스 하나(시간 한도 넘으면 그 프로세스만 끊는다)."""
    name = "rhwp-cli"

    def __init__(self, binary: str | None = None):
        self.bin = binary or os.environ.get("HWPAI_RHWP_BIN") or shutil.which("rhwp")
        if not self.bin:
            raise EngineMissing(GUIDE)
        try:
            out = subprocess.run([self.bin, "--version"], capture_output=True, text=True, timeout=20)
            self.version = (out.stdout or out.stderr).strip().split()[-1] if (out.stdout or out.stderr) else "?"
        except Exception:
            self.version = "?"

    def convert(self, src, dst, timeout=120.0, password=None):
        if password:
            return {"ok": False, "error": "rhwp-cli 경로는 암호 문서를 지원하지 않음 — rhwp-wasm 엔진 사용",
                    "kind": "unsupported"}
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        part = dst + ".part.hwpx"
        t0 = time.perf_counter()
        try:
            p = subprocess.run([self.bin, "export-hwpx", src, part], capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            _rm(part)
            return {"ok": False, "error": f"시간 한도 {timeout:.0f}초 초과", "kind": "timeout"}
        ms = round((time.perf_counter() - t0) * 1000, 1)
        if p.returncode != 0 or not os.path.isfile(part):
            _rm(part)
            return {"ok": False, "error": (p.stderr or p.stdout)[-400:], "kind": "engine_error", "ms": ms}
        os.replace(part, dst)
        return {"ok": True, "ms": ms, "bytes": os.path.getsize(dst), "loss": None}



def _upconvert_old(src: str):
    """0.9.2: HWP 2.0·2.1 문서는 엔진이 읽지 못한다. 3.0 형식으로 올린 임시 파일을 만들어 넘긴다.
    돌려주는 값: (임시 파일 경로 또는 None, 알림 또는 None). 2.x 가 아니면 (None, None)."""
    try:
        with open(src, "rb") as f:
            head = f.read(23)
            f.seek(0)
            head4k = f.read(4096)
    except OSError:
        return None, None
    if b"<HWPML" in head4k:
        return _hml_version_fix(src, head4k)
    if not head.startswith(b"HWP Document File V") or head.startswith(b"HWP Document File V3"):
        return None, None
    ver = head[19:23].decode("ascii", "replace")
    if not head.startswith((b"HWP Document File V2.00", b"HWP Document File V2.10", b"HWP Document File V1.")):
        return None, f"HWP {ver} 문서는 지원하지 않습니다(지원: HWP 1.x·2.0·2.1·3.0·5.x)"
    try:
        from ..hwp3 import upconvert_v2
        data = upconvert_v2(src)
    except Exception as e:
        return None, f"HWP {ver} 문서를 3.0 형식으로 올리지 못했습니다: {e}"
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="hwpai_v2_", suffix=".hwp")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    cutnote = ""
    try:
        from ..hwp3 import salvage_note
        if salvage_note(src):
            cutnote = " — 원본 문서가 중간에 끊겨 있어 온전히 읽히는 문단까지만 변환했습니다"
    except Exception:
        pass
    return tmp, (f"HWP {ver} 문서를 HWP 3.0 형식으로 올린 뒤 변환했습니다" + cutnote
                 + ((" — 1.20 은 글자·문단·쪽 모양까지 옮기고(한글 2024 정답지 13건과 같음), 줄 나눔은 한글이 다시 계산합니다"
                     if ver.startswith("1.2") else " — 1.10 은 글과 문단만 옮기고 글자·문단 모양은 기본값입니다(한글 2024 도 열지 못해 정답 없음)")
                    if ver.startswith("1.") else ""))



_HML_ENGINE_VERSIONS = ("2.1", "2.9", "2.91")


def _hml_version_fix(src: str, head4k: bytes):
    """엔진은 HWPML 2.1·2.9·2.91 표기만 받는다. 그 밖의 2.x 표기(예: 2.8)는 표기만 2.9 로 바꾼 임시 파일을 넘긴다.
    내용은 손대지 않는다 — 결과는 검증서가 원본 HML 과 직접 대조한다."""
    import re, tempfile
    from ..hml1 import is_hml1, to_hml29
    if is_hml1(head4k):
        with open(src, "rb") as f:
            xml, lost = to_hml29(f.read())
        fd, tmp = tempfile.mkstemp(prefix="hwpai_hml1_", suffix=".hml")
        with os.fdopen(fd, "wb") as f:
            f.write(xml)
        return tmp, ("HWPML 1.x(한글 97 시절 HML) 문서를 HWPML 2.9 로 옮긴 뒤 변환했습니다"
                     + (f" — 그림·그리기 개체 {lost}개는 모양을 옮기지 못했습니다(글상자 안 글은 문단으로 옮김)" if lost else ""))
    m = re.search(rb'<HWPML\b[^>]*?\bVersion="([^"]*)"', head4k)
    if not m:
        return None, None
    ver = m.group(1).decode("ascii", "replace")
    if ver in _HML_ENGINE_VERSIONS or not re.fullmatch(r"2\.\d{1,2}", ver):
        return None, None
    with open(src, "rb") as f:
        data = f.read()
    a, b = m.span(1)
    fd, tmp = tempfile.mkstemp(prefix="hwpai_hml_", suffix=".hml")
    with os.fdopen(fd, "wb") as f:
        f.write(data[:a] + b"2.9" + data[b:])
    return tmp, f"HWPML {ver} 문서를 2.9 표기로 바꿔 변환했습니다(내용은 그대로)"

def _salvage_v3(src: str):
    """끊긴 HWP 3.0 문서를 읽히는 데까지 잘라 임시 파일로 만든다. (경로 또는 None, 알림 또는 None)"""
    try:
        with open(src, "rb") as f:
            if not f.read(23).startswith(b"HWP Document File V3"):
                return None, None
        from ..hwp3 import upconvert_v2, salvage_note
        cut = salvage_note(src)
        if not cut:
            return None, None
        data = upconvert_v2(src)
    except Exception:
        return None, None
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="hwpai_v3_", suffix=".hwp")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return tmp, "원본 문서가 중간에 끊겨 있어 온전히 읽히는 문단까지만 변환했습니다"


def _retry_without_empty_script(eng, src, dst, timeout, password):
    """C83: 압축 비트가 꺼진 HWP 에 비어 있는 스크립트가 압축형으로 들어 있는 옛 저장본은 엔진이 스크립트 스트림을 못 읽어 변환을 거부한다.
    스크립트 내용이 비어 있음(0x00·0xFF 뿐)을 직접 확인한 경우에만, 같은 길이의 빈 스크립트로 바꾼 임시 사본으로 한 번 다시 변환한다.
    내용이 있는 스크립트는 건드리지 않는다(변환 실패로 둔다). 원본 파일은 바꾸지 않는다."""
    import shutil, tempfile, zlib
    try:
        import olefile
    except Exception:
        return None
    tmpd = tempfile.mkdtemp(prefix="hwpai_scr_")
    try:
        cp = os.path.join(tmpd, "c.hwp")
        shutil.copyfile(src, cp)
        o = olefile.OleFileIO(cp, write_mode=True)
        try:
            if not o.exists("Scripts/DefaultJScript"):
                return None
            fh = o.openstream("FileHeader").read()
            if len(fh) < 40 or (int.from_bytes(fh[36:40], "little") & 1):
                return None  # 압축 파일은 이 경로가 아니다
            b = o.openstream("Scripts/DefaultJScript").read()
            if len(b) % 2:
                return None
            try:
                raw = zlib.decompress(b, -15)
            except Exception:
                return None
            if not raw or any(x not in (0x00, 0xFF) for x in raw):
                return None
            o.write_stream("Scripts/DefaultJScript", b"\x00" * len(b))
        finally:
            o.close()
        r = eng._convert_once(cp, dst, timeout, password)
        if r.get("ok"):
            r["notes"] = list(r.get("notes") or []) + ["빈 스크립트 스트림(형식 불일치)을 같은 길이의 빈 스크립트로 바꿔 변환(내용 손실 없음)"]
        return r
    except Exception:
        return None
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


from ..postfix import (apply_all, _restore_extensionless_images, _restore_symbol_codepoints, _fix_note_autonum,  # noqa: E402  (뒤처리는 postfix.py 로 옮김)
                       _fix_revision_sign_field, _fix_last_page_number_pos)


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


ENGINES = {"rhwp-wasm": RhwpWasmEngine, "rhwp-cli": RhwpCliEngine}


def get_engine(pref: str = "auto") -> Engine:
    """pref: auto | rhwp-wasm | rhwp-cli. 없으면 EngineMissing(설치 안내)."""
    order = list(ENGINES) if pref == "auto" else [pref]
    errs = []
    for n in order:
        if n not in ENGINES:
            raise EngineMissing(f"알 수 없는 엔진: {n} (가능: {', '.join(ENGINES)})")
        try:
            return ENGINES[n]()
        except EngineMissing as e:
            errs.append(f"[{n}] " + str(e).splitlines()[0])
    raise EngineMissing("\n".join(errs) + "\n\n" + GUIDE)


def probe() -> list[dict]:
    """설치 상태 점검(엔진 띄우지 않고 위치만)."""
    node = find_node()
    core = find_core()
    rbin = os.environ.get("HWPAI_RHWP_BIN") or shutil.which("rhwp")
    return [
        {"engine": "rhwp-wasm", "node": node, "node_major": _node_major(node) if node else 0, "core": core,
         "usable": bool(node and core and _node_major(node) >= 18)},
        {"engine": "rhwp-cli", "binary": rbin, "usable": bool(rbin)},
    ]
