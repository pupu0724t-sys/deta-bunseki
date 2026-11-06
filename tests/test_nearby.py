import os
import tempfile
import unittest

from indeed_tool.nearby import parse_salary, parse_holidays, read_csv, read_text, summarize, CSV_COLUMNS


class ParseSalaryTest(unittest.TestCase):
    def test_man_with_rest(self):
        s = parse_salary("月給 25万700円 〜")
        self.assertEqual((s["kind"], s["low"], s["high"]), ("月給", 250700, None))

    def test_range_man(self):
        s = parse_salary("月給 25万 ～ 30万円")
        self.assertEqual((s["monthly_low"], s["monthly_high"]), (250000, 300000))

    def test_range_upper_without_man(self):
        s = parse_salary("月給25万〜30")
        self.assertEqual((s["monthly_low"], s["monthly_high"]), (250000, 300000))

    def test_comma_yen(self):
        s = parse_salary("月給250,000円～350,000円")
        self.assertEqual((s["monthly_low"], s["monthly_high"]), (250000, 350000))

    def test_fullwidth(self):
        s = parse_salary("月給２５万円～")
        self.assertEqual(s["monthly_low"], 250000)

    def test_decimal_man(self):
        self.assertEqual(parse_salary("月給 22.5万円")["monthly_low"], 225000)

    def test_annual(self):
        s = parse_salary("年収 360万円 ～ 480万円")
        self.assertEqual((s["monthly_low"], s["monthly_high"], s["converted"]), (300000, 400000, "年収÷12"))

    def test_hourly(self):
        s = parse_salary("時給 1,200円")
        self.assertEqual((s["kind"], s["monthly_low"]), ("時給", 1200 * 8 * 21))

    def test_unreadable(self):
        self.assertIsNone(parse_salary("経験・能力を考慮"))

    def test_holidays(self):
        self.assertEqual(parse_holidays("年間休日120日以上"), 120)


class SummaryTest(unittest.TestCase):
    def _csv(self, rows):
        fd, p = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(",".join(CSV_COLUMNS) + "\n")
            for r in rows:
                fh.write(",".join(r) + "\n")
        self.addCleanup(os.remove, p)
        return p

    def test_mean_excludes_hourly_and_unreadable(self):
        p = self._csv([["A", "", "", "月給25万円〜30万円", "120日", "", "", "", "", "", ""],
                       ["B", "", "", "月給30万円〜", "", "", "", "", "", "", ""],
                       ["C", "", "", "時給1200円", "", "", "", "", "", "", ""],
                       ["D", "", "", "応相談", "", "", "", "", "", "", ""]])
        s = summarize(read_csv(p), client=250700)
        self.assertEqual((s["total"], s["used"], s["unread"], s["excluded_hourly"]), (4, 2, 1, 1))
        self.assertEqual(s["low_mean"], 275000)
        self.assertEqual(s["holiday_mean"], 120)
        self.assertEqual(s["client_rank"], 2)

    def test_text_mode(self):
        fd, p = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        self.addCleanup(os.remove, p)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("法人営業スタッフ\n株式会社X\n大阪市\n月給 26万円 ～ 35万円\n\n企画営業\n株式会社Y\n月給 24万円\n")
        jobs = read_text(p)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["求人タイトル"], "法人営業スタッフ")


if __name__ == "__main__":
    unittest.main()
