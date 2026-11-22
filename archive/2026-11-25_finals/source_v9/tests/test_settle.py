"""제자리 교체·원본 보관·기한 삭제(settle.py) — 합성 파일로 확인. 엔진 불필요."""
import datetime as dt
import hashlib
import shutil
import tempfile
import unittest
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from hwpai.settle import Settler  # noqa: E402


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _setup(tmp_path):
    root, out, arc = tmp_path / "src", tmp_path / "out", tmp_path / "arc"
    root.mkdir(); out.mkdir()
    hwp = root / "문서.hwp"; hwp.write_bytes(b"HWP-ORIGINAL")
    conv = out / "문서.hwpx"
    with zipfile.ZipFile(conv, "w") as z:
        z.writestr("mimetype", "application/hwp+zip"); z.writestr("Contents/section0.xml", "<a/>")
    row = {"상태": "변환완료", "판정": "PASS", "변환본": "문서.hwpx", "원본_SHA256": _sha(hwp), "변환본_SHA256": _sha(conv)}
    return root, out, arc, hwp, row


def test_settle_moves_original_and_keeps_hwpx(tmp_path):
    root, out, arc, hwp, row = _setup(tmp_path)
    s = Settler(str(arc), keep_days=90)
    r = s.settle(str(root), "문서.hwp", str(out), row)
    assert r["제자리교체"] == "완료"
    assert not hwp.exists() and (root / "문서.hwpx").exists() and (arc / "문서.hwp").read_bytes() == b"HWP-ORIGINAL"


def test_non_pass_is_untouched(tmp_path):
    root, out, arc, hwp, row = _setup(tmp_path)
    row["판정"] = "WARN"
    r = Settler(str(arc)).settle(str(root), "문서.hwp", str(out), row)
    assert "안 함" in r["제자리교체"] and hwp.exists() and not (root / "문서.hwpx").exists()


def test_original_changed_during_conversion_is_untouched(tmp_path):
    root, out, arc, hwp, row = _setup(tmp_path)
    hwp.write_bytes(b"EDITED")
    r = Settler(str(arc)).settle(str(root), "문서.hwp", str(out), row)
    assert "바뀜" in r["제자리교체"] and hwp.exists()


def test_existing_different_hwpx_is_not_overwritten(tmp_path):
    root, out, arc, hwp, row = _setup(tmp_path)
    (root / "문서.hwpx").write_bytes(b"USER-FILE")
    r = Settler(str(arc)).settle(str(root), "문서.hwp", str(out), row)
    assert "다름" in r["제자리교체"] and hwp.exists() and (root / "문서.hwpx").read_bytes() == b"USER-FILE"


def test_purge_only_when_due_and_safe(tmp_path):
    root, out, arc, hwp, row = _setup(tmp_path)
    s = Settler(str(arc), keep_days=90)
    s.settle(str(root), "문서.hwp", str(out), row)
    later = dt.date.today() + dt.timedelta(days=91)
    assert s.purge(today=dt.date.today(), dry_run=False)["삭제"] == 0          # 기한 전
    assert s.purge(today=later, dry_run=True)["삭제"] == 1 and (arc / "문서.hwp").exists()  # 미리보기
    (root / "문서.hwpx").write_bytes(b"MODIFIED")                               # 제자리 HWPX 수정됨 → 보류
    r = s.purge(today=later, dry_run=False)
    assert r["삭제"] == 0 and r["보류"] == 1 and (arc / "문서.hwp").exists()


def test_purge_deletes_when_safe(tmp_path):
    root, out, arc, hwp, row = _setup(tmp_path)
    s = Settler(str(arc), keep_days=0)
    s.settle(str(root), "문서.hwp", str(out), row)
    r = s.purge(dry_run=False)
    assert r["삭제"] == 1 and not (arc / "문서.hwp").exists() and (root / "문서.hwpx").exists()


class TestDropAndGuiSettle(unittest.TestCase):
    """끌어놓기·화면 연동 — 옵션을 주면 제자리 교체, 안 주면 이전과 같음"""

    def _sample(self, tmp):
        src = os.path.join(tmp, "in")
        os.makedirs(src)
        sd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data")
        shutil.copy(os.path.join(sd, "sample_notice.hwp"), src)
        return src

    def test_drop_with_archive(self):
        from hwpai import drop
        with tempfile.TemporaryDirectory() as tmp:
            src = self._sample(tmp)
            drop.run([src], open_result=False, log=lambda *a, **k: None, archive="auto", keep_days=90)
            self.assertTrue(os.path.isfile(os.path.join(src, "sample_notice.hwpx")))
            self.assertFalse(os.path.exists(os.path.join(src, "sample_notice.hwp")))
            self.assertTrue(os.path.isfile(os.path.join(src + "_원본보관", "sample_notice.hwp")))
            self.assertTrue(os.path.isfile(os.path.join(src + "_원본보관", "보관대장.csv")))

    def test_drop_default_untouched(self):
        from hwpai import drop
        with tempfile.TemporaryDirectory() as tmp:
            src = self._sample(tmp)
            drop.run([src], open_result=False, log=lambda *a, **k: None)
            self.assertTrue(os.path.isfile(os.path.join(src, "sample_notice.hwp")))
            self.assertFalse(os.path.exists(os.path.join(src, "sample_notice.hwpx")))

    def test_drop_archive_inside_source_refused(self):
        from hwpai import drop
        with tempfile.TemporaryDirectory() as tmp:
            src = self._sample(tmp)
            res = drop.run([src], open_result=False, log=lambda *a, **k: None, archive=os.path.join(src, "보관"))
            self.assertEqual(res, [])
            self.assertTrue(os.path.isfile(os.path.join(src, "sample_notice.hwp")))


class TestSettleDefaults(unittest.TestCase):
    def test_drop_default_on_30days(self):
        from hwpai import drop, __main__ as m
        import argparse
        seen = {}
        orig = drop.run
        drop.run = lambda paths, **k: seen.update(k) or [{"src": "", "out": "", "only": None, "stats": {}}]
        try:
            a = argparse.Namespace(paths=["x"], jobs=1, no_open=True, json=False, archive=None, keep_days=None, no_settle=False)
            drop.cmd_drop(a)
            self.assertEqual((seen["archive"], seen["keep_days"]), ("auto", 30))
            a.no_settle = True
            drop.cmd_drop(a)
            self.assertIsNone(seen["archive"])
            a.no_settle, a.keep_days = False, 0
            drop.cmd_drop(a)
            self.assertIsNone(seen["keep_days"])
        finally:
            drop.run = orig


def test_safe_rel_rejects_windows_device_names():
    from hwpai.gui import safe_rel
    for bad in ("con.hwp", "a/NUL.hwp", "com1.hwp", "lpt3.x.hwp"):
        assert safe_rel(bad) is None
    assert safe_rel("console.hwp") == "console.hwp"
