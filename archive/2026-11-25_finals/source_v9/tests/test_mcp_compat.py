"""결선 보완 6차 — MCP 서버 호환성(표준 규격) 회귀 시험. 실행: python -m unittest discover -s tests
API·네트워크 호출 없음. 서버를 자식 프로세스로 띄워 표준입출력으로 JSON-RPC 를 주고받는다.
test_non_object_* · test_utf8_* 는 제출본 코드에서 실패한다(서버가 죽음)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
APP = os.path.join(ROOT, "app")
SAMPLE = os.path.join(ROOT, "sample_data", "sample_notice.hwp")
sys.path.insert(0, APP)
from hwpai import mcp  # noqa: E402


def _req(i, method, params=None):
    d = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        d["params"] = params
    return json.dumps(d, ensure_ascii=False)


def _run(lines, cwd, env_extra=None):
    env = dict(os.environ, PYTHONPATH=APP, HWPAI_GRADE_LOG=cwd)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-m", "hwpai", "mcp"], input=("\n".join(lines) + "\n").encode("utf-8"),
                       capture_output=True, env=env, cwd=cwd, timeout=120)
    return p.returncode, [l for l in p.stdout.decode("utf-8").split("\n") if l.strip()], p.stderr.decode("utf-8", "replace")


class McpCompat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hwpai_mcp_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_protocol_version_negotiation(self):
        for want, got in (("2025-06-18", "2025-06-18"), ("2025-03-26", "2025-03-26"), ("2024-11-05", "2024-11-05"),
                          ("2025-11-25", "2025-06-18"), ("bogus", "2025-06-18")):
            r = mcp.handle(json.loads(_req(1, "initialize", {"protocolVersion": want})))["result"]
            self.assertEqual(r["protocolVersion"], got)
            self.assertIn("tools", r["capabilities"])
            self.assertEqual(r["serverInfo"]["name"], "hwpai")

    def test_notifications_get_no_reply_and_ping_works(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}))
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 0, "method": "ping"}), {"jsonrpc": "2.0", "id": 0, "result": {}})

    def test_unknown_method_is_32601(self):
        r = mcp.handle({"jsonrpc": "2.0", "id": "a", "method": "resources/list"})
        self.assertEqual((r["id"], r["error"]["code"]), ("a", -32601))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "foo/bar"}))

    def test_tools_list_schema_is_valid_json_schema(self):
        tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual(len(tools), 8)
        try:
            import jsonschema
        except ImportError:
            jsonschema = None
        for t in tools:
            self.assertTrue(t["name"] and t["description"])
            sc = t["inputSchema"]
            self.assertEqual(sc["type"], "object")
            self.assertTrue(set(sc.get("required", [])) <= set(sc["properties"]))
            if jsonschema:
                jsonschema.Draft202012Validator.check_schema(sc)
                jsonschema.Draft7Validator.check_schema(sc)
        json.dumps(tools)  # 직렬화 가능

    def test_non_object_messages_do_not_kill_server(self):
        for bad in ("5", '"x"', "null", "[5]", "[]"):
            rc, out, err = _run([bad, _req(9, "ping")], self.tmp)
            self.assertEqual(rc, 0, f"{bad}: {err[-200:]}")
            msgs = [json.loads(x) for x in out]
            self.assertTrue(any(m.get("id") == 9 for m in msgs), bad)
            self.assertTrue(any(m.get("error", {}).get("code") == -32600 for m in msgs), bad)

    def test_parse_error_then_continue(self):
        rc, out, _ = _run(["{bad", _req(1, "ping")], self.tmp)
        m = [json.loads(x) for x in out]
        self.assertEqual(m[0]["error"]["code"], -32700)
        self.assertEqual(m[1]["id"], 1)

    def test_stdout_is_only_jsonrpc_and_korean_path_works(self):
        kd = os.path.join(self.tmp, "한글 폴더")
        os.makedirs(kd)
        ko = os.path.join(kd, "공고문 샘플.hwp")
        shutil.copy(SAMPLE, ko)
        reqs = [_req(1, "initialize", {"protocolVersion": "2025-06-18"}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                _req(2, "tools/call", {"name": "read_hwp", "arguments": {"path": ko}}),
                _req(3, "tools/call", {"name": "convert_to_hwpx", "arguments": {"path": kd, "out": os.path.join(self.tmp, "결과 폴더")}}),
                _req(4, "tools/call", {"name": "nope", "arguments": {}})]
        rc, out, err = _run(reqs, self.tmp)
        self.assertEqual(rc, 0, err[-300:])
        msgs = [json.loads(x) for x in out]  # 한 줄이라도 JSON 이 아니면 여기서 실패 = stdout 오염
        self.assertEqual([m["id"] for m in msgs], [1, 2, 3, 4])
        self.assertFalse(msgs[1]["result"]["isError"])
        self.assertIn("HWPX", msgs[1]["result"]["content"][0]["text"])
        self.assertFalse(msgs[2]["result"]["isError"], msgs[2])
        self.assertTrue(msgs[3]["result"]["isError"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "결과 폴더", "공고문 샘플.hwpx")))

    def test_utf8_stdio_without_python_utf8_mode(self):
        """윈도 기본(cp949)처럼 파이썬이 UTF-8 모드가 아니어도 한글 입력·출력이 깨지지 않는다(MCP 표준입출력은 UTF-8)."""
        kd = os.path.join(self.tmp, "한글")
        os.makedirs(kd)
        ko = os.path.join(kd, "공고문.hwp")
        shutil.copy(SAMPLE, ko)
        rc, out, err = _run([_req(2, "tools/call", {"name": "read_hwp", "arguments": {"path": ko}})], self.tmp,
                            {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp949"})
        self.assertEqual(rc, 0, err[-300:])
        r = json.loads(out[0])["result"]
        self.assertFalse(r["isError"], r)
        self.assertIn("개방형 문서", r["content"][0]["text"])

    def test_unwritable_launch_folder_without_grade_log_env(self):
        """7차(윈도 실측): Claude 데스크톱이 서버를 C:\\WINDOWS\\system32 에서 띄우면 등급 기록 폴더를 못 만들어
        PermissionError 로 모든 도구가 실패했다(구판). 시작 폴더에 기록 폴더를 만들 수 없어도(여기서는 같은 이름의 파일로 재현)
        HWPAI_GRADE_LOG 없이 도구가 동작해야 한다."""
        wd = os.path.join(self.tmp, "쓰기불가 시작폴더")
        os.makedirs(wd)
        open(os.path.join(wd, "hwpai_등급기록"), "w").close()  # 같은 이름의 파일 -> makedirs 실패
        ko = os.path.join(self.tmp, "공고문.hwp")
        shutil.copy(SAMPLE, ko)
        env = {k: v for k, v in os.environ.items() if k != "HWPAI_GRADE_LOG"}
        env.update(PYTHONPATH=APP, LOCALAPPDATA=os.path.join(self.tmp, "la"), HOME=self.tmp, TMPDIR=self.tmp)
        p = subprocess.run([sys.executable, "-m", "hwpai", "mcp"],
                           input=(_req(1, "tools/call", {"name": "read_hwp", "arguments": {"path": ko}}) + "\n").encode("utf-8"),
                           capture_output=True, env=env, cwd=wd, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace")[-300:])
        r = json.loads(p.stdout.decode("utf-8").split("\n")[0])["result"]
        self.assertFalse(r["isError"], r)
        self.assertIn("개방형 문서", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
