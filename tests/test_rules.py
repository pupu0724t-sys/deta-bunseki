import json
import os
import tempfile
import unittest

from indeed_tool import rules
from indeed_tool.pipeline import check_manuscript
from indeed_tool.proposal_deck import build as build_deck

TEXT = """【正社員】テスト店の店舗スタッフ｜残業無し／未経験でも月給27万スタート！駅から徒歩2分
応募画面へ進む
仕事内容
人気チェーン『テストバーガー』の正社員募集
未経験OK！研修あり
◇ 社宅あり
◇ 3日連休OK
将来的には店長を目指したい方
東京に15店舗展開中
給与
月給 27万円 〜 32万円
基本給：月給 22万5500円 〜 22万6000円
※給与には20時間の
固定残業代32,020円を含む
給与例
勤務時間
月平均残業時間20時間以内
＜1.応募＞
履歴書・職務経歴書をご送付ください。
"""


def agg(title, ref, first, last, days, imp, clk, st, app, cost):
    return {"title": title, "ref": ref, "first": first, "last": last, "days": days,
            "imp": imp, "clk": clk, "st": st, "app": app, "cost": cost}


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.chk = check_manuscript(TEXT)
        self.aggs = [agg("A", "1", "2026/10/01", "2026/10/31", 31, 9444, 245, 8, 6, 150000),
                     agg("A", "2", "2026/11/01", "2026/11/10", 10, 1836, 74, 0, 0, 48646)]

    def test_split_title(self):
        emp, job, catch = rules.split_title("【正社員】テスト店の店舗スタッフ｜残業無し／未経験︕")
        self.assertEqual((emp, job), ("【正社員】", "テスト店の店舗スタッフ"))
        self.assertIn("！", catch)

    def test_overtime_extract(self):
        h, a = rules._overtime_window(rules._n(TEXT))
        self.assertEqual((h, a), ("20", "32,020円"))
        h2, a2 = rules._overtime_window("固定残業代：あり\n1ヶ月あたり1万5500円 〜（固定残業時間：1ヶ月あたり10時間）")
        self.assertEqual((h2, a2), ("10", "1万5500円"))

    def test_small_period_judged_on_previous(self):
        D = rules.diagnose_funnel(self.aggs)
        self.assertIs(D["judge_on"], self.aggs[0])        # 11月は74クリックと少ないため、10月で判定
        self.assertEqual(D["status"]["ctr"], "bad")       # 2.6%は目安5%を明確に下回る
        self.assertAlmostEqual(D["base"]["asr"], rules.DEFAULT_ASR)  # 判定期間そのものを基準にしない

    def test_build_spec_and_deck(self):
        spec, meta, D, ordered = rules.build_spec(self.aggs, TEXT, self.chk, "テスト株式会社")
        ids = [c["id"] for c in ordered]
        for must in ("catch", "brand", "overtime", "salary"):
            self.assertIn(must, ids)
        # 応募完了率が問題ない(75%)ため、書類の提案は候補にはなるが上位7件には入らない
        self.assertNotIn("docs", ids)
        self.assertIsNotNone(rules.rule_docs(D, TEXT, self.chk))
        self.assertLessEqual(len(ordered), 7)
        types = [s["type"] for s in spec["slides"]]
        for t in ("cover", "funnel", "decompose", "summary", "overview", "proposal", "kpi", "plan", "checklist"):
            self.assertIn(t, types)
        self.assertNotIn("{no}", json.dumps(spec, ensure_ascii=False))
        self.assertTrue(meta["priority"].startswith("提案"))
        out = os.path.join(tempfile.mkdtemp(), "t.pptx")
        build_deck(spec, out)
        self.assertGreater(os.path.getsize(out), 10000)

    def test_grab_skips_title_and_ui(self):
        lines = rules.grab(TEXT, r"連休|残業", 0, 5)
        self.assertFalse(any("応募画面" in x or x.startswith("【正社員】") for x in lines))


if __name__ == "__main__":
    unittest.main()
