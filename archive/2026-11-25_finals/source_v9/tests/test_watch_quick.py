"""감시 개선 — 크기·수정시각이 같으면 지문(SHA-256) 계산을 건너뛰고, 바뀌면 다시 계산한다. 엔진 불필요."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from hwpai import batch as B


def _setup(tmp_path, quick):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir(); out.mkdir()
    f = src / "가.hwp"; f.write_bytes(b"X" * 100)
    (out / "가.hwpx").write_bytes(b"Y" * 50)
    st = os.stat(f)
    led = B.Ledger(str(out))
    led.add({"원본": "가.hwp", "상태": B.STATUS_DONE, "판정": "PASS", "변환본": "가.hwpx", "변환본_크기": 50,
             "원본_SHA256": B.sha256_file(str(f)), "원본_크기": st.st_size, "원본_mtime_ns": st.st_mtime_ns})
    bc = B.BatchConverter(str(src), str(out), log=lambda *a, **k: None, quick_resume=quick)
    return bc, led, f


def test_quick_resume_skips_hash_when_unchanged(tmp_path, monkeypatch):
    bc, led, f = _setup(tmp_path, True)
    calls = []
    monkeypatch.setattr(B, "sha256_file", lambda p: calls.append(p) or "x")
    r = bc.process("가.hwp", led)
    assert r.get("_resumed") and not calls


def test_quick_resume_rehashes_when_changed(tmp_path, monkeypatch):
    bc, led, f = _setup(tmp_path, True)
    f.write_bytes(b"Z" * 101)
    calls = []
    real = B.sha256_file
    monkeypatch.setattr(B, "sha256_file", lambda p: calls.append(p) or real(p))
    bc.process("가.hwp", led)
    assert calls


def test_default_still_hashes(tmp_path, monkeypatch):
    bc, led, f = _setup(tmp_path, False)
    calls = []
    real = B.sha256_file
    monkeypatch.setattr(B, "sha256_file", lambda p: calls.append(p) or real(p))
    r = bc.process("가.hwp", led)
    assert calls and r.get("_resumed")


def test_idle_round_does_not_rewrite_ledger_each_25(tmp_path, monkeypatch):
    """이어하기만 있는 대기 한 바퀴는 대장을 25개마다 통째로 다시 쓰지 않는다(문서 수의 제곱에 비례해 느려지던 오류)."""
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
    from hwpai import batch
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    sd = os.path.join(os.path.dirname(__file__), "..", "sample_data", "sample_notice.hwp")
    import shutil
    for i in range(120):
        shutil.copy(sd, src / f"d{i:03d}.hwp")
    batch.BatchConverter(str(src), str(out), log=lambda *a, **k: None, quick_resume=True).run()
    calls = []
    orig = batch.Ledger.write_csv
    monkeypatch.setattr(batch.Ledger, "write_csv", lambda self, order: calls.append(1) or orig(self, order))
    s = batch.BatchConverter(str(src), str(out), log=lambda *a, **k: None, quick_resume=True).run()
    assert s["resumed"] == 120
    assert len(calls) <= 2, calls   # 마지막 한 번(+요약) 뿐
