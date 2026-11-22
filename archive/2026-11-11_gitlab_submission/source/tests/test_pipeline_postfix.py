"""변환 파이프라인과 한컴 호환 뒤처리(C112~C121) 회귀 시험 — 실행: python -m unittest discover -s tests
API·네트워크 호출 없음. sample_data 의 합성 HWP 4건과 손으로 만든 최소 HWPX 로 시험한다."""
import glob
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
import xml.dom.minidom
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
from hwpai import postfix  # noqa: E402

SEC = "Contents/section0.xml"
HDR = "Contents/header.xml"
NS = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"')


def make_hwpx(path, section_body, fonts=("함초롬바탕",)):
    faces = "".join(f'<hh:font id="{i}" face="{f}" type="TTF" isEmbedded="0"/>' for i, f in enumerate(fonts))
    header = f'<?xml version="1.0" encoding="UTF-8"?><hh:head {NS}><hh:refList><hh:fontfaces><hh:fontface lang="HANGUL">{faces}</hh:fontface></hh:fontfaces></hh:refList></hh:head>'
    section = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" {NS}>{section_body}</hs:sec>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(HDR, header)
        z.writestr(SEC, section)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path, name=SEC):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def para(text, segs):
    ls = "".join(f'<hp:lineseg textpos="{tp}" vertpos="0" vertsize="1000" textheight="1000" baseline="850" spacing="600" horzpos="0" horzsize="42520" flags="{fl}"/>' for tp, fl in segs)
    return f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run><hp:linesegarray>{ls}</hp:linesegarray></hp:p>'


class ForeignLineseg(unittest.TestCase):
    """C120: 영문 글꼴 별칭 + 한컴 줄 나눔 표지 없음일 때만 줄 배치 저장값을 지운다."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _doc(self, fonts, flag):
        body = "".join(para("가" * 80, [(0, 393216)] + [(20 * k, flag) for k in range(1, 4)]) for _ in range(5))
        p = os.path.join(self.d, "t.hwpx")
        make_hwpx(p, body, fonts)
        return p

    def test_strips_when_both_signs(self):
        p = self._doc(("Batang", "Gulim"), 393216)
        self.assertGreater(postfix._fix_foreign_lineseg(p), 0)
        self.assertNotIn("linesegarray", read(p))

    def test_keeps_hancom_layout(self):
        p = self._doc(("Batang",), 1441792)   # 이어지는 줄에 한컴 표지(비트 20) 있음
        self.assertEqual(postfix._fix_foreign_lineseg(p), 0)
        self.assertIn("linesegarray", read(p))

    def test_keeps_korean_font_names(self):
        p = self._doc(("바탕", "굴림"), 393216)
        self.assertEqual(postfix._fix_foreign_lineseg(p), 0)
        self.assertIn("linesegarray", read(p))


def eq(h, bl, script="x"):
    return (f'<hp:p><hp:run><hp:equation id="1" baseUnit="900" baseLine="{bl}" version="Equation Version 60">'
            f'<hp:sz width="1000" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:script>{script}</hp:script></hp:equation></hp:run></hp:p>')


class EquationSizes(unittest.TestCase):
    """C121: 옛 한글 조판 수식 크기 표지가 5개 이상인 문서만 한글 2024 값으로 바꾼다."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_fixes_stale_doc(self):
        p = os.path.join(self.d, "e.hwpx")
        make_hwpx(p, "".join(eq(1125, 78) for _ in range(5)) + eq(1125, 78, "f&apos;"))
        self.assertEqual(postfix._fix_equation_sizes(p), 6)
        s = read(p)
        self.assertEqual(s.count('height="900"'), 6)
        self.assertEqual(s.count('baseLine="86"'), 6)
        self.assertIn('width="1150"', s)   # 프라임 하나에 너비 150
        xml.dom.minidom.parseString(s.encode())

    def test_keeps_doc_with_few_signs(self):
        p = os.path.join(self.d, "k.hwpx")
        make_hwpx(p, "".join(eq(1125, 78) for _ in range(4)) + eq(900, 86, "f&apos;"))
        before = read(p)
        self.assertEqual(postfix._fix_equation_sizes(p), 0)
        self.assertEqual(read(p), before)


class ColumnAndShadow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_column_enum_names(self):
        p = os.path.join(self.d, "c.hwpx")
        make_hwpx(p, '<hp:p><hp:run><hp:ctrl><hp:colPr id="" type="BalancedNewspaper" layout="LEFT" colCount="2" sameSz="1" sameGap="0"/></hp:ctrl></hp:run></hp:p>')
        postfix._fix_column_enums(p)
        s = read(p)
        self.assertIn('type="BALANCED_NEWSPAPER"', s)
        xml.dom.minidom.parseString(s.encode())

    def test_shadow_margin_zero(self):
        p = os.path.join(self.d, "s.hwpx")
        rect = ('<hp:rect id="1"><hp:shadow type="PARALLEL_RIGHTBOTTOM" color="#000000" offsetX="283" offsetY="283" alpha="0"/>'
                '<hp:outMargin left="0" right="600" top="0" bottom="600"/></hp:rect>')
        make_hwpx(p, f"<hp:p><hp:run>{rect}</hp:run></hp:p>")
        self.assertEqual(postfix._fix_shadow_margin(p), 1)
        self.assertIn('<hp:outMargin left="0" right="0" top="0" bottom="0"/>', read(p))

    def test_shadow_none_untouched(self):
        p = os.path.join(self.d, "n.hwpx")
        rect = '<hp:rect id="1"><hp:shadow type="NONE"/><hp:outMargin left="0" right="600" top="0" bottom="600"/></hp:rect>'
        make_hwpx(p, f"<hp:p><hp:run>{rect}</hp:run></hp:p>")
        self.assertEqual(postfix._fix_shadow_margin(p), 0)


class FieldIdsWellFormed(unittest.TestCase):
    """C112 결함 회귀: 닫는 태그 없는 fieldBegin 에 속성을 붙여도 XML 이 깨지지 않아야 한다."""

    def test_self_closing_field(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "f.hwpx")
            body = ('<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="HYPERLINK" name="" editable="0" dirty="0"/></hp:ctrl>'
                    '<hp:t>링크</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p>')
            make_hwpx(p, body)
            postfix._fix_field_ids(p)
            xml.dom.minidom.parseString(read(p).encode())
        finally:
            shutil.rmtree(d, ignore_errors=True)


class SampleDataPipeline(unittest.TestCase):
    """sample_data 4건: 변환·검증 PASS, 원본 불변, 변환본 XML 정상."""

    @classmethod
    def setUpClass(cls):
        cls.src = os.path.join(ROOT, "sample_data")
        cls.files = sorted(glob.glob(os.path.join(cls.src, "*.hwp")))
        cls.before = {f: sha(f) for f in cls.files}
        cls.out = tempfile.mkdtemp()
        try:
            from hwpai.engines import get_engine
            get_engine("auto")
            cls.engine_ok = True
        except Exception:
            cls.engine_ok = False

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_convert_and_audit(self):
        if not self.engine_ok:
            self.skipTest("변환 엔진(Node·rhwp)을 찾지 못함")
        import subprocess
        r = subprocess.run([sys.executable, "-m", "hwpai", "convert", self.src, "--out", self.out],
                           cwd=os.path.join(ROOT, "app"), capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        with open(os.path.join(self.out, "이관대장.csv"), encoding="utf-8-sig") as fh:
            ledger = fh.read()
        self.assertEqual(ledger.count("PASS"), len(self.files))
        for f in self.files:
            self.assertEqual(sha(f), self.before[f], "원본이 바뀌면 안 된다")
        for h in glob.glob(os.path.join(self.out, "*.hwpx")):
            with zipfile.ZipFile(h) as z:
                for n in z.namelist():
                    if n.endswith(".xml"):
                        xml.dom.minidom.parseString(z.read(n))
        from hwpai import hwpxcheck
        for h in glob.glob(os.path.join(self.out, "*.hwpx")):
            self.assertEqual(hwpxcheck.check(h)["errors"], [], h)


if __name__ == "__main__":
    unittest.main()
