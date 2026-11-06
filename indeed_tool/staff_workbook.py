"""担当者向け資料(Excel)を作る。docs/提案書作成プロンプト.md の「8. 担当者向け資料」に対応。

入力はすべてローカルのファイル(顧客情報を含むため data/ 配下・Git対象外):
  - 日別データを1つにまとめたCSV(職種タイトル・参照番号列つき)
  - 提案書の中身(proposal_spec JSON)
  - 顧客・出典などの補足(meta JSON)

使い方:
  python -m indeed_tool.staff_workbook data/combined.csv data/proposal_spec_v3.json data/staff_meta.json -o output/担当者向け資料.xlsx
  (周辺求人を入れる場合) ... --nearby data/nearby.csv
"""
import argparse
import csv
import json
from collections import OrderedDict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from indeed_tool.diagnose import DEFAULT_CTR, DEFAULT_CVR, parse_number, wilson
from indeed_tool.nearby import load as load_nearby

NAVY, PINK, PANEL, INPUT = "1E2B45", "FBE7E2", "EEF1F6", "FFF7D6"
FONT = "Yu Gothic"
thin = Side(style="thin", color="D5DBE5")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def f(bold=False, color="2B3345", size=11):
    return Font(name=FONT, bold=bold, color=color, size=size)


def head(ws, row, labels, widths=None):
    for c, lab in enumerate(labels, 1):
        cell = ws.cell(row=row, column=c, value=lab)
        cell.font = f(True, "FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    if widths:
        for c, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = w


def put(ws, row, col, value, fmt=None, bold=False, fill=None, wrap=True, color="2B3345", align=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = f(bold, color)
    cell.border = BORDER
    cell.alignment = Alignment(wrap_text=wrap, vertical="top", horizontal=align)
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = PatternFill("solid", fgColor=fill)
    return cell


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = f(True, NAVY, 16)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = f(False, "7A8599", 10)
    ws.sheet_view.showGridLines = False


def load_daily(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def aggregate(rows):
    agg = OrderedDict()
    for r in rows:
        k = (r["職種タイトル"], r.get("参照番号", ""))
        a = agg.setdefault(k, {"title": r["職種タイトル"], "ref": r.get("参照番号", ""), "imp": 0, "clk": 0, "st": 0,
                               "app": 0, "cost": 0.0, "days": 0, "first": r["配信日"], "last": r["配信日"]})
        a["imp"] += parse_number(r["表示数"]) or 0
        a["clk"] += parse_number(r["クリック数"]) or 0
        a["st"] += parse_number(r["応募開始数"]) or 0
        a["app"] += parse_number(r["応募数"]) or 0
        a["cost"] += parse_number(r["利用済予算"]) or 0
        a["days"] += 1
        a["first"] = min(a["first"], r["配信日"])
        a["last"] = max(a["last"], r["配信日"])
    return list(agg.values())


def judge(x, n, bench):
    if n <= 0:
        return "データなし"
    lo, hi = wilson(x, n)
    if lo >= bench:
        return "目安以上"
    if hi < bench:
        return "目安を下回る"
    return "判断保留（断定できない）"


def sheet_summary(wb, meta, aggs, props):
    ws = wb.active
    ws.title = "1.要約"
    title(ws, f"担当者向け資料｜{meta['client']}", f"作成日 {meta['date']}／顧客情報を含むため社外に出さない")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 100
    rows = [("結論", meta["conclusion"]), ("最優先", meta["priority"]), ("進め方", meta["order"]),
            ("対象期間", meta["period"]), ("未確認の主な点", meta["unconfirmed"])]
    for i, (k, v) in enumerate(rows, 4):
        put(ws, i, 1, k, bold=True, fill=PANEL)
        put(ws, i, 2, v)
        ws.row_dimensions[i].height = 48
    r = 4 + len(rows) + 1
    put(ws, r, 1, "提案一覧", bold=True, fill=PANEL)
    for i, p in enumerate(props, 1):
        put(ws, r + i, 1, f"提案{p['no']}", bold=True)
        put(ws, r + i, 2, f"{p['name']}　［{p['tag']}］　目的：{p['purpose']}")


def sheet_diag(wb, aggs):
    ws = wb.create_sheet("2.実績と診断")
    title(ws, "実績と課題の診断", "水色の列は数式。率の判定は95%信頼区間（Wilson法）。件数が少ないときは断定しない")
    labels = ["原稿", "参照番号", "期間", "日数", "表示回数", "クリック数", "応募開始数", "応募数", "利用済予算",
              "クリック率", "応募開始率", "応募完了率", "応募率", "クリック単価", "応募単価", "1日の費用",
              "1日のクリック数", "クリック率 下限", "クリック率 上限", "応募率 下限", "応募率 上限", "クリック率の判定", "応募率の判定"]
    head(ws, 4, labels, [34, 11, 22, 6, 10, 10, 10, 8, 12, 9, 10, 10, 8, 10, 10, 10, 11, 10, 10, 10, 10, 20, 20])
    ws.row_dimensions[4].height = 34
    n = len(aggs)
    for i, a in enumerate(aggs):
        r = 5 + i
        lo_c, hi_c = wilson(a["clk"], a["imp"])
        lo_v, hi_v = wilson(a["app"], a["clk"])
        vals = [a["title"], a["ref"], f"{a['first']}〜{a['last']}", a["days"], a["imp"], a["clk"], a["st"], a["app"], a["cost"]]
        for c, v in enumerate(vals, 1):
            put(ws, r, c, v, fmt="#,##0" if c >= 4 else None)
        form = {10: f"=IFERROR(F{r}/E{r},\"-\")", 11: f"=IFERROR(G{r}/F{r},\"-\")", 12: f"=IFERROR(H{r}/G{r},\"-\")",
                13: f"=IFERROR(H{r}/F{r},\"-\")", 14: f"=IFERROR(I{r}/F{r},\"-\")", 15: f"=IFERROR(I{r}/H{r},\"算出不可(応募0)\")",
                16: f"=IFERROR(I{r}/D{r},\"-\")", 17: f"=IFERROR(F{r}/D{r},\"-\")"}
        for c, v in form.items():
            put(ws, r, c, v, fmt="0.0%" if c in (10, 11, 12, 13) else "#,##0", fill=PANEL)
        for c, v in zip((18, 19, 20, 21), (lo_c, hi_c, lo_v, hi_v)):
            put(ws, r, c, v, fmt="0.0%")
        put(ws, r, 22, judge(a["clk"], a["imp"], DEFAULT_CTR), bold=True)
        put(ws, r, 23, judge(a["app"], a["clk"], DEFAULT_CVR), bold=True)
    r = 5 + n + 1
    put(ws, r, 1, "判定の基準：クリック率5.0%／応募率1.5%（目安値）。応募率＝応募数÷クリック数。応募単価＝クリック単価÷応募率。", wrap=False)
    put(ws, r + 1, 1, "応募完了0件の偶然性（前回の完了率で計算）：", wrap=False)
    if n >= 2 and aggs[0]["st"] and aggs[1]["st"] is not None:
        p_done = aggs[0]["app"] / aggs[0]["st"]
        put(ws, r + 1, 5, (1 - p_done) ** aggs[1]["st"], fmt="0.0%", bold=True)
        put(ws, r + 1, 6, f"＝(1−{p_done:.3f})^{int(aggs[1]['st'])}", wrap=False)


def sheet_daily(wb, rows):
    ws = wb.create_sheet("3.日別データ")
    title(ws, "日別データ（元CSVの内容。合計行は除く）")
    keys = ["職種タイトル", "参照番号", "配信日", "表示数", "クリック数", "応募開始数", "応募数", "クリック単価", "利用済予算"]
    head(ws, 3, keys, [34, 11, 12, 9, 9, 10, 8, 11, 11])
    for i, r in enumerate(rows, 4):
        for c, k in enumerate(keys, 1):
            v = r[k]
            if c >= 4:
                v = parse_number(v)
            put(ws, i, c, v, fmt="#,##0" if c >= 4 else None, wrap=False)


def sheet_props(wb, props):
    ws = wb.create_sheet("4.提案の詳細")
    title(ws, "提案の詳細", "スライドの内容に、根拠・未確認の点・実施状況を加えたもの")
    labels = ["提案", "名称", "区分", "変更前", "変更後", "目的", "期待する効果", "理由（根拠）", "未確認の点・注意", "反映に必要な情報", "状態"]
    head(ws, 4, labels, [6, 24, 22, 30, 34, 34, 28, 40, 40, 30, 12])
    for i, p in enumerate(props, 5):
        vals = [p["no"], p["name"], p["tag"], p["before"], p["after"], p["purpose"], p["effect"], p["reasons"], p["notes"], p["need"], "未着手"]
        for c, v in enumerate(vals, 1):
            put(ws, i, c, v, fill=INPUT if c == 11 else None)
        ws.row_dimensions[i].height = 110


def sheet_nearby(wb, meta, jobs=None, include_hourly=False):
    ws = wb.create_sheet("5.周辺比較")
    sub = ("公開されている求人情報で確認できた範囲だけを記入し、確認日を必ず書く。効果の優劣は断定しない"
           if not jobs else f"周辺求人 {len(jobs)}件を読み込み、給与を月給に換算して記入（年収は÷12。時給・日給は"
           + ("8h×21日で換算" if include_hourly else "集計から除外") + "）")
    title(ws, "周辺の求人との比較", sub)
    labels = ["No.", "求人タイトル", "会社名", "勤務地・最寄駅", "給与（原文）", "月給下限", "月給上限", "年間休日",
              "残業の記載", "未経験の可否", "特徴的な訴求", "出典URL", "確認日", "換算・備考"]
    head(ws, 4, labels, [5, 34, 20, 18, 26, 11, 11, 10, 16, 12, 26, 32, 12, 26])
    jobs = jobs or []
    n = max(15, len(jobs))
    for i in range(n):
        r = 5 + i
        j = jobs[i] if i < len(jobs) else None
        sal = j["salary"] if j else None
        use = bool(sal) and (include_hourly or sal["kind"] not in ("時給", "日給"))
        note = ""
        if j:
            if not sal:
                note = "給与を読み取れず集計外"
            elif not use:
                note = f"{sal['kind']}のため集計外"
            elif sal["converted"] != "なし":
                note = sal["converted"]
            if j.get("備考"):
                note = (note + "／" if note else "") + j["備考"]
        vals = [i + 1, j and j["求人タイトル"], j and j["会社名"], j and j["勤務地・最寄駅"], j and j["給与"],
                sal["monthly_low"] if use else None, sal["monthly_high"] if use else None, j and j["holidays"],
                j and j["残業の記載"], j and j["未経験の可否"], j and j["特徴的な訴求"], j and j["出典URL"], j and j["確認日"], note or None]
        for c, v in enumerate(vals, 1):
            put(ws, r, c, v or None if c != 1 else v, fill=INPUT if (c > 1 and not j) else None,
                fmt="#,##0" if c in (6, 7) else None)
    last = 5 + n - 1
    t = last + 2
    rows = [("平均", "AVERAGE"), ("中央値", "MEDIAN"), ("件数", "COUNT")]
    for k, (lab, fn) in enumerate(rows):
        put(ws, t + k, 2, lab, bold=True, fill=PANEL)
        for c, col in ((6, "F"), (7, "G"), (8, "H")):
            put(ws, t + k, c, f"=IFERROR({fn}({col}5:{col}{last}),\"-\")", fmt="0" if fn == "COUNT" or c == 8 else "#,##0",
                fill=PANEL)
    cr = t + len(rows)
    put(ws, cr, 2, "貴社（今回原稿）", bold=True, fill=PINK)
    put(ws, cr, 6, meta["salary_min"], fmt="#,##0", fill=PINK)
    put(ws, cr, 7, meta["salary_max"], fmt="#,##0", fill=PINK)
    put(ws, cr, 8, meta["holidays"], fmt="0", fill=PINK)
    put(ws, cr + 1, 2, "貴社 − 平均", bold=True)
    for c, col in ((6, "F"), (7, "G"), (8, "H")):
        put(ws, cr + 1, c, f"=IFERROR({col}{cr}-{col}{t},\"-\")", fmt="#,##0;[Red]-#,##0")
    put(ws, cr + 2, 2, "貴社の順位（月給下限が高い順）", bold=True)
    put(ws, cr + 2, 6, f"=IFERROR(COUNTIF(F5:F{last},\">\"&F{cr})+1&\"位／\"&COUNT(F5:F{last})&\"件中\",\"-\")")
    put(ws, cr + 4, 1, "注意：件数が少ない場合は参考値。求人サイトからの自動取得は利用規約で禁止されているため行わず、"
                       "人が集めた情報（CSV・貼り付けテキスト）を読み取って集計しています。", wrap=False)
    put(ws, cr + 5, 1, "注意：年収表記の求人は賞与込みの額を÷12しているため、月給表記の求人より高めに出ます。"
                       "月給表記どうしの比較もあわせて確認してください。", wrap=False)


def sheet_market(wb):
    ws = wb.create_sheet("6.市場データ")
    title(ws, "採用市場レポートの比較（記入用）", "未記入。職種ごとの求職者数・競合の少なさを比べ、職種名を選ぶ根拠にする（提案1の確認）")
    labels = ["職種名の候補", "求職者数（母数）", "1求人あたり求職者数", "採用難易度", "平均月給", "人気の検索キーワード", "実態との一致", "備考"]
    head(ws, 4, labels, [30, 14, 18, 12, 12, 40, 14, 30])
    cands = ["広告営業", "企画営業", "法人営業", "広報", "メディア営業", "教育関連の営業"]
    for i, cnd in enumerate(cands, 5):
        for c in range(1, 9):
            put(ws, i, c, cnd if c == 1 else None, fill=INPUT if c > 1 else None, fmt="#,##0" if c in (2, 3, 5) else None)
    notes = ["注意：レポートは府県単位で地域を絞れない／検索語ごとの集計のため、同じ求人が複数の職種に表示されうる／実績と時期がずれる",
             "実態と一致することが必須条件。仕事内容と合わない職種名は使わない",
             "判断の考え方：条件が平均以上なら母数の大きい市場、差をつけにくいなら1求人あたり求職者数が多い市場を優先"]
    for i, t in enumerate(notes, 12):
        put(ws, i, 1, t, wrap=False)


def sheet_decision(wb, meta):
    ws = wb.create_sheet("7.決裁者向け参考")
    title(ws, "決裁者向けの参考（条件の比較）", "給与・休日など決裁が必要な条件。周辺の実例を主に、地域の平均は参考とする")
    head(ws, 4, ["項目", "現在の原稿", "周辺の実例（5.周辺比較から）", "差・考え方", "判断（決裁者が記入）"], [24, 40, 34, 36, 24])
    items = meta["conditions"]
    for i, (k, v) in enumerate(items, 5):
        put(ws, i, 1, k, bold=True, fill=PANEL)
        put(ws, i, 2, v)
        put(ws, i, 3, None, fill=INPUT)
        put(ws, i, 4, None, fill=INPUT)
        put(ws, i, 5, None, fill=INPUT)
        ws.row_dimensions[i].height = 36


def sheet_sources(wb, meta):
    ws = wb.create_sheet("8.根拠一覧")
    title(ws, "根拠一覧（参照ID・出典・確認日）")
    head(ws, 3, ["参照ID", "内容", "出典", "確認日", "備考"], [8, 50, 56, 14, 40])
    for i, row in enumerate(meta["sources"], 4):
        for c, v in enumerate(row, 1):
            put(ws, i, c, v)


def sheet_questions(wb, items):
    ws = wb.create_sheet("9.追加確認事項")
    title(ws, "追加確認事項（お客様に確認する内容）")
    head(ws, 3, ["提案", "確認する内容", "具体的に聞くこと", "確認日", "回答", "状態"], [10, 28, 60, 12, 40, 10])
    for i, (no, item, why) in enumerate(items, 4):
        for c, v in enumerate([no, item, why, None, None, "未確認"], 1):
            put(ws, i, c, v, fill=INPUT if c in (4, 5, 6) else None)
        ws.row_dimensions[i].height = 40


def sheet_verify(wb, props):
    ws = wb.create_sheet("10.検証記録")
    title(ws, "検証記録（次回の打ち合わせで、前回施策のBefore/Afterを示すため）", "変更を反映したら記入する。1つずつ変更し、効果を見分ける")
    labels = ["提案", "名称", "反映日", "対象指標", "Before（期間・数値）", "After（期間・数値）", "変化", "判断", "次のアクション"]
    head(ws, 4, labels, [8, 26, 12, 14, 28, 28, 12, 12, 34])
    for i, p in enumerate(props, 5):
        for c, v in enumerate([f"提案{p['no']}", p["name"], None, p["metric"], None, None, None, None, None], 1):
            put(ws, i, c, v, fill=INPUT if c >= 3 and c != 4 else None)
    r = 5 + len(props) + 1
    put(ws, r, 1, "記入の目安：変更前後で同じ指標を、同じ日数以上で比較する。件数が少ないときは断定せず、掲載期間を延ばして再確認する。", wrap=False)


METRIC = {1: "クリック率・クリック単価", 2: "クリック率", 3: "応募完了率", 4: "応募開始率", 5: "応募開始率", 6: "応募開始率", 7: "応募開始率・完了率"}


def extract_props(spec, meta):
    out = []
    for s in spec["slides"]:
        if s["type"] != "proposal":
            continue
        no = int(s["title"].split("|")[0].replace("提案", ""))
        p = s["panel"]
        eff = " ".join(t.replace("**", "") for t in p["effect"])
        out.append({"no": no, "name": s["title"].split("|", 1)[1], "tag": p["tag"], "before": p["before"], "after": p["after"],
                    "purpose": p["purpose"], "effect": eff, "reasons": "\n".join("・" + t for t in p["reasons"]),
                    "notes": "\n".join("・" + t for t in s.get("notes", [])), "need": meta["need"].get(str(no), "なし"),
                    "metric": METRIC.get(no, "")})
    return out


def build_workbook(daily_csv, spec, meta, out, nearby=None, include_hourly=False):
    """日別CSV・提案書の中身(spec)・補足(meta)から担当者向けExcelを作る。"""
    rows = load_daily(daily_csv)
    aggs = aggregate(rows)
    props = extract_props(spec, meta)
    checklist = next((s["items"] for s in spec["slides"] if s["type"] == "checklist"), [])
    wb = Workbook()
    sheet_summary(wb, meta, aggs, props)
    sheet_diag(wb, aggs)
    sheet_daily(wb, rows)
    sheet_props(wb, props)
    sheet_nearby(wb, meta, load_nearby(nearby) if nearby else None, include_hourly)
    sheet_market(wb)
    sheet_decision(wb, meta)
    sheet_sources(wb, meta)
    sheet_questions(wb, checklist)
    sheet_verify(wb, props)
    for ws in wb.worksheets:
        ws.freeze_panes = "A5" if ws.title not in ("1.要約",) else None
    wb.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("daily_csv")
    ap.add_argument("spec")
    ap.add_argument("meta")
    ap.add_argument("--nearby", help="周辺求人のCSV、または検索結果をコピーした .txt")
    ap.add_argument("--include-hourly", action="store_true", help="時給・日給も月給に換算して含める")
    ap.add_argument("-o", default="output/staff.xlsx")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    with open(a.meta, encoding="utf-8") as fh:
        meta = json.load(fh)
    build_workbook(a.daily_csv, spec, meta, a.o, a.nearby, a.include_hourly)
    print("保存しました:", a.o)


if __name__ == "__main__":
    main()
