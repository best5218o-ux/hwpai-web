import asyncio, json, os, sys, glob
import importlib.metadata as md
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import jsonschema

SRC = "/home/claude/hwpai_v9"
HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "run")
KO = os.path.join(HERE, "한글 폴더", "입력")
R = []
def g(o, *ns):
    for n in ns:
        if hasattr(o, n): return getattr(o, n)
    raise AttributeError(ns)
def rec(name, ok, note=""):
    R.append((name, ok, note)); print(("PASS" if ok else "FAIL"), name, note, flush=True)

async def main():
    env = dict(os.environ, PYTHONPATH=SRC + "/app", PYTHONUTF8="1", HWPAI_MCP_ROOTS=HERE)
    params = StdioServerParameters(command="/usr/local/bin/python3", args=["-m", "hwpai", "mcp"], env=env, cwd=RUN)
    import io
    errlog = open(os.path.join(RUN, "stderr.txt"), "w")
    async with stdio_client(params, errlog=errlog) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            rec("initialize", True, f"proto={g(init,'protocolVersion','protocol_version')} server={g(init,'serverInfo','server_info').name} caps={init.capabilities.model_dump(exclude_none=True)}")
            tl = await s.list_tools()
            names = [t.name for t in tl.tools]
            rec("tools/list 8개", len(names) == 8, str(names))
            bad = []
            for t in tl.tools:
                try:
                    jsonschema.Draft202012Validator.check_schema(g(t,'inputSchema','input_schema'))
                    jsonschema.Draft7Validator.check_schema(g(t,'inputSchema','input_schema'))
                    assert g(t,'inputSchema','input_schema').get("type") == "object"
                    assert t.description
                except Exception as e:
                    bad.append((t.name, str(e)[:100]))
            rec("inputSchema JSON Schema 유효(2020-12·draft-07, type=object)", not bad, str(bad))
            await s.send_ping() if hasattr(s, "send_ping") else None
            rec("ping", True)
            mn = os.path.join(KO, "회의록 샘플.hwp")
            res = await s.call_tool("read_hwp", {"path": mn})
            txt = res.content[0].text
            rec("tools/call read_hwp 한글 경로", (not g(res,'isError','is_error')) and len(txt) > 200 and "회의" in txt, f"len={len(txt)} isError={g(res,'isError','is_error')}")
            res = await s.call_tool("get_tables", {"path": mn, "as": "csv"})
            rec("tools/call get_tables(인자 'as')", not g(res,'isError','is_error'), res.content[0].text[:80].replace("\n", " "))
            res = await s.call_tool("search_chunks", {"path": mn, "query": "회의"})
            rec("tools/call search_chunks", not g(res,'isError','is_error'))
            out = os.path.join(HERE, "run", "변환 결과")
            res = await s.call_tool("convert_to_hwpx", {"path": KO, "out": out})
            j = json.loads(res.content[0].text) if not g(res,'isError','is_error') else {}
            rec("tools/call convert_to_hwpx 폴더(한글 경로)", (not g(res,'isError','is_error')) and j.get("files") == 2, res.content[0].text[:200].replace("\n", " "))
            hx = sorted(glob.glob(os.path.join(out, "**", "*.hwpx"), recursive=True))
            rec("변환 결과 hwpx 생성", len(hx) == 2, str([os.path.basename(x) for x in hx]))
            if hx:
                hm = [x for x in hx if "회의록" in x][0]
                res = await s.call_tool("audit", {"original": mn, "converted": hm})
                rec("tools/call audit", (not g(res,'isError','is_error')) and ("PASS" in res.content[0].text), res.content[0].text[:120].replace("\n", " "))
            res = await s.call_tool("read_hwp", {"path": "/nonexistent/없는파일.hwp"})
            rec("도구 오류는 isError 결과", g(res,'isError','is_error') and "오류" in res.content[0].text, res.content[0].text[:80])
            res = await s.call_tool("read_hwp", {"path": "/etc/hostname"})
            rec("허용 폴더 밖 차단(HWPAI_MCP_ROOTS)", g(res,'isError','is_error') and "허용된 폴더" in res.content[0].text)
            try:
                res = await s.call_tool("no_such_tool", {})
                rec("알 수 없는 도구", bool(g(res,'isError','is_error')), "isError 결과로 돌려줌: " + res.content[0].text[:60])
            except Exception as e:
                rec("알 수 없는 도구", True, "프로토콜 오류: " + str(e)[:80])
            res = await s.call_tool("read_hwp", {"path": mn, "grade": "공개"})
            rec("등급 인자 주입 거부", g(res,'isError','is_error'))
    errlog.close()
    st = open(os.path.join(RUN, "stderr.txt"), encoding="utf-8").read()
    rec("stderr 크기(참고)", True, f"{len(st)}자")
    print("SDK", md.version("mcp"))
    print("SUMMARY", sum(1 for x in R if x[1]), "/", len(R))
asyncio.run(main())
