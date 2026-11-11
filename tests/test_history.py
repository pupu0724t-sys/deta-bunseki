import json
import os
import tempfile
import unittest

from indeed_tool import pipeline, rules
from indeed_tool.pipeline import check_manuscript, proposed_ids

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
"""


def agg(ref, first, last, days, imp, clk, st, app, cost):
    return {"title": "A", "ref": ref, "first": first, "last": last, "days": days,
            "imp": imp, "clk": clk, "st": st, "app": app, "cost": cost}


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.chk = check_manuscript(TEXT)
        self.aggs = [agg("1", "2026/10/01", "2026/10/31", 31, 9444, 245, 8, 6, 150000),
                     agg("2", "2026/11/01", "2026/11/10", 10, 1836, 74, 0, 0, 48646)]

    def test_proposed_ids(self):
        h = {"rounds": [{"proposals": [{"id": "catch"}, {"id": "docs", "status": "再提案可"}]}],
             "manual": [{"ids": ["repost"]}, {"ids": ["career"], "status": "再提案可"}]}
        self.assertEqual(proposed_ids(h), {"catch", "repost"})

    def test_excluded_proposals_are_not_repeated(self):
        _, _, _, first = rules.build_spec(self.aggs, TEXT, self.chk, "T")
        first_ids = {c["id"] for c in first}
        self.assertIn("catch", first_ids)
        _, _, D, second = rules.build_spec(self.aggs, TEXT, self.chk, "T", exclude=first_ids, round_no=2)
        self.assertFalse(first_ids & {c["id"] for c in second})   # 前回と1つも被らない
        self.assertTrue(D["skipped"])

    def test_round_number_in_cover(self):
        spec, _, _, _ = rules.build_spec(self.aggs, TEXT, self.chk, "T", round_no=2)
        self.assertIn("第2回", spec["slides"][0]["title"])

    def test_auto_appends_history_and_skips_next_time(self):
        d = tempfile.mkdtemp()
        # prepare は CSV を読むため、最小のCSVを作る
        hdr = "配信日,表示数,クリック率,クリック数,応募開始率,応募開始数,応募完了率,応募数,応募率,クリック単価,応募開始単価,応募単価,利用済予算\n"
        csv1 = os.path.join(d, "広告詳細_111111_正社員_A_260101_20260110_100000.csv")
        with open(csv1, "w", encoding="utf-8-sig") as fh:
            fh.write(hdr + '"2026/01/01","1000","","60","","3","","2","","","","","9000"\n')
        pdf = os.path.join(d, "x.pdf")
        # PDFを作らず、prepare をそのまま使わないため、履歴の読み書きだけ確認
        h = os.path.join(d, "h.json")
        self.assertEqual(pipeline.load_history(h), {"rounds": [], "manual": []})
        json.dump({"rounds": [{"proposals": [{"id": "catch", "name": "x"}]}], "manual": []}, open(h, "w", encoding="utf-8"))
        self.assertEqual(proposed_ids(pipeline.load_history(h)), {"catch"})


if __name__ == "__main__":
    unittest.main()
