"""CSVを読み込み、表示→クリック→応募の漏斗で数値を診断する。"""
import csv
import math
import re
import statistics
import unicodedata

DEFAULT_CTR = 0.05   # クリック率の目安
DEFAULT_CVR = 0.015  # 応募率の目安
Z = 1.96             # 95%信頼区間

ALIASES = {
    "title": ["職種タイトル", "求人タイトル", "タイトル", "職種", "求人名", "求人", "キャンペーン"],
    "impressions": ["表示回数", "表示数", "インプレッション"],
    "clicks": ["クリック数", "クリック"],
    "apps": ["応募数", "応募"],
    "cost": ["利用済予算", "利用済み予算", "利用済予算額", "費用", "消化金額"],
}
TOTAL_WORDS = {"合計", "総計", "total", "全体"}


def parse_number(value):
    """「1,234」「¥500」「3.2%」「-」などを数値にする。空欄・不明は None。"""
    if value is None:
        return None
    s = unicodedata.normalize("NFKC", str(value)).strip()
    s = re.sub(r"[,¥円\s]", "", s)
    if s in ("", "-", "--", "—", "N/A", "n/a"):
        return None
    pct = s.endswith("%")
    s = s.rstrip("%")
    try:
        n = float(s)
    except ValueError:
        return None
    return n / 100 if pct else n


def normalize_title(title):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", title or "")).lower()


def read_rows(path):
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=enc) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判別できません: {path}")


def _find_column(headers, key):
    norm = {unicodedata.normalize("NFKC", h or "").strip(): h for h in headers}
    for alias in ALIASES[key]:
        if alias in norm:
            return norm[alias]
    return None


def load_listings(path):
    """CSVを職種タイトルごとに集計して返す。期間別の行があっても合算する。"""
    rows = read_rows(path)
    if not rows:
        raise ValueError(f"CSVにデータがありません: {path}")
    headers = rows[0].keys()
    cols = {k: _find_column(headers, k) for k in ALIASES}
    missing = [k for k in ("impressions", "clicks", "apps", "cost") if not cols[k]]
    if missing:
        raise ValueError(f"必要な列が見つかりません: {missing}。列名: {list(headers)}")

    agg = {}
    for r in rows:
        title = (r.get(cols["title"]) if cols["title"] else None) or "（職種名なし）"
        title = title.strip()
        if normalize_title(title) in TOTAL_WORDS:
            continue
        key = normalize_title(title)
        a = agg.setdefault(key, {"title": title, "impressions": 0, "clicks": 0, "apps": 0, "cost": 0.0})
        for k in ("impressions", "clicks", "apps", "cost"):
            a[k] += parse_number(r.get(cols[k])) or 0
    return list(agg.values())


def wilson(successes, n, z=Z):
    """割合の信頼区間（件数が少ないときに広くなる）。"""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, center - half), min(1.0, center + half))


def judge(successes, n, benchmark):
    """good / bad / near(判断保留) と、点推定が基準の上下どちらかを返す。"""
    if n <= 0:
        return {"status": "nodata", "direction": None, "rate": None}
    rate = successes / n
    lo, hi = wilson(successes, n)
    if lo >= benchmark:
        status = "good"
    elif hi < benchmark:
        status = "bad"
    else:
        status = "near"
    return {"status": status, "direction": "above" if rate >= benchmark else "below",
            "rate": rate, "low": lo, "high": hi}


def metrics(item):
    i, c, a, cost = item["impressions"], item["clicks"], item["apps"], item["cost"]
    return {
        "impressions": i, "clicks": c, "apps": a, "cost": cost,
        "ctr": c / i if i else None,
        "cvr": a / c if c else None,
        "cpc": cost / c if c else None,
        "cpa": cost / a if a else None,
    }


def diagnose_one(item, past=None, median_impressions=None):
    m = metrics(item)
    if past:
        pm = metrics(past)
        bench_ctr = pm["ctr"] if pm["ctr"] else DEFAULT_CTR
        bench_cvr = pm["cvr"] if pm["cvr"] else DEFAULT_CVR
        basis = "過去実績"
    else:
        pm = None
        bench_ctr, bench_cvr, basis = DEFAULT_CTR, DEFAULT_CVR, "目安値"

    jc = judge(m["clicks"], m["impressions"], bench_ctr)
    jv = judge(m["apps"], m["clicks"], bench_cvr)
    s_ctr, s_cvr = jc["status"], jv["status"]

    volume_low = bool(median_impressions) and m["impressions"] < median_impressions * 0.5

    if s_ctr == "nodata":
        issue = "nodata"
    elif s_ctr == "bad" and s_cvr == "bad":
        issue = "both"
    elif s_ctr == "bad":
        issue = "ctr"
    elif s_cvr == "bad":
        issue = "cvr"
    elif s_ctr == "good" and s_cvr == "good":
        issue = "volume" if volume_low else "good"
    elif (s_ctr == "near" and jc["direction"] == "below") or (s_cvr == "near" and jv["direction"] == "below"):
        issue = "watch"
    else:
        issue = "ok"

    findings = _findings(m, pm, jc, jv, bench_ctr, bench_cvr, basis, issue, volume_low)
    return {
        "title": item["title"], "metrics": m, "past_metrics": pm,
        "benchmark": {"ctr": bench_ctr, "cvr": bench_cvr, "basis": basis},
        "ctr": jc, "cvr": jv, "issue": issue, "volume_low": volume_low, "findings": findings,
    }


ISSUE_LABEL = {
    "ctr": "一覧画面での選ばれ方（クリック率）が主な課題",
    "cvr": "詳細ページから応募に至る率（応募率）が主な課題",
    "both": "クリック率・応募率の両方に課題",
    "watch": "基準付近。下回り気味のため継続して確認",
    "ok": "基準付近。大きな課題は見られない",
    "good": "クリック率・応募率ともに基準以上",
    "volume": "率は良好。表示回数を増やすことが課題",
    "nodata": "表示データがなく判断できない",
}


def _pct(x):
    return "－" if x is None else f"{x * 100:.1f}%"


def _yen(x):
    return "－" if x is None else f"{x:,.0f}円"


def _findings(m, pm, jc, jv, bctr, bcvr, basis, issue, volume_low):
    out = []
    out.append(f"クリック率 {_pct(m['ctr'])}（{basis} {_pct(bctr)}）／応募率 {_pct(m['cvr'])}（{basis} {_pct(bcvr)}）")
    for name, j, bench in (("クリック率", jc, bctr), ("応募率", jv, bcvr)):
        if j["status"] == "near":
            out.append(f"{name}は{basis}付近で、件数が少なく「基準より{'低い' if j['direction'] == 'below' else '高い'}」と断定できません（95%範囲 {_pct(j['low'])}〜{_pct(j['high'])}）。")
    if issue == "ctr":
        out.append("応募率は大きな問題がないため、表示されても選ばれていない点（タイトル・一覧に出る情報）を優先して見直します。")
    elif issue == "cvr":
        out.append("クリック率は大きな問題がないため、クリック後の詳細ページ・条件・応募のしやすさを優先して見直します。")
    elif issue == "both":
        out.append("両方が基準を下回ります。まずクリック率（母数）を改善し、その上で応募率を見直す順序が効率的です。")
    elif issue == "volume":
        out.append("クリック数・応募数が少ない場合でも、原因は原稿ではなく表示回数の不足です。予算・単価・勤務地や職種条件を確認します。")
    elif issue == "watch":
        out.append("下回り気味ですが断定できません。掲載期間を延ばして件数を増やし、再確認します。")
    if volume_low and issue != "volume":
        out.append("他の原稿に比べ表示回数が少なく、クリック・応募の件数も少なくなっている可能性があります。件数ではなく率で判断しています。")
    if m["cpc"] and m["cpa"] and m["cvr"]:
        out.append(f"応募単価 {_yen(m['cpa'])} ＝ クリック単価 {_yen(m['cpc'])} ÷ 応募率 {_pct(m['cvr'])}。単価は、クリック単価と応募率の両方で決まります。")
        if pm and pm["cpc"] and pm["cpa"]:
            out.append(f"過去実績との比較：クリック単価 {_yen(pm['cpc'])}→{_yen(m['cpc'])}、応募単価 {_yen(pm['cpa'])}→{_yen(m['cpa'])}。")
    elif m["apps"] == 0:
        out.append("応募が0件のため、応募単価は算出できません。")
    return out


def diagnose(csv_path, past_path=None):
    listings = load_listings(csv_path)
    past_map = {}
    if past_path:
        past_map = {normalize_title(p["title"]): p for p in load_listings(past_path)}
    imps = [x["impressions"] for x in listings if x["impressions"] > 0]
    median_imp = statistics.median(imps) if len(imps) >= 2 else None
    results = [diagnose_one(x, past_map.get(normalize_title(x["title"])), median_imp) for x in listings]

    total = {"title": "全体", **{k: sum(x[k] for x in listings) for k in ("impressions", "clicks", "apps", "cost")}}
    overall = diagnose_one(total)
    for r in results:
        r["issue_label"] = ISSUE_LABEL[r["issue"]]
    overall["issue_label"] = ISSUE_LABEL[overall["issue"]]
    return {"listings": results, "overall": overall}
