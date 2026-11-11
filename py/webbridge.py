"""hwpai 웹 버전 — 브라우저(Pyodide) 안에서 hwpai 본체(변경 없이 복사한 hwpai/*.py)를 부르는 얇은 겹.

본체 코드는 바꾸지 않는다. 바꾼 것은 둘뿐이다.
  1) 변환 엔진: Node 일꾼 대신 같은 rhwp wasm 을 브라우저(JS)에서 부른다(hwpaiConvert).
  2) 이어하기 대장·격리 사본: 브라우저에서는 쓰지 않는다(원본은 사용자 디스크에 그대로 있다).
처리 흐름(BatchConverter.process → 검증서 → 민감정보 검출)은 데스크톱판 batch.py 와 같은 함수를 부른다.
"""
from __future__ import annotations

import json
import os
import shutil
import time

ROOT = "/work"
LOG = ROOT + "/gradelog"
_cfg: dict = {}
_gate = None
_scan_cache: dict = {}


def _setup_modules():
    from hwpai import batch, engines, sens

    class WebEngine(engines.Engine):
        name = "rhwp-wasm"

        def __init__(self):
            self.version = _cfg.get("engine_version", "?")

        def convert(self, src, dst, timeout=120.0, password=None, **kw):
            import js
            t0 = time.perf_counter()
            r = js.hwpaiConvert(src, dst, password or None)
            r = r.to_py()
            if r.get("ok") and src:
                try:   # 데스크톱 엔진 래퍼와 같은 뒤처리(C86·C88·C90·C92·C93)
                    from hwpai import postfix
                    notes = postfix.apply_all(src, dst)
                    if notes:
                        r["notes"] = list(r.get("notes") or []) + notes
                    if postfix.ERRORS:
                        r["notes"] = list(r.get("notes") or []) + ["뒤처리 오류(진단): " + "; ".join(postfix.ERRORS[-3:])]
                        del postfix.ERRORS[:]
                except Exception as ex:
                    r["notes"] = list(r.get("notes") or []) + [f"뒤처리 오류(진단): {type(ex).__name__}: {str(ex)[:80]}"]
            r["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if not r.get("ok"):
                r.setdefault("kind", "engine_error")
            return r

    batch.get_engine = lambda pref="auto": WebEngine()
    engines.get_engine = batch.get_engine

    orig = sens.scan_file

    def cached(path, store=None):
        k = (path, os.path.getmtime(path), id(store))
        r = _scan_cache.get(k)
        if r is None:
            r = orig(path, store)
            _scan_cache.clear()
            _scan_cache[k] = r
        return r
    sens.scan_file = cached


def configure(cfg_json: str):
    """cfg: {policy, engine_version, include_hwpx, password, timeout}"""
    global _cfg, _gate
    _cfg = json.loads(cfg_json)
    if not getattr(configure, "_done", False):
        _setup_modules()
        configure._done = True
    from hwpai.grade import Gate, set_active
    os.makedirs(LOG, exist_ok=True)
    _gate = Gate(grades={}, default=None, mode="cli", logdir=LOG, policy=_cfg.get("policy", "review"))
    set_active(_gate, tool="convert")
    return "ok"


def put_records(records_json: str):
    """사람이 확인한 민감정보 결정(문서 SHA-256 → 기록)을 저장소에 넣는다(값은 없다: 종류·자리·길이·결정)."""
    recs = json.loads(records_json)
    d = os.path.join(LOG, "민감확인")
    os.makedirs(d, exist_ok=True)
    for sha, rec in recs.items():
        with open(os.path.join(d, sha + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    _scan_cache.clear()
    if _gate is not None:
        _gate._seen.clear()
    return len(recs)


def _sens_payload(path: str, with_text: bool = True):
    from hwpai import sens
    st = sens.scan_file(path, _gate.store)
    if st.get("state") is None:
        return {"state": None, "error": st.get("error")}
    out = {"state": st["state"], "pending": st["pending"], "total": st["total"], "sensitive": st["sensitive"],
           "probably_ok": st["probably_ok"], "kinds": st["kinds"], "sha256": st["sha256"], "items": st["items"]}
    if with_text and st["items"]:
        out["text"] = st["text"]
    return out


def process(job: str, rel: str, dst_rel: str, opts_json: str) -> str:
    """파일 하나. 입력은 /work/<job>/in/<rel> 에 있다. 결과는 /work/<job>/out 아래에 쓰고, 행(row)과 민감정보 검출을 돌려준다."""
    from hwpai import batch
    opts = json.loads(opts_json)
    base = f"{ROOT}/{job}"
    src_root, out = base + "/in", base + "/out"
    os.makedirs(out, exist_ok=True)

    class _L:
        rows: dict = {}
    bc = batch.BatchConverter(src_root, out, timeout=float(opts.get("timeout", 120)), jobs=1,
                              password=opts.get("password") or None, verify=True, quarantine_copy=False,
                              include_hwpx=bool(opts.get("include_hwpx")), gate=_gate, log=None)
    bc._dst_rel = {rel: dst_rel}
    abs_in = os.path.join(src_root, rel)
    d = _gate.check(rel, abs_in, tool="convert")
    if not d["allowed"]:
        row = {"원본": rel, "상태": "등급차단", "판정": "", "처리시각": batch._now(),
               "판정_이유": f"{d['decision']}: {d['reason']}"[:300]}
        return json.dumps({"row": row, "blocked": True}, ensure_ascii=False)
    if d.get("sens_state"):
        bc._sens[rel] = d
    if d["suffix"]:
        pass  # 예외허용(민감 등급)은 웹에서 쓰지 않는다 — 등급 파일이 없다
    try:
        row = bc.process(rel, _L())
    except Exception as e:  # 데스크톱 run() 과 같이 그 파일만 실패로
        row = {"원본": rel, "상태": batch.STATUS_FAIL, "판정": "FAIL", "처리시각": batch._now(),
               "판정_이유": f"처리 오류: {type(e).__name__}: {e}"[:300]}
    row.pop("_total_ms", None)
    row.pop("_resumed", None)
    sd = bc._sens.get(rel)
    if sd:
        row["민감정보"] = sd.get("sens_state") or ""
        kinds = sd.get("sens_kinds") or {}
        row["민감정보_항목"] = ", ".join(f"{k} {v}" for k, v in kinds.items()) + (
            f" (추정 비민감 {sd['sens_probably_ok']}건)" if sd.get("sens_probably_ok") else "")
    res = {"row": row, "blocked": False}
    try:
        res["sens"] = _sens_payload(abs_in)
    except Exception as e:
        res["sens"] = {"state": None, "error": f"{type(e).__name__}: {e}"[:200]}
    res["files"] = []
    for dp, _dns, fns in os.walk(out):
        for fn in fns:
            res["files"].append(os.path.relpath(os.path.join(dp, fn), out).replace("\\", "/"))
    return json.dumps(res, ensure_ascii=False, default=str)


def export_doc(job: str, rel: str, formats_json: str, ai_folder: bool) -> str:
    """Markdown·구조 JSON·RAG 조각. 데스크톱 export.export_doc 를 그대로 부른다."""
    from hwpai import export, grade
    base = f"{ROOT}/{job}"
    outdir = base + "/export"
    os.makedirs(outdir, exist_ok=True)
    grade.set_active(_gate, tool="export")
    r = export.export_doc(os.path.join(base, "in", rel), outdir, tuple(json.loads(formats_json)), bool(ai_folder))
    files = []
    for dp, _dns, fns in os.walk(outdir):
        for fn in fns:
            files.append(os.path.relpath(os.path.join(dp, fn), outdir).replace("\\", "/"))
    r["files"] = files
    return json.dumps(r, ensure_ascii=False, default=str)


def finalize(job: str, rows_json: str, order_json: str, wall: float) -> str:
    """이관대장(csv·jsonl·xlsx)과 요약.md 를 데스크톱판과 같은 함수로 만든다."""
    from hwpai import batch
    rows_in = json.loads(rows_json)
    for r in rows_in:  # JS 를 오가며 100.0 이 100 이 된 점수를 본래 꼴(소수 한 자리)로 되돌린다
        v = r.get("검증점수")
        if isinstance(v, int) and not isinstance(v, bool):
            r["검증점수"] = float(v)
    order = json.loads(order_json)
    out = f"{ROOT}/{job}/final"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    ledger = batch.Ledger(out)
    for r in rows_in:
        ledger.add(r)
    rows = ledger.write_csv(order)
    blocked = sum(1 for r in rows if r.get("상태") == "등급차단")
    stats = {"files": len(rows) - blocked, "resumed": 0, "wall_seconds": round(wall, 1)}
    stats.update(batch.summarize(rows))
    batch.write_summary(out, stats, rows)
    try:
        from hwpai.xlsx import ledger_xlsx
        ledger_xlsx(os.path.join(out, "이관대장.xlsx"), batch.COLUMNS, rows,
                    {"대상": stats["files"], "걸린 시간(초)": stats["wall_seconds"],
                     **{f"상태 {k}": v for k, v in stats["status"].items()},
                     **{f"판정 {k}": v for k, v in stats["verdict"].items()},
                     **{f"이유 {k}": v for k, v in stats["reason_codes"].items()}})
    except Exception:
        pass
    return json.dumps({"stats": stats, "files": sorted(os.listdir(out))}, ensure_ascii=False, default=str)


def cleanup(job: str):
    shutil.rmtree(f"{ROOT}/{job}", ignore_errors=True)
    return "ok"
