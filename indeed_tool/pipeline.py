"""データ(CSV)と原稿(PDF)を渡すと、提案書の下準備と組み立てを行う。

  python run.py proposal prepare データ1.csv データ2.csv --pdf 原稿.pdf --client "株式会社〇〇" -o data/work
      → CSVの集計・診断、原稿テキストの抽出と自動チェック、現状スライドの下書き、作業メモ(brief.md)を作る
  （提案の中身は、brief.md をもとにClaudeが proposal_spec.json に書く。外部のAIには送らない）
  python run.py proposal build data/work -o output
      → 提案書(pptx)と担当者向け資料(xlsx)を作る

顧客情報を扱うため、すべてローカルで処理し、外部へは送らない。
"""
import csv
import json
import os
import re
import statistics
import unicodedata
from datetime import date

from indeed_tool import nearby as nb
from indeed_tool.diagnose import DEFAULT_CTR, DEFAULT_CVR, diagnose, parse_number
from indeed_tool.proposal_deck import build as build_deck
from indeed_tool.staff_workbook import aggregate, build_workbook

COMBINED_FIELDS = ["職種タイトル", "参照番号"]


# ---------- CSV ----------
def _name_parts(path):
    """ファイル名「広告詳細_<ID>_<雇用形態>_<タイトル>_...」から参照番号とタイトルを推定する。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = stem.split("_")
    ref = next((p for p in parts if re.fullmatch(r"\d{5,}", p)), "")
    title = parts[3].strip() if len(parts) >= 4 and parts[0].startswith("広告詳細") else stem
    return ref, title or stem


def read_daily(path):
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=enc) as fh:
                return list(csv.DictReader(fh))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判別できません: {path}")


NORM_FIELDS = ["職種タイトル", "参照番号", "配信日", "期間開始", "日数", "表示数", "クリック数", "応募開始数", "応募数", "クリック単価", "利用済予算"]


def _export_date(path):
    m = re.search(r"_(\d{4})(\d{2})(\d{2})_\d{6}\.csv$", path)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _period_from_name(path):
    """ファイル名「…2026_11_1～11_30…」から集計期間を読む。"""
    m = re.search(r"(\d{4})_(\d{1,2})_(\d{1,2})\s*[～~〜-]\s*(\d{1,2})_(\d{1,2})", os.path.basename(path))
    if not m:
        return None
    y, mo, d, mo2, d2 = (int(x) for x in m.groups())
    return date(y, mo, d), date(y + (1 if mo2 < mo else 0), mo2, d2)


def load_source(path):
    """日別CSV(広告詳細)または月次CSV(広告配信実績)を、共通の形(NORM_FIELDS)に直して返す。
    月次CSVは1行が1期間の合計。期間はファイル名から読み、出力日が期間内なら出力日までの途中経過とする。"""
    rows = read_daily(path)
    if not rows:
        return []
    ref, title = _name_parts(path)
    if "配信日" in rows[0]:  # 日別
        out = []
        for r in rows:
            if (r.get("配信日") or "").strip() in ("合計", "総計", ""):
                continue
            out.append({"職種タイトル": title, "参照番号": ref, "配信日": r["配信日"], "期間開始": "", "日数": "",
                        "表示数": r.get("表示数"), "クリック数": r.get("クリック数"), "応募開始数": r.get("応募開始数"),
                        "応募数": r.get("応募数"), "クリック単価": r.get("クリック単価"), "利用済予算": r.get("利用済予算")})
        return out
    if "求人番号" in rows[0]:  # 月次
        per = _period_from_name(path)
        if not per:
            raise ValueError(f"月次CSVの期間をファイル名から読めません: {os.path.basename(path)}")
        first, last = per
        exp = _export_date(path)
        partial = bool(exp and first <= exp < last)
        if partial:
            last = exp
        out = []
        for r in rows:
            if (r.get("求人番号") or "").strip() in ("合計", "総計", ""):
                continue
            out.append({"職種タイトル": (r.get("求人内容") or title).strip(), "参照番号": ref,
                        "配信日": last.strftime("%Y/%m/%d"), "期間開始": first.strftime("%Y/%m/%d"),
                        "日数": (last - first).days + 1, "表示数": r.get("表示数"), "クリック数": r.get("クリック数"),
                        "応募開始数": r.get("応募開始数"), "応募数": r.get("応募数"), "クリック単価": r.get("クリック単価"),
                        "利用済予算": r.get("利用済予算")})
        return out
    raise ValueError(f"CSVの形式を判別できません（日別・月次のどちらでもない）: {os.path.basename(path)}")


def combine(csv_paths, out_path):
    """原稿ごとのCSV(日別または月次)を、職種タイトル・参照番号つきの1つのCSVにまとめる(合計行は除く)。"""
    rows_out = []
    # 同じ広告(参照番号)のCSVが複数あるときは、配信日が最も新しいもの(同じなら出力日時が後のもの)だけを使う
    best = {}
    for p in csv_paths:
        ref, _ = _name_parts(p)
        rs = load_source(p)
        stamp = "_".join(os.path.splitext(os.path.basename(p))[0].split("_")[-2:])  # 出力日時(例 20261105_093241)。後のものが完全なデータ
        key = (max((r["配信日"] for r in rs), default=""), stamp, len(rs))
        if not ref:
            best[p] = (key, rs)
        elif ref not in best or key > best[ref][0]:
            best[ref] = (key, rs)
    for _, rs in best.values():
        rows_out.extend(rs)
    fields = NORM_FIELDS
    if not rows_out:
        raise ValueError("データが読み込めませんでした")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)
    return rows_out


# ---------- 原稿PDF ----------
FOOT = re.compile(r"^\s*(https?://\S+|\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}.*|\d+\s*/\s*\d+\s*)$")


_RADICAL = re.compile("[⺀-⻿⼀-⿟豈-﫿]")


def fix_radicals(s):
    """PDFから出る部首文字(例：⽴⾼⼟⼥)や互換漢字だけを通常の漢字に直す。他の文字は原文のまま。"""
    return _RADICAL.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), s)


def pdf_text(path):
    from pypdf import PdfReader
    pages = [fix_radicals(p.extract_text() or "") for p in PdfReader(path).pages]
    lines = []
    for ln in "\n".join(pages).splitlines():
        if FOOT.match(ln):
            continue
        lines.append(ln.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _n(s):
    return unicodedata.normalize("NFKC", s or "")


def check_manuscript(text):
    """原稿の自動チェック。提案の材料(確認が必要な点)を返す。断定はせず「可能性」として扱う。"""
    t = _n(text)
    out = {"info": [], "flags": []}
    head_lines = []
    for ln in text.strip().splitlines():
        if re.search(r"応募画面へ進む|約1分|お仕事について", ln):
            break
        head_lines.append(ln.strip())
    first = re.sub(r"\s+", " ", "".join(x for x in head_lines if x)).strip() or (text.strip().splitlines() or [""])[0]
    out["title"] = first
    m = re.match(r"^(【[^】]*】)?\s*(.*?)(?:\s*[/／]\s*(.*))?$", first)
    job, catch = (m.group(2), m.group(3)) if m else (first, "")
    out["info"].append(f"タイトル：{first}（全体{len(first)}文字／職種タイトル部分{len(job.strip())}文字／キャッチ部分{len((catch or '').strip())}文字）")
    out["info"].append(f"原稿全体の文字数（目安）：{len(re.sub(r'\\s', '', text))}文字")

    ot = sorted({re.sub(r"\s+", "", x) for x in re.findall(
        r"残業(?:ほぼ)?(?:少|なし|無し|ゼロ)|月?平均残業時間\s*\d+\s*時間(?:以内)?|残業月?\s*\d+(?:\.\d+)?\s*時間(?:以内)?|固定残業時間[:：]?\s*(?:1ヶ月あたり)?\d+\s*時間", t)})
    if len(ot) >= 3:
        out["flags"].append(("条件表記のゆれ", f"残業の表記が{len(ot)}通り：" + "／".join(x.strip() for x in ot[:6]), "表記を数値1つにそろえる提案の候補"))
    if re.search(r"(履歴書|職務経歴書)[^\n]{0,20}(送付|郵送|送信|アップロード|ご提出|提出)", t):
        out["flags"].append(("応募時の書類", "選考プロセスに「履歴書・職務経歴書の送付」の記載（※応募画面の標準表示は変えられない）", "応募時に書類を求めているように読めるか確認"))
    if re.search(r"給与例\s*\n\s*(勤務時間|休日|社会保険|【)", t):
        out["flags"].append(("給与例が空欄", "「給与例」の項目の内容が空欄", "年収モデルを書く提案の候補"))
    if re.search(r"(2|3)0代[〜~\-～]?\s*(3|4)?0?代?\s*活躍", t):
        out["flags"].append(("年代の表記", "タイトルや本文に年代の表記（例：20〜40代活躍中）", "該当しない方が対象外と感じる可能性。応募の動機に置き換える候補"))
    for key, label in (("未経験", "未経験の可否"), ("ノルマ", "ノルマ"), ("研修", "研修"), ("賞与", "賞与"), ("昇給", "昇給"),
                       ("年間休日", "年間休日"), ("転勤", "転勤"), ("設立", "設立年")):
        out["info"].append(f"{label}：{'記載あり' if key in t else '記載なし'}")
    sal = nb.parse_salary(next((ln for ln in t.splitlines() if re.search(r"月給|年収", ln)), ""))
    if sal:
        out["salary"] = sal
    hm = re.search(r"年間休日\D{0,6}(\d{2,3})\s*日", t)
    out["holidays"] = int(hm.group(1)) if hm else None
    return out


def conditions(text):
    t = _n(text)
    keys = [("月給（下限）", r"月給[^\n]*"), ("基本給", r"基本給[^\n]*"), ("固定残業代", r"固定残業代[^\n]*"),
            ("賞与", r"賞与[^\n]*"), ("昇給", r"昇給[^\n]*"), ("年間休日", r"年間休日[\s】]*\d{2,3}日"),
            ("有給休暇", r"有給休暇[\s】]*\d+日"), ("試用期間", r"試用・?研修?期間[:：]?[^\n]*"), ("交通費", r"交通費[^\n]*")]
    out = []
    for label, pat in keys:
        m = re.search(pat, t)
        if m:
            out.append([label, re.sub(r"\s+", " ", m.group(0)).strip()[:80]])
    return out


# ---------- 現状スライド(自動) ----------
def _md(d):
    y, m, dd = d.replace("-", "/").split("/")[:3]
    return f"{int(m)}/{int(dd)}"


def _pct(x, d=1):
    return "－" if x is None else f"{x * 100:.{d}f}%"


def _round100(x):
    return f"約{int(round(x / 100.0) * 100):,}円"


def funnel_slide(aggs, client_label):
    aggs = sorted(aggs, key=lambda a: a["last"])
    cur, prev = aggs[-1], (aggs[-2] if len(aggs) > 1 else None)

    def m(a):
        return {"cpd": a["cost"] / a["days"], "cpc": a["cost"] / a["clk"] if a["clk"] else None,
                "ctr": a["clk"] / a["imp"] if a["imp"] else None, "asr": a["st"] / a["clk"] if a["clk"] else None,
                "acr": a["app"] / a["st"] if a["st"] else None, "cpa": a["cost"] / a["app"] if a["app"] else None,
                "cvr": a["app"] / a["clk"] if a["clk"] else None, "cpday": a["clk"] / a["days"]}

    mc, mp = m(cur), (m(prev) if prev else None)
    # 同じ原稿(タイトルが同じ)の月ごとの比較か、原稿が違う前回/今回の比較かで、呼び方を変える
    same_ad = bool(prev) and prev["title"] == cur["title"]
    if same_ad:
        import calendar
        y, mo = int(cur["last"][:4]), int(cur["last"][5:7])
        partial = int(cur["last"][8:10]) < calendar.monthrange(y, mo)[1]
        lp = f"{int(prev['first'][5:7])}月"
        lc = f"{int(cur['first'][5:7])}月" + ("(途中経過)" if partial else "")
        name_prev, name_cur = f"{lp}分", f"{int(cur['first'][5:7])}月分" + ("（途中）" if partial else "")
    else:
        lp, lc, name_prev, name_cur = "前回", "今回", "前回原稿", "今回原稿"

    def worse(k, higher_is_worse=False, th=0.1):
        if not mp or mp[k] is None or mc[k] is None:
            return False
        return mc[k] > mp[k] * (1 + th) if higher_is_worse else mc[k] < mp[k] * (1 - th)

    def row(a, mm, label, hl):
        bad_ctr = (worse("ctr") if hl and mp else (mm["ctr"] is not None and mm["ctr"] < DEFAULT_CTR and hl))
        cells = [
            {"v": _round100(mm["cpd"]), "s": f"{a['cost']:,.0f}円÷{a['days']}日"},
            {"v": f"{mm['cpc']:,.0f}円" if mm["cpc"] else "－", "s": f"クリック{a['clk']:,.0f}件", "bad": hl and worse("cpc", True, 0.3)},
            {"v": _pct(mm["ctr"]), "s": f"{a['clk']:,.0f} / {a['imp']:,.0f}", "bad": bad_ctr},
            {"v": _pct(mm["asr"]), "s": f"{a['st']:,.0f} / {a['clk']:,.0f}", "bad": hl and worse("asr")},
            {"v": _pct(mm["acr"]), "s": f"{a['st'] and a['app']:,.0f} / {a['st']:,.0f}", "bad": hl and (a["st"] > 0 and a["app"] == 0 or worse("acr"))},
            {"v": f"{mm['cpa']:,.0f}円" if mm["cpa"] else "算出不可", "s": f"応募{a['app']:,.0f}件" if a["app"] else "応募0件",
             "bad": hl and (not a["app"] or worse("cpa", True, 0.3))}]
        short = a["title"] if len(a["title"]) <= 12 else a["title"][:12] + "…"
        sub = (f"{_md(a['first'])}〜{_md(a['last'])}（{a['days']}日）" if same_ad else f"{short}｜{_md(a['first'])}〜{_md(a['last'])}")
        return {"name": label, "sub": sub, "highlight": hl, "cells": cells}

    rows = ([row(prev, mp, name_prev, False)] if prev else []) + [row(cur, mc, name_cur if prev else "対象原稿", True)]
    pts = []
    if prev:
        same_cost = abs(mc["cpd"] / mp["cpd"] - 1) <= 0.15
        if same_cost and mp["cpc"] and mc["cpc"] and mc["cpc"] / mp["cpc"] >= 1.3:
            pts.append(f"1日の費用は{lp}とほぼ同じですが、**クリック単価が約{mc['cpc'] / mp['cpc']:.1f}倍**になり、1日のクリック数は約{mp['cpday']:.0f}件→約{mc['cpday']:.0f}件に変化しています")
        else:
            pts.append(f"クリック率 {_pct(mp['ctr'])} → **{_pct(mc['ctr'])}**、1日のクリック数 約{mp['cpday']:.0f}件 → 約{mc['cpday']:.0f}件")
    if cur["st"] > 0 and cur["app"] == 0:
        pts.append(f"応募を始めた{cur['st']:.0f}名が**全員、完了前に離脱**。" + (f"{lp}は約{mp['acr'] * 100:.0f}%が完了しており、最も大きな差はここにあります" if mp and mp["acr"] else ""))
    elif mp and mp["acr"] is not None and mc["acr"] is not None:
        pts.append(f"応募完了率は {lp}{_pct(mp['acr'])} → **{lc}{_pct(mc['acr'])}**")
    else:
        pts.append(f"クリック率 {_pct(mc['ctr'])}（目安 {_pct(DEFAULT_CTR)}）、応募率 {_pct(mc['cvr'])}（目安 {_pct(DEFAULT_CVR)}）")
    headline = ("応募開始はあるが、完了は0件" if cur["st"] > 0 and cur["app"] == 0 else "数値の現状と課題")
    return {"type": "funnel", "title": f"現状|{headline}（※見出しは内容に合わせて修正）",
            "columns": ["1日の費用", "クリック単価", "クリック率", "応募開始率", "応募完了率", "応募単価"], "rows": rows, "points": pts,
            "notes": ["数値はIndeedのCSV（日別または月次）の集計。1日の費用＝費用÷配信日数",
                      "月次CSVの途中経過は、出力日までの数値。月の最終日まで配信された場合の数値ではない"]}


def cover_slide(client, aggs):
    aggs = sorted(aggs, key=lambda a: a["last"])
    cur = aggs[-1]
    sub = f"対象：{cur['title']}（{cur['first']}〜{cur['last']}）"
    if len(aggs) > 1:
        sub += (f"／比較：前月分（{aggs[-2]['first']}〜{aggs[-2]['last']}）" if aggs[-2]["title"] == cur["title"]
                else f"／比較：前回原稿（{aggs[-2]['first']}〜{aggs[-2]['last']}）")
    return {"type": "cover", "title": "Indeed掲載原稿 改善のご提案", "client": f"{client} 御中", "sub": sub}


# ---------- prepare ----------
def prepare(csv_paths, pdf_path, outdir, client="（顧客名）", today=None):
    os.makedirs(outdir, exist_ok=True)
    today = today or date.today().strftime("%Y/%m/%d")
    comb = os.path.join(outdir, "combined.csv")
    rows = combine(csv_paths, comb)
    aggs = aggregate(rows)
    diag = diagnose(comb)
    with open(os.path.join(outdir, "diagnosis.json"), "w", encoding="utf-8") as fh:
        json.dump(diag, fh, ensure_ascii=False, indent=2)

    text = pdf_text(pdf_path) if pdf_path else ""
    chk = check_manuscript(text) if text else {"info": [], "flags": [], "title": ""}
    if text:
        with open(os.path.join(outdir, "原稿.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)

    spec = {"slides": [cover_slide(client, aggs), funnel_slide(aggs, client),
                       {"type": "todo", "note": "課題(issues)・全体像(overview)・タイトルBefore/After(title_ba)・各提案(proposal)・期待する効果(kpi)・目指す状態(goal)・ご確認事項(checklist)をClaudeが書く"}]}
    with open(os.path.join(outdir, "proposal_spec.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)

    cur = sorted(aggs, key=lambda a: a["last"])[-1]
    sal = chk.get("salary")
    meta = {"client": f"{client} 御中", "date": today,
            "period": "／".join(f"{a['title']} {a['first']}〜{a['last']}" for a in sorted(aggs, key=lambda a: a["first"])),
            "conclusion": "（要記入：提案書の結論を1〜2文で）", "priority": "（要記入：最優先の提案）",
            "order": "（要記入：進め方）", "unconfirmed": "（要記入：未確認の点）",
            "salary_min": sal["monthly_low"] if sal else None, "salary_max": (sal["monthly_high"] if sal else None),
            "holidays": chk.get("holidays"), "conditions": conditions(text) if text else [], "need": {},
            "sources": ([[f"S{i}", f"日別データ（{a['title']}）", f"Indeed広告詳細CSV（参照番号 {a['ref']}）", today, ""]
                         for i, a in enumerate(aggs, 1)]
                        + ([[f"S{len(aggs) + 1}", "原稿の本文", f"原稿PDF（{os.path.basename(pdf_path)}）", today, "前回原稿の本文は受領した場合のみ"]] if pdf_path else [])
                        + [[f"S{len(aggs) + 2}", "Indeedの仕様（タイトルの3つの部分など）", "運用担当者の知見。Indeed公式の仕様ではない", "2026/11/03", ""]])}
    with open(os.path.join(outdir, "staff_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    brief = make_brief(client, aggs, diag, chk, text, cur)
    with open(os.path.join(outdir, "brief.md"), "w", encoding="utf-8") as fh:
        fh.write(brief)
    return {"aggs": aggs, "checks": chk, "outdir": outdir}


def make_brief(client, aggs, diag, chk, text, cur):
    L = [f"# 提案書の作業メモ｜{client}", "", "※顧客情報を含む。社外に出さない。手順は CLAUDE.md を参照。", "",
         "## 1. 数値（自動集計）", "", "| 原稿 | 期間 | 日数 | 表示 | クリック | 応募開始 | 応募 | 費用 | クリック率 | 応募開始率 | 応募完了率 | クリック単価 | 応募単価 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in sorted(aggs, key=lambda a: a["first"]):
        L.append(f"| {a['title'][:20]} | {a['first']}〜{a['last']} | {a['days']} | {a['imp']:,.0f} | {a['clk']:,.0f} | {a['st']:,.0f} | {a['app']:,.0f} | {a['cost']:,.0f} | "
                 f"{_pct(a['clk'] / a['imp'] if a['imp'] else None)} | {_pct(a['st'] / a['clk'] if a['clk'] else None)} | {_pct(a['app'] / a['st'] if a['st'] else None)} | "
                 f"{a['cost'] / a['clk']:,.0f}円 | {(format(round(a['cost'] / a['app']), ',') + '円') if a['app'] else '算出不可'} |")
    L += ["", "### 診断（95%信頼区間・目安 クリック率5%／応募率1.5%）"]
    for r in diag["listings"]:
        L.append(f"- **{r['title'][:30]}**：{r['issue_label']}")
        for f_ in r["findings"][:4]:
            L.append(f"  - {f_}")
    if not text:
        L += ["", "## 2. 原稿", "", "原稿PDFが渡されていません。"]
    else:
        L += ["", "## 2. 原稿の自動チェック（提案の材料。断定せず「可能性」として扱う）", ""]
        L += [f"- {x}" for x in chk["info"]]
        L += ["", "### 気づいた点"]
        L += [f"- **{a}**：{b}（{c}）" for a, b, c in chk["flags"]] or ["- 自動で検出できた点はありません。原稿を読んで確認する"]
    L += ["", "## 3. Claudeが書くこと", "",
          "1. `原稿.txt` を全文読み、**応募をためらう本当の理由**を考える（誰が・なぜ・どこで迷うか）",
          "2. 提案ごとに、目的・期待する効果（第1目標つき）・根拠・未確認の点を書く。「文言を足す」だけの提案にしない",
          "3. Indeedの制約を守る：本文はテキストのみ（記号の装飾はOK）／「約1分でカンタン入力」「【正社員】」は変更できない",
          "4. 原稿にない事実は書かず、確認が必要な点は「〇〇」と「確認後に掲載」にする",
          "5. `proposal_spec.json` の `todo` を実際のスライドに置き換え、`staff_meta.json` の（要記入）を埋める",
          "6. `python run.py proposal build <このフォルダ> -o output` で組み立て、画像にして見た目を確認する"]
    return "\n".join(L) + "\n"


# ---------- build ----------
def spec_problems(spec):
    return [s.get("note", "") for s in spec["slides"] if s["type"] == "todo"]


def deck_text(spec, meta):
    return json.dumps(spec, ensure_ascii=False) + json.dumps(meta, ensure_ascii=False)


def record_history(history_path, spec, deck, client=None, metrics=None, basis=None):
    """提案書に載った提案を履歴に記録する。同じ提案書名の回があれば置き換える（Claudeが提案を足して組み直したとき）。"""
    h = load_history(history_path)
    props = []
    for s in spec["slides"]:
        if s["type"] != "proposal":
            continue
        name = s["title"].split("|", 1)[-1].replace("（最優先）", "")
        props.append({"id": s.get("pid") or "custom:" + name, "name": name, "status": "提案済み"})
    rd = next((r for r in h["rounds"] if r.get("deck") == deck), None)
    if rd is None:
        rd = {"date": date.today().strftime("%Y/%m/%d"), "deck": deck}
        h["rounds"].append(rd)
    rd["proposals"] = props
    if metrics is not None:
        rd["metrics"] = metrics
    if basis:
        rd["basis"] = basis
    if client:
        h["client"] = client
    os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
    with open(history_path, "w", encoding="utf-8") as fh:
        json.dump(h, fh, ensure_ascii=False, indent=2)
    return props


def build_all(workdir, outdir, nearby_path=None, forbid=None, name="提案書", history_path=None):
    with open(os.path.join(workdir, "proposal_spec.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    with open(os.path.join(workdir, "staff_meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    todo = spec_problems(spec)
    if todo:
        raise SystemExit("提案の中身がまだ書かれていません（todo のスライドが残っています）:\n  " + "\n  ".join(todo))
    hits = [w for w in (forbid or []) if w and w in deck_text(spec, meta)]
    if hits:
        raise SystemExit(f"他のお客様の情報が混ざっている可能性があります（禁止語：{hits}）。作成を中止しました")
    os.makedirs(outdir, exist_ok=True)
    pptx = os.path.join(outdir, f"{name}.pptx")
    xlsx = os.path.join(outdir, f"{name}_担当者向け資料.xlsx")
    build_deck(spec, pptx)
    build_workbook(os.path.join(workdir, "combined.csv"), spec, meta, xlsx, nearby_path)
    unresolved = deck_text(spec, meta).count("（要記入")
    if history_path:
        record_history(history_path, spec, os.path.basename(pptx))
    return pptx, xlsx, unresolved


# ---------- auto：提案書を自動で生成する ----------
def load_market(path):
    """採用市場レポートの数値（手入力のCSV）。列：職種名,求職者数,求人数,求人あたり求職者数,採用難易度,平均給与,モバイル比率,現在
    現在の職種の行は「現在」列に ○ を入れる。"""
    if not path:
        return None
    rows = []
    for r in read_daily(path):
        if not (r.get("職種名") or "").strip():
            continue
        row = {"職種名": r["職種名"].strip(), "現在": bool((r.get("現在") or "").strip())}
        for k in ("求職者数", "求人数", "求人あたり求職者数", "採用難易度", "平均給与", "モバイル比率"):
            v = parse_number(r.get(k))
            row[k] = (v if (k != "モバイル比率" or v is None or v <= 1) else v / 100) if v is not None else None
        rows.append(row)
    return rows


def load_history(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    return {"rounds": [], "manual": []}


def proposed_ids(h):
    """提案済みの提案ID。status が「再提案可」のものは除く。"""
    ids = set()
    for rd in h.get("rounds", []):
        for p in rd.get("proposals", []):
            if p.get("status") != "再提案可" and p.get("id"):
                ids.add(p["id"])
    for m in h.get("manual", []):
        if m.get("status") != "再提案可":
            ids.update(m.get("ids", []))
    return ids


def auto(csv_paths, pdf_path, workdir, outdir, client, nearby_path=None, market_path=None, posted=None,
         forbid=None, name="提案書", max_props=7, history_path=None, redo=False):
    """下準備 → ルールで提案を自動作成 → 提案書(pptx)と担当者向け資料(xlsx)まで一気に作る。
    history_path：会社ごとの提案履歴。提案済みの提案は除き、作成後に今回の提案を追記する。
    redo：直前の回の作り直し（修正）。直前の回を置き換え、履歴の重複扱いにしない。"""
    from indeed_tool import rules
    hist = load_history(history_path)
    if redo and hist["rounds"]:
        hist["rounds"] = hist["rounds"][:-1]
    r = prepare(csv_paths, pdf_path, workdir, client)
    with open(os.path.join(workdir, "原稿.txt"), encoding="utf-8") as fh:
        text = fh.read()
    nearby = None
    if nearby_path:
        sal = (r["checks"].get("salary") or {}).get("monthly_low")
        nearby = nb.summarize(nb.load(nearby_path), client=sal)
    spec, meta_fill, D, ordered = rules.build_spec(r["aggs"], text, r["checks"], client, nearby,
                                                   load_market(market_path), posted, max_props,
                                                   exclude=proposed_ids(hist), round_no=len(hist["rounds"]) + 1,
                                                   last_round=(hist["rounds"][-1] if hist["rounds"] else None))
    if not ordered:  # 履歴にない自動提案がない：提案はClaudeが考えて加える。それまで組み立てない
        spec["slides"].insert(5, {"type": "todo", "note": "履歴にない新しい提案を考えて、overview・title_ba・proposal・kpi・goal・checklist のスライドを書く"})
    with open(os.path.join(workdir, "proposal_spec.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
    mp = os.path.join(workdir, "staff_meta.json")
    with open(mp, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta.update(meta_fill)
    if nearby_path:
        meta["sources"].append([f"S{len(meta['sources']) + 1}", "周辺の求人", "公開されている求人の検索結果（手作業で収集）", meta["date"],
                                "担当者向け資料の「5.周辺比較」。提案書では社名を出さない"])
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    if not ordered:
        return None, None, [], D.get("skipped", [])
    pptx, xlsx, _ = build_all(workdir, outdir, nearby_path, forbid, name)
    if history_path:
        mc = D["mc"]
        if redo:  # 作り直し：直前の回を外した履歴を書き戻してから記録する
            with open(history_path, "w", encoding="utf-8") as fh:
                json.dump(hist, fh, ensure_ascii=False, indent=2)
        record_history(history_path, spec, os.path.basename(pptx), client,
                       {k: (round(mc[k], 4) if mc.get(k) is not None else None) for k in ("ctr", "asr", "acr", "cvr", "cpc", "cpa")},
                       f"{D['lp'] + '→' if D['lp'] else ''}{D['lc']}（{D['cur']['first']}〜{D['cur']['last']}）")
    return pptx, xlsx, ordered, D.get("skipped", [])
