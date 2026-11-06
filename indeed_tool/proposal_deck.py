"""提案中心・図中心の改善提案スライドを作る。

内容は JSON(spec) で渡す。顧客情報は spec 側(data/ 配下・Git対象外)にだけ置き、
このファイルには入れない。

使い方:
  python -m indeed_tool.proposal_deck data/proposal_spec.json -o output/提案書.pptx
"""
import argparse
import copy
import json

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

W, H = 13.333, 7.5
FONT = "Yu Gothic"
NAVY = RGBColor(0x1E, 0x2B, 0x45)
RED = RGBColor(0xD9, 0x53, 0x3B)
PINK = RGBColor(0xFB, 0xE7, 0xE2)
PANEL = RGBColor(0xEE, 0xF1, 0xF6)
BORDER = RGBColor(0xE1, 0xE6, 0xEE)
GRAY = RGBColor(0x7A, 0x85, 0x99)
LGRAY = RGBColor(0x9A, 0xA3, 0xB2)
TEXT = RGBColor(0x2B, 0x33, 0x45)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FOOTER = "Indeed掲載原稿 改善のご提案"


# ---------- 基本部品 ----------
def _font(run, size, color=TEXT, bold=False, strike=False):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    f.name = FONT
    rpr = run._r.get_or_add_rPr()
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = etree.SubElement(rpr, qn("a:ea"))
    ea.set("typeface", FONT)
    if strike:
        rpr.set("strike", "sngStrike")


def text(slide, x, y, w, h, paras, size=14, color=TEXT, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=1.15, gap=0, bullet=False):
    """paras: 文字列 / 段落のリスト。段落は文字列か [(文字, {color,bold,strike,size}), ...]。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for side in ("left", "right", "top", "bottom"):
        setattr(tf, f"margin_{side}", Inches(0.02))
    if isinstance(paras, str):
        paras = [paras]
    paras = [q for p in paras for q in (p.split("\n") if isinstance(p, str) else [p])]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        if gap and i:
            p.space_before = Pt(gap)
        runs = [(para, {})] if isinstance(para, str) else para
        if bullet:
            runs = [("・", {})] + list(runs)
        for t, st in runs:
            r = p.add_run()
            r.text = t
            _font(r, st.get("size", size), st.get("color", color), st.get("bold", bold), st.get("strike", False))
    return tb


def box(slide, x, y, w, h, fill=PANEL, line=None, radius=0.12, shape=MSO_SHAPE.ROUNDED_RECTANGLE, alpha=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = min(0.5, radius / min(w, h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
        if alpha is not None:
            clr = s.fill._xPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
            a = etree.SubElement(clr, qn("a:alpha"))
            a.set("val", str(int(alpha * 100000)))
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    s.shadow.inherit = False
    s.text_frame.text = ""
    return s


def pill(slide, x, y, w, h, label, fill=NAVY, color=WHITE, size=12):
    box(slide, x, y, w, h, fill, radius=h / 2)
    text(slide, x, y, w, h, label, size=size, color=color, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def num_circle(slide, x, y, d, label, fill=RED, size=16):
    box(slide, x, y, d, d, fill, shape=MSO_SHAPE.OVAL)
    text(slide, x, y, d, d, str(label), size=size, color=WHITE, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def arrow(slide, x, y, w, h, fill=RED, shape=MSO_SHAPE.RIGHT_ARROW):
    box(slide, x, y, w, h, fill, shape=shape)


def new_slide(prs, title, page, notes=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    text(s, 0.6, 0.38, 12.1, 0.8, title, size=28, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 0.6, 7.0, 6, 0.3, FOOTER, size=10, color=LGRAY)
    text(s, 11.7, 7.0, 1.0, 0.3, str(page), size=10, color=LGRAY, align=PP_ALIGN.RIGHT)
    if notes:
        s.notes_slide.notes_text_frame.text = "\n".join(notes)
    return s


def rich(s):
    """「普通**赤太字**普通~~取り消し~~」を runs に変換する。"""
    out, i, buf = [], 0, ""
    while i < len(s):
        if s.startswith("**", i) or s.startswith("~~", i):
            mark = s[i:i + 2]
            j = s.find(mark, i + 2)
            if j < 0:
                break
            if buf:
                out.append((buf, {}))
                buf = ""
            seg = s[i + 2:j]
            out.append((seg, {"color": RED, "bold": True} if mark == "**" else {"color": LGRAY, "strike": True}))
            i = j + 2
        else:
            buf += s[i]
            i += 1
    if buf:
        out.append((buf, {}))
    return out


# ---------- スライド種別 ----------
def slide_cover(prs, sp, page):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, NAVY, radius=0, shape=MSO_SHAPE.RECTANGLE)
    box(s, 9.6, 0.9, 4.6, 4.6, RED, shape=MSO_SHAPE.OVAL)
    box(s, 8.4, 3.6, 3.6, 3.6, RGBColor(0x8A, 0x96, 0xAD), shape=MSO_SHAPE.OVAL, alpha=0.45)
    text(s, 0.75, 2.4, 9, 1.0, sp["title"], size=40, color=WHITE, bold=True)
    box(s, 0.78, 3.55, 1.5, 0.06, RED, radius=0, shape=MSO_SHAPE.RECTANGLE)
    text(s, 0.75, 3.8, 8.5, 1.6, [sp.get("client", ""), sp.get("sub", "")], size=18, color=RGBColor(0xC9, 0xD0, 0xDD), gap=6)


def slide_funnel(prs, sp, page):
    """現状：原稿ごとに、段階別の数値を横に並べる。"""
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    cols = sp["columns"]
    n = len(cols)
    lw, x0, gapx = 2.1, 0.6, 0.12
    cw = (12.1 - lw - gapx * (n - 1)) / n
    y = 1.5
    for j, c in enumerate(cols):
        x = x0 + lw + j * (cw + gapx)
        text(s, x, y, cw, 0.35, c, size=12, color=GRAY, bold=True, align=PP_ALIGN.CENTER)
    for i, row in enumerate(sp["rows"]):
        ry = y + 0.45 + i * 1.45
        hl = row.get("highlight", False)
        box(s, x0, ry, 12.1, 1.3, PINK if hl else PANEL)
        text(s, x0 + 0.2, ry, lw - 0.2, 1.3, [row["name"], [(row.get("sub", ""), {"size": 10.5, "color": GRAY, "bold": False})]],
             size=16, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE, gap=2)
        for j, cell in enumerate(row["cells"]):
            x = x0 + lw + j * (cw + gapx)
            bad = cell.get("bad", False)
            box(s, x, ry + 0.15, cw, 1.0, WHITE)
            text(s, x, ry + 0.2, cw, 0.55, cell["v"], size=22, color=RED if bad else NAVY, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE)
            text(s, x, ry + 0.75, cw, 0.35, cell.get("s", ""), size=10, color=GRAY, align=PP_ALIGN.CENTER)
            if j < n - 1:
                arrow(s, x + cw - 0.02, ry + 0.58, gapx + 0.04, 0.14, LGRAY)
    box(s, x0, 4.95, 12.1, 1.8, PANEL)
    text(s, x0 + 0.35, 5.1, 11.4, 1.5, [rich(t) for t in sp["points"]], size=15, gap=8, bullet=True,
         anchor=MSO_ANCHOR.MIDDLE)


def slide_issues(prs, sp, page):
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    L = sp["left"]
    box(s, 0.6, 1.5, 7.3, 5.3, PANEL)
    text(s, 0.95, 1.7, 6.8, 0.45, L["head"], size=18, color=NAVY, bold=True)
    for i, it in enumerate(L["items"]):
        y = 2.35 + i * 1.45
        num_circle(s, 0.95, y + 0.05, 0.75, it.get("mark", i + 1), size=20)
        text(s, 1.95, y, 5.8, 0.45, it["h"], size=17, color=NAVY, bold=True)
        text(s, 1.95, y + 0.48, 5.8, 0.8, it["d"], size=13, color=GRAY)
    R = sp["right"]
    box(s, 8.1, 1.5, 4.6, 5.3, PINK)
    text(s, 8.4, 1.7, 4.1, 0.45, R["head"], size=18, color=NAVY, bold=True)
    text(s, 8.4, 2.2, 4.1, 1.0, R["lead"], size=13, color=TEXT, bold=True)
    cd = CategoryChartData()
    cd.categories = R["categories"]
    for name, vals in R["series"]:
        cd.add_series(name, vals)
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(8.3), Inches(3.2), Inches(4.25), Inches(3.0), cd)
    ch = gf.chart
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.TOP
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(11)
    ch.legend.font.name = FONT
    ch.value_axis.visible = False
    ch.value_axis.has_major_gridlines = False
    ch.category_axis.tick_labels.font.size = Pt(11)
    ch.category_axis.tick_labels.font.name = FONT
    ch.category_axis.format.line.color.rgb = LGRAY
    plot = ch.plots[0]
    plot.gap_width = 60
    plot.overlap = -10
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = '0.0%'
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(11)
    dl.font.name = FONT
    for ser, col in zip(plot.series, (LGRAY, RED)):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = col
    text(s, 8.4, 6.2, 4.1, 0.5, R.get("note", ""), size=10, color=GRAY)


def slide_overview(prs, sp, page):
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    for k, col in enumerate(sp["columns"]):
        x = 0.6 + k * 6.2
        text(s, x, 1.45, 5.9, 0.45, [[(col["head"], {"size": 18, "bold": True, "color": NAVY}),
                                     ("  " + col.get("sub", ""), {"size": 12, "color": GRAY})]])
        items = col["items"]
        ch = min(1.15, (4.95 - 0.12 * (len(items) - 1)) / len(items))
        for i, it in enumerate(items):
            y = 2.0 + i * (ch + 0.12)
            box(s, x, y, 5.9, ch, PANEL)
            num_circle(s, x + 0.2, y + (ch - 0.6) / 2, 0.6, it["no"], size=16)
            text(s, x + 1.0, y + 0.08, 3.3, 0.4, it["name"], size=15, color=NAVY, bold=True)
            text(s, x + 1.0, y + 0.47, 4.75, ch - 0.5, "目的：" + it["purpose"], size=11.5, color=GRAY)
            tag_fill = RED if it.get("confirm") else NAVY
            pill(s, x + 4.35, y + 0.1, 1.4, 0.32, it["tag"], fill=tag_fill, size=10)
        if col.get("footer"):
            fy = 2.0 + len(items) * (ch + 0.12)
            fh = 0.36 * len(col["footer"]) + 0.35
            box(s, x, fy, 5.9, fh, WHITE, line=BORDER)
            text(s, x + 0.25, fy + 0.12, 5.4, fh - 0.2, [rich(t) for t in col["footer"]], size=12.5, gap=4)


def slide_title_ba(prs, sp, page):
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    for k, (lab, key, fill, pfill) in enumerate((("Before(現状)", "before", PANEL, GRAY), ("After(改善後)", "after", PINK, RED))):
        x = 0.6 + k * 6.55
        pill(s, x, 1.45, 2.2, 0.4, lab, fill=pfill, size=12)
        box(s, x, 2.0, 5.55, 2.9, fill)
        runs = rich(sp[key])
        if key == "before":
            runs = [(t, st if st else {"color": TEXT}) for t, st in runs]
        text(s, x + 0.3, 2.25, 5.0, 2.9, [runs], size=20, color=TEXT, spacing=1.3)
    arrow(s, 6.25, 3.15, 0.6, 0.6)
    text(s, 0.6, 5.05, 12, 0.35, [[("取り消し線", {"color": LGRAY, "strike": True}), ("＝変更前の表現　", {"color": GRAY}),
                                  ("赤の太字", {"color": RED, "bold": True}), ("＝変更後の表現　", {"color": GRAY}),
                                  (sp.get("legend_note", ""), {"color": GRAY})]], size=11)
    n = len(sp["links"])
    cw = (12.1 - 0.25 * (n - 1)) / n
    for i, (no, name) in enumerate(sp["links"]):
        x = 0.6 + i * (cw + 0.25)
        box(s, x, 5.9, cw, 0.85, PANEL)
        num_circle(s, x + 0.25, 6.03, 0.6, no, size=15)
        text(s, x + 1.05, 5.9, cw - 1.2, 0.85, f"提案{no}　{name}", size=15, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)


def proposal_panel(s, p):
    x, y, w = 8.35, 1.45, 4.4
    box(s, x, y, w, 5.4, WHITE, line=BORDER)
    ix, iw = x + 0.28, w - 0.56
    pill(s, ix, y + 0.22, iw, 0.38, p["tag"], fill=NAVY, size=11.5)
    cy = y + 0.75
    text(s, ix, cy, iw, 0.7, [[("変更前　", {"color": GRAY, "bold": True}), (p["before"], {"color": GRAY})]], size=12)
    cy += p.get("before_h", 0.58)
    text(s, ix, cy, iw, 0.9, [[("変更後　", {"color": RED, "bold": True}), (p["after"], {"color": RED, "bold": True})]], size=12.5)
    cy += p.get("after_h", 0.68)
    box(s, ix, cy, iw, 0.02, BORDER, radius=0, shape=MSO_SHAPE.RECTANGLE)
    cy += 0.12
    text(s, ix, cy, iw, 0.3, "目的", size=12, color=NAVY, bold=True)
    text(s, ix, cy + 0.3, iw, 0.75, p["purpose"], size=12)
    cy += p.get("purpose_h", 0.88)
    text(s, ix, cy, iw, 0.3, "期待する効果", size=12, color=NAVY, bold=True)
    box(s, ix, cy + 0.32, iw, 0.62, PINK, radius=0.08)
    text(s, ix + 0.12, cy + 0.32, iw - 0.24, 0.62, [rich(t) for t in p["effect"]], size=12, color=TEXT,
         anchor=MSO_ANCHOR.MIDDLE)
    cy += 1.0
    text(s, ix, cy, iw, 0.3, "理由", size=12, color=NAVY, bold=True)
    text(s, ix, cy + 0.3, iw, 6.75 - cy - 0.3, p["reasons"], size=10.5, color=TEXT, bullet=True, gap=3)


# ---- 左側の図 ----
def vis_search_compare(s, v, x, y, w, h):
    text(s, x + 0.3, y + 0.2, w - 0.6, 0.45, [[(v["head"], {"bold": True, "color": NAVY, "size": 17}),
                                             ("  " + v.get("note", ""), {"color": GRAY, "size": 11})]])
    for i, c in enumerate(v["cards"]):
        cy = y + 0.85 + i * 1.5
        pill(s, x + 0.3, cy, 1.9, 0.34, c["label"], fill=RED if c.get("after") else GRAY, size=11)
        box(s, x + 0.3, cy + 0.42, w - 0.6, 0.9, WHITE)
        text(s, x + 0.5, cy + 0.45, w - 1.0, 0.85, [rich(c["title"])], size=15, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    by = y + 3.95
    text(s, x + 0.3, by, w - 0.6, 0.35, v["bars_head"], size=12, color=NAVY, bold=True)
    if "pairs" in v:
        n = len(v["pairs"])
        pw = (w - 0.6 - 0.2 * (n - 1)) / n
        for i, (lab, before, after) in enumerate(v["pairs"]):
            px = x + 0.3 + i * (pw + 0.2)
            box(s, px, by + 0.42, pw, 0.92, WHITE)
            text(s, px + 0.15, by + 0.47, pw - 0.3, 0.3, lab, size=11, color=GRAY, bold=True)
            text(s, px + 0.15, by + 0.78, pw - 0.3, 0.5, [[(before, {"color": TEXT}), ("  →  ", {"color": GRAY}),
                                                          (after, {"color": RED, "bold": True})]], size=16, bold=True)
        return
    mx = max(b[1] for b in v["bars"])
    for i, (lab, val, disp, hl) in enumerate(v["bars"]):
        yy = by + 0.42 + i * 0.4
        text(s, x + 0.3, yy, 2.3, 0.32, lab, size=11, color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
        bw = (w - 3.6) * val / mx
        box(s, x + 2.65, yy + 0.04, bw, 0.26, RED if hl else LGRAY, radius=0.03, shape=MSO_SHAPE.RECTANGLE)
        text(s, x + 2.72 + bw, yy, 0.8, 0.32, disp, size=11, color=RED if hl else TEXT, bold=True, anchor=MSO_ANCHOR.MIDDLE)


def vis_search_mock(s, v, x, y, w, h):
    text(s, x + 0.3, y + 0.2, w - 0.6, 0.45, [[(v["head"], {"bold": True, "color": NAVY, "size": 17}),
                                             ("  (イメージ図)", {"color": GRAY, "size": 11})]])
    box(s, x + 0.3, y + 0.8, w - 0.6, 2.55, WHITE)
    text(s, x + 0.55, y + 0.95, w - 1.1, 1.0, [rich(v["title"])], size=15, color=NAVY, bold=True, spacing=1.2)
    text(s, x + 0.55, y + 2.0, w - 1.1, 0.6, v["meta"], size=11, color=GRAY)
    for i, chip in enumerate(v["chips"]):
        box(s, x + 0.55 + i * 2.0, y + 2.75, 1.85, 0.4, PANEL, radius=0.08)
        text(s, x + 0.55 + i * 2.0, y + 2.75, 1.85, 0.4, chip, size=11, color=TEXT, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.6 + len(v["chips"]) * 2.0, y + 2.75, 2.6, 0.4, v.get("chip_note", ""), size=10, color=GRAY,
         anchor=MSO_ANCHOR.MIDDLE)
    n = len(v["icons"])
    iw = (w - 0.6) / n
    for i, (mark, lab) in enumerate(v["icons"]):
        ix = x + 0.3 + i * iw
        num_circle(s, ix + 0.1, y + 3.65, 0.8, mark, size=18)
        text(s, ix + 1.0, y + 3.65, iw - 1.05, 0.8, lab, size=13, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, y + 4.65, w - 0.6, 0.5, v.get("caption", ""), size=11, color=GRAY)


def vis_funnel_compare(s, v, x, y, w, h):
    text(s, x + 0.3, y + 0.2, w - 0.6, 0.45, v["head"], size=17, color=NAVY, bold=True)
    for i, r in enumerate(v["rows"]):
        ry = y + 0.8 + i * 1.15
        hl = r.get("bad", False)
        text(s, x + 0.3, ry, 1.6, 0.9, r["name"], size=13, color=RED if hl else NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        for j, (lab, val) in enumerate(r["steps"]):
            bx = x + 1.95 + j * 1.85
            box(s, bx, ry, 1.6, 0.9, PINK if (hl and j == len(r["steps"]) - 1) else WHITE)
            text(s, bx, ry + 0.05, 1.6, 0.3, lab, size=10, color=GRAY, align=PP_ALIGN.CENTER)
            text(s, bx, ry + 0.33, 1.6, 0.5, val, size=17, color=RED if (hl and j == len(r["steps"]) - 1) else NAVY,
                 bold=True, align=PP_ALIGN.CENTER)
            if j < len(r["steps"]) - 1:
                arrow(s, bx + 1.63, ry + 0.33, 0.2, 0.24, LGRAY)
    cy = y + 3.25
    if "quote" in v:
        q = v["quote"]
        text(s, x + 0.3, cy, w - 0.6, 0.35, q["head"], size=12, color=NAVY, bold=True)
        box(s, x + 0.3, cy + 0.42, 3.2, 1.1, WHITE)
        text(s, x + 0.45, cy + 0.42, 2.9, 1.1, q["before"], size=12, color=GRAY, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        arrow(s, x + 3.6, cy + 0.77, 0.45, 0.4)
        box(s, x + 4.15, cy + 0.42, 3.1, 1.1, PINK)
        text(s, x + 4.3, cy + 0.42, 2.8, 1.1, q["after"], size=12, color=RED, bold=True, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.3, cy + 1.6, w - 0.6, 0.4, v.get("caption", ""), size=11, color=GRAY)
        return
    text(s, x + 0.3, cy, w - 0.6, 0.35, v["conflict_head"], size=12, color=NAVY, bold=True)
    a, b = v["conflict"]
    box(s, x + 0.3, cy + 0.42, 3.05, 1.05, WHITE)
    text(s, x + 0.45, cy + 0.42, 2.75, 1.05, a, size=12.5, color=TEXT, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    num_circle(s, x + 3.47, cy + 0.67, 0.55, "≠", size=18)
    box(s, x + 4.15, cy + 0.42, 3.1, 1.05, WHITE)
    text(s, x + 4.3, cy + 0.42, 2.8, 1.05, b, size=12.5, color=TEXT, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, cy + 1.55, w - 0.6, 0.4, v.get("caption", ""), size=11, color=RED, bold=True)


def vis_list_ba(s, v, x, y, w, h):
    for k, key in enumerate(("before", "after")):
        bx = x + 0.3 + k * (w - 0.6) / 2
        bw = (w - 0.6) / 2 - 0.15
        labels = v.get("labels", ["Before", "After"])
        pill(s, bx, y + 0.25, 2.9, 0.34, labels[k], fill=GRAY if k == 0 else RED, size=11)
        bh = max(len(v["before"]), len(v["after"])) * 0.42 + 0.5
        box(s, bx, y + 0.7, bw, bh, WHITE if k == 0 else PINK)
        lines = []
        for t in v[key]:
            lines.append(rich(t) if k else [(t, {})])
        text(s, bx + 0.2, y + 0.85, bw - 0.35, bh - 0.2, lines, size=12.5, gap=5)
    text(s, x + 0.3, y + 0.85 + bh, w - 0.6, 0.6, v.get("caption", ""), size=11.5, color=GRAY)


def vis_chips_unify(s, v, x, y, w, h):
    text(s, x + 0.3, y + 0.2, w - 0.6, 0.45, v["head"], size=17, color=NAVY, bold=True)
    for i, (where, what) in enumerate(v["chips"]):
        cy = y + 0.85 + i * 0.72
        text(s, x + 0.3, cy, 1.3, 0.55, where, size=11, color=GRAY, anchor=MSO_ANCHOR.MIDDLE)
        box(s, x + 1.6, cy, 3.1, 0.55, WHITE)
        text(s, x + 1.6, cy, 3.1, 0.55, what, size=12.5, color=TEXT, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    mid = y + 0.85 + (len(v["chips"]) * 0.72 - 0.17) / 2
    arrow(s, x + 4.85, mid - 0.3, 0.55, 0.6)
    box(s, x + 5.5, mid - 0.55, 1.75, 1.1, RED)
    text(s, x + 5.5, mid - 0.55, 1.75, 1.1, v["unified"], size=14, color=WHITE, bold=True, align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, y + 4.0, w - 0.6, 1.1, [rich(t) for t in v.get("caption", [])], size=12, gap=4)


def vis_flow_steps(s, v, x, y, w, h):
    text(s, x + 0.3, y + 0.2, w - 0.6, 0.45, [[(v["head"], {"bold": True, "color": NAVY, "size": 17}),
                                             ("  " + v.get("note", ""), {"color": GRAY, "size": 11})]])
    n = len(v["steps"])
    sw = (w - 0.6 - 0.25 * (n - 1)) / n
    for i, (t, d) in enumerate(v["steps"]):
        sx = x + 0.3 + i * (sw + 0.25)
        box(s, sx, y + 0.85, sw, 2.5, WHITE)
        num_circle(s, sx + (sw - 0.6) / 2, y + 1.0, 0.6, i + 1, size=16)
        text(s, sx + 0.08, y + 1.7, sw - 0.16, 0.65, t, size=13, color=NAVY, bold=True, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, sx + 0.1, y + 2.4, sw - 0.2, 1.15, d, size=10.5, color=GRAY, align=PP_ALIGN.CENTER)
        if i < n - 1:
            arrow(s, sx + sw + 0.03, y + 2.05, 0.19, 0.3)
    box(s, x + 0.3, y + 3.6, w - 0.6, 0.95, PINK)
    text(s, x + 0.5, y + 3.6, w - 1.0, 0.95, [rich(t) for t in v["strip"]], size=12, anchor=MSO_ANCHOR.MIDDLE, gap=2)


def vis_fix_table(s, v, x, y, w, h):
    text(s, x + 0.3, y + 0.2, w - 0.6, 0.45, v["head"], size=17, color=NAVY, bold=True)
    widths = [1.6, 2.65, 2.7]
    heads = ["箇所", "現状", "修正案"]
    ty = y + 0.8
    cx = x + 0.3
    for j, hd in enumerate(heads):
        box(s, cx, ty, widths[j] - 0.05, 0.4, NAVY, radius=0.05)
        text(s, cx, ty, widths[j] - 0.05, 0.4, hd, size=11.5, color=WHITE, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        cx += widths[j]
    for i, row in enumerate(v["rows"]):
        ry = ty + 0.5 + i * 1.0
        cx = x + 0.3
        for j, cell in enumerate(row):
            box(s, cx, ry, widths[j] - 0.05, 0.9, WHITE if j < 2 else PINK, radius=0.05)
            text(s, cx + 0.08, ry, widths[j] - 0.21, 0.9, [rich(cell)] if j == 2 else cell, size=11,
                 color=NAVY if j == 0 else (GRAY if j == 1 else TEXT), bold=(j == 0), anchor=MSO_ANCHOR.MIDDLE)
            cx += widths[j]


VISUALS = {"search_compare": vis_search_compare, "search_mock": vis_search_mock, "funnel_compare": vis_funnel_compare,
           "list_ba": vis_list_ba, "chips_unify": vis_chips_unify, "flow_steps": vis_flow_steps, "fix_table": vis_fix_table}


def slide_proposal(prs, sp, page):
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    box(s, 0.6, 1.45, 7.55, 5.4, PANEL)
    v = sp["visual"]
    VISUALS[v["type"]](s, v, 0.6, 1.45, 7.55, 5.4)
    proposal_panel(s, sp["panel"])


def slide_kpi(prs, sp, page):
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    t = sp["table"]
    widths = [2.0, 1.6, 1.6, 1.9, 2.2]
    tx, ty = 0.6, 1.45
    for j, hd in enumerate(t["heads"]):
        x = tx + sum(widths[:j])
        box(s, x, ty, widths[j] - 0.06, 0.45, NAVY, radius=0.05)
        text(s, x, ty, widths[j] - 0.06, 0.45, hd, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    for i, row in enumerate(t["rows"]):
        y = ty + 0.55 + i * 0.68
        for j, cell in enumerate(row):
            x = tx + sum(widths[:j])
            hl = j == 3
            box(s, x, y, widths[j] - 0.06, 0.6, PINK if hl else PANEL, radius=0.05)
            text(s, x, y, widths[j] - 0.06, 0.6, [rich(cell)], size=13 if j else 12.5, color=RED if hl else (NAVY if j == 0 else TEXT),
                 bold=(j in (0, 3)), align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, tx, ty + 0.6 + len(t["rows"]) * 0.68, 9.4, 0.35, t.get("note", ""), size=10, color=GRAY)
    # 右：応募単価の試算
    c = sp["cpa"]
    x0 = 10.1
    box(s, x0, 1.45, 2.6, 5.4, WHITE, line=BORDER)
    text(s, x0 + 0.2, 1.55, 2.2, 0.4, c["head"], size=14, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
    for i, (lab, val, sub, hl) in enumerate(c["steps"]):
        y = 2.05 + i * 1.5
        box(s, x0 + 0.2, y, 2.2, 1.15, PINK if hl else PANEL)
        text(s, x0 + 0.25, y + 0.05, 2.1, 0.35, lab, size=10.5, color=GRAY, align=PP_ALIGN.CENTER)
        text(s, x0 + 0.25, y + 0.35, 2.1, 0.45, val, size=19, color=RED if hl else NAVY, bold=True, align=PP_ALIGN.CENTER)
        text(s, x0 + 0.25, y + 0.8, 2.1, 0.3, sub, size=9.5, color=GRAY, align=PP_ALIGN.CENTER)
        if i < len(c["steps"]) - 1:
            arrow(s, x0 + 1.1, y + 1.18, 0.4, 0.3, LGRAY, shape=MSO_SHAPE.DOWN_ARROW)
    # 下：単価の注意
    box(s, 0.6, 5.2, 9.3, 1.65, PINK)
    text(s, 0.85, 5.25, 8.9, 1.55, [rich(x) for x in sp["insight"]], size=13, gap=5, anchor=MSO_ANCHOR.MIDDLE)


def slide_checklist(prs, sp, page):
    s = new_slide(prs, sp["title"], page, sp.get("notes"))
    step = min(1.02, 5.35 / len(sp["items"]))
    rh = step - 0.12
    for i, (no, item, why) in enumerate(sp["items"]):
        y = 1.45 + i * step
        box(s, 0.6, y, 12.1, rh, PANEL)
        pill(s, 0.85, y + (rh - 0.36) / 2, 1.6, 0.36, no, fill=RED, size=11)
        text(s, 2.7, y, 4.6, rh, item, size=13.5, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text(s, 7.4, y, 5.15, rh, why, size=11, color=GRAY, anchor=MSO_ANCHOR.MIDDLE)


def slide_goal(prs, sp, page):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, NAVY, radius=0, shape=MSO_SHAPE.RECTANGLE)
    box(s, -1.2, -1.6, 3.6, 3.6, RGBColor(0x2E, 0x3D, 0x5C), shape=MSO_SHAPE.OVAL)
    box(s, 11.4, 5.4, 3.0, 3.0, RED, shape=MSO_SHAPE.OVAL)
    text(s, 0.8, 0.7, 10, 0.4, sp.get("kicker", ""), size=14, color=RGBColor(0xF2, 0xB8, 0xAB), bold=True)
    text(s, 0.8, 1.2, 11.5, 1.5, sp["title"], size=30, color=WHITE, bold=True, spacing=1.2)
    for i, (h_, d) in enumerate(sp["points"]):
        y = 3.2 + i * 0.95
        num_circle(s, 0.85, y + 0.08, 0.55, i + 1, size=15)
        text(s, 1.65, y, 10.8, 0.4, h_, size=17, color=WHITE, bold=True)
        text(s, 1.65, y + 0.42, 10.8, 0.4, d, size=12.5, color=RGBColor(0xC9, 0xD0, 0xDD))
    if sp.get("notes"):
        s.notes_slide.notes_text_frame.text = "\n".join(sp["notes"])


TYPES = {"cover": slide_cover, "funnel": slide_funnel, "issues": slide_issues, "overview": slide_overview,
         "title_ba": slide_title_ba, "proposal": slide_proposal, "kpi": slide_kpi, "checklist": slide_checklist,
         "goal": slide_goal}


def build(spec, out_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    for page, sp in enumerate(spec["slides"], 1):
        TYPES[sp["type"]](prs, sp, page)
    prs.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("-o", default="output/proposal.pptx")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    build(spec, a.o)
    print("保存しました:", a.o)


if __name__ == "__main__":
    main()
