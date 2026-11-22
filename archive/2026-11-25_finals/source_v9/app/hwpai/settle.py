"""변환 뒤 「제자리 교체 + 원본 보관 + 기간 뒤 삭제」 (선택 기능, 기본 꺼짐).

  - 변환·검증이 끝난 문서만(기본 PASS) 원래 있던 자리에 같은 이름 .hwpx 를 두고,
    원본 .hwp 는 지우지 않고 보관 폴더로 옮긴다(폴더 구조 그대로).
  - 보관 폴더의 「보관대장.csv」에 원본·변환본 SHA-256, 보관일, 삭제 예정일(--keep-days)을 적는다.
  - 삭제는 이 파일의 purge() 만 한다. 기본은 미리보기(dry-run)이고, 지울 때도
    ① 삭제 예정일이 지났고 ② 제자리 .hwpx 가 그대로(해시 같음·zip 정상) 있고 ③ 보관된 .hwp 가 기록한 그대로(해시 같음)일 때만 지운다.
    조건이 하나라도 어긋나면 지우지 않고 사유를 남긴다.
  - 어느 단계에서든 실패하면 원본은 제자리에 그대로 남는다(되돌릴 것이 없다).
"""
import csv
import datetime as _dt
import hashlib
import os
import shutil
import threading
import zipfile

LEDGER = "보관대장.csv"
DELLOG = "삭제기록.csv"
COLS = ["원본경로", "보관위치", "원본_SHA256", "HWPX위치", "HWPX_SHA256", "보관일", "삭제예정일", "상태", "삭제일", "비고"]
ST_KEPT, ST_DELETED, ST_HELD = "보관중", "삭제됨", "삭제보류"


def _sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _zip_ok(p: str) -> bool:
    try:
        with zipfile.ZipFile(p) as z:
            return z.testzip() is None and "mimetype" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _today() -> _dt.date:
    return _dt.date.today()


class Settler:
    def __init__(self, archive_dir: str, keep_days: int | None = None, verdicts=("PASS",), log=print):
        self.archive = os.path.abspath(archive_dir)
        self.keep_days = keep_days
        self.verdicts = tuple(v.strip().upper() for v in verdicts)
        self.log = log or (lambda *a, **k: None)
        self._lock = threading.Lock()

    # ---- 대장
    def _ledger_path(self) -> str:
        return os.path.join(self.archive, LEDGER)

    def _read(self) -> list[dict]:
        p = self._ledger_path()
        if not os.path.isfile(p):
            return []
        with open(p, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def _write(self, rows: list[dict]):
        os.makedirs(self.archive, exist_ok=True)
        tmp = self._ledger_path() + ".part"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, self._ledger_path())

    # ---- 제자리 교체 + 보관
    def settle(self, root: str, rel: str, outdir: str, row: dict) -> dict:
        """row 는 이관대장 행. 돌려주는 dict 를 행에 합친다(보관 결과)."""
        if row.get("상태") != "변환완료":
            return {}
        verdict = str(row.get("판정") or "").upper()
        if verdict not in self.verdicts:
            return {"제자리교체": f"안 함 — 판정 {verdict or '없음'}(허용: {','.join(self.verdicts)})"}
        src = os.path.join(root, rel)
        conv = os.path.join(outdir, row.get("변환본") or "")
        try:
            if not os.path.isfile(src):
                return {"제자리교체": "안 함 — 원본이 이미 없음"}
            if not os.path.isfile(conv):
                return {"제자리교체": "안 함 — 변환본 없음"}
            sha_o, sha_c = row.get("원본_SHA256"), row.get("변환본_SHA256")
            if _sha(src) != sha_o:
                return {"제자리교체": "안 함 — 변환 중 원본이 바뀜(다음 주기에 다시 변환)"}
            if _sha(conv) != sha_c or not _zip_ok(conv):
                return {"제자리교체": "안 함 — 변환본 해시·구조 확인 실패"}
            target = os.path.splitext(src)[0] + ".hwpx"
            if os.path.exists(target):
                if _sha(target) != sha_c:
                    return {"제자리교체": "안 함 — 같은 이름 .hwpx 가 이미 있고 내용이 다름(건드리지 않음)"}
            else:
                part = target + ".part"
                shutil.copyfile(conv, part)
                if _sha(part) != sha_c or not _zip_ok(part):
                    os.remove(part)
                    return {"제자리교체": "안 함 — 복사본 확인 실패"}
                os.replace(part, target)
            # 원본 보관: 복사 → 해시 확인 → 원본 제거
            dst = self._archive_path(rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            part = dst + ".part"
            shutil.copy2(src, part)
            if _sha(part) != sha_o:
                os.remove(part)
                return {"제자리교체": "HWPX 두기만 함 — 원본 보관 복사 확인 실패(원본 그대로)"}
            os.replace(part, dst)
            try:
                os.remove(src)
            except OSError as e:  # 한글이 열고 있는 경우 등 — 원본은 그대로 두고 보관 사본만 지운다
                os.remove(dst)
                return {"제자리교체": f"HWPX 두기만 함 — 원본을 옮기지 못함(열려 있음?): {type(e).__name__}"}
            today = _today()
            due = (today + _dt.timedelta(days=self.keep_days)).isoformat() if self.keep_days is not None else ""
            rec = {"원본경로": os.path.abspath(src), "보관위치": os.path.relpath(dst, self.archive),
                   "원본_SHA256": sha_o, "HWPX위치": os.path.abspath(target), "HWPX_SHA256": sha_c,
                   "보관일": today.isoformat(), "삭제예정일": due, "상태": ST_KEPT, "삭제일": "", "비고": ""}
            with self._lock:
                rows = self._read()
                rows.append(rec)
                self._write(rows)
            return {"제자리교체": "완료", "보관위치": os.path.relpath(dst, self.archive), "삭제예정일": due or "없음(무기한)"}
        except OSError as e:
            return {"제자리교체": f"안 함 — {type(e).__name__}: {e}"[:200]}

    def _archive_path(self, rel: str) -> str:
        d = os.path.join(self.archive, rel)
        if not os.path.exists(d):
            return d
        base, ext = os.path.splitext(d)
        n = 2
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

    # ---- 기간이 지난 보관 원본 정리
    def purge(self, today: _dt.date | None = None, dry_run: bool = True) -> dict:
        today = today or _today()
        with self._lock:
            rows = self._read()
            res = {"대상": 0, "삭제": 0, "보류": 0, "아직": 0, "미리보기": dry_run, "내역": []}
            log_rows = []
            for r in rows:
                if r.get("상태") != ST_KEPT and r.get("상태") != ST_HELD:
                    continue
                due = r.get("삭제예정일") or ""
                if not due:
                    continue
                try:
                    if _dt.date.fromisoformat(due) > today:
                        res["아직"] += 1
                        continue
                except ValueError:
                    continue
                res["대상"] += 1
                hw = os.path.join(self.archive, r["보관위치"])
                why = ""
                if not os.path.isfile(hw):
                    why = "보관된 원본이 없음"
                elif not os.path.isfile(r["HWPX위치"]):
                    why = "제자리 HWPX 가 없음 — 지우면 문서가 사라짐"
                elif _sha(r["HWPX위치"]) != r["HWPX_SHA256"]:
                    why = "제자리 HWPX 가 변환 당시와 다름(수정됨) — 사람 확인"
                elif not _zip_ok(r["HWPX위치"]):
                    why = "제자리 HWPX 구조 이상"
                elif _sha(hw) != r["원본_SHA256"]:
                    why = "보관된 원본이 기록과 다름"
                if why:
                    res["보류"] += 1
                    res["내역"].append((r["보관위치"], "보류", why))
                    if not dry_run:
                        r["상태"], r["비고"] = ST_HELD, why
                    continue
                res["내역"].append((r["보관위치"], "삭제" if not dry_run else "삭제 예정", ""))
                if dry_run:
                    res["삭제"] += 1
                    continue
                try:
                    os.remove(hw)
                except OSError as e:
                    res["보류"] += 1
                    r["상태"], r["비고"] = ST_HELD, f"삭제 실패 {type(e).__name__}"
                    continue
                r["상태"], r["삭제일"], r["비고"] = ST_DELETED, today.isoformat(), ""
                res["삭제"] += 1
                log_rows.append({"삭제일": today.isoformat(), "보관위치": r["보관위치"], "원본경로": r["원본경로"],
                                 "원본_SHA256": r["원본_SHA256"], "HWPX위치": r["HWPX위치"]})
            if not dry_run:
                self._write(rows)
                if log_rows:
                    p = os.path.join(self.archive, DELLOG)
                    new = not os.path.isfile(p)
                    with open(p, "a", encoding="utf-8-sig", newline="") as f:
                        w = csv.DictWriter(f, ["삭제일", "보관위치", "원본경로", "원본_SHA256", "HWPX위치"])
                        if new:
                            w.writeheader()
                        w.writerows(log_rows)
            return res


def cmd_purge(a) -> int:
    s = Settler(a.archive)
    res = s.purge(dry_run=not a.yes)
    head = "삭제 미리보기(아무것도 지우지 않음)" if res["미리보기"] else "삭제 실행"
    print(f"{head}: 기한 지난 {res['대상']}건 — {'삭제 예정' if res['미리보기'] else '삭제'} {res['삭제']} · 보류 {res['보류']} · 기한 전 {res['아직']}")
    for name, what, why in res["내역"]:
        print(f"  {what}: {name}" + (f" — {why}" if why else ""))
    if res["미리보기"] and res["삭제"]:
        print("실제로 지우려면 --yes 를 붙여 다시 실행하세요.")
    return 0
