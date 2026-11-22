"""기관 단위 일괄 변환·이관 대장.

  python -m hwpai convert <폴더|파일> --to hwpx [--out 출력폴더] [--jobs 2] [--timeout 120]

출력 폴더
  <원본 상대경로>.hwpx      변환본 (원본 폴더 구조 그대로)
  _검증서/<상대경로>.md|json 파일별 변환 검증서 (hwpai.audit)
  이관대장.csv              파일마다 한 줄 — 원본 해시·크기·형식·엔진·소요·검증점수·판정·이유
  이관대장.jsonl            처리 기록(한 줄씩 덧붙임) — 이어하기의 근거. 중간에 끊겨도 남는다
  _격리/                    변환하지 못한 원본의 사본(사유별 폴더)
  요약.md                   판정 분포·실패 사유·사람 확인 목록

이어하기: 같은 출력 폴더로 다시 실행하면 이관대장.jsonl 을 읽어, 원본 해시가 같고 변환본이
         그대로 있는 파일은 건너뛴다. 실패·격리 건은 --retry-failed 를 줄 때만 다시 한다.
실패 격리: 파일 하나의 손상·시간 초과·엔진 비정상 종료가 나머지에 번지지 않는다(엔진 일꾼 재시작).

특수 문서 처리 경로
  HWP 3.0        엔진(rhwp)이 변환. 원본 독립 판독은 hwpai 미지원 → 검증서 WARN(미검증) 표시
  열기 암호      --password(모든 파일 공통) 또는 --password-file(CSV: 상대경로,암호)로 엔진이 열어 변환.
                 암호가 없으면 격리(사유: 열기 암호). 원본 미리보기 글은 대장에 남지 않는다(보안).
  배포용 문서    엔진이 변환. 검증은 hwpai 가 배포용 본문(ViewText)을 풀어 대조
  DRM            격리(기관 DRM 해제 후 재시도). 변환 시도하지 않음
  손상·형식 아님 격리(빈 파일·OLE 손상·HWP 가 아닌 OLE·ZIP 손상)
  이미 HWPX      건너뜀(--include-hwpx 를 주면 엔진으로 다시 저장해 정규화·검증)
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import audit as _audit
from .engines import EngineMissing, get_engine

COLUMNS = ["순번", "원본", "원본_SHA256", "원본_크기", "원본_형식", "특성", "상태", "엔진", "엔진_판",
           "변환_소요ms", "변환본", "변환본_SHA256", "변환본_크기", "엔진_손실보고", "검증점수", "판정",
           "판정_이유", "검증서", "처리시각", "민감정보", "민감정보_항목"]
STATUS_DONE, STATUS_SKIP, STATUS_FAIL, STATUS_QUAR = "변환완료", "건너뜀", "변환실패", "격리"
SRC_EXT = (".hwp", ".hwpx")
OUT_SUFFIX = "_hwpx변환"  # 결과 폴더 = 〈원본 폴더〉_hwpx변환 (원본 폴더 밖)


def default_out(path: str) -> str:
    p = os.path.abspath(path)
    return (os.path.splitext(p)[0] if os.path.isfile(p) else p.rstrip("/\\")) + OUT_SUFFIX


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def scan(src: str, include_hwpx: bool) -> list[str]:
    if os.path.isfile(src):
        return [os.path.basename(src)]
    out = []
    for dp, dns, fns in os.walk(src):
        dns[:] = sorted(d for d in dns if not d.startswith((".", "_검증서", "_격리")))
        for f in sorted(fns):
            ext = os.path.splitext(f)[1].lower()
            if ext == ".hwp" or (ext == ".hwpx"):
                out.append(os.path.relpath(os.path.join(dp, f), src))
    return out


def _dst_name(rel: str) -> str:
    """원본 상대경로 → 변환본 상대경로(확장자만 .hwpx). 겹치면 run() 이 「 (2)」를 붙인다."""
    return os.path.splitext(rel)[0] + ".hwpx"


def _traits(sn: dict) -> str:
    t = []
    for k, nm in (("encrypted", "암호"), ("distribute", "배포용"), ("drm", "DRM")):
        if sn.get(k):
            t.append(nm)
    if sn.get("version"):
        t.append("v" + sn["version"])
    return "·".join(t)


def load_passwords(path: str | None) -> dict:
    if not path:
        return {}
    pw = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                pw[os.path.normpath(row[0].strip())] = row[1]
    return pw


class Ledger:
    """이관대장 — jsonl 덧붙임(이어하기 근거) + csv 재생성."""

    def __init__(self, outdir: str):
        self.outdir = outdir
        self.jl = os.path.join(outdir, "이관대장.jsonl")
        self.csvp = os.path.join(outdir, "이관대장.csv")
        self.lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        if os.path.exists(self.jl):
            with open(self.jl, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        self.rows[r["원본"]] = r
                    except (json.JSONDecodeError, KeyError):
                        continue  # 끊긴 마지막 줄 등

    def add(self, row: dict):
        with self.lock:
            self.rows[row["원본"]] = row
            with open(self.jl, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def write_csv(self, order: list[str]):
        with self.lock:
            rows = [self.rows[r] for r in order if r in self.rows]
            rows += [v for k, v in self.rows.items() if k not in set(order)]
            tmp = self.csvp + ".part"
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:  # 엑셀에서 바로 열리게 BOM
                w = csv.DictWriter(f, COLUMNS, extrasaction="ignore")
                w.writeheader()
                for i, r in enumerate(rows, 1):
                    w.writerow({**r, "순번": i})
            os.replace(tmp, self.csvp)
            return rows


class BatchConverter:
    def __init__(self, src: str, outdir: str, engine: str = "auto", timeout: float = 120.0,
                 jobs: int = 1, password: str | None = None, password_file: str | None = None,
                 verify: bool = True, quarantine_copy: bool = True, include_hwpx: bool = False,
                 retry_failed: bool = False, reverify: bool = False, log=print, on_row=None, gate=None,
                 only: list | None = None, files: list | None = None):
        self.files = files  # 미리 구한 상대경로 목록(전체 변환용) — 없으면 폴더를 훑는다
        self.src = os.path.abspath(src)
        self.root = self.src if os.path.isdir(self.src) else os.path.dirname(self.src)
        self.outdir = os.path.abspath(outdir)
        self.engine_pref = engine
        self.timeout = timeout
        self.jobs = max(1, jobs)
        self.password = password
        self.passwords = load_passwords(password_file)
        self.verify = verify
        self.quarantine_copy = quarantine_copy
        self.include_hwpx = include_hwpx
        self.retry_failed = retry_failed
        self.reverify = reverify
        self.on_row = on_row  # (처리 수, 전체 수, 행) — 화면 진행률용
        self.only = [os.path.normpath(x) for x in only] if only else None  # 이 상대경로들만 처리(끌어놓기)
        self.gate = gate  # grade.Gate — 공개 등급만 통과 (없으면 게이트 없이 동작)
        self.blocked: list = []  # 등급 차단된 파일 (상대경로, 결정, 사유)
        self._sens: dict = {}   # 상대경로 → 민감정보 상태(확인 필요 등) — 변환 검증 판정과 별도
        self._suffix: dict = {}  # 예외허용 파일의 결과 이름 꼬리표
        self.log = log or (lambda *a, **k: None)
        self._local = threading.local()
        self._engines = []
        self._dst_rel: dict = {}
        self._elock = threading.Lock()

    # ---- 엔진(스레드마다 하나 — 각자 별도 프로세스)
    def _engine(self):
        e = getattr(self._local, "engine", None)
        if e is None:
            e = get_engine(self.engine_pref)
            self._local.engine = e
            with self._elock:
                self._engines.append(e)
        return e

    def _inherit(self, src: str, dst: str):
        if self.gate is not None:
            self.gate.inherit(src, dst)

    def _dst(self, rel: str) -> str:
        return os.path.join(self.outdir, self._dst_rel.get(rel) or _dst_name(rel))

    def _quarantine(self, rel, reason_dir):
        if not self.quarantine_copy:
            return ""
        d = os.path.join(self.outdir, "_격리", reason_dir, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        try:
            shutil.copy2(os.path.join(self.root, rel), d)
        except OSError:
            return ""
        return os.path.relpath(d, self.outdir)

    def _resume_skip(self, rel: str, sha: str, prev: dict | None) -> bool:
        if not prev or prev.get("원본_SHA256") != sha:
            return False
        if prev.get("상태") == STATUS_DONE:
            dst = os.path.join(self.outdir, prev.get("변환본", ""))
            return bool(prev.get("변환본")) and os.path.isfile(dst) and \
                os.path.getsize(dst) == int(prev.get("변환본_크기") or -1)
        if prev.get("상태") in (STATUS_FAIL, STATUS_QUAR):
            return not self.retry_failed
        return prev.get("상태") == STATUS_SKIP

    def process(self, rel: str, ledger: Ledger) -> dict:
        path = os.path.join(self.root, rel)
        t0 = time.perf_counter()
        sn = _audit.sniff(path)
        row = {"원본": rel, "원본_크기": sn.get("size", ""), "원본_형식": sn.get("format"),
               "특성": _traits(sn), "처리시각": _now()}
        try:
            row["원본_SHA256"] = sha256_file(path)
        except OSError as e:
            row.update(상태=STATUS_QUAR, 판정_이유=f"읽기 실패: {e}")
            return row
        prev = ledger.rows.get(rel)
        if self._resume_skip(rel, row["원본_SHA256"], prev):
            if self.reverify and prev.get("상태") == STATUS_DONE:
                # 변환은 그대로 두고 검증서만 새 판으로 다시 만든다(검증 규칙 갱신 시)
                dst = os.path.join(self.outdir, prev["변환본"])
                self._inherit(path, dst)
                a = _audit.audit(path, dst)
                base = os.path.join(self.outdir, "_검증서", rel)
                _audit.write_audit(a, base)
                return {**prev, "검증점수": "" if a.score is None else round(a.score, 1), "판정": a.verdict, "처리시각": _now(),
                        "판정_이유": " / ".join(f"{x['code']}: {x['msg']}" for x in a.reasons)[:500]}
            return {**prev, "_resumed": True}

        fmt = sn.get("format")
        if fmt == "hwpx" and not self.include_hwpx:
            row.update(상태=STATUS_SKIP, 판정_이유="이미 HWPX")
            return row
        if fmt in ("empty", "unknown", "ole-broken", "ole-not-hwp", "zip-broken", "zip-not-hwpx"):
            q = self._quarantine(rel, "손상_형식아님")
            row.update(상태=STATUS_QUAR, 판정_이유=f"손상·형식 아님({fmt})", 검증서=q)
            return row
        if sn.get("drm"):
            q = self._quarantine(rel, "DRM")
            row.update(상태=STATUS_QUAR, 판정_이유="DRM 문서 — 기관 DRM 해제 후 재시도", 검증서=q)
            return row
        pw = self.passwords.get(os.path.normpath(rel)) or self.password
        if sn.get("encrypted") and not pw:
            q = self._quarantine(rel, "열기암호")
            row.update(상태=STATUS_QUAR, 판정_이유="열기 암호 문서 — --password 또는 --password-file 로 재시도", 검증서=q)
            return row

        dst = self._dst(rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        eng = self._engine()
        # 암호가 주어지면 늘 넘긴다 — HWP 3.0 암호처럼 형식 판별로 못 가리는 경우가 있고,
        # rhwp 는 암호 없는 문서에 암호를 줘도 정상으로 연다(openWithPassword 설명)
        # 비배포 문서의 ViewText 글이 한글에 없는데 HWPX 에 들어가는 것을 막는다 (viewtext.py)
        from . import viewtext as _vt
        # 엔진 입력 사본 선택·변경 추적 전체 구조 모드·안 되면 다시 변환까지 한 함수(viewtext.convert_hwp)
        r = _vt.convert_hwp(eng, path, dst, timeout=self.timeout, password=pw)
        row.update(엔진=eng.name, 엔진_판=eng.version, 변환_소요ms=r.get("ms", ""))
        if not r.get("ok") and "비밀번호" in (r.get("error") or "") and not pw:
            # 형식 판별로 못 가린 암호 문서(HWP 3.0 암호 등) — 엔진이 알려 주면 암호 격리로
            q = self._quarantine(rel, "열기암호")
            row.update(상태=STATUS_QUAR, 판정_이유="열기 암호 문서(엔진 판별) — --password 또는 --password-file 로 재시도",
                       검증서=q)
            _rm_quiet(dst)
            return row
        if not r.get("ok"):
            kind = r.get("kind", "engine_error")
            sub = {"timeout": "시간초과", "crash": "엔진중단"}.get(kind, "엔진오류")
            q = self._quarantine(rel, sub)
            row.update(상태=STATUS_FAIL, 판정="FAIL", 판정_이유=f"{sub}: {r.get('error', '')[:200]}", 검증서=q)
            return row
        loss = r.get("loss") or {}
        row.update(상태=STATUS_DONE, 변환본=os.path.relpath(dst, self.outdir),
                   변환본_SHA256=sha256_file(dst), 변환본_크기=os.path.getsize(dst),
                   엔진_손실보고=loss.get("count", "") if isinstance(loss, dict) else "")
        if self.verify:
            self._inherit(path, dst)
            a = _audit.audit(path, dst, engine_report=loss if isinstance(loss, dict) else None)
            base = os.path.join(self.outdir, "_검증서", rel)
            _audit.write_audit(a, base)
            row.update(검증점수="" if a.score is None else round(a.score, 1), 판정=a.verdict,
                       판정_이유=" / ".join(f"{x['code']}: {x['msg']}" for x in a.reasons)[:500],
                       검증서=os.path.relpath(base + ".md", self.outdir))
        row["_total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return row

    def run(self, limit: int | None = None) -> dict:
        os.makedirs(self.outdir, exist_ok=True)
        files = list(self.files) if self.files is not None else scan(self.src, self.include_hwpx)
        if self.only is not None:
            keep = set(self.only)
            files = [f for f in files if os.path.normpath(f) in keep]
        if self.gate is not None:
            kept = []
            for rel in files:
                d = self.gate.check(rel, os.path.join(self.root, rel), tool="convert")
                if d["allowed"]:
                    kept.append(rel)
                    if d.get("sens_state"):
                        self._sens[rel] = d
                    if d["suffix"]:
                        self._suffix[rel] = d["suffix"]
                else:
                    self.blocked.append((rel, d["decision"], d["reason"]))
                    self.log(f"  차단 {rel}: {d['reason']}")
            files = kept
        if limit:
            files = files[:limit]
        # 출력 이름 겹침 방지: 「가.hwp」와 HWP 내용인 「가.hwpx」, 대소문자만 다른 「가.HWP」 등
        self._dst_rel, seen = {}, set()
        for rel in files:
            d = _dst_name(rel)
            if rel in self._suffix:
                d = os.path.splitext(d)[0] + self._suffix[rel] + ".hwpx"
            k, n = d.lower(), 2
            while k in seen:
                d = f"{os.path.splitext(_dst_name(rel))[0]} ({n}).hwpx"
                k, n = d.lower(), n + 1
            seen.add(k)
            self._dst_rel[rel] = d
        ledger = Ledger(self.outdir)
        for rel, dec, reason in self.blocked:  # 등급 차단 파일도 이관대장에 남긴다 (표 31 이력)
            brow = {"원본": rel, "상태": "등급차단", "판정": "", "처리시각": _now(),
                    "판정_이유": f"{dec}: {reason}"[:300]}
            ledger.add(brow)
            if self.on_row:  # 화면 표에도 차단 건을 바로 보인다(진행 수에는 넣지 않는다)
                try:
                    self.on_row(None, len(files), brow)
                except Exception:
                    pass
        # 엔진은 처음 쓸 때 띄운다 — 변환할 것이 없으면(전부 이어하기) 엔진 없이도 끝난다
        t0 = time.time()
        stats = {"files": len(files), "resumed": 0}
        done = [0]

        def work(rel):
            try:
                row = self.process(rel, ledger)
            except EngineMissing:
                raise
            except Exception as e:  # 예상 못 한 오류도 그 파일만 실패로
                row = {"원본": rel, "상태": STATUS_FAIL, "판정": "FAIL", "처리시각": _now(),
                       "판정_이유": f"처리 오류: {type(e).__name__}: {e}"[:300]}
            sd = self._sens.get(rel)
            if sd:
                row["민감정보"] = sd.get("sens_state") or ""
                kinds = sd.get("sens_kinds") or {}
                row["민감정보_항목"] = ", ".join(f"{k} {v}" for k, v in kinds.items()) + (
                    f" (추정 비민감 {sd['sens_probably_ok']}건)" if sd.get("sens_probably_ok") else "")
            if row.pop("_resumed", False):
                stats["resumed"] += 1
            else:
                row.pop("_total_ms", None)
                ledger.add(row)
            done[0] += 1
            if self.on_row:
                try:
                    self.on_row(done[0], len(files), row)
                except Exception:
                    pass
            if done[0] % 25 == 0 or done[0] == len(files):
                ledger.write_csv(files)
                self.log(f"  {done[0]}/{len(files)} 처리 ({time.time() - t0:.0f}초)")
            return row

        try:
            if self.jobs == 1:
                for rel in files:
                    work(rel)
            else:
                with ThreadPoolExecutor(self.jobs) as ex:
                    list(ex.map(work, files))
        finally:
            for e in self._engines:
                e.close()
        rows = ledger.write_csv(files)
        stats["wall_seconds"] = round(time.time() - t0, 1)
        stats.update(summarize(rows))
        write_summary(self.outdir, stats, rows)
        try:
            from .xlsx import ledger_xlsx
            ledger_xlsx(os.path.join(self.outdir, "이관대장.xlsx"), COLUMNS, rows,
                        {"대상": stats["files"], "걸린 시간(초)": stats["wall_seconds"],
                         **{f"상태 {k}": v for k, v in stats["status"].items()},
                         **{f"판정 {k}": v for k, v in stats["verdict"].items()},
                         **{f"이유 {k}": v for k, v in stats["reason_codes"].items()}})
        except Exception as e:  # 엑셀은 부가 산출물 — 실패해도 대장 CSV 는 남는다
            self.log(f"  엑셀 보고서 생략: {type(e).__name__}: {e}")
        return stats


def _rm_quiet(p):
    try:
        os.remove(p)
    except OSError:
        pass


def summarize(rows: list[dict]) -> dict:
    import collections
    st = collections.Counter(r.get("상태") for r in rows)
    vd = collections.Counter(r.get("판정") for r in rows if r.get("상태") == STATUS_DONE)
    codes = collections.Counter()
    for r in rows:
        for part in (r.get("판정_이유") or "").split(" / "):
            if ":" in part and r.get("상태") == STATUS_DONE:
                codes[part.split(":")[0].strip()] += 1
    fails = collections.Counter((r.get("판정_이유") or "").split(":")[0].split("(")[0]
                                for r in rows if r.get("상태") in (STATUS_FAIL, STATUS_QUAR))
    ms = [float(r["변환_소요ms"]) for r in rows if r.get("상태") == STATUS_DONE and r.get("변환_소요ms") not in ("", None)]
    sens = collections.Counter(r.get("민감정보") for r in rows if r.get("민감정보"))
    return {"sensitive": dict(sens), "status": dict(st), "verdict": dict(vd), "reason_codes": dict(codes.most_common()),
            "fail_kinds": dict(fails.most_common()),
            "convert_ms_total": round(sum(ms), 1), "convert_ms_median": sorted(ms)[len(ms) // 2] if ms else None,
            "bytes_in": sum(int(r.get("원본_크기") or 0) for r in rows if r.get("상태") == STATUS_DONE),
            "bytes_out": sum(int(r.get("변환본_크기") or 0) for r in rows if r.get("상태") == STATUS_DONE)}


def write_summary(outdir: str, s: dict, rows: list[dict]):
    L = ["# 일괄 변환 요약", "", f"- 대상 {s['files'] + s.get('status', {}).get('등급차단', 0)}개 (등급 게이트 차단 {s.get('status', {}).get('등급차단', 0)}개 제외, 변환 시도 {s['files']}개) · 이어하기로 건너뜀 {s.get('resumed', 0)}개 · 걸린 시간 {s['wall_seconds']}초",
         f"- 상태: " + ", ".join(f"{k} {v}" for k, v in s["status"].items()),
         f"- 변환본 검증 판정: " + ", ".join(f"{k} {v}" for k, v in s["verdict"].items()), ""]
    sn = s.get("sensitive") or {}
    if sn:
        L += [f"- 민감정보(변환 검증 판정과 별도): " + ", ".join(f"{k} {v}" for k, v in sn.items()),
              f"- **확인 대기 {sn.get('확인 필요', 0)}건** — 확인 전에는 AI(ask·MCP)에 보내지 않습니다. 변환은 이 컴퓨터 안에서 이미 끝났습니다. 확인: `python -m hwpai sens review <문서|폴더>`", ""]
    if s["fail_kinds"]:
        L += ["## 변환하지 못한 파일 — 사유별", ""] + [f"- {k}: {v}" for k, v in s["fail_kinds"].items()] + [""]
    if s["reason_codes"]:
        L += ["## 검증 판정 이유(코드별 건수)", ""] + [f"- {k}: {v}" for k, v in s["reason_codes"].items()] + [""]
    need = [r for r in rows if r.get("판정") in ("FAIL", "WARN") or r.get("상태") in (STATUS_FAIL, STATUS_QUAR)]
    wait = [r for r in rows if r.get("민감정보") == "확인 필요"]
    if wait:
        L += ["## 민감정보 확인 대기 목록", "", "| 원본 | 항목 |", "|---|---|"] + [f"| {r['원본']} | {r.get('민감정보_항목', '')} |" for r in wait[:500]] + [""]
    if need:
        L += ["## 사람 확인 목록", "", "| 원본 | 상태 | 판정 | 이유 | 검증서 |", "|---|---|---|---|---|"]
        for r in need[:500]:
            L.append(f"| {r['원본']} | {r.get('상태', '')} | {r.get('판정', '')} | "
                     f"{(r.get('판정_이유') or '')[:120].replace('|', '/')} | {r.get('검증서', '')} |")
    with open(os.path.join(outdir, "요약.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def watch(src: str, outdir: str, interval: float = 30.0, rounds: int | None = None, log=print, **kw) -> int:
    """폴더 감시 자동 변환 — 주기마다 이어하기로 돌린다(새 파일·바뀐 파일만 엔진을 부른다).
    rounds 를 주면 그 횟수만 돌고 끝낸다(시험용). 처리한 새 파일 수 합계를 돌려준다."""
    import time as _t
    log = log or (lambda *a, **k: None)
    n = total_new = 0
    while rounds is None or n < rounds:
        n += 1
        s = BatchConverter(src, outdir, log=lambda *a, **k: None, **kw).run()
        new = s["files"] - s.get("resumed", 0)
        total_new += new
        if new:
            log(f"[감시] {_now()} 새로 처리 {new}개 — 판정 {s['verdict']} · 상태 {s['status']}")
        if rounds is not None and n >= rounds:
            break
        _t.sleep(interval)
    return total_new
