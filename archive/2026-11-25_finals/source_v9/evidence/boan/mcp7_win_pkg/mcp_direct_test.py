# -*- coding: utf-8 -*-
"""hwpai MCP 서버 직접 구동 시험 클라이언트 (표준 라이브러리만). 포함 python.exe 로 실행한다.
사용: python mcp_direct_test.py <v9루트> <결과폴더> <합성문서1.hwp> <한글공백경로 합성문서.hwp>
stdio 로 initialize -> tools/list -> tools/call(read_hwp, get_tables, convert_to_hwpx, audit) 을 보내고 결과·시간을 UTF-8 로 기록한다."""
import json, os, subprocess, sys, threading, queue, time, glob, shutil

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
ROOT, OUT, SAMPLE, SAMPLE_KO = sys.argv[1:5]
LOG = os.path.join(OUT, "10_직접구동_결과.txt")
ROWS = []


def log(s=""):
    print(s)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


class Server:
    def __init__(self, argv, cwd, env):
        self.t0 = time.perf_counter()
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env)
        self.q = queue.Queue()
        self.err = []
        threading.Thread(target=self._rd, daemon=True).start()
        threading.Thread(target=lambda: [self.err.append(l) for l in self.p.stderr], daemon=True).start()
        self.n = 0

    def _rd(self):
        for line in self.p.stdout:
            self.q.put(line)
        self.q.put(None)

    def call(self, method, params=None, timeout=300, notify=False):
        self.n += 1
        m = {"jsonrpc": "2.0", "method": method}
        if not notify:
            m["id"] = self.n
        if params is not None:
            m["params"] = params
        self.p.stdin.write((json.dumps(m, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        if notify:
            return None
        while True:
            line = self.q.get(timeout=timeout)
            if line is None:
                raise RuntimeError("서버가 응답 없이 종료됨 (rc=%s) stderr=%s" % (self.p.poll(), b"".join(self.err)[-400:].decode("utf-8", "replace")))
            r = json.loads(line.decode("utf-8"))
            if r.get("id") == self.n:
                return r

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:
            self.p.kill()


def text_of(r):
    c = r.get("result", {}).get("content", [])
    return "".join(x.get("text", "") for x in c)


def base_env(drop_utf8=True, extra=None):
    e = dict(os.environ)
    if drop_utf8:
        e.pop("PYTHONUTF8", None); e.pop("PYTHONIOENCODING", None)
    e.pop("HWPAI_GRADE_LOG", None); e.pop("HWPAI_MCP_ROOTS", None)
    e.update(extra or {})
    return e


def timing(label, argv, cwd, env, n=3):
    ts = []
    for i in range(n):
        s = Server(argv, cwd, env)
        try:
            r = s.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "win-test", "version": "1"}}, timeout=120)
            ts.append(time.perf_counter() - s.t0)
            ok = "protocolVersion" in r.get("result", {})
        except Exception as ex:
            ts.append(None); ok = False
            log("  시간측정 %d회차 오류: %s" % (i + 1, ex))
        finally:
            s.close()
    vals = ["%.2f초" % t if t is not None else "오류" for t in ts]
    log("[시작~initialize 응답 시간] %s: %s" % (label, " / ".join(vals)))
    ROWS.append(("시작~initialize 3회 " + label, "통과" if all(t is not None for t in ts) else "실패", " / ".join(vals)))


def full(label, argv, cwd, env, sample, tag):
    log("")
    log("=== 시험: %s ===" % label)
    log("명령: %s   작업폴더: %s" % (" ".join(argv), cwd))
    log("문서: %s" % sample)
    steps = []
    s = None
    try:
        s = Server(argv, cwd, env)
        r = s.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "win-test", "version": "1"}}, timeout=120)
        t_init = time.perf_counter() - s.t0
        ok = r["result"]["protocolVersion"] and r["result"]["serverInfo"]["name"] == "hwpai"
        steps.append(("initialize", ok, "%.2f초, protocol=%s" % (t_init, r["result"]["protocolVersion"])))
        s.call("notifications/initialized", notify=True)
        r = s.call("tools/list")
        names = [t["name"] for t in r["result"]["tools"]]
        steps.append(("tools/list", len(names) == 8, "%d개 %s" % (len(names), ",".join(names))))
        r = s.call("tools/call", {"name": "read_hwp", "arguments": {"path": sample}})
        tx = text_of(r)
        steps.append(("read_hwp", (not r["result"].get("isError")) and len(tx) > 20, "isError=%s 글자수=%d 앞부분=%s" % (r["result"].get("isError"), len(tx), tx[:80].replace("\n", " "))))
        r = s.call("tools/call", {"name": "get_tables", "arguments": {"path": sample}})
        steps.append(("get_tables", not r["result"].get("isError"), "isError=%s %s" % (r["result"].get("isError"), text_of(r)[:80].replace("\n", " "))))
        outd = os.path.join(OUT, "변환_" + tag)
        shutil.rmtree(outd, ignore_errors=True)
        r = s.call("tools/call", {"name": "convert_to_hwpx", "arguments": {"path": sample, "out": outd}}, timeout=600)
        hw = glob.glob(os.path.join(outd, "**", "*.hwpx"), recursive=True)
        steps.append(("convert_to_hwpx", (not r["result"].get("isError")) and bool(hw), "isError=%s hwpx=%s" % (r["result"].get("isError"), [os.path.basename(x) for x in hw])))
        if hw:
            r = s.call("tools/call", {"name": "audit", "arguments": {"original": sample, "converted": hw[0]}}, timeout=600)
            tx = text_of(r)
            steps.append(("audit", not r["result"].get("isError"), "isError=%s %s" % (r["result"].get("isError"), tx[:100].replace("\n", " "))))
        else:
            steps.append(("audit", False, "변환 결과 없음"))
    except Exception as ex:
        steps.append(("오류", False, str(ex)[:500]))
    finally:
        if s:
            err = b"".join(s.err).decode("utf-8", "replace")
            s.close()
            if err.strip():
                log("stderr: " + err[-500:])
    for n, ok, d in steps:
        log("  %-16s %s  %s" % (n, "통과" if ok else "실패", d))
    allok = all(o for _, o, _ in steps)
    ROWS.append((label, "통과" if allok else "실패", "; ".join("%s=%s" % (n, "O" if o else "X") for n, o, _ in steps)))


def main():
    open(LOG, "w", encoding="utf-8").close()
    py = os.path.join(ROOT, "python", "python.exe")
    bat = os.path.join(ROOT, "hwpai.bat")
    app = os.path.join(ROOT, "app")
    log("hwpai MCP Windows 직접 구동 시험 %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    log("클라이언트 파이썬: %s %s, 기본 인코딩=%s, PYTHONUTF8=%s" % (sys.version.split()[0], sys.executable, sys.getdefaultencoding() + "/" + __import__("locale").getpreferredencoding(), os.environ.get("PYTHONUTF8")))
    r = subprocess.run([py, "-c", "import hwpai,sys,locale;print(hwpai.__file__);print(sys.flags.utf8_mode, locale.getpreferredencoding())"], capture_output=True, cwd=ROOT, env=base_env())
    log("서버 파이썬이 읽는 hwpai: " + r.stdout.decode("utf-8", "replace").replace("\n", " | "))
    mcpfile = os.path.join(app, "hwpai", "mcp.py")
    log("v9 mcp.py 줄 수: %d" % len(open(mcpfile, encoding="utf-8").read().splitlines()))
    # 1 hwpai.bat 방식
    full("A hwpai.bat mcp (작업폴더=v9 루트)", [bat, "mcp"], ROOT, base_env(extra={"HWPAI_GRADE_LOG": os.path.join(OUT, "gradelog_A")}), SAMPLE, "A_bat")
    # 2 python.exe 방식, 한글·공백 경로 문서, UTF-8 모드 미설정(윈도 기본 cp949)
    full("B python.exe -m hwpai mcp (PYTHONUTF8 미설정, 한글·공백 경로 문서)", [py, "-m", "hwpai", "mcp"], ROOT, base_env(extra={"HWPAI_GRADE_LOG": os.path.join(OUT, "gradelog_B")}), SAMPLE_KO, "B_py")
    # 3 cp949 를 명시
    full("C python.exe, PYTHONUTF8=0 PYTHONIOENCODING=cp949 명시(한글·공백 경로)", [py, "-m", "hwpai", "mcp"], ROOT, base_env(extra={"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp949", "HWPAI_GRADE_LOG": os.path.join(OUT, "gradelog_C")}), SAMPLE_KO, "C_cp949")
    # 4 System32 에서 띄움 + HWPAI_GRADE_LOG 없음 (구판에서 실패했던 상황)
    sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    full("D python.exe 를 C:\\Windows\\System32 에서 띄움·HWPAI_GRADE_LOG 없음(구판 실패 재현)", [py, "-m", "hwpai", "mcp"], sysdir, base_env(), SAMPLE, "D_sys32")
    # 5 hwpai.bat 을 System32 에서
    full("E hwpai.bat 을 C:\\Windows\\System32 에서 띄움·HWPAI_GRADE_LOG 없음", [bat, "mcp"], sysdir, base_env(), SAMPLE, "E_sys32bat")
    log("")
    timing("hwpai.bat", [bat, "mcp"], ROOT, base_env(extra={"HWPAI_GRADE_LOG": os.path.join(OUT, "gradelog_T")}))
    timing("python.exe", [py, "-m", "hwpai", "mcp"], ROOT, base_env(extra={"HWPAI_GRADE_LOG": os.path.join(OUT, "gradelog_T")}))
    log("")
    log("=== 요약 ===")
    for a, b, c in ROWS:
        log("%-70s %-4s %s" % (a, b, c))
    json.dump(ROWS, open(os.path.join(OUT, "10_직접구동_요약.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


main()
