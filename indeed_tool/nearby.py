"""周辺の求人の給与を読み取り、月給に換算して平均などを出す。

求人サイトからの自動取得(スクレイピング)は利用規約で禁止されているため行わない。
人が集めた情報(CSV、または検索結果画面をコピーしたテキスト)を入力にする。

使い方:
  python -m indeed_tool.nearby data/nearby.csv --client 250700
  python -m indeed_tool.nearby data/nearby.txt --client 250700        # 貼り付けテキスト(簡易)
  python -m indeed_tool.nearby data/nearby.csv --include-hourly        # 時給・日給も月給換算して含める
"""
import argparse
import csv
import re
import statistics
import unicodedata

HOURS_PER_DAY = 8      # 時給・日給を月給に換算するときの仮定
DAYS_PER_MONTH = 21

KINDS = ("月給", "月収", "年収", "年俸", "時給", "日給")
DASH = r"[〜~～\-－―ー]"
NUM = r"(\d+(?:\.\d+)?)\s*(万)?\s*(\d+)?\s*円?"
PAT = re.compile(r"(月給|月収|年収|年俸|時給|日給)\s*[:：]?\s*" + NUM + r"\s*(?:" + DASH + r"\s*(?:" + NUM + r")?)?")

CSV_COLUMNS = ["求人タイトル", "会社名", "勤務地・最寄駅", "給与", "年間休日", "残業の記載", "未経験の可否",
               "特徴的な訴求", "出典URL", "確認日", "備考"]


def _yen(num, man, rest):
    if num is None:
        return None
    v = float(num)
    if man:
        v = v * 10000 + (float(rest) if rest else 0)
    return int(round(v))


def _normalize(text):
    s = unicodedata.normalize("NFKC", text or "")
    return s.replace(",", "").replace("、", "")


def parse_salary(text):
    """給与の文字から最初の給与表記を読み取る。読めなければ None。

    戻り値: {"kind", "low", "high", "monthly_low", "monthly_high", "converted"}
    converted: "なし"(月給) / "年収÷12" / "時給×8h×21日" / "日給×21日"
    """
    s = _normalize(text)
    m = PAT.search(s)
    if not m:
        return None
    kind = m.group(1)
    low = _yen(m.group(2), m.group(3), m.group(4))
    high = _yen(m.group(5), m.group(6), m.group(7)) if m.group(5) else None
    # 「25万〜30」のように上限側だけ「万」が省略された表記は、下限に合わせる
    if high is not None and m.group(3) and not m.group(6) and high < 10000:
        high = high * 10000
    if kind in ("月給", "月収"):
        factor, conv = 1, "なし"
    elif kind in ("年収", "年俸"):
        factor, conv = 1 / 12, "年収÷12"
    elif kind == "時給":
        factor, conv = HOURS_PER_DAY * DAYS_PER_MONTH, f"時給×{HOURS_PER_DAY}h×{DAYS_PER_MONTH}日"
    else:
        factor, conv = DAYS_PER_MONTH, f"日給×{DAYS_PER_MONTH}日"
    return {"kind": kind, "low": low, "high": high,
            "monthly_low": int(round(low * factor)),
            "monthly_high": int(round(high * factor)) if high is not None else None,
            "converted": conv}


def parse_holidays(text):
    m = re.search(r"(\d{2,3})\s*日", _normalize(text or ""))
    return int(m.group(1)) if m else None


def read_csv(path):
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=enc) as fh:
                rows = list(csv.DictReader(fh))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"文字コードを判別できません: {path}")
    jobs = []
    for r in rows:
        sal = parse_salary(r.get("給与", ""))
        jobs.append({**{k: (r.get(k) or "").strip() for k in CSV_COLUMNS}, "salary": sal,
                     "holidays": parse_holidays(r.get("年間休日", ""))})
    return jobs


def read_text(path):
    """検索結果画面をコピーしたテキストから、給与の行を1求人として拾う(簡易)。"""
    with open(path, encoding="utf-8-sig") as fh:
        lines = [ln.strip() for ln in fh]
    jobs = []
    for i, ln in enumerate(lines):
        sal = parse_salary(ln)
        if not sal:
            continue
        prev = [x for x in lines[max(0, i - 4):i] if x]
        jobs.append({**{k: "" for k in CSV_COLUMNS}, "求人タイトル": prev[0] if prev else "", "給与": ln,
                     "備考": "テキストから自動抽出（求人タイトルは推定）", "salary": sal, "holidays": None})
    return jobs


def load(path):
    return read_text(path) if path.lower().endswith(".txt") else read_csv(path)


def usable(jobs, include_hourly=False):
    ok = []
    for j in jobs:
        s = j["salary"]
        if not s:
            continue
        if s["kind"] in ("時給", "日給") and not include_hourly:
            continue
        ok.append(j)
    return ok


def summarize(jobs, include_hourly=False, client=None):
    ok = usable(jobs, include_hourly)
    lows = [j["salary"]["monthly_low"] for j in ok]
    highs = [j["salary"]["monthly_high"] for j in ok if j["salary"]["monthly_high"] is not None]
    hol = [j["holidays"] for j in ok if j["holidays"]]
    out = {"total": len(jobs), "used": len(ok), "unread": sum(1 for j in jobs if not j["salary"]),
           "excluded_hourly": sum(1 for j in jobs if j["salary"] and j["salary"]["kind"] in ("時給", "日給")) if not include_hourly else 0,
           "low_mean": statistics.mean(lows) if lows else None, "low_median": statistics.median(lows) if lows else None,
           "low_min": min(lows) if lows else None, "low_max": max(lows) if lows else None,
           "high_mean": statistics.mean(highs) if highs else None, "high_count": len(highs),
           "holiday_mean": statistics.mean(hol) if hol else None, "holiday_count": len(hol)}
    if client and lows:
        out["client"] = client
        out["client_vs_mean"] = client - out["low_mean"]
        out["client_rank"] = sum(1 for v in lows if v > client) + 1  # 月給下限が高い順の順位
    return out


def _y(v):
    return "－" if v is None else f"{v:,.0f}円"


def report(summary):
    s = summary
    lines = [f"読み込んだ求人：{s['total']}件／集計に使用：{s['used']}件"
             f"（給与を読めない：{s['unread']}件、時給・日給で除外：{s['excluded_hourly']}件）"]
    if s["used"] < 5:
        lines.append("注意：件数が少ないため、平均は参考値です。")
    lines += [f"月給下限の平均：{_y(s['low_mean'])}／中央値：{_y(s['low_median'])}（最小 {_y(s['low_min'])}〜最大 {_y(s['low_max'])}）",
              f"月給上限の平均：{_y(s['high_mean'])}（上限の記載あり {s['high_count']}件）"]
    if s["holiday_mean"]:
        lines.append(f"年間休日の平均：{s['holiday_mean']:.0f}日（記載あり {s['holiday_count']}件）")
    if "client" in s:
        diff = s["client_vs_mean"]
        lines.append(f"貴社の月給下限 {_y(s['client'])}：平均より {abs(diff):,.0f}円{'高い' if diff >= 0 else '低い'}"
                     f"（{s['used']}件中 {s['client_rank']}位）")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="周辺求人のCSV、または検索結果をコピーした .txt")
    ap.add_argument("--client", type=int, help="比較する貴社の月給下限（円）")
    ap.add_argument("--include-hourly", action="store_true", help="時給・日給も月給に換算して含める")
    a = ap.parse_args()
    jobs = load(a.input)
    print(report(summarize(jobs, a.include_hourly, a.client)))


if __name__ == "__main__":
    main()
