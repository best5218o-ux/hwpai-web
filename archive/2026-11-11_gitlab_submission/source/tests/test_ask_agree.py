"""모델 간 핵심 값 비교 단위 시험 (API 호출 없음).  python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from hwpai.ask import compare, judge, key_values  # noqa: E402


def A(ans, ev):
    return {"answer": ans, "evidence": ev, "model": "m", "seconds": 0}


class KeyValues(unittest.TestCase):
    def test_units_commas(self):
        kv = key_values("2분기 대상 부서 수는 12개, 처리 건수는 8,500건입니다.")
        self.assertIn("12개", kv)
        self.assertIn("8500건", kv)
        self.assertIn("2분기", kv)

    def test_counter_noun_shown(self):
        self.assertEqual(key_values("12개 부서에서")["12개"], "12개 부서")

    def test_dates(self):
        a, b = key_values("2026. 11. 11.까지"), key_values("2026-11-11 마감")
        self.assertIn("2026-11-11", a)
        self.assertEqual(set(a), set(b))

    def test_org(self):
        kv = key_values("행정안전부와 총무과가 담당하며 결과는 일부 공개")
        self.assertIn("기관:행정안전부", kv)
        self.assertIn("기관:총무과", kv)
        self.assertNotIn("기관:결과", kv)
        self.assertNotIn("기관:일부", kv)


class Compare(unittest.TestCase):
    def test_same_values_different_sentences(self):
        r = judge({"question": "2분기 대상 부서 수와 처리 건수는?", "answers": {
            "a": A("2분기 대상 부서 수는 12개, 처리 건수는 8,500건입니다.", [4]),
            "b": A("2분기에는 12개 부서에서 8,500건의 문서가 처리됩니다.", [3, 4])}})
        self.assertFalse(r["agree_answer"])          # 문장은 다르다
        self.assertEqual(r["agree"]["verdict"], "일치")  # 핵심 값은 같다
        self.assertEqual(r["agree"]["common"], ["12개", "8500건"])
        self.assertEqual(r["evidence_overlap"], 0.5)
        self.assertIn("핵심 값 일치: 12개 부서 · 8,500건 (예)", r["agree_line"])

    def test_conflict(self):
        c = compare({"a": A("12개 부서, 8,500건", [1]), "b": A("12개 부서, 8,000건", [1])}, "")
        self.assertEqual(c["verdict"], "불일치")

    def test_subset_is_partial(self):
        c = compare({"a": A("1분기 3개, 1,200건", [1]), "b": A("1분기 3개", [1])}, "")
        self.assertEqual(c["verdict"], "부분")
        self.assertEqual(c["only"], {"a": ["1200건"]})

    def test_outside_context(self):
        c = compare({"a": A("12개 부서", [1]), "b": A("12개 부서", [1])}, "", context="[근거 1] 전 부서 13개")
        self.assertEqual(c["outside"], ["12개"])

    def test_no_values(self):
        r = judge({"question": "q", "answers": {"a": A("근거 없음", []), "b": A("근거 없음", [])}})
        self.assertEqual(r["agree"]["verdict"], "값없음")
        self.assertTrue(r["agree_answer"])


if __name__ == "__main__":
    unittest.main()
