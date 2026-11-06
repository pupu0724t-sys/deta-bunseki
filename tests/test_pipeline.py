import json
import os
import tempfile
import unittest

from indeed_tool import pipeline
from indeed_tool.proposal_deck import build as build_deck

HEAD = "配信日,表示数,クリック率,クリック数,応募開始率,応募開始数,応募完了率,応募数,応募率,クリック単価,応募開始単価,応募単価,利用済予算\n"


def _csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(HEAD)
        fh.write('"合計","999","","999","","9","","9","","","","","999999"\n')
        for d, imp, clk, st, app, cost in rows:
            fh.write(f'"{d}","{imp}","","{clk}","","{st}","","{app}","","","","","{cost}"\n')


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_name_parts(self):
        ref, title = pipeline._name_parts("広告詳細_2948092_正社員_私立中学校への広告営業　_261027_20261105_093241.csv")
        self.assertEqual(ref, "2948092")
        self.assertIn("広告営業", title)

    def test_combine_skips_total_and_keeps_latest_export(self):
        old = os.path.join(self.d, "広告詳細_111111_正社員_A_260101_20260110_100000.csv")
        new = os.path.join(self.d, "広告詳細_111111_正社員_A_260101_20260111_100000.csv")
        _csv(old, [("2026/01/01", 100, 5, 1, 0, 1000), ("2026/01/02", 50, 2, 0, 0, 500)])
        _csv(new, [("2026/01/01", 100, 5, 1, 0, 1000), ("2026/01/02", 80, 4, 1, 1, 800)])
        rows = pipeline.combine([old, new], os.path.join(self.d, "c.csv"))
        self.assertEqual(len(rows), 2)  # 合計行は除き、新しい方の出力だけ使う
        self.assertEqual(rows[1]["表示数"], "80")

    def test_fix_radicals(self):
        self.assertEqual(pipeline.fix_radicals("私⽴中学校・⾼校"), "私立中学校・高校")
        self.assertEqual(pipeline.fix_radicals("（原文のまま）"), "（原文のまま）")

    def test_check_manuscript(self):
        text = ("【正社員】テスト営業 ／20〜40代活躍中！／残業少\n応募画面へ進む\n「残業ほぼなし」\n月平均残業時間20時間以内\n"
                "給与例\n勤務時間\n＜1.応募＞\n履歴書・職務経歴書をご送付ください。\n月給 25万700円 〜")
        c = pipeline.check_manuscript(text)
        names = [f[0] for f in c["flags"]]
        self.assertIn("条件表記のゆれ", names)
        self.assertIn("応募時の書類", names)
        self.assertIn("給与例が空欄", names)
        self.assertEqual(c["salary"]["monthly_low"], 250700)

    def test_prepare_and_build_requires_proposals(self):
        a = os.path.join(self.d, "広告詳細_111111_正社員_前回_260101_20260301_100000.csv")
        b = os.path.join(self.d, "広告詳細_222222_正社員_今回_260201_20260301_100000.csv")
        _csv(a, [("2026/01/01", 1000, 50, 10, 6, 8000), ("2026/01/02", 1000, 50, 10, 6, 8000)])
        _csv(b, [("2026/02/01", 1000, 40, 4, 0, 8000), ("2026/02/02", 1000, 40, 4, 0, 8000)])
        out = os.path.join(self.d, "work")
        pipeline.prepare([a, b], None, out, "テスト株式会社")
        spec = json.load(open(os.path.join(out, "proposal_spec.json"), encoding="utf-8"))
        self.assertEqual([s["type"] for s in spec["slides"]], ["cover", "funnel", "todo"])
        with self.assertRaises(SystemExit):  # 提案の中身(todo)が残っていると作らない
            pipeline.build_all(out, os.path.join(self.d, "o"))

    def test_sample_spec_builds_and_forbid(self):
        spec_path = os.path.join(os.path.dirname(__file__), "..", "samples", "sample_proposal_spec.json")
        spec = json.load(open(spec_path, encoding="utf-8"))
        out = os.path.join(self.d, "s.pptx")
        build_deck(spec, out)
        self.assertTrue(os.path.getsize(out) > 10000)
        self.assertIn("サンプル", pipeline.deck_text(spec, {}))


if __name__ == "__main__":
    unittest.main()
