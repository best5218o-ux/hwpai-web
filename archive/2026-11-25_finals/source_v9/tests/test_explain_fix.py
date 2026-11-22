"""검증서 쉬운 설명·AI 수정안 시험 — 망가진 변환본을 검증서의 수정안만으로 고쳐 다시 PASS 가 되는지.
실행: python -m unittest discover -s tests  (손으로 만든 HWPX 쌍 — 변환 엔진 불필요)"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
from test_pipeline_postfix import make_hwpx  # noqa: E402
from test_boan_audit import P, T, TBL  # noqa: E402
from hwpai.audit import audit, to_markdown  # noqa: E402
from hwpai.edit import replace_text, insert_hwpx  # noqa: E402

ORIG = P(T("회의 결과 보고")) + P(T("일시는 3월 5일 14시")) + P(T("마무리 문단")) + P(TBL("협의 내용 확인"))


class TestExplainFix(unittest.TestCase):
    def _pair(self, tmp, conv_body):
        a, b = os.path.join(tmp, "o.hwpx"), os.path.join(tmp, "c.hwpx")
        make_hwpx(a, ORIG)
        make_hwpx(b, conv_body)
        return a, b

    def test_pass_has_plain_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self._pair(tmp, ORIG)
            d = audit(a, b).to_dict()
            self.assertEqual(d["verdict"], "PASS")
            self.assertEqual(d["쉬운설명"]["결론"], "✔ 정상 변환")
            self.assertEqual(d["쉬운설명"]["다른 부분"], [])
            md = to_markdown(audit(a, b))
            self.assertIn("## 쉬운 설명", md)
            self.assertIn("없음. 비교한 모든 항목이 같습니다", md)

    def test_fail_explains_and_ai_fix_loop(self):
        bad = P(T("회의 결과 보고")) + P(T("마무리 문단")) + P(TBL("엉뚱한 말"))   # 문단 하나 빠짐 + 표 칸 글 바뀜
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self._pair(tmp, bad)
            d = audit(a, b).to_dict()
            self.assertEqual(d["verdict"], "FAIL")
            ex = d["쉬운설명"]
            self.assertEqual(ex["결론"], "✖ 변환 실패")
            kinds = {f["종류"] for f in ex["AI가_고치려면"]["수정안"]}
            self.assertEqual(kinds, {"빠진 글 채우기", "표 칸 글 바로잡기"})
            self.assertTrue(all(c["왜"] and c["어떻게"] for c in ex["왜 그런가"]))
            fix = ex["AI가_고치려면"]
            r = replace_text(b, fix["replace_text_한번에"], os.path.join(tmp, "fixed.hwpx"))   # 기존 치환 도구 하나로 끝
            self.assertEqual(r["not_inserted"], [])
            d2 = audit(a, r["out"]).to_dict()
            self.assertEqual(d2["verdict"], "PASS", json.dumps(d2["reasons"], ensure_ascii=False))
            self.assertTrue(d2["checks"]["text_exact"])

    def test_insert_refuses_ambiguous_anchor(self):
        body = P(T("같은 문단")) + P(T("같은 문단"))
        with tempfile.TemporaryDirectory() as tmp:
            b = os.path.join(tmp, "c.hwpx")
            make_hwpx(b, body)
            r = insert_hwpx(b, [{"after": "같은 문단", "text": "새 글"}], os.path.join(tmp, "o.hwpx"))
            self.assertEqual(r["inserted"], [])
            self.assertIn("2곳", r["not_inserted"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
