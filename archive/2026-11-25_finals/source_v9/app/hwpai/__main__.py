"""hwpai 명령줄.

  python -m hwpai read    문서.hwp [--out 폴더]            AI 용 마크다운·표 CSV·청크 (변환 없이 바로 판독)
  python -m hwpai convert 폴더|파일 --to hwpx [--out 폴더]  한글 없이 일괄 HWP→HWPX + 이관대장 + 검증서
  python -m hwpai convert 폴더|파일 --to md   [--out 폴더]  일괄 AI 판독(마크다운·CSV·청크)
  python -m hwpai audit   원본.hwp 변환.hwpx [--out 이름]   변환 검증서(PASS/WARN/FAIL)
  python -m hwpai engines                                   변환 엔진 설치 점검
  python -m hwpai doctor                                    설치 점검 + 시험 변환·검증(한국어 안내)
  python -m hwpai gui                                       화면(127.0.0.1)으로 폴더 변환·판정 보기 (폴더 끌어놓기)
  python -m hwpai drop    폴더|파일 …                       끌어놓기 일괄 변환 → 〈원본〉_hwpx변환
  python -m hwpai mcp | mcp-install                         AI 앱용 MCP 서버 / 설정 자동 등록
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def cmd_read(a):
    from . import convert
    from .batch import outside_out   # 결선 보완 B6: 입력 폴더 밖 〈폴더〉_hwpai/〈문서 이름〉
    out = a.out or os.path.join(outside_out(a.path, "_hwpai"), os.path.splitext(os.path.basename(a.path))[0])
    print(json.dumps(convert(a.path, out), ensure_ascii=False, indent=1))
    return 0


def cmd_convert(a):
    if a.to == "md":
        from .batch import scan
        from . import convert
        root = a.path if os.path.isdir(a.path) else os.path.dirname(os.path.abspath(a.path))
        from .batch import outside_out
        out = a.out or outside_out(a.path, "_md")
        ok = bad = 0
        for rel in scan(a.path, True):
            try:
                convert(os.path.join(root, rel), os.path.join(out, os.path.splitext(rel)[0]))
                ok += 1
            except Exception as e:
                bad += 1
                print(f"  실패 {rel}: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"판독 {ok}개, 실패 {bad}개 → {out}")
        return 0 if not bad else 1
    from .batch import BatchConverter
    from .engines import EngineMissing
    from .batch import default_out
    out = a.out or default_out(a.path)
    pw = a.password or os.environ.get("HWPAI_PASSWORD")
    try:
        st_ = _settler(a)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        bc = BatchConverter(a.path, out, engine=a.engine, timeout=a.timeout, jobs=a.jobs, password=pw,
                            password_file=a.password_file, verify=not a.no_verify,
                            quarantine_copy=not a.no_quarantine_copy, include_hwpx=a.include_hwpx,
                            retry_failed=a.retry_failed, reverify=a.reverify, gate=a.gate, settle=st_)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"일괄 변환: {a.path} → {out}")
    try:
        s = bc.run(limit=a.limit)
    except EngineMissing as e:
        print(str(e), file=sys.stderr)
        return 3
    print(json.dumps({k: s[k] for k in ("files", "resumed", "wall_seconds", "status", "verdict")}, ensure_ascii=False))
    print(f"이관대장: {os.path.join(out, '이관대장.csv')}  ·  요약: {os.path.join(out, '요약.md')}")
    return 0


def cmd_audit(a):
    from .audit import audit, to_markdown, write_audit
    from .grade import guard  # audit() 은 예외를 삼키므로 먼저 등급을 확인한다
    guard(a.original, tool="audit")
    guard(a.converted, tool="audit")
    r = audit(a.original, a.converted)
    if a.out:
        jp, mp = write_audit(r, a.out)
        print(f"검증서: {mp} · {jp}")
    if a.json:
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=1))
    elif not a.out:
        print(to_markdown(r))
    return {"PASS": 0, "WARN": 1, "FAIL": 2}.get(r.verdict, 2)


def cmd_engines(a):
    """설치 점검 + 자가 점검: 엔진이 HWP 를 만들고 → HWPX 로 바꾸고 → 검증서가 PASS 인지."""
    import tempfile
    from .audit import audit
    from .engines import GUIDE, EngineMissing, RhwpWasmEngine, probe
    p = probe()
    print(json.dumps(p, ensure_ascii=False, indent=1))
    if not any(x["usable"] for x in p):
        print(GUIDE)
        return 3
    if not p[0]["usable"]:
        return 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        src, dst = os.path.join(d, "점검.hwp"), os.path.join(d, "점검.hwpx")
        try:
            with RhwpWasmEngine() as eng:
                r1 = eng.selftest(src)
                r2 = eng.convert(src, dst, timeout=60) if r1.get("ok") else r1
        except EngineMissing as e:
            print(str(e))
            return 3
        if not r2.get("ok"):
            print("자가 점검 실패:", r2.get("error"))
            return 3
        v = audit(src, dst)
        print(f"자가 점검: 엔진 rhwp-wasm {eng.version} · HWP 생성→HWPX 변환 {r2.get('ms')}ms · 검증서 {v.verdict}")
        return 0 if v.verdict == "PASS" else 1


def cmd_gui(a):
    from .gui import serve
    serve(a.port, not a.no_browser)
    return 0


def cmd_mcp(a):
    from .mcp import serve
    serve()
    return 0


def cmd_mcp_install(a):
    from .mcp import install
    if a.print:
        print(install(a.config, dry=True))
        return 0
    p = install(a.config)
    print(f"등록했습니다: {p} (기존 설정은 .bak 로 보관). AI 앱(Claude 데스크톱 등)을 다시 시작하면 hwpai 도구 5개가 보입니다.")
    return 0


def cmd_ask(a):
    from .ask import ask, load_profiles
    prof = load_profiles(a.profiles)
    if not prof:
        print("모델 설정이 없습니다. --profiles 설정.json 또는 HWPAI_LLM_BASE_URL·HWPAI_LLM_MODEL·HWPAI_LLM_API_KEY 를 주세요.",
              file=sys.stderr)
        return 3
    r = ask(a.path, a.question, prof, a.profile or None, a.top_k)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"질문: {r['question']}  ·  근거 후보 조각 {r['retrieved']}")
        for n, x in r["answers"].items():
            print(f"- [{n} · {x.get('model')}] " + (x.get("error") or f"{x['answer']}  (근거 {x['evidence']}, {x['seconds']}초)"))
        if len(r["answers"]) >= 2:
            print("모델 간 비교: " + r["agree_line"])
    return 0


def cmd_fill(a):
    from .fill import fill
    with open(a.values, encoding="utf-8-sig") as f:
        vals = json.load(f)
    r = fill(a.form, vals, a.out)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["verify"]["ok"] and not r["missing"] else 1


def cmd_replace(a):
    from .edit import replace_text
    with open(a.mapping, encoding="utf-8-sig") as f:
        m = json.load(f)
    r = replace_text(a.doc, m, a.out)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["verify"]["ok"] and not r["not_found"] else 1


def _settler(a):
    """--archive 가 있을 때만 제자리 교체·원본 보관 기능을 켠다(기본 꺼짐)."""
    if not getattr(a, "archive", None):
        return None
    from .settle import Settler
    arc = a.archive
    if arc.lower() == "auto":  # 따로 정하지 않으면 원본 폴더 옆 〈폴더〉_원본보관 (폴더 밖)
        from .batch import outside_out
        arc = outside_out(a.path, "_원본보관")
    kd = getattr(a, "keep_days", None)
    kd = 30 if kd is None else (kd or None)   # 안 주면 30일, 0 이면 무기한(삭제 예정일 없음)
    return Settler(arc, keep_days=kd, verdicts=a.settle_verdicts.split(","))


def cmd_watch(a):
    if not getattr(a, "archive", None) and not getattr(a, "no_settle", False):
        a.archive = "auto"   # 자동화 기본: 검증 PASS 문서는 제자리 교체 + 원본 보관(끄려면 --no-settle)
    from .batch import watch
    from .batch import default_out
    out = a.out or default_out(a.path)
    print(f"폴더 감시: {a.path} → {out} ({a.interval:.0f}초마다, 끝내려면 Ctrl+C)")
    try:
        st = _settler(a)
        if st is not None:
            print(f"원본 보관: {st.archive}" + (f" · {st.keep_days}일 뒤 삭제 예정 기록" if st.keep_days is not None else " · 무기한") + (" · 기한 지난 원본 자동 정리" if getattr(a, 'auto_purge', False) else ""))
        watch(a.path, out, a.interval, a.rounds, jobs=a.jobs, settle=st, auto_purge=st if getattr(a, 'auto_purge', False) else None)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_check(a):
    from .check import check
    rows = check(a.path, a.out, a.mask)
    for r in rows:
        print(f"[{r['verdict']}] {r['file']} — 가독성 {r.get('score')} · 공개구분 {r.get('disclosure', '')} · 개인정보 {r.get('pii_count', 0)}"
              + (f" · {' / '.join(r['reasons'])}" if r.get("reasons") else ""))
    if a.out:
        print(f"결과: {os.path.join(a.out, 'AI투입점검.xlsx')}")
    return 0


def cmd_corpus(a):
    from .corpus import write_corpus
    if os.path.isdir(a.path):   # 폴더: 하위 폴더까지 HWP·HWPX 마다 조각을 만들고 폴더 구조를 그대로 둔다
        n = bad = 0
        for dp, dns, fns in os.walk(a.path):
            dns.sort()
            for fn in sorted(fns):
                if not fn.lower().endswith((".hwp", ".hwpx")):
                    continue
                src = os.path.join(dp, fn)
                out = os.path.normpath(os.path.join(a.out, os.path.relpath(dp, a.path)))
                try:
                    r = write_corpus(src, out); n += 1
                    print(f"[{r['status']}] {r['chunks']}개 조각 — {r['corpus']}")
                except Exception as e:   # 한 파일이 막혀도(확인 요청·손상) 나머지는 계속
                    bad += 1
                    print(f"[건너뜀] {fn}: {str(e)[:160]}")
        print(f"폴더 처리: 조각 만든 문서 {n}건, 건너뛴 문서 {bad}건 — {a.out}")
        return 0 if n else 1
    r = write_corpus(a.path, a.out)
    print(f"[{r['status']}] {r['chunks']}개 조각 — {r['corpus']}")
    print(f"품질 점검: {r['quality']}")
    return 0


def cmd_doctor(a):
    from .doctor import run
    return 3 if run(sample=not a.no_sample).failed else 0


def cmd_open(a):
    from .opener import open_hwp
    return open_hwp(a.path)


def cmd_mcp_setup(a):
    from . import mcp_setup as ms
    if a.action == "status":
        for t in (["claude", "chatgpt"] if a.target == "all" else [a.target]):
            print(ms.status(t))
        return 0
    targets = ["claude", "chatgpt"] if a.target == "all" else [a.target]
    for t in targets:
        msg = ms.install(t, yes=a.yes) if a.action == "install" else ms.remove(t, yes=a.yes)
        print(msg)
    return 0


def cmd_review(a):
    from . import review as rv
    if a.action == "make":
        print(rv.make(a.path, a.out))
    elif a.action == "decide":
        if a.all_action:
            print(rv.decide(a.path, None, None, a.all_action))
        else:
            print(rv.decide(a.path, a.ids, a.decision))
    elif a.action == "apply":
        print(rv.apply(a.path, a.by))
    elif a.action == "add":
        print(rv.add(a.path, a.text, a.kind))
    return 0


def cmd_cert(a):
    from .cert import make_certificate
    r = make_certificate(a.original, a.converted, a.out, a.title, a.ref)
    print(f"[{r['verdict']}] 보존 증명서: {r['path']}")
    return 0 if r["verdict"] == "PASS" else 1


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(prog="hwpai", description="HWP·HWPX 를 AI 가 바로 쓰는 어댑터 + 한글 없는 일괄 HWPX 변환·검증")
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("read", help="문서 하나를 마크다운·표 CSV·청크로")
    r.add_argument("path")
    r.add_argument("--out")
    r.set_defaults(fn=cmd_read)
    c = sp.add_parser("convert", help="폴더·파일 일괄 변환")
    c.add_argument("path")
    c.add_argument("--to", choices=["hwpx", "md"], default="hwpx")
    c.add_argument("--out")
    c.add_argument("--engine", default="auto", help="auto | rhwp-wasm | rhwp-cli")
    c.add_argument("--timeout", type=float, default=120.0, help="파일 하나 시간 한도(초)")
    c.add_argument("--jobs", type=int, default=1, help="동시 변환 수(엔진 일꾼 수)")
    c.add_argument("--password", help="열기 암호(모든 파일 공통). 환경변수 HWPAI_PASSWORD 도 됨")
    c.add_argument("--password-file", help="CSV: 상대경로,암호")
    c.add_argument("--include-hwpx", action="store_true", help="이미 HWPX 인 파일도 다시 저장·검증")
    c.add_argument("--retry-failed", action="store_true", help="이어하기 때 실패·격리 건도 다시 시도")
    c.add_argument("--reverify", action="store_true", help="이어하기 때 이미 변환된 파일의 검증서만 새로 만듦")
    c.add_argument("--no-verify", action="store_true", help="검증서 생략(빠름)")
    c.add_argument("--no-quarantine-copy", action="store_true", help="실패 원본을 _격리 에 복사하지 않음")
    c.add_argument("--limit", type=int)
    c.add_argument("--archive", help="(선택) 변환·검증(PASS)이 끝난 문서는 원래 자리에 .hwpx 를 두고 원본 .hwp 는 이 보관 폴더로 옮김. auto 라고 쓰면 원본 폴더 옆 〈폴더〉_원본보관. 기본 꺼짐")
    c.add_argument("--keep-days", type=int, help="보관한 원본의 삭제 예정일을 이 일수 뒤로 기록(기본 30, 예: 90·180, 0=무기한). 실제 삭제는 purge 명령만 한다")
    c.add_argument("--settle-verdicts", default="PASS", help="제자리 교체를 허용할 판정(쉼표, 기본 PASS)")
    c.set_defaults(fn=cmd_convert)
    d = sp.add_parser("audit", help="원본과 변환본 대조 검증서")
    d.add_argument("original")
    d.add_argument("converted")
    d.add_argument("--out", help="검증서 파일 이름(확장자 없이) — .md 와 .json 을 만든다")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_audit)
    e = sp.add_parser("engines", help="변환 엔진 설치 점검")
    e.set_defaults(fn=cmd_engines)
    dr = sp.add_parser("doctor", help="설치 점검 + 시험 변환·검증 (한국어 원인·해결 안내)")
    dr.add_argument("--no-sample", action="store_true")
    dr.set_defaults(fn=cmd_doctor)
    g = sp.add_parser("gui", help="내 컴퓨터 안에서만 열리는 화면(폴더 선택·진행률·판정 표·검증서)")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")
    g.set_defaults(fn=cmd_gui)
    m = sp.add_parser("mcp", help="MCP 서버(표준입출력) — AI 앱이 띄운다")
    m.set_defaults(fn=cmd_mcp)
    mi = sp.add_parser("mcp-install", help="AI 앱(Claude 데스크톱) 설정에 hwpai MCP 서버 등록")
    mi.add_argument("--config", help="설정 파일 경로(기본: 운영체제별 Claude 데스크톱 위치)")
    mi.add_argument("--print", action="store_true", help="파일을 고치지 않고 들어갈 설정만 보여 줌")
    mi.set_defaults(fn=cmd_mcp_install)
    q = sp.add_parser("ask", help="문서에 질문(OpenAI 호환 모델 아무거나, 여러 모델 비교)")
    q.add_argument("path")
    q.add_argument("question")
    q.add_argument("--profiles", help="모델 설정 JSON")
    q.add_argument("--profile", action="append", help="쓸 프로필 이름(여러 번 가능, 비우면 전부)")
    q.add_argument("--top-k", type=int, default=5)
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_ask)
    fl = sp.add_parser("fill", help="HWPX 양식 칸 채우기(서식 유지) + 되읽기 검증")
    fl.add_argument("form")
    fl.add_argument("values", help="값 JSON 파일 {키: 값}")
    fl.add_argument("--out")
    fl.set_defaults(fn=cmd_fill)
    rp = sp.add_parser("replace", help="HWPX 서식 보존 텍스트 치환 + 변경 보고서(원본 보존, 새 파일)")
    rp.add_argument("doc")
    rp.add_argument("mapping", help="치환 JSON 파일 {찾는글: 바꿀글}")
    rp.add_argument("--out")
    rp.set_defaults(fn=cmd_replace)
    mt = sp.add_parser("meta", help="문서 속성(작성자·단체·제목 등) 점검 + HWPX 속성 비우기(--scrub)")
    mt.add_argument("path")
    mt.add_argument("--scrub", help="HWPX 결과 파일(속성을 비운 새 파일)")
    mt.set_defaults(fn=lambda a: __import__("hwpai.meta", fromlist=["cmd_meta"]).cmd_meta(a))
    ac = sp.add_parser("aicheck", help="AI 친화도 점검 보고서(병합 칸·그림 설명·글상자·개요 등)")
    ac.add_argument("path")
    ac.add_argument("--out")
    ac.set_defaults(fn=lambda a: __import__("hwpai.aicheck", fromlist=["cmd_aicheck"]).cmd_aicheck(a))
    vs = sp.add_parser("visual", help="변환 전후 시각 비교 보고서(HTML): 쪽 수·쪽별 글·그림 대조 + 나란히 보기")
    vs.add_argument("orig")
    vs.add_argument("conv")
    vs.add_argument("--out")
    vs.add_argument("--pages", type=int, default=12)
    vs.add_argument("--embed", action="store_true", help="쪽 그림을 HTML 안에 넣는다(파일 하나, 큰 문서는 매우 커짐)")
    vs.set_defaults(fn=lambda a: __import__("hwpai.visual", fromlist=["cmd_visual"]).cmd_visual(a))
    cx = sp.add_parser("ctxmenu", help="[선택 기능·기본 꺼짐] 탐색기 우클릭 「HWPX로 변환」 메뉴(.reg 만들기 / --apply·--remove)")
    cx.add_argument("--root", help="hwpai.bat 이 있는 폴더")
    cx.add_argument("--out", help=".reg 파일을 둘 폴더")
    cx.add_argument("--apply", action="store_true")
    cx.add_argument("--remove", action="store_true")
    cx.set_defaults(fn=lambda a: __import__("hwpai.ctxmenu", fromlist=["cmd_ctxmenu"]).cmd_ctxmenu(a))
    ex = sp.add_parser("export", help="Markdown·구조화 JSON·RAG 청크 파일 출력(--ai-folder: 확인 전 문서는 쓰지 않음)")
    ex.add_argument("path")
    ex.add_argument("--out")
    ex.add_argument("--formats", default="md,json,chunks")
    ex.add_argument("--ai-folder", action="store_true", help="결과 폴더를 AI 가 읽는다 — 민감정보 확인 전 문서는 쓰지 않고 확인 대기 목록에 올림")
    ex.set_defaults(fn=lambda a: __import__("hwpai.export", fromlist=["cmd_export"]).cmd_export(a))
    dp = sp.add_parser("drop", help="끌어놓기 — 폴더·파일 여러 개를 한 번에 HWPX 변환(〈원본〉_hwpx변환), 끝나면 결과·요약 열기")
    dp.add_argument("paths", nargs="+")
    dp.add_argument("--jobs", type=int, default=2)
    dp.add_argument("--no-open", action="store_true", help="끝나도 결과 폴더·요약을 열지 않음")
    dp.add_argument("--json", action="store_true")
    dp.add_argument("--archive", help="보관 폴더(기본 auto=〈폴더〉_원본보관). 끌어놓기는 기본으로 제자리 교체 + 원본 보관")
    dp.add_argument("--keep-days", type=int, default=None, help="보관 원본 삭제 예정일까지의 일수(기본 30, 90=3개월, 180=6개월, 0=무기한)")
    dp.add_argument("--no-settle", action="store_true", help="제자리 교체를 끄고 예전처럼 원본 불변 + 〈폴더〉_hwpx변환 에만 저장")
    dp.set_defaults(fn=lambda a: __import__("hwpai.drop", fromlist=["cmd_drop"]).cmd_drop(a))
    w = sp.add_parser("watch", help="폴더 감시 — 새로 들어온·바뀐 HWP 를 자동으로 HWPX 변환·검증")
    w.add_argument("path")
    w.add_argument("--out")
    w.add_argument("--interval", type=float, default=30.0)
    w.add_argument("--rounds", type=int, help="이만큼만 돌고 끝냄(시험용)")
    w.add_argument("--jobs", type=int, default=1)
    w.add_argument("--archive", help="(선택) 변환·검증(PASS)이 끝난 문서는 원래 자리에 .hwpx 를 두고 원본 .hwp 는 이 보관 폴더로 옮김. auto 라고 쓰면 원본 폴더 옆 〈폴더〉_원본보관. 기본 꺼짐")
    w.add_argument("--keep-days", type=int, help="보관한 원본의 삭제 예정일을 이 일수 뒤로 기록(기본 30, 예: 90·180, 0=무기한). 실제 삭제는 purge 명령만 한다")
    w.add_argument("--no-settle", action="store_true", help="감시 기본인 제자리 교체·원본 보관을 끈다(예전처럼 원본 불변)")
    w.add_argument("--settle-verdicts", default="PASS", help="제자리 교체를 허용할 판정(쉼표, 기본 PASS)")
    w.add_argument("--auto-purge", action="store_true", help="(선택) 매 주기 보관 기한이 지난 원본을 정리 — 조건(제자리 HWPX 그대로·원본 해시 같음)을 확인한 것만 삭제")
    w.set_defaults(fn=cmd_watch)
    pg = sp.add_parser("purge", help="보관 폴더에서 삭제 예정일이 지난 원본 HWP 정리(기본은 미리보기, --yes 로 실제 삭제)")
    pg.add_argument("archive")
    pg.add_argument("--yes", action="store_true", help="미리보기가 아니라 실제로 삭제")
    pg.set_defaults(fn=lambda a: __import__("hwpai.settle", fromlist=["cmd_purge"]).cmd_purge(a))
    ck = sp.add_parser("check", help="AI 투입 점검(개인정보·공개구분·공문 구조·가독성) + 가림본")
    ck.add_argument("path")
    ck.add_argument("--out")
    ck.add_argument("--mask", action="store_true", help="개인정보를 가린 마크다운·청크를 --out 에 씀")
    ck.set_defaults(fn=cmd_check)
    cp = sp.add_parser("corpus", help="학습자료용 출처 붙은 조각(JSONL) + 품질 점검(OK·REVIEW·BAD)")
    cp.add_argument("path")
    cp.add_argument("--out", required=True)
    cp.set_defaults(fn=cmd_corpus)
    ms = sp.add_parser("mcp-setup", help="AI 앱(Claude·ChatGPT 데스크톱)에 hwpai 등록·해제 — 승인 후에만 설정을 바꾼다")
    ms.add_argument("action", choices=["status", "install", "remove"])
    ms.add_argument("--target", default="all", choices=["claude", "chatgpt", "all"])
    ms.add_argument("--yes", action="store_true", help="확인 질문 없이 진행 (직접 승인한 뒤에만 사용)")
    ms.set_defaults(fn=cmd_mcp_setup)
    rvp = sp.add_parser("review", help="개인정보 가림 — 후보 검토(사람 확정) 후에만 확정본 작성")
    rvp.add_argument("action", choices=["make", "decide", "apply", "add"])
    rvp.add_argument("path", help="make: 문서 / decide·apply: 검토.json")
    rvp.add_argument("--out", help="make: 검토 폴더")
    rvp.add_argument("--ids", type=int, nargs="*", help="decide: 후보 번호들")
    rvp.add_argument("--decision", choices=["가림", "남김"], help="decide: 결정")
    rvp.add_argument("--all", dest="all_action", choices=["가림", "남김"], help="decide: 모든 후보에 같은 결정")
    rvp.add_argument("--by", help="apply: 확정자 이름")
    rvp.add_argument("--text", help="add: 놓친 글자 그대로")
    rvp.add_argument("--kind", default="기타", help="add: 종류 (성명·전화·이메일·주소·기타 등)")
    rvp.set_defaults(fn=cmd_review)
    op = sp.add_parser("open", help="HWP 를 HWPX 로 변환·검증한 뒤 연다 (원본 보존)")
    op.add_argument("path")
    op.set_defaults(fn=cmd_open)
    ce = sp.add_parser("cert", help="보존 증명서 — 원본·변환본 해시 + 줄 단위 대조 + 감사 판정")
    ce.add_argument("original")
    ce.add_argument("converted")
    ce.add_argument("--ref", help="한글이 내보낸 텍스트(전문) 파일 — 있으면 줄 단위 대조")
    ce.add_argument("--out", required=True, help="증명서·검증서를 쓸 폴더")
    ce.add_argument("--title", help="증명서 제목(기본: 파일 이름)")
    ce.set_defaults(fn=cmd_cert)
    sa = sp.add_parser("scan-all", help="[선택 기능·기본 꺼짐] 내 컴퓨터 전체의 HWP 를 미리보기 확인 후 HWPX 로 변환(원본 읽기 전용)")
    sa.add_argument("--roots", nargs="+", help="훑을 드라이브·폴더(기본: 모든 고정 드라이브)")
    sa.add_argument("--out", help="결과 폴더(기본: 내 폴더의 hwpai_전체변환). 원본 폴더 구조 그대로")
    sa.add_argument("--preview-only", action="store_true", help="미리보기만 하고 변환하지 않음")
    sa.add_argument("--yes", action="store_true", help="확인 질문 없이 진행(무인 실행). 기본은 확인")
    sa.add_argument("--beside", action="store_true", help="결과를 원본 옆 〈같은 이름〉.hwpx 로도 둠(덮어쓰기 없음, 있으면 번호)")
    sa.add_argument("--window", help="작업 시간대 HH:MM-HH:MM (예: 22:00-06:00, 밖에서는 기다림)")
    sa.add_argument("--jobs", type=int, default=1, help="동시 변환 수(기본 1 — CPU 부하 제한)")
    sa.add_argument("--max-files", type=int, help="미리보기·변환 상한(시험용)")
    sa.set_defaults(fn=lambda a: __import__("hwpai.scanall", fromlist=["cmd_scan_all"]).cmd_scan_all(a))
    ins = sp.add_parser("install", help="설치 단계 옵션(기본: 아무것도 하지 않음). --scan-all 로 「내 컴퓨터 전체 변환」 옵션을 켠다")
    ins.add_argument("--scan-all", action="store_true")
    ins.add_argument("--yes", action="store_true")
    ins.set_defaults(fn=lambda a: __import__("hwpai.scanall", fromlist=["cmd_install"]).cmd_install(a))
    sn = sp.add_parser("sens", help="민감정보 확인 — 검출은 차단이 아니라 확인 요청. scan|review|decide|apply")
    sn.add_argument("action", choices=["scan", "review", "decide", "apply"])
    sn.add_argument("path", nargs="?", help="문서 또는 폴더")
    sn.add_argument("--out", help="review: 검토 화면(HTML) 파일")
    sn.add_argument("--decisions", help="apply: 화면이 내려받은 민감확인_결정.json")
    sn.add_argument("--set", choices=["sensitive", "not_sensitive"], help="decide: 일괄 결정")
    sn.add_argument("--kind", help="decide: 이 종류만")
    sn.add_argument("--policy", choices=["mask", "block"], default="block", help="민감정보 있음 문서의 AI 노출: mask 가려서 / block 막기")
    sn.add_argument("--reviewer", help="확인자 이름(기본: 로그인 이름)")
    sn.add_argument("--store", help="확인 결과 저장 폴더(기본 ./hwpai_등급기록)")
    sn.set_defaults(fn=lambda a: __import__("hwpai.sens", fromlist=["cmd_sens"]).cmd_sens(a))
    # 보안등급 게이트 — 문서를 읽는 명령에만 적용. 등급을 주지 않으면 차단(기본 거부).
    for name in DOC_CMDS:
        if name in sp.choices:
            add_grade_args(sp.choices[name])
    a = ap.parse_args(argv)
    # check 는 개인정보를 찾아 가림본을 만드는 명령이라 게이트를 걸지 않는다 (가린 뒤 다시 넣는 길을 막지 않기 위해)
    if a.cmd in DOC_CMDS and a.cmd != "check":
        from .grade import Gate, GradeBlocked, load_grades, set_active
        a.gate = Gate(grades=load_grades(a.grade_file), default=a.grade, exception=a.exception,
                      mode="cli", logdir=a.grade_log, policy=getattr(a, "grade_policy", "review"))
        set_active(a.gate, tool=a.cmd)
        try:
            return a.fn(a)
        except GradeBlocked as e:
            print(str(e), file=sys.stderr)
            print("→ 확인 요청: 사람이 `hwpai.bat sens review <폴더>`로 확인하면 AI로 보낼 수 있습니다. 공개 문서라면 `--grade 공개`, 민감·기밀 문서는 --grade-file 로 등급을 지정하세요.", file=sys.stderr)
            return 4
    return a.fn(a)


DOC_CMDS = ("read", "export", "replace", "aicheck", "visual", "convert", "drop", "scan-all", "audit", "cert", "check", "corpus", "ask", "review", "fill", "watch", "open")


def add_grade_args(p):
    g = p.add_argument_group("보안등급 (공공데이터 AI 친화 관리 가이드라인의 3단계 등급 구분을 참고)")
    g.add_argument("--grade", choices=["공개", "민감", "기밀"],
                   help="이 문서(또는 이 실행의 모든 문서)의 등급. 없으면 아래 정책을 따름")
    g.add_argument("--grade-file", help="파일별 등급 CSV: 경로,등급[,예외사유·승인자]")
    g.add_argument("--exception", help="민감 등급 예외 처리의 사유·승인자 (사람이 적는다). 기밀은 예외 없음")
    g.add_argument("--grade-log", help="등급_기록.jsonl 을 쓸 폴더 (기본: ./hwpai_등급기록)")
    g.add_argument("--grade-policy", choices=["review", "pii", "pii-strict", "deny"], default="review",
                   help="등급 미표기 문서 정책. review(기본): 개인정보 꼴이 있어도 변환은 하고, AI 에 보이는 길(ask·MCP·export --ai-folder)만 사람이 확인한 뒤에 연다 · (이전 차단형) pii: 개인정보가 있으면 변환하지 않음(유선 전화번호만이면 허용) · pii-strict: 유선 전화번호도 차단 · deny: 등급 없으면 차단")


if __name__ == "__main__":
    sys.exit(main())
