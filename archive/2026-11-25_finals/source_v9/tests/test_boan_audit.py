"""결선 보완(2026-11-20) 회귀 시험 — 검증서가 놓치던 손실을 이제 잡는지, 정상 변환은 그대로 통과하는지.
실행: python -m unittest discover -s tests  (API·네트워크·변환 엔진 불필요 — 손으로 만든 HWPX 원본·변환본 쌍으로 대조)
B1 수식 캡션 · B2 짝 못 찾은 표 · B3 머리말·꼬리말 글 · B4 필드·쪽 번호 · B6 기본 결과 위치(입력 폴더 밖)
· B9 그림 채운 사각형(글상자 안 사각형 채우기를 바깥 사각형이 겹쳐 세지 않음)
· 3차 C3-1 묶음 안 그림·글상자 순서(원본 판독기) · C3-2a 변경 추적 이력 · C3-2b 도형 종류별 개수"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
from test_pipeline_postfix import make_hwpx  # noqa: E402
from hwpai.audit import audit  # noqa: E402


def P(inner):
    return f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">{inner}</hp:run></hp:p>'


def T(text):
    return f"<hp:t>{text}</hp:t>"


def SUB(inner):
    return f'<hp:subList>{inner}</hp:subList>'


def EQ(script, caption=None):
    cap = f"<hp:caption>{SUB(P(T(caption)))}</hp:caption>" if caption else ""
    return f'<hp:equation id="1">{cap}<hp:script>{script}</hp:script></hp:equation>'


def TBL(text):
    return (f'<hp:tbl id="1" rowCnt="1" colCnt="1"><hp:tr><hp:tc><hp:cellAddr colAddr="0" rowAddr="0"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>{SUB(P(T(text)))}</hp:tc></hp:tr></hp:tbl>')


def HEADER(inner):
    return f'<hp:ctrl><hp:header id="1" applyPageType="BOTH">{SUB(inner)}</hp:header></hp:ctrl>'


def LINK(url, text):
    return (f'<hp:ctrl><hp:fieldBegin id="7" type="HYPERLINK" name=""><hp:parameters cnt="1" name="">'
            f'<hp:stringParam name="Command">{url};1;0;0;</hp:stringParam></hp:parameters></hp:fieldBegin></hp:ctrl>'
            f'{T(text)}<hp:ctrl><hp:fieldEnd beginIDRef="7"/></hp:ctrl>')


def PAGENUM(pos="BOTTOM_CENTER"):
    return f'<hp:ctrl><hp:pageNum pos="{pos}" formatType="DIGIT" sideChar="-"/></hp:ctrl>'


def IMGRECT(inner=""):
    """그림으로 채운 사각형. inner 가 있으면 글상자(drawText)로 넣는다."""
    dt = f"<hp:drawText>{SUB(inner)}</hp:drawText>" if inner else ""
    return ('<hp:rect id="1"><hc:fillBrush><hc:imgBrush mode="TOTAL"><hc:img binaryItemIDRef="image1" bright="0" '
            f'contrast="0" effect="REAL_PIC" alpha="0"/></hc:imgBrush></hc:fillBrush>{dt}</hp:rect>')


class BoanAudit(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def pair(self, orig_body, conv_body):
        a, b = os.path.join(self.d, "orig.hwpx"), os.path.join(self.d, "conv.hwpx")
        make_hwpx(a, orig_body)
        make_hwpx(b, conv_body)
        return audit(a, b)

    def codes(self, r):
        return {x["code"] for x in r.reasons}

    def test_b1_equation_caption_lost_is_fail(self):
        r = self.pair(P(T("본문 글입니다")) + P(EQ("a+b", "수식 1 A")), P(T("본문 글입니다")) + P(EQ("a+b")))
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("EQUATION_CAPTION", self.codes(r))

    def test_b1_equation_caption_kept_passes(self):
        body = P(T("본문 글입니다")) + P(EQ("a+b", "수식 1 A"))
        r = self.pair(body, body)
        self.assertEqual(r.verdict, "PASS", r.reasons)

    def test_b2_unpaired_identical_tables_compared(self):
        # 같은 표 두 개 중 하나의 칸 글만 사라지면 짝 맞춤이 「삭제+추가」로 갈라진다 — 이전 판은 대조하지 않았다
        r = self.pair(P(TBL("누리집 안내")) + P(TBL("누리집 안내")), P(TBL("")) + P(TBL("누리집 안내")))
        self.assertIn("TABLE_CELL", self.codes(r))

    def test_b3_header_text_also_in_body(self):
        # 머리말 글이 본문에도 있으면 이전 판은 머리말이 빠져도 개수 대조를 못 했다
        orig = P(HEADER(P(T("보도자료 배포일시"))) + T("보도자료 배포일시 안내 본문"))
        conv = P(HEADER(P(T(""))) + T("보도자료 배포일시 안내 본문"))
        r = self.pair(orig, conv)
        self.assertEqual(r.verdict, "FAIL")

    def test_b4_hyperlink_lost_and_changed(self):
        body = P(LINK("http\\://www.mois.go.kr", "행정안전부 누리집"))
        r = self.pair(body, P(T("행정안전부 누리집")))
        self.assertIn("FIELD_LOST", self.codes(r))
        r = self.pair(body, P(LINK("http\\://changed.invalid", "행정안전부 누리집")))
        self.assertIn("FIELD_LOST", self.codes(r))
        r = self.pair(body, body)
        self.assertEqual(r.verdict, "PASS", r.reasons)

    def test_b4_page_number(self):
        r = self.pair(P(PAGENUM() + T("본문 글입니다")), P(T("본문 글입니다")))
        self.assertIn("PAGENUM_LOST", self.codes(r))
        # 한 구역에 같은 쪽 번호 설정이 여러 번 있어도 적용되는 값(마지막)이 같으면 손실이 아니다
        r = self.pair(P(PAGENUM() + T("본문 글입니다")) + P(PAGENUM() + T("둘째 문단")),
                      P(PAGENUM() + T("본문 글입니다")) + P(T("둘째 문단")))
        self.assertNotIn("PAGENUM_LOST", self.codes(r))

    def test_b6_default_output_outside_input_folder(self):
        from hwpai.batch import outside_out, default_out
        folder = os.path.join(self.d, "문서함")
        os.makedirs(folder)
        f = os.path.join(folder, "가.hwp")
        open(f, "wb").close()
        self.assertEqual(default_out(f), folder + "_hwpx변환")
        self.assertEqual(default_out(folder), folder + "_hwpx변환")
        self.assertEqual(outside_out(f, "_hwpai"), folder + "_hwpai")
        self.assertFalse(default_out(f).startswith(folder + os.sep))


    def test_b9_image_rect_inside_textbox_counted_once(self):
        # 바깥 사각형(채우기 없음)의 글상자 안에 그림 채운 사각형이 하나 — 그림은 1개다(이전 판은 바깥 사각형이 안쪽 채우기를 또 세어 2)
        outer = '<hp:rect id="2">' + "<hp:drawText>" + SUB(P(IMGRECT())) + "</hp:drawText></hp:rect>"
        body = P(T("본문 글입니다")) + P(outer)
        r = self.pair(body, body)
        self.assertEqual(r.checks.get("images"), [1, 1], r.checks.get("images"))

    # ---- 3차 보완
    def test_c3_1_group_children_keep_record_order(self):
        # 그림+글상자 쌍이 여러 개인 묶음(보류 표본 35c715135448) — 이전 판은 그림을 모두 앞에, 글상자를 모두 뒤에 모아
        # 변환본·한글 저장본(문서 순서)과 순서가 달라져 거짓 TEXT_LOSS 가 났다
        import struct
        from hwpai import hwp5 as H
        from hwpai.model import Image, Paragraph, TextBox
        sp = H.SectionParser.__new__(H.SectionParser)
        pic = b"\x00" * 71 + struct.pack("<H", 1)
        recs = [(H.T_CTRL_HEADER, 1, b" osg"), (H.T_SHAPE_COMP, 2, b"noc$"),
                (H.T_SHAPE_COMP, 3, b"cip$"), (H.T_PICTURE, 4, pic),
                (H.T_SHAPE_COMP, 3, b"cer$"), (H.T_LIST_HEADER, 4, b""), (H.T_SHAPE_RECT, 4, b""),
                (H.T_SHAPE_COMP, 3, b"cip$"), (H.T_PICTURE, 4, pic),
                (H.T_SHAPE_COMP, 3, b"cer$"), (H.T_LIST_HEADER, 4, b""), (H.T_SHAPE_RECT, 4, b"")]
        sp.tag, sp.lv, sp.pl = [r[0] for r in recs], [r[1] for r in recs], [r[2] for r in recs]
        sp.st = {"bin_names": {1: "BIN0001.png"}, "warnings": []}
        years = iter(["2019", "2021"])
        sp.paras_from = lambda m, ke, lv: ([Paragraph(next(years))], m)
        out = sp.shape(0, len(recs))
        kinds = [type(b).__name__ + (":" + b.blocks[0].text if isinstance(b, TextBox) else "") for b in out]
        self.assertEqual(kinds, ["Image", "TextBox:2019", "Image", "TextBox:2021"])

    def test_c3_2a_tracked_history_lost(self):
        # 지운 글 이력(deleteBegin~deleteEnd)이 빠지면 최종 본문이 같아도 잡는다(보류 표본 0a606aa5243d, 제출본 PASS 92)
        hist = '배포일시 2<hp:deleteBegin Id="1" TcId="1"/>5<hp:deleteEnd Id="1" TcId="1" paraend="0"/>6일'
        r = self.pair(P(T(hist)), P(T("배포일시 256일")))
        self.assertIn("TRACK_LOST", self.codes(r))
        self.assertEqual(r.checks.get("tracked_deleted_chars"), [1, 0])
        r = self.pair(P(T(hist)), P(T(hist)))
        self.assertEqual(r.verdict, "PASS", r.reasons)

    def test_c3_2b_shape_kinds(self):
        rect = '<hp:rect id="3"/>'
        ell = '<hp:ellipse id="3"/>'
        body = P(T("본문 글입니다")) + P(rect)
        r = self.pair(body, P(T("본문 글입니다")) + P(ell))
        self.assertIn("SHAPE_KIND", self.codes(r))
        r = self.pair(body, P(T("본문 글입니다")))
        self.assertIn("SHAPE_MISSING", self.codes(r))
        self.assertEqual(r.verdict, "FAIL")
        r = self.pair(body, body)
        self.assertEqual(r.verdict, "PASS", r.reasons)


if __name__ == "__main__":
    unittest.main()
