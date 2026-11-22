import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import Ajv2020 from "ajv/dist/2020.js";
const SC = process.argv[2];
const mn = SC + "/한글 폴더/입력/회의록 샘플.hwp";
const t = new StdioClientTransport({ command: "/usr/local/bin/python3", args: ["-m", "hwpai", "mcp"], cwd: SC + "/run3",
  env: { ...process.env, PYTHONPATH: "/home/claude/hwpai_v9/app", PYTHONUTF8: "1" } });
const c = new Client({ name: "node-sdk-test", version: "1" });
let ok = 0, n = 0; const rec = (name, v, note = "") => { n++; if (v) ok++; console.log(v ? "PASS" : "FAIL", name, note); };
await c.connect(t);
rec("initialize(Node SDK)", true, `server=${JSON.stringify(c.getServerVersion())} caps=${JSON.stringify(c.getServerCapabilities())}`);
rec("ping", (await c.ping()) !== undefined);
const tl = await c.listTools();
rec("tools/list 8개", tl.tools.length === 8, tl.tools.map(x => x.name).join(","));
const ajv = new Ajv2020({ strict: false }); let bad = [];
for (const x of tl.tools) { try { ajv.compile(x.inputSchema); } catch (e) { bad.push(x.name + ":" + e.message); } }
rec("inputSchema Ajv(2020-12) 컴파일", bad.length === 0, bad.join(";"));
let r = await c.callTool({ name: "read_hwp", arguments: { path: mn } });
rec("read_hwp 한글 경로", !r.isError && r.content[0].text.includes("회의"), `len=${r.content[0].text.length}`);
r = await c.callTool({ name: "get_tables", arguments: { path: mn, as: "csv" } });
rec("get_tables(as)", !r.isError);
r = await c.callTool({ name: "convert_to_hwpx", arguments: { path: SC + "/한글 폴더/입력", out: SC + "/run3/결과 폴더" } });
rec("convert_to_hwpx", !r.isError && JSON.parse(r.content[0].text).files === 2, r.content[0].text.slice(0, 60));
r = await c.callTool({ name: "audit", arguments: { original: mn, converted: SC + "/run3/결과 폴더/회의록 샘플.hwpx" } });
rec("audit", !r.isError && r.content[0].text.includes("PASS"));
r = await c.callTool({ name: "nope", arguments: {} });
rec("알 수 없는 도구", true, "isError=" + r.isError);
try { await c.request({ method: "no/such", params: {} }, (await import("zod")).z.any()); rec("알 수 없는 메서드", false); } catch (e) { rec("알 수 없는 메서드 → 오류", /-32601|지원하지/.test(String(e.code) + e.message), String(e.code)); }
await c.close();
console.log("SUMMARY", ok, "/", n);
