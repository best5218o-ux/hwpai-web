import json, os, subprocess, sys
SRC="/home/claude/hwpai_v9"
HERE=os.path.dirname(os.path.abspath(__file__))
def run(lines, env_extra=None, raw=False):
    env=dict(os.environ, PYTHONPATH=SRC+"/app", PYTHONUTF8="1"); env.update(env_extra or {})
    p=subprocess.run(["/usr/local/bin/python3","-m","hwpai","mcp"], input=("\n".join(lines)+"\n").encode("utf-8"), capture_output=True, env=env, cwd=os.path.join(HERE,"run2"), timeout=120)
    out=p.stdout.decode("utf-8", "replace")
    return p.returncode, [l for l in out.split("\n") if l.strip()], p.stderr.decode("utf-8","replace")
os.makedirs(os.path.join(HERE,"run2"),exist_ok=True)
def J(**k): return json.dumps(dict(jsonrpc="2.0",**k))
res=[]
def t(name, ok, note=""):
    res.append(ok); print("PASS" if ok else "FAIL", name, note)
for v in ["2025-11-25","2025-06-18","2025-03-26","2024-11-05","2024-10-07","bogus"]:
    rc,o,e=run([J(id=1,method="initialize",params={"protocolVersion":v,"capabilities":{},"clientInfo":{"name":"t","version":"1"}})])
    r=json.loads(o[0])["result"]
    t(f"initialize 요청 {v}", r["protocolVersion"] in ("2025-06-18","2025-03-26","2024-11-05") and "serverInfo" in r and "capabilities" in r, "-> "+r["protocolVersion"])
rc,o,e=run([J(id=1,method="initialize",params={"protocolVersion":"2025-06-18"}), J(method="notifications/initialized"), J(method="notifications/cancelled",params={"requestId":9}), J(id=2,method="ping")])
t("notifications 는 응답 없음, ping 응답", len(o)==2 and json.loads(o[1])=={"jsonrpc":"2.0","id":2,"result":{}}, f"{len(o)}줄")
rc,o,e=run([J(id=0,method="ping"), J(id="abc",method="ping")])
t("ping 초기화 전·id 0/문자열 되돌림", [json.loads(x)["id"] for x in o]==[0,"abc"])
rc,o,e=run([J(id=5,method="foo/bar"), J(method="foo/notif"), J(id=6,method="resources/list"), J(id=7,method="prompts/list")])
r=[json.loads(x) for x in o]
t("알 수 없는 메서드 -32601, 알림은 무응답", len(r)==3 and all(x["error"]["code"]==-32601 for x in r), str([x.get("error",{}).get("code") for x in r]))
rc,o,e=run(["{bad json", J(id=1,method="ping")])
r=[json.loads(x) for x in o]
t("JSON 파싱 오류 -32700 후 계속 동작", r[0]["error"]["code"]==-32700 and r[1].get("id")==1)
for bad in ["5", '"x"', "[]", "[5]", "null", "[1,{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"ping\"}]"]:
    rc,o,e=run([bad, J(id=9,method="ping")])
    ok = rc==0 and any(json.loads(x).get("id")==9 for x in o)
    t(f"비정상 메시지 {bad} 에도 서버 생존", ok, f"rc={rc} out={len(o)} err={e.strip().splitlines()[-1][:80] if e.strip() else ''}")
rc,o,e=run([J(id=1,method="tools/call",params={}), J(id=2,method="tools/call",params={"name":"read_hwp","arguments":"zz"}), J(id=3,method="tools/call",params={"name":"read_hwp","arguments":{}}), J(id=4,method="tools/call",params={"name":"read_hwp"}), J(id=5,method="tools/list",params={"cursor":"x"})])
r=[json.loads(x) for x in o]
t("tools/call 잘못된 호출 모두 응답(서버 생존)", len(r)==5, str([("err" if "error" in x else ("isError" if x["result"].get("isError") else "ok")) for x in r]))
t("tools/list 커서 무시하고 전체 반환", len(r[4]["result"]["tools"])==8)
# stdout 오염: 도구 전부를 호출하고 stdout 의 모든 줄이 JSON-RPC 인지
mn=os.path.join(HERE,"한글 폴더","입력","회의록 샘플.hwp"); d=os.path.join(HERE,"한글 폴더","입력")
reqs=[J(id=1,method="initialize",params={"protocolVersion":"2025-06-18"}),J(method="notifications/initialized"),
 J(id=2,method="tools/call",params={"name":"read_hwp","arguments":{"path":mn,"format":"json"}}),
 J(id=3,method="tools/call",params={"name":"get_tables","arguments":{"path":mn}}),
 J(id=4,method="tools/call",params={"name":"search_chunks","arguments":{"path":mn,"query":"참석"}}),
 J(id=5,method="tools/call",params={"name":"convert_to_hwpx","arguments":{"path":d,"out":os.path.join(HERE,"run2","out 한글")}}),
 J(id=6,method="tools/call",params={"name":"export_doc","arguments":{"path":mn,"out":os.path.join(HERE,"run2","exp 한글")}}),
 J(id=7,method="tools/call",params={"name":"replace_text","arguments":{"path":os.path.join(HERE,"run2","out 한글","회의록 샘플.hwpx"),"replacements":{"회의":"미팅"},"out":os.path.join(HERE,"run2","수정본.hwpx")}}),
 J(id=8,method="tools/call",params={"name":"fill_form","arguments":{"path":os.path.join(HERE,"run2","out 한글","회의록 샘플.hwpx"),"values":{"성명":"홍길동"},"out":os.path.join(HERE,"run2","채움.hwpx")}}),
 J(id=9,method="tools/call",params={"name":"audit","arguments":{"original":mn,"converted":os.path.join(HERE,"run2","out 한글","회의록 샘플.hwpx")}})]
rc,o,e=run(reqs)
ok=True; kinds=[]
for x in o:
    try:
        m=json.loads(x); assert m.get("jsonrpc")=="2.0"
    except Exception: ok=False; kinds.append("BAD:"+x[:60])
t("8개 도구 호출 중 stdout 모든 줄이 JSON-RPC", ok and len(o)==9, f"{len(o)}줄 {kinds}")
for x in o[2:]:
    m=json.loads(x); r=m["result"]; print("   id",m["id"],"isError",r["isError"], r["content"][0]["text"][:90].replace("\n"," "))
print("stderr:",e[:300])
# 인코딩: 한글 경로 입력을 UTF-8 이 아닌 기본 인코딩 환경에서
rc,o,e=run([J(id=2,method="tools/call",params={"name":"read_hwp","arguments":{"path":mn}})], env_extra={"PYTHONUTF8":"0","PYTHONIOENCODING":"cp949"})
txt=json.loads(o[0])["result"]["content"][0]["text"] if o else ""
t("UTF-8 강제 없는 환경(cp949 입출력)에서 한글 경로·출력", bool(o) and "isError\": false" in o[0].replace('"isError": false','isError": false') and "회의" in txt, f"rc={rc} out={o[0][:120] if o else ''} err={e.strip()[-120:]}")
print("SUMMARY",sum(res),"/",len(res))
