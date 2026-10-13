import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indeed_tool.diagnose import diagnose, judge, parse_number

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "sample_indeed.csv")


class DiagnoseTest(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(parse_number("1,234"), 1234)
        self.assertEqual(parse_number("¥500"), 500)
        self.assertAlmostEqual(parse_number("3.2%"), 0.032)
        self.assertIsNone(parse_number("-"))

    def test_small_sample_is_not_concluded(self):
        # クリック率が目安未満でも、件数が少なければ「bad」にしない
        self.assertEqual(judge(4, 100, 0.05)["status"], "near")
        self.assertEqual(judge(250, 10000, 0.05)["status"], "bad")

    def test_sample_issues(self):
        r = {x["title"]: x["issue"] for x in diagnose(SAMPLE)["listings"]}
        self.assertEqual(r["サンプル職種A"], "ctr")
        self.assertEqual(r["サンプル職種B"], "cvr")
        self.assertEqual(r["サンプル職種C"], "watch")


if __name__ == "__main__":
    unittest.main()
