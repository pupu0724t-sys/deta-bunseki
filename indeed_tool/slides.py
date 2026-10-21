"""診断結果と分析文（JSON）から、お客様向けPowerPointを作る。"""
import math

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

NAVY = RGBColor(0x1F, 0x2A, 0x44)
BLUE = RGBColor(0x2F, 0x6D, 0xB5)
LIGHT = RGBColor(0xEE, 0xF3, 0xF9)
GRAY = RGBColor(0x6B, 0x72, 0x80)
TEXT = RGBColor(0x22, 0x2B, 0x38)
GOOD = RGBColor(0x2E, 0x8B, 0x57)
BAD = RGBColor(0xC8, 0x4B, 0x3C)
WARN = RGBColor(0xD9, 0x91, 0x1A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Yu Gothic"

W, H = 13.333, 7.5
warnings = []


def _lines(text, width_in, pt):
    per_line = max(1, int(width_in * 72 / pt * 0.95))
    return sum(max(1, math.ceil(len(p) / per_line)) for p in str(text).split("\n"))


def _fit_size(paras, width_in, height_in, start, minimum, spacing=1.45, gap_pt=6):
    """全段落が枠に収まる最大のフォントサイズを返す。収まらなければ警告。"""
    pt = start
    while pt >= minimum:
        total = sum(_lines(p, width_in - 0.2, pt) * pt * spacing + gap_pt for p in paras) / 72
        if total <= height_in - 0.1:
            return pt
        pt -= 1
    warnings.append(f"文字が枠に収まらない可能性: {paras[0][:20]}…")
    return minimum


def text_box(slide, x, y, w, h, paras, start=16, minimum=11, color=TEXT, bold=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, bullet=False, fixed=False):
    paras = [paras] if isinstance(paras, str) else list(paras)
    shown = [("・" + p if bullet else p) for p in paras]
    pt = start if fixed else _fit_size(shown, w, h, start, minimum)
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Inches(0.05))
    for i, p in enumerate(shown):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.space_after = Pt(6)
        run = para.add_run()
        run.text = p
        run.font.size = Pt(pt)
        run.font.name = FONT
        run.font.bold = bold
        run.font.color.rgb = color
    return tb


def rect(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line:
        s.line.color.rgb = line
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def new_slide(prs, title, subtitle=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, W, 0.12, BLUE)
    text_box(s, 0.6, 0.35, 12.1, 0.8, title, start=28, minimum=20, color=NAVY, bold=True,
             anchor=MSO_ANCHOR.MIDDLE)
    if subtitle:
        text_box(s, 0.6, 1.1, 12.1, 0.45, subtitle, start=14, minimum=11, color=GRAY)
    return s


def pct(x):
    return "－" if x is None else f"{x * 100:.1f}%"


def yen(x):
    return "－" if x is None else f"{x:,.0f}円"


def num(x):
    return f"{x:,.0f}"


STATUS = {
    "good": ("基準以上", GOOD),
    "bad": ("基準を下回る", BAD),
    "near": ("基準付近（判断保留）", WARN),
    "nodata": ("データなし", GRAY),
}


def kpi_card(slide, x, y, w, h, label, value, sub=None, color=NAVY):
    rect(slide, x, y, w, h, LIGHT)
    text_box(slide, x + 0.1, y + 0.03, w - 0.2, 0.3, label, start=12, color=GRAY, fixed=True)
    text_box(slide, x + 0.1, y + 0.33, w - 0.2, 0.48, value, start=20, color=color, bold=True, fixed=True)


def rate_chart(slide, x, y, w, h, d):
    cd = CategoryChartData()
    cd.categories = ["クリック率", "応募率"]
    cd.add_series("実績", [(d["metrics"]["ctr"] or 0) * 100, (d["metrics"]["cvr"] or 0) * 100])
    cd.add_series(d["benchmark"]["basis"], [d["benchmark"]["ctr"] * 100, d["benchmark"]["cvr"] * 100])
    gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(12)
    ch.legend.font.name = FONT
    ch.value_axis.has_major_gridlines = False
    ch.value_axis.visible = False
    ch.value_axis.minimum_scale = 0
    ch.category_axis.tick_labels.font.size = Pt(13)
    ch.category_axis.tick_labels.font.name = FONT
    for series, color in zip(ch.plots[0].series, (BLUE, RGBColor(0xB8, 0xC4, 0xD6))):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
    plot = ch.plots[0]
    plot.gap_width = 80
    plot.has_data_labels = True
    plot.data_labels.number_format = '0.0"%"'
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.font.size = Pt(12)
    plot.data_labels.font.name = FONT
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END


def metrics_slide(prs, d, title):
    m = d["metrics"]
    s = new_slide(prs, title, f"判定の基準：{d['benchmark']['basis']}（クリック率 {pct(d['benchmark']['ctr'])}／応募率 {pct(d['benchmark']['cvr'])}）")
    cards = [("表示回数", num(m["impressions"])), ("クリック数", num(m["clicks"])), ("応募数", num(m["apps"])),
             ("利用済予算", yen(m["cost"])), ("クリック単価", yen(m["cpc"])), ("応募単価", yen(m["cpa"]))]
    for i, (lab, val) in enumerate(cards):
        kpi_card(s, 0.6 + (i % 2) * 2.5, 1.7 + (i // 2) * 0.95, 2.4, 0.85, lab, val)
    rate_chart(s, 5.7, 1.65, 3.6, 2.9, d)
    for i, (name, key) in enumerate((("クリック率", "ctr"), ("応募率", "cvr"))):
        label, color = STATUS[d[key]["status"]]
        rect(s, 9.5, 1.7 + i * 1.45, 3.2, 1.3, LIGHT)
        text_box(s, 9.6, 1.75 + i * 1.45, 3.0, 0.3, name, start=12, color=GRAY, fixed=True)
        text_box(s, 9.6, 2.05 + i * 1.45, 3.0, 0.45, label, start=16, color=color, bold=True, fixed=True)
        d_ = d[key]
        if d_.get("low") is not None:
            text_box(s, 9.6, 2.55 + i * 1.45, 3.0, 0.35, f"95%範囲 {pct(d_['low'])}〜{pct(d_['high'])}", start=11, color=GRAY, fixed=True)
    rect(s, 0.6, 4.65, 12.1, 0.05, BLUE)
    text_box(s, 0.6, 4.75, 12.1, 2.45, d["findings"], start=14, minimum=10, bullet=True)
    return s


def labeled_box(slide, x, y, w, h, label, paras, fill=LIGHT, accent=BLUE, start=14, minimum=10):
    rect(slide, x, y, w, h, fill)
    rect(slide, x, y, 0.07, h, accent)
    text_box(slide, x + 0.15, y + 0.05, w - 0.25, 0.32, label, start=12, color=accent, bold=True, fixed=True)
    text_box(slide, x + 0.15, y + 0.38, w - 0.25, h - 0.43, paras, start=start, minimum=minimum)


def proposal_slide(prs, listing_title, no, p):
    s = new_slide(prs, f"案{no}　{p['name']}", f"{listing_title}　／　修正する箇所：{p['area']}　／　改善を見る指標：{p['target_metric']}")
    labeled_box(s, 0.6, 1.7, 5.95, 1.75, "課題点", p["issue"], accent=BAD)
    labeled_box(s, 6.75, 1.7, 5.95, 1.75, "なぜこの提案か（根拠）", p["why"])
    labeled_box(s, 0.6, 3.6, 5.6, 2.0, "現状", p["before"], fill=RGBColor(0xF3, 0xF4, 0xF6), accent=GRAY)
    arrow = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(6.3), Inches(4.35), Inches(0.7), Inches(0.5))
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = BLUE
    arrow.line.fill.background()
    labeled_box(s, 7.1, 3.6, 5.6, 2.0, "修正案", p["after"], fill=RGBColor(0xE3, 0xEE, 0xFA), accent=BLUE)
    labeled_box(s, 0.6, 5.75, 5.95, 1.4, "期待する効果と確認方法", p["expected"], accent=GOOD)
    labeled_box(s, 6.75, 5.75, 5.95, 1.4, "留意点", p.get("caution", "特になし"), accent=WARN)


def build(diagnosis, analysis, out_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    overall = diagnosis["overall"]
    listings = diagnosis["listings"]
    by_title = {a["title"]: a for a in analysis.get("listings", [])}

    # 表紙（署名・社名は入れない）
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, W, H, NAVY)
    rect(s, 0.8, 3.55, 1.6, 0.07, BLUE)
    text_box(s, 0.8, 1.9, 11.5, 1.5, analysis.get("report_title", "Indeed掲載 効果分析と改善のご提案"),
             start=40, minimum=28, color=WHITE, bold=True, anchor=MSO_ANCHOR.BOTTOM)
    text_box(s, 0.8, 3.8, 11.5, 1.2, [x for x in (analysis.get("client_name"), analysis.get("period")) if x],
             start=20, color=RGBColor(0xC9, 0xD6, 0xE8))

    # サマリー
    s = new_slide(prs, "結論サマリー")
    text_box(s, 0.6, 1.4, 12.1, 1.5, analysis.get("summary", overall["issue_label"]), start=20, minimum=14, color=NAVY, bold=True)
    items = [f"【{x['title']}】{x['issue_label']}" for x in listings]
    text_box(s, 0.6, 3.0, 12.1, 3.9, items, start=16, minimum=11, bullet=True)

    # 全体像
    if len(listings) > 1:
        metrics_slide(prs, overall, "全体の数値")
        s = new_slide(prs, "原稿別の比較", "率で比較します（件数ではなく、表示・クリックに対する割合）")
        rows, cols = len(listings) + 1, 6
        shape = s.shapes.add_table(rows, cols, Inches(0.6), Inches(1.7), Inches(12.1), Inches(0.5 * rows))
        heads = ["職種タイトル", "表示回数", "クリック率", "応募率", "応募単価", "判定"]
        widths = [3.7, 1.6, 1.6, 1.6, 1.7, 1.9]
        for i, wd in enumerate(widths):
            shape.table.columns[i].width = Inches(wd)
        for c, h_ in enumerate(heads):
            _cell(shape.table.cell(0, c), h_, True)
        for r, d in enumerate(listings, 1):
            m = d["metrics"]
            vals = [d["title"], num(m["impressions"]), pct(m["ctr"]), pct(m["cvr"]), yen(m["cpa"]),
                    {"ctr": "クリック率に課題", "cvr": "応募率に課題", "both": "両方に課題", "watch": "継続確認",
                     "ok": "大きな課題なし", "good": "良好", "volume": "表示回数に課題", "nodata": "データなし"}[d["issue"]]]
            for c, v in enumerate(vals):
                _cell(shape.table.cell(r, c), v, False)

    # 原稿別
    for d in listings:
        a = by_title.get(d["title"], {})
        nm = d.get("place") or d["title"]
        metrics_slide(prs, d, f"数値の診断：{nm}")
        if a.get("observations"):
            s = new_slide(prs, f"原稿の課題点：{nm}", "数値の診断と、原稿の該当箇所を結びつけて整理しました。")
            n = len(a["observations"])
            rh = min(1.7, 5.3 / n)
            for i, o in enumerate(a["observations"]):
                y = 1.7 + i * (rh + 0.1)
                rect(s, 0.6, y, 12.1, rh, LIGHT)
                rect(s, 0.6, y, 0.08, rh, BLUE)
                text_box(s, 0.8, y + 0.05, 2.2, rh - 0.1, o["area"], start=16, minimum=11, color=NAVY, bold=True,
                         anchor=MSO_ANCHOR.MIDDLE)
                text_box(s, 3.1, y + 0.05, 9.5, rh - 0.1,
                         [f"課題：{o['problem']}", f"根拠：{o['evidence']}"], start=14, minimum=10)
        if a.get("proposals"):
            s = new_slide(prs, f"改善案の一覧：{nm}", "課題と提案の対応です。詳細は次ページ以降をご覧ください。")
            ps = a["proposals"]
            shape = s.shapes.add_table(len(ps) + 1, 4, Inches(0.6), Inches(1.7), Inches(12.1), Inches(0.9 * (len(ps) + 1)))
            for i, wd in enumerate([2.6, 3.0, 4.5, 2.0]):
                shape.table.columns[i].width = Inches(wd)
            for c, h_ in enumerate(["提案", "修正する箇所", "解決したい課題", "改善を見る指標"]):
                _cell(shape.table.cell(0, c), h_, True)
            for r, p in enumerate(ps, 1):
                for c, v in enumerate([f"案{r}　{p['name']}", p["area"], p["issue"], p["target_metric"]]):
                    _cell(shape.table.cell(r, c), v, False)
            for i, p in enumerate(ps, 1):
                proposal_slide(prs, nm, i, p)
        if a.get("competitor_ideas"):
            s = new_slide(prs, f"同業他社に見られる工夫（参考）：{nm}",
                          "掲載中の他社原稿から、特徴的な内容を紹介します。効果の優劣は判断していません。")
            n = len(a["competitor_ideas"])
            cw = (12.1 - 0.3 * (n - 1)) / n
            for i, c in enumerate(a["competitor_ideas"]):
                x = 0.6 + i * (cw + 0.3)
                rect(s, x, 1.8, cw, 4.6, LIGHT)
                text_box(s, x + 0.1, 1.9, cw - 0.2, 4.4, [c["idea"], c.get("note", "")] if c.get("note") else [c["idea"]],
                         start=15, minimum=10)

    # 次のアクション
    if analysis.get("next_actions"):
        s = new_slide(prs, "次のアクション")
        text_box(s, 0.6, 1.5, 12.1, 5.4, [f"{i}. {t}" for i, t in enumerate(analysis["next_actions"], 1)],
                 start=18, minimum=12)
    if analysis.get("notes"):
        s = new_slide(prs, "ご確認事項")
        text_box(s, 0.6, 1.5, 12.1, 5.4, analysis["notes"], start=14, minimum=11, bullet=True)

    prs.save(out_path)
    return list(warnings)


def _cell(cell, text, header):
    cell.text = ""
    p = cell.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = str(text)
    r.font.size = Pt(14)
    r.font.name = FONT
    r.font.bold = header
    r.font.color.rgb = WHITE if header else TEXT
    cell.fill.solid()
    cell.fill.fore_color.rgb = NAVY if header else WHITE
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE

