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
                                     encoding="utf-8", bufsize=1)
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
        """일꾼이 중간에 죽으면(메모리 압박 등 일시적 원인일 수 있다) 새 일꾼으로 한 번만 다시 시도한다. 시간 초과·엔진 오류는 다시 시도하지 않는다."""
        r = self._convert_once(src, dst, timeout, password, op, text)
        if not r.get("ok") and r.get("kind") == "crash" and src:
            r2 = self._convert_once(src, dst, timeout, password, op, text)
            r2["retried_after_crash"] = True
            if r2.get("ok"):
                return r2
            r["retried_after_crash"] = True
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
