"""数値の診断と原稿の自動チェックから、提案書の中身(spec)を自動で組み立てるルール。

外部のAIは使わない（顧客情報を外に出さないため）。ここで作るのは「下書きとして完成した提案書」で、
Claude（または担当者）が内容を確認・修正してから提出する前提。

考え方（参考にした提案書の型）
- 応募単価 = クリック単価 ÷ 応募開始率 ÷ 応募完了率 に分解し、基準より悪い段階を特定する
- 提案は「詰まっている段階」に効くものを優先し、すべてに 目的・期待する効果・理由・未確認の点 を付ける
- 「文言を足す」だけでなく、原稿にない判断材料（休日・異動・給与例・道筋・営業の中身）を求める
- Indeedの本文はテキストのみ。図の提案はしない。標準表示（約1分でカンタン入力・【雇用形態】）は変えない
"""
import calendar
import math
import re
import unicodedata

from indeed_tool.diagnose import DEFAULT_CTR, wilson

DEFAULT_ASR = 0.05   # 応募開始率の仮の目安（比べる過去実績がないとき）
DEFAULT_ACR = 0.60   # 応募完了率の仮の目安
TEXT_ONLY_NOTE = "Indeedの本文はテキストのみ。【】◆などの記号で見出しを付けて読みやすくする"


# ---------- 小道具 ----------
def _n(s):
    return unicodedata.normalize("NFKC", s or "")


def pct(x, d=1):
    return "－" if x is None else f"{x * 100:.{d}f}%"


def yen(x):
    return "－" if x is None else f"{x:,.0f}円"


UI = re.compile(r"応募画面へ進む|約1分でカンタン入力|^https?://")


def body_lines(text):
    """タイトル部分（最初の「応募画面へ進む」まで）と画面の文字を除いた本文の行。"""
    lines = [ln.strip().replace("︓", "：").replace("︕", "！").replace("︖", "？") for ln in text.splitlines()]
    start = next((i + 1 for i, ln in enumerate(lines) if "応募画面へ進む" in ln), 0)
    return [ln for ln in lines[start:] if ln and not UI.search(ln)]


def _is_heading(x):
    return len(x) <= 6 and not re.search(r"[◇◆■＊・★\d]", x)


def grab(text, pattern, after=0, maxn=6):
    """本文から pattern に合う行（と続く after 行）を、原文のまま最大 maxn 行返す。見出しだけの行は除く。"""
    lines = body_lines(text)
    out = []
    for i, ln in enumerate(lines):
        if re.search(pattern, _n(ln)):
            for x in lines[i:i + 1 + after]:
                if x and x not in out and not _is_heading(x):
                    out.append(x[:34] + ("…" if len(x) > 34 else ""))
        if len(out) >= maxn:
            break
    return out[:maxn]


def split_title(title):
    title = (title or "").replace("︕", "！").replace("︖", "？")
    m = re.match(r"^(【[^】]*】)?\s*(.+?)(?:\s*[｜|/／]\s*(.*))?$", title or "")
    if not m:
        return "", title or "", ""
    return (m.group(1) or ""), (m.group(2) or "").strip(), (m.group(3) or "").strip()


DUP = re.compile(r"(月給|時給|日給|年収)\s*\d|\d+\s*万|駅|徒歩\s*\d")
AGE = re.compile(r"\d0代")

STRENGTHS = [
    ("未経験OK", r"未経験"),
    ("完全週休2日", r"完全週休\s*(2|二)日"),
    ("土日休み", r"土日(祝)?休"),
    ("年間休日{0}日", r"年間休日[^\d\n]{0,4}(1[2-9]\d)"),
    ("3日連休OK", r"3日連休"),
    ("連休OK", r"連休"),
    ("残業ほぼなし", r"残業(ほぼ)?(なし|無し|少)"),
    ("社宅あり", r"社宅|寮"),
    ("転勤なし", r"転勤なし"),
    ("ノルマなし", r"ノルマなし"),
    ("日払いOK", r"日払い"),
    ("髪型自由", r"髪型[^\n]{0,4}自由|髪色自由"),
    ("資格取得支援", r"資格取得支援"),
    ("賞与あり", r"賞与"),
    ("食事補助あり", r"まかない|食事補助"),
    ("研修あり", r"研修"),
]


def strengths(text, limit=4):
    t = _n(text)
    out = []
    for label, pat in STRENGTHS:
        m = re.search(pat, t)
        if not m:
            continue
        if label == "連休OK" and "3日連休OK" in out:
            continue
        out.append(label.format(m.group(1)) if "{0}" in label else label)
        if len(out) >= limit:
            break
    return out


def wil_status(x, n, base):
    if n <= 0 or base is None:
        return "nodata"
    lo, hi = wilson(x, n)
    if hi < base:
        return "bad"
    if x / n < base * 0.8:
        return "watch"
    return "ok"


# ---------- 数値の診断 ----------
def metrics(a):
    return {"imp": a["imp"], "clk": a["clk"], "st": a["st"], "app": a["app"], "cost": a["cost"], "days": a["days"],
            "ctr": a["clk"] / a["imp"] if a["imp"] else None, "asr": a["st"] / a["clk"] if a["clk"] else None,
            "acr": a["app"] / a["st"] if a["st"] else None, "cvr": a["app"] / a["clk"] if a["clk"] else None,
            "cpc": a["cost"] / a["clk"] if a["clk"] else None, "cpa": a["cost"] / a["app"] if a["app"] else None,
            "cpd": a["cost"] / a["days"] if a["days"] else None, "ipd": a["imp"] / a["days"] if a["days"] else None,
            "cpday": a["clk"] / a["days"] if a["days"] else None}


def labels(prev, cur):
    if prev and prev["title"] == cur["title"]:
        y, mo = int(cur["last"][:4]), int(cur["last"][5:7])
        partial = int(cur["last"][8:10]) < calendar.monthrange(y, mo)[1]
        return f"{int(prev['first'][5:7])}月", f"{int(cur['first'][5:7])}月" + ("（途中）" if partial else ""), partial
    return ("前回", "今回", False) if prev else (None, "今回", False)


def diagnose_funnel(aggs):
    aggs = sorted(aggs, key=lambda a: a["last"])
    cur, prev = aggs[-1], (aggs[-2] if len(aggs) > 1 else None)
    mc, mp = metrics(cur), (metrics(prev) if prev else None)
    lp, lc, partial = labels(prev, cur)
    # 基準：クリック率は目安。応募開始率・完了率は前回(あれば)、なければ仮の目安
    base = {"ctr": DEFAULT_CTR,
            "asr": (mp["asr"] if mp and mp["asr"] else DEFAULT_ASR),
            "acr": (mp["acr"] if mp and mp["acr"] else DEFAULT_ACR)}
    base_src = {"ctr": "目安", "asr": (lp if mp and mp["asr"] else "仮の目安"), "acr": (lp if mp and mp["acr"] else "仮の目安")}
    # 判定に使う期間：今回の件数が少なすぎる（クリック100未満）ときは、前回の数値で判定する
    judge_on = cur
    if prev and cur["clk"] < 100 and prev["clk"] >= cur["clk"]:
        judge_on = prev
    mj = metrics(judge_on)
    st = {"ctr": wil_status(judge_on["clk"], judge_on["imp"], DEFAULT_CTR),
          "asr": wil_status(judge_on["st"], judge_on["clk"], base["asr"] if judge_on is cur else DEFAULT_ASR),
          "acr": wil_status(judge_on["app"], judge_on["st"], base["acr"] if judge_on is cur else DEFAULT_ACR)}
    if cur["st"] > 0 and cur["app"] == 0:
        st["acr"] = "bad"
    if judge_on is cur:
        jbase, jsrc = base, base_src
    else:
        jbase = {"ctr": DEFAULT_CTR, "asr": DEFAULT_ASR, "acr": DEFAULT_ACR}
        jsrc = {"ctr": "目安", "asr": "仮の目安", "acr": "仮の目安"}
    cpc_ratio = (mc["cpc"] / mp["cpc"]) if (mp and mp["cpc"] and mc["cpc"]) else None
    st["cpc"] = "bad" if cpc_ratio and cpc_ratio >= 1.3 else "ok"
    zero_p = None
    if cur["clk"] and cur["st"] == 0:
        p = (prev["st"] / prev["clk"]) if prev and prev["clk"] and prev["st"] else DEFAULT_ASR
        zero_p = (1 - p) ** cur["clk"]
    return {"cur": cur, "prev": prev, "mc": mc, "mp": mp, "mj": mj, "judge_on": judge_on, "lp": lp, "lc": lc,
            "partial": partial, "base": jbase, "base_src": jsrc, "raw_base": base, "status": st,
            "jl": (lc if judge_on is cur else lp), "cpc_ratio": cpc_ratio, "zero_p": zero_p}


def first_target(D, k):
    """第1目標。クリック率は目安の8割に届かなければまず8割、届いていれば目安。他は基準（前回または仮の目安）。"""
    v, b = (D["mj"][k] or 0), D["base"][k]
    if k == "ctr":
        return b * 0.8 if v < b * 0.8 else max(v, b)
    return b if v < b else v


def eff(D, k, word="以上", note=None):
    name = {"ctr": "クリック率", "asr": "応募開始率", "acr": "応募完了率"}[k]
    return [f"{name} {pct(D['mj'][k])}（{D['jl']}） → **{pct(first_target(D, k))}{word}**",
            note or f"（基準：{D['base_src'][k]} {pct(D['base'][k])}）"]


# ---------- 提案のルール ----------
class P(dict):
    """提案1件。stage: ctr / cpc / asr / acr。score が高いほど優先。"""


def _panel(tag, before, after, purpose, effect, reasons):
    return {"tag": tag, "before": before, "after": after, "purpose": purpose, "effect": effect, "reasons": reasons}


def rule_catch(D, text, chk, t_job, t_catch, nearby):
    segs = re.split(r"([／/｜|！!︕、])", t_catch)
    dup = [s for s in segs if s.strip() and (DUP.search(_n(s)) or AGE.search(_n(s)))]
    if not dup:
        return None
    st = strengths(text)
    after_catch = "・".join(st[:4])
    struck = "".join(f"~~{s}~~" if s in dup else s for s in segs)
    sal = (chk.get("salary") or {})
    reasons = ["給与・最寄駅は一覧の別欄に出るため、キャッチで重ねると選ぶ理由を伝える余地が減る"]
    if nearby and nearby.get("low_median"):
        reasons.append(f"周辺の求人も月給下限の中央値が約{nearby['low_median'] / 10000:.1f}万円で、給与だけでは差がつきにくい")
    elif any(AGE.search(_n(s)) for s in dup):
        reasons.append("年代の表記は、該当しない方が対象外と感じる可能性")
    else:
        reasons.append("原稿にある働きやすさの強みが、一覧では伝わっていない")
    return P(id="catch", stage="ctr", score=7, name="キャッチを一覧で重複しない強みに",
             purpose="一覧の別欄と重なる情報を外し、選ぶ理由を出す", tag="今回原稿", confirm=False,
             title_before=struck, title_after_catch=after_catch,
             slide={"type": "proposal", "title": "提案{no}|キャッチを「一覧で重複しない強み」にする",
                    "visual": {"type": "search_mock", "head": "検索結果での見え方",
                               "title": f"{chk.get('emp', '')}{t_job}｜**{after_catch}**",
                               "meta": "（会社名・勤務地）", "chips": [f"月給 {sal['monthly_low'] / 10000:g}万円 〜" if sal.get("monthly_low") else "給与", "雇用形態"],
                               "chip_note": "← 給与・最寄駅は別欄に表示",
                               "icons": [[str(i + 1), s] for i, s in enumerate(st[:3])],
                               "caption": "外した給与・駅の情報は、一覧の別欄に表示されます。強みはいずれも現在の原稿にある内容です。"},
                    "panel": _panel("クリック率の改善｜対象：今回原稿", "／".join(s.strip() for s in dup)[:30], after_catch,
                                    "一覧の別欄と重なる情報を外し、この求人を選ぶ理由を伝える",
                                    eff(D, "ctr"), reasons),
                    "notes": ["強みは原稿から自動で抜き出した候補。実態と優先順位を確認して選ぶ", "キャッチの表示文字数の上限は未確認"]},
             checklist=None, plan=("すぐ", "キャッチの差し替え", "クリック率"))


def rule_brand(D, text, chk, t_job, t_catch, nearby):
    t = _n("\n".join(text.splitlines()[:40]))
    m = re.search(r"『\s*([^』\s]{2,14})\s*』", t)
    if not m:
        return None
    brand = m.group(1).strip()
    if brand in _n(t_job) or not re.search(r"チェーン|ブランド|店|フランチャイズ", t):
        return None
    after_job = re.sub(r"^.*?(の|：)", brand + r"\1", t_job, count=1) if re.search(r"の|：", t_job) else f"{brand}の{t_job}"
    return P(id="brand", stage="ctr", score=5, name=f"職種名で「{brand}」を伝える",
             purpose=f"「{brand}」で探す方に届くようにする", tag="確認後に掲載", confirm=True,
             title_job_after=after_job,
             slide={"type": "proposal", "title": f"提案{{no}}|職種名で「{brand}」を伝える",
                    "visual": {"type": "search_compare", "head": "職種名の変更", "note": "(イメージ図)",
                               "cards": [{"label": "Before(現状)", "title": t_job}, {"label": "After(改善後)", "after": True, "title": f"**{after_job}**"}],
                               "bars_head": "参考：現在の数値", "pairs": [["クリック率", pct(D["mc"]["ctr"]), "目安 5.0%"], ["1日の表示回数", f"{D['mc']['ipd']:.0f}回", "表示の変化も確認"]]},
                    "panel": _panel("クリック率の改善｜確認後に掲載", t_job, after_job,
                                    f"知名度のある「{brand}」で、働きたい方の検索に表示され、選ばれやすくする",
                                    ["クリック率 **目安5.0%**に近づける", "（キャッチの改善と合わせて）"],
                                    ["職種名は、どの検索に表示されるかに影響。ブランド名で探す方に届きにくい可能性", "フランチャイズ等のルールで、タイトルにブランド名を使えるか確認が必要"]),
                    "notes": [f"原稿に『{brand}』の記載あり", "Indeedの採用市場レポートで職種名ごとの求職者数・競合を確認して判断する"]},
             checklist=("ブランド名の使用", f"求人タイトルに「{brand}」を使ってよいか（本部などのルール）"),
             plan=("次の段階", "職種名の変更", "クリック率"))


def rule_market(D, market):
    """採用市場レポートの数値（任意入力）から、職種カテゴリの変更を提案する。"""
    if not market:
        return None
    cur = next((r for r in market if r.get("現在")), None)
    others = [r for r in market if r is not cur and r.get("求人あたり求職者数")]
    if not cur or not others:
        return None
    best = max(others, key=lambda r: r["求人あたり求職者数"])
    if best["求人あたり求職者数"] <= (cur.get("求人あたり求職者数") or 0):
        return None
    ratio = best["求人あたり求職者数"] / cur["求人あたり求職者数"] if cur.get("求人あたり求職者数") else None
    pairs = [["求人あたり求職者数", f"{cur['求人あたり求職者数']:,.0f}人", f"{best['求人あたり求職者数']:,.0f}人"]]
    if cur.get("求人数") and best.get("求人数"):
        pairs.append(["求人数（競合）", f"{cur['求人数']:,.0f}件", f"{best['求人数']:,.0f}件"])
    elif cur.get("採用難易度") is not None and best.get("採用難易度") is not None:
        pairs.append(["採用難易度", f"{cur['採用難易度']:g}", f"{best['採用難易度']:g}"])
    return P(id="market", stage="cpc", score=6, name="職種カテゴリを見直す",
             purpose="競合の少ない市場で、関心のある方に届ける", tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": f"提案{{no}}|職種カテゴリを「{best['職種名']}」に見直す",
                    "visual": {"type": "search_compare", "head": "職種カテゴリの比較", "note": "(採用市場レポート)",
                               "cards": [{"label": "現在", "title": cur["職種名"]}, {"label": "変更案", "after": True, "title": f"**{best['職種名']}**"}],
                               "bars_head": "現在 → 変更案", "pairs": pairs[:2]},
                    "panel": _panel("クリック率・単価の改善｜確認後に掲載", cur["職種名"], best["職種名"],
                                    "1求人あたりの求職者が多い（競合の少ない）市場で、同じ表示でも選ばれやすくする",
                                    [f"求人あたり求職者数 **約{ratio:.1f}倍**" if ratio else "競合の少ない市場へ", "（クリック率・単価の改善を見込む）"],
                                    ["職種カテゴリは、どの検索・どの求職者に表示されるかを決める", "実態と一致することが前提。仕事内容と合わない職種名は使わない"]),
                    "notes": ["出典：Indeed採用市場レポート（入力値）。府県単位の集計で、実績と時期がずれる点に注意", "母集団（求職者の総数）は減ることがある"]},
             checklist=("職種カテゴリ", f"「{best['職種名']}」が仕事の実態と合っているか"),
             plan=("次の段階", "職種カテゴリの変更", "クリック率・単価"))


def rule_cpc(D, t_job, market):
    """クリック単価が前回の1.3倍以上で、市場データがないとき：職種名と入札設定の見直しを提案する。"""
    if market or D["status"]["cpc"] != "bad":
        return None
    mp, mc = D["mp"], D["mc"]
    cand = None
    if D["prev"] and D["prev"]["title"] != D["cur"]["title"]:
        cand = split_title(D["prev"]["title"])[1].replace("　", " ").strip()[:30]
    after = cand or "（実態に合い、競合の少ない職種名）"
    return P(id="cpc", stage="cpc", score=7, name="職種名で表示される市場を見直す",
             purpose="競合の多い市場から外し、単価を前回水準へ", tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": "提案{no}|職種名で「表示される市場」を見直す",
                    "visual": {"type": "search_compare", "head": "職種名の見直し", "note": "(候補は採用市場レポートで確認)",
                               "cards": [{"label": "現在", "title": t_job}, {"label": "見直し案" + ("（前回の職種名）" if cand else ""), "after": True, "title": f"**{after}**"}],
                               "bars_head": f"参考：{D['lp']} → {D['lc']}", "pairs": [["クリック単価", yen(mp["cpc"]), yen(mc["cpc"])], ["クリック率", pct(mp["ctr"]), pct(mc["ctr"])]]},
                    "panel": _panel("クリック率・単価の改善｜確認後に掲載", t_job[:20], after[:24],
                                    "職種名は、どの検索に表示され、どの求人と並ぶかを決める。競合の少ない市場で単価を抑える",
                                    [f"クリック単価 {yen(mc['cpc'])} → **{yen(mp['cpc'])}前後**", f"（{D['lp']}の水準）"],
                                    [f"クリック単価が{D['lp']}の約{D['cpc_ratio']:.1f}倍。1日の費用が同じなら、クリック数は減る",
                                     (f"{D['lp']}の職種名では単価{yen(mp['cpc'])}・クリック率{pct(mp['ctr'])}だった" if cand else "応募率だけを戻しても、単価が高いままでは応募単価は戻らない")]),
                    "notes": ["単価上昇の理由（職種名・入札設定・時期・競合）は未確認。職種名との関係は仮説", "Indeedの採用市場レポートで、候補の職種名の求職者数・1求人あたり求職者数を確認する（--market で入力すると自動で比較）"]},
             checklist=("単価が上がった理由", "入札設定の変更有無。採用市場レポートで職種名ごとの競合を確認"),
             plan=("次の段階", "職種名・入札設定の見直し", "クリック単価"))


def rule_image(D, text, chk, t_catch, market):
    if D["status"]["ctr"] == "ok":
        return None
    st = strengths(text, 5)
    sal = chk.get("salary")
    lines = [f"**◆ {s}**" for s in st[:4]]
    if sal and sal.get("monthly_low"):
        lines.insert(0, f"**◆ 月給{sal['monthly_low'] / 10000:g}万円〜**")
    mob = next((r.get("モバイル比率") for r in (market or []) if r.get("現在") and r.get("モバイル比率")), None)
    reasons = ["PCで一覧を見る方には、キャッチが表示されない可能性（運用担当者の知見・要確認）"]
    reasons.append(f"このカテゴリのクリックのうちPCは約{(1 - mob) * 100:.0f}%（採用市場レポート）" if mob else "画像は一覧で最も目に入る要素で、条件を一目で伝えられる")
    return P(id="image", stage="ctr", score=6, name="掲載画像に条件を入れる",
             purpose="PCでもスマホでも、一覧で条件が伝わるようにする", tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": "提案{no}|掲載画像に条件の訴求を入れる",
                    "visual": {"type": "list_ba", "labels": ["現在のキャッチ", "画像に入れる文言案"],
                               "before": [x for x in re.split(r"[／/｜|！!]", t_catch) if x.strip()][:6] or ["（キャッチなし）"],
                               "after": lines[:5],
                               "caption": "キャッチはPCでは表示されない可能性があります（要確認）。写真の上に、原稿にある条件を大きく入れます。"},
                    "panel": _panel("クリック率の改善｜確認後に掲載", "写真のみ（条件の文字なし）", "写真＋条件の文字（3〜4項目）",
                                    "PCでも一覧で条件が伝わり、クリックされる理由をつくる",
                                    eff(D, "ctr", note="（キャッチの改善と合わせて）"), reasons),
                    "notes": ["画像の作成・差し替えが必要", "PCでキャッチが表示されない点は運用担当者の知見。画面で確認する"]},
             checklist=("掲載画像", "条件を入れた画像を作成・差し替えできるか"),
             plan=("1〜2週間", "掲載画像の差し替え", "クリック率"))


def rule_repost(D, posted):
    """掲載開始から4か月以上たっていて、クリック率が低いとき、新規投稿（出し直し）を提案する。"""
    if not posted:
        return None
    y, m, d = (int(x) for x in re.split(r"[/-]", posted)[:3])
    ly, lm = int(D["cur"]["last"][:4]), int(D["cur"]["last"][5:7])
    months = (ly - y) * 12 + (lm - m)
    if months < 4 or D["status"]["ctr"] == "ok":
        return None
    return P(id="repost", stage="ctr", score=5, name="新規投稿（出し直し）で表示を回復",
             purpose="新着として上位に表示され、表示回数を回復させる", tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": "提案{no}|新規投稿（出し直し）で表示回数を回復する",
                    "visual": {"type": "fix_table", "head": "出し直しの判断",
                               "rows": [["掲載期間", f"{posted}〜（約{months}か月）", "**4か月以上**のため対象"],
                                        ["クリック率", pct(D["mc"]["ctr"]), "目安5.0%を下回る"],
                                        ["進め方", "原稿・画像の改善を先に実施", "**2週間で改善しなければ出し直し**"]]},
                    "panel": _panel("表示回数の改善｜確認後に実施", f"掲載約{months}か月（新着枠の対象外）", "休止 → 新規投稿",
                                    "掲載が長期化した求人を新着として出し直し、表示回数を回復させる",
                                    ["1日の表示回数の**回復**", "（新着として約1週間は上位表示の傾向）"],
                                    ["掲載が長期化すると新着枠から外れ、表示が減る傾向（運用担当者の知見）", "出し直すと掲載実績がリセットされるため、原稿改善を先に行う"]),
                    "notes": ["新着の上位表示の期間は運用担当者の知見で、Indeed公式の仕様ではない"]},
             checklist=("出し直し", "求人をいったん休止して新規投稿してよいか"),
             plan=("2週間後に判定", "新規投稿（出し直し）", "表示回数"))


def _overtime_window(t):
    """固定残業代の時間と金額。「固定残業代32,020円」「1ヶ月あたり1万5500円（固定残業時間：10時間）」などの書き方に対応。"""
    AMT = r"(\d{1,2}万\d{0,4}円|\d{1,3}(?:,\d{3})+円|\d{4,6}円)"
    a = (re.search(r"固定残業代[:：\s]*(?:1ヶ月あたり)?\s*" + AMT, t)
         or re.search(r"固定残業代[:：]?\s*あり\s*\n\s*(?:1ヶ月あたり)?\s*" + AMT, t))
    h = (re.search(r"固定残業時間[:：]?\s*(?:1ヶ月あたり)?\s*(\d{1,3})\s*時間", t)
         or re.search(r"(\d{1,3})\s*時間の\s*\n?\s*固定残業", t)
         or re.search(r"固定残業代[^\n]{0,20}?(\d{1,3})\s*時間", t))
    return (h.group(1) if h else None), (a.group(1) if a else None)


def rule_overtime(D, text, chk, t_job, t_catch):
    t = _n(text)
    variants = sorted({re.sub(r"\s+", "", x) for x in re.findall(
        r"残業(?:ほぼ)?(?:少|なし|無し|ゼロ)|月?平均残業時間\s*\d+\s*時間(?:以内)?|残業月?\s*\d+(?:\.\d+)?\s*時間(?:以内)?|残業は発生しても[^\n。]{0,10}", t)})
    claims_none = bool(re.search(r"残業(なし|無し|ゼロ)", _n(t_job + t_catch + "\n" + "\n".join(t.splitlines()[:25]))))
    has_fixed = "固定残業" in t
    conflict = claims_none and has_fixed
    if not conflict and len(variants) < 3:
        return None
    hours, amount = _overtime_window(t)
    in_title = [v for v in variants if v in _n(t_job + t_catch)]
    chips = [["タイトル", v] for v in in_title[:1]] + [["本文", v] for v in variants if v not in in_title][:3 - len(in_title[:1])]
    if has_fixed:
        chips.append(["給与", f"固定残業代{hours + '時間分' if hours else ''}を含む"])
    base_line = (grab(text, r"^\s*基本給\s*[:：]", 0, 1) or [""])[0]
    cap = []
    if has_fixed:
        cap.append(f"給与の内訳（{base_line or '基本給〇〇円'}、固定残業代{amount or '〇〇円'}／{hours or '〇〇'}時間分）を明記します")
        cap.append("固定残業代が「残業が少なくても全額支給」であれば、それ自体が安心材料になります（確認後に掲載）")
    else:
        cap.append("**働き方の表記は数値1つに統一**します（〇〇は実際の残業時間）")
    unified = ["残業ほぼなし", "（実態の数値）"] if conflict else ["残業", "月平均〇時間"]
    return P(id="overtime", stage="asr", score=8 if conflict else 6,
             name="残業と給与の内訳を正確に" if conflict else "残業の表記をそろえる",
             purpose="「残業代込みでは」という疑いを先に解く" if conflict else "条件の食い違いによる不信感を防ぐ",
             tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": "提案{no}|" + ("残業と給与の内訳を正確に伝える" if conflict else "残業の表記を数値1つにそろえる"),
                    "visual": {"type": "chips_unify", "head": "原稿内の残業の表記", "chips": chips[:4], "unified": unified, "caption": cap},
                    "panel": _panel("応募率の改善｜確認後に掲載",
                                    "「残業なし」と固定残業代の併記" if conflict else f"残業の表記が{len(variants)}通り",
                                    "実態の数値＋給与の内訳を明記" if conflict else "「残業月平均〇時間」に統一",
                                    "条件の食い違いをなくし、応募直前の不信感を防ぐ",
                                    eff(D, "asr", "前後", "（他の本文の提案と合わせて）"),
                                    ["条件の食い違いは、条件をよく読む正社員希望者ほど気づきやすい",
                                     "「なし」と言い切ると、固定残業代や実際の残業と矛盾して見える可能性" if conflict else "「ほぼなし」と「20時間以内」では受け取り方が大きく異なる"]),
                    "notes": ["検出した残業の表記：" + "／".join(variants), f"固定残業：{hours or '不明'}時間・{amount or '不明'}（自動抽出・要確認）", "実際の月平均残業時間は未確認"]},
             checklist=("残業時間と固定残業代", "実際の月平均残業時間。固定残業代は残業が少なくても全額支給か"),
             plan=("すぐ（数値は確認後）", "残業表記の統一・給与内訳", "応募開始率"))


def rule_docs(D, text, chk):
    if not any(f[0] == "応募時の書類" for f in chk["flags"]):
        return None
    lines = grab(text, r"(履歴書|職務経歴書)[^\n]{0,20}(送付|郵送|送信|提出|アップロード)", 0, 1)
    rows = []
    for a, lab in ((D["prev"], D["lp"]), (D["cur"], D["lc"])):
        if a:
            rows.append({"name": [lab or "今回", ""], "bad": a is D["cur"] and a["st"] > 0 and a["app"] == 0,
                         "steps": [["クリック", f"{a['clk']:,.0f}件"], ["応募開始", f"{a['st']:,.0f}件"],
                                   [f"完了 {pct(a['app'] / a['st'] if a['st'] else None)}", f"{a['app']:,.0f}件"]]})
    sc = 9 if D["status"]["acr"] == "bad" else 4
    return P(id="docs", stage="acr", score=sc, name="応募時の書類を不要にする",
             purpose="応募を始めた方が最後まで完了できるように", tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": "提案{no}|応募時の書類を不要にする",
                    "visual": {"type": "funnel_compare", "head": "応募開始から完了まで", "rows": rows,
                               "quote": {"head": "応募時に書類が必要と読める記載", "before": "\n".join(lines) or "（該当箇所）",
                                         "after": "まずはWEBからご応募ください。\n書類は面接時にご持参ください"},
                               "caption": "在職中の方は、応募の時点で書類を用意していないことが多い可能性があります"},
                    "panel": _panel("応募率の改善｜確認後に掲載", "応募時に履歴書・職務経歴書を送付", "応募時は書類不要。書類は面接時に持参",
                                    "応募を始めた方が、書類の準備で止まらず、最後まで完了できるようにする",
                                    [f"応募完了率 {pct(D['mc']['acr'])}（{D['lc']}） → **{pct(max(D['base']['acr'], 0.5), 0)}以上**", f"（基準：{D['base_src']['acr']}）"],
                                    ["応募の途中でやめる理由として、入力や書類準備の手間が考えられる", "応募フォームの必須項目（書類添付など）を確認のうえ調整"]),
                    "notes": ["応募フォームの必須項目は未確認", "「約1分でカンタン入力」はIndeedの標準表示で、変更・根拠にはしない"]},
             checklist=("応募フォームの必須項目", "履歴書の添付・質問項目が必須か。応募時は書類不要にできるか"),
             plan=("すぐ", "応募時の書類を不要に", "応募完了率"))


def _blank_rule(pid, score, name, purpose, title, before, after, caption, panel_before, panel_after, panel_purpose, reasons, check, D, notes=None):
    return P(id=pid, stage="asr", score=score, name=name, purpose=purpose, tag="確認後に掲載", confirm=True,
             slide={"type": "proposal", "title": "提案{no}|" + title,
                    "visual": {"type": "list_ba", "labels": ["現状の原稿", "追記イメージ（テキスト）"], "before": before, "after": after, "caption": caption},
                    "panel": _panel("応募率の改善｜確認後に掲載", panel_before, panel_after, panel_purpose,
                                    eff(D, "asr", "前後", "（他の本文の提案と合わせて）"), reasons),
                    "notes": (notes or []) + ["〇〇は確認のうえ記載。事実が確認できた項目のみ掲載する"]},
             checklist=check, plan=("情報受領後", name, "応募開始率"))


def rule_salary_example(D, text, chk):
    if not any(f[0] == "給与例が空欄" for f in chk["flags"]):
        return None
    before = grab(text, r"^月給|基本給|手当[:：]|昇給|賞与", 0, 5) + ["給与例（空欄）"]
    after = ["**【給与例】**", "**◆ 入社時（未経験）：月給〇〇万円**", "**◆ 〇年目・〇〇：月給〇〇万円**", "**◆ 役職者：月給〇〇万円**", "**◆ 賞与：〇か月分（支給実績）**"]
    return _blank_rule("salary", 6, "給与例と昇給の目安を書く", "収入の伸び方を金額で示す", "空欄の「給与例」に、入社後の月給の例を書く",
                       before, after, "給与の幅が何で決まるか（手当・評価）もあわせて記載します。〇〇は貴社の実績をもとに記載します。",
                       "給与例が空欄", "入社時〜役職者の月給の例", "入社後の収入の伸びを見通せるようにする",
                       ["給与の幅（下限〜上限）の差が何で決まるか分からない", "昇給・賞与・評価制度の強みが、金額がなく伝わりにくい"],
                       ("給与例と手当の内容", "入社時・数年後・役職者の月給例、給与の幅の内訳、賞与実績"), D)


def rule_basics(D, text, chk, emp):
    t = _n(text)
    if "正社員" not in emp and "正社員" not in t[:300]:
        return None
    no_hol = not re.search(r"年間休日\D{0,6}\d{2,3}\s*日", t)
    shops = re.search(r"(\d{1,3})\s*店舗", t)
    no_move = shops and not re.search(r"転勤|異動", t)
    if not (no_hol or no_move):
        return None
    missing = [x for x, f in (("年間休日・有給休暇", no_hol), ("異動の有無", no_move)) if f]
    before = grab(text, r"週休|休日|連休|有給", 0, 5) + ["→ " + "・".join(missing) + "の記載なし"]
    after = []
    if no_hol:
        after += ["**【休日】年間休日〇〇日**", "**◇ 有給休暇：入社〇か月後に〇日**"]
    if no_move:
        after += ["**【勤務地】〇〇店で勤務**", "**◇ 異動：〇〇（例：原則なし／希望を考慮）**"]
    reasons = ["年間休日は、正社員の求人で比べられる基本情報"] if no_hol else []
    if no_move:
        reasons.append(f"{shops.group(1)}店舗を展開しており、正社員は異動の有無を気にしやすい")
    return _blank_rule("basics", 6, "年間休日・異動を明記する", "正社員として決める基本情報をそろえる", "年間休日と異動の有無を明記する",
                       before[:6], after, "〇〇は確認のうえ記載します。", "・".join(missing) + "の記載なし", "・".join(missing) + "を明記",
                       "正社員として応募を決めるための基本情報（休みの量・勤務地の将来）をそろえる", reasons[:2] or ["正社員の判断材料が不足"],
                       ("年間休日・有給・異動", "年間休日の日数、有給休暇の付与日数、異動の有無と範囲"), D)


def rule_career(D, text, chk):
    t = _n(text)
    if not re.search(r"店長|キャリア|昇格|管理職|リーダー", t):
        return None
    if re.search(r"(最短|入社)\s*\d+\s*(年|か月|ヶ月)", t):
        return None
    before = grab(text, r"店長|キャリア|評価|まずは", 0, 4) + ["→ 期間・道筋の記載なし"]
    after = ["**【入社後の流れ（目安）】**", "**◆ 1か月目：〇〇**", "**◆ 〇か月目：〇〇、1人で担当**", "**◆ 〇か月目〜：〇〇（後輩の教育など）**", "**◆ 最短〇年で〇〇（昇格〇名）**"]
    return _blank_rule("career", 5, "入社後の流れと道筋を書く", "「この先どうなれるか」を見せる", "入社後の流れと、将来の道筋を書く",
                       before, after, "現在の原稿の育成の順番に、期間の目安と道筋を加えます。", "道筋の記載なし", "入社後の流れと将来の目安",
                       "未経験者の「やっていけるか」と、経験者の「この先どうなれるか」の両方に答える",
                       ["「店長」「キャリア」などの言葉はあるが、期間や段階が見えない", "道筋が具体的な求人ほど、入社後を想像しやすい"],
                       ("育成期間と道筋", "1人立ちまでの期間、昇格までの最短年数、昇格者数"), D)


def rule_sales(D, text, chk, t_job):
    if "営業" not in t_job:
        return None
    before = grab(text, r"^■|提案|営業", 0, 4) + ["→ 進め方・担当量の記載なし"]
    after = ["**【営業スタイル】**", "**◆ 担当：1人あたり約〇件**", "**◆ 既存のお客様への提案が約〇割**", "**◆ 新規へは〇〇でアプローチ**", "**◆ 評価は〇〇で行います**"]
    return _blank_rule("sales", 6, "「どんな営業か」を書く", "営業の中身への不安に先回りして答える", "「どんな営業か」を具体的に書く",
                       before, after, "Indeedの本文はテキストのため、【】◆で見出しを付けます。", "業務の項目のみ", "担当量・新規/既存・評価方法",
                       "未経験者が営業職で一番不安に感じやすい「どんな営業をするのか」に答える",
                       ["「ノルマなし」でも、新規開拓や飛び込みの量が分からないと応募をためらう可能性", "既存のお客様が中心なら、それ自体が安心材料になる"],
                       ("営業スタイル", "担当件数、既存/新規の割合、新規の進め方、評価方法"), D)


def rule_company(D, text, chk):
    t = _n(text)
    small = re.search(r"1\s*[〜～~-]\s*49\s*人", t)
    est = re.search(r"設立\D{0,4}(\d{4})", t)
    if not (small or est):
        return None
    before = grab(text, r"設立|従業員|親会社|店舗", 1, 5)
    after = ["**【私たちについて】**", f"**◆ {est.group(1)}年設立。〇〇を展開**" if est else "**◆ 〇〇年設立**", "**◆ 取引先・店舗：約〇〇**", "**◆ 〇〇グループの一員**"]
    return _blank_rule("company", 4, "会社の実績・安定性を書く", "「長く働けるか」という不安に実績で答える", "会社の実績と安定性を伝える",
                       before or ["（会社情報欄のみ）"], after, "仕事内容の冒頭近くに置きます。", "会社情報欄のみ", "設立年・規模・実績を本文に",
                       "会社の規模や実績が分からないことによる不安に、事実で答える",
                       ["設立年や規模の強みが、目に入りにくい場所にしかない", "実績は、仕事の信頼性と規模感を同時に伝えられる"],
                       ("会社の実績", "取引先数・店舗数、グループ名を本文に出してよいか"), D)


def rule_structure(D, text, chk):
    chars = len(re.sub(r"\s", "", text))
    if chars < 3000:
        return None
    rows = [["冒頭", "強み・特徴の紹介が中心", "**【条件まとめ】**給与の内訳・休日・残業・勤務地を最初に"]]
    if text.count("【社会保険】") >= 2:
        rows.append(["重複", "社会保険の記載が2回", "**1回に整理**"])
    rows.append(["長さ", f"原稿全体で約{chars:,}文字", "**重複を削り**、決める情報を先に"])
    t = _n(text)
    area = re.search(r"([東京埼玉神奈川千葉大阪兵庫京都愛知福岡・、]{2,})に\s*(\d+)\s*店舗", t)
    return P(id="structure", stage="asr", score=3, name="冒頭に条件をまとめる", purpose="決める情報を最初の画面で見つけやすく", tag="今回原稿", confirm=False,
             slide={"type": "proposal", "title": "提案{no}|冒頭に条件をまとめ、重複を整える",
                    "visual": {"type": "fix_table", "head": "整える箇所", "rows": rows[:4]},
                    "panel": _panel("応募率の改善｜対象：今回原稿", f"条件が本文に分散（約{chars:,}文字）", "冒頭に【条件まとめ】、重複を削除",
                                    "スマートフォンで読む方が、最初の画面で応募を決める材料を確認できるようにする",
                                    ["応募開始率を**下支え**", "（他の提案の情報を見つけやすくする）"],
                                    ["応募率の高い原稿は1,000〜1,200文字程度が多く、冒頭にメリットを箇条書きにする傾向（運用担当者の知見）", "決め手になる情報が、本文の後半に分散している"]),
                    "notes": ["文字数は原稿全体（項目名を含む）の目安", "「1,000〜1,200文字」は運用担当者の知見で、Indeed公式の基準ではない"] + ([f"展開地域の記載：{area.group(0)}（勤務地と合っているか要確認）"] if area else [])},
             checklist=None, plan=("すぐ", "冒頭の条件まとめ・重複削除", "応募開始率"))


# ---------- 組み立て ----------
STAGE_W = {"bad": 3, "watch": 2, "ok": 1, "nodata": 1}


def build_spec(aggs, text, chk, client, nearby=None, market=None, posted=None, max_props=7):
    D = diagnose_funnel(aggs)
    emp, t_job, t_catch = split_title(chk.get("title", ""))
    chk = dict(chk, emp=emp)
    cands = [rule_catch(D, text, chk, t_job, t_catch, nearby), rule_brand(D, text, chk, t_job, t_catch, nearby),
             rule_market(D, market), rule_cpc(D, t_job, market), rule_image(D, text, chk, t_catch, market), rule_repost(D, posted),
             rule_overtime(D, text, chk, t_job, t_catch), rule_docs(D, text, chk), rule_salary_example(D, text, chk),
             rule_basics(D, text, chk, emp), rule_career(D, text, chk), rule_sales(D, text, chk, t_job),
             rule_company(D, text, chk), rule_structure(D, text, chk)]
    cands = [c for c in cands if c]
    for c in cands:
        stage = "ctr" if c["stage"] == "cpc" else c["stage"]
        w = max(STAGE_W[D["status"][stage]], STAGE_W[D["status"]["cpc"]] if c["stage"] == "cpc" else 0)
        c["prio"] = w * 10 + c["score"]
    chosen = sorted(cands, key=lambda c: -c["prio"])[:max_props]
    top = chosen[0] if chosen else None
    ctr_g = [c for c in chosen if c["stage"] in ("ctr", "cpc")]
    rest = sorted([c for c in chosen if c["stage"] not in ("ctr", "cpc")], key=lambda c: -c["prio"])
    ordered = sorted(ctr_g, key=lambda c: -c["prio"]) + rest
    for i, c in enumerate(ordered, 1):
        c["no"] = i
        c["slide"]["title"] = c["slide"]["title"].replace("{no}", str(i))
        if c is top:
            c["slide"]["title"] += "（最優先）"

    slides = [cover(client, D), funnel(D), decompose(D), summary(D, ordered, top), issues(D, ordered, t_catch)]
    slides.append(overview(ordered, top))
    tb = title_ba(chk, emp, t_job, t_catch, ordered)
    if tb:
        slides.append(tb)
    slides += [c["slide"] for c in ordered]
    slides += [kpi(D, ordered), plan(ordered), goal(ordered), checklist(D, ordered)]
    meta_fill = {"conclusion": summary_sentence(D), "priority": f"提案{top['no']}（{top['name']}）" if top else "（なし）",
                 "order": order_sentence(ordered), "unconfirmed": "／".join(c["checklist"][0] for c in ordered if c.get("checklist")) or "なし",
                 "need": {str(c["no"]): c["checklist"][1] for c in ordered if c.get("checklist")}}
    return {"slides": slides}, meta_fill, D, ordered


def summary_sentence(D):
    mc, st = D["mc"], D["status"]
    parts = [f"{D['lc']}はクリック率{pct(mc['ctr'])}・応募開始率{pct(mc['asr'])}・応募完了率{pct(mc['acr'])}、応募単価{yen(mc['cpa']) if mc['cpa'] else '算出不可'}。"]
    worst = [k for k in ("ctr", "asr", "acr", "cpc") if st[k] == "bad"]
    name = {"ctr": "クリック率（一覧）", "asr": "応募開始率（詳細）", "acr": "応募完了率（応募導線）", "cpc": "クリック単価"}
    parts.append("課題は" + "・".join(name[k] for k in worst) + "。" if worst else "大きな異常値はなく、継続して確認。")
    return "".join(parts)


def order_sentence(ordered):
    now = [f"提案{c['no']}" for c in ordered if not c["confirm"]]
    later = [f"提案{c['no']}" for c in ordered if c["confirm"] and c["stage"] not in ("ctr", "cpc")]
    title = [f"提案{c['no']}" for c in ordered if c["stage"] in ("ctr", "cpc") and c["confirm"]]
    s = []
    if now:
        s.append("まず" + "・".join(now))
    if later:
        s.append("次に" + "・".join(later) + "（情報をいただき次第）")
    if title:
        s.append("最後に" + "・".join(title) + "（効果を見分けるため1つずつ）")
    return " → ".join(s) or "－"


def cover(client, D):
    cur = D["cur"]
    sub = f"対象：{cur['title'][:40]}（{cur['first']}〜{cur['last']}）"
    if D["prev"]:
        sub += f"／比較：{D['lp']}（{D['prev']['first']}〜{D['prev']['last']}）"
    return {"type": "cover", "title": "Indeed掲載原稿 改善のご提案", "client": f"{client} 御中", "sub": sub}


def funnel(D):
    from indeed_tool.pipeline import funnel_slide
    aggs = [a for a in (D["prev"], D["cur"]) if a]
    f = funnel_slide(aggs, "")
    mc, st = D["mc"], D["status"]
    if st["acr"] == "bad" and D["cur"]["st"] > 0 and D["cur"]["app"] == 0:
        head = "応募開始はあるが、完了は0件"
    elif st["cpc"] == "bad":
        head = f"同じ費用で、クリック単価が約{D['cpc_ratio']:.1f}倍"
    elif st["ctr"] == "bad":
        r = (D["mj"]["ctr"] or 0) / DEFAULT_CTR
        head = f"一覧で選ばれる率が、目安の約{r * 10:.0f}割" if r < 0.95 else "一覧で選ばれる率が目安を下回る"
    elif st["asr"] in ("bad", "watch"):
        head = "クリック後に、応募を始める方が少ない"
    else:
        head = "大きな異常値はなく、伸びしろを狙う"
    f["title"] = "現状|" + head
    if D["zero_p"] is not None and D["cur"]["clk"] < 200:
        f["notes"].append(f"{D['lc']}の応募開始0件：{D['lp'] or '目安'}の率のままでも{D['cur']['clk']:.0f}クリックで0件になる確率は約{D['zero_p'] * 100:.1f}%（断定はできない）")
    if D["judge_on"] is not D["cur"]:
        f["notes"].append(f"{D['lc']}は件数が少ないため、課題の判定は{D['lp']}の数値で行った")
    return f


def decompose(D):
    mj, base, st = D["mj"], D["base"], D["status"]
    on = D["lc"] if D["judge_on"] is D["cur"] else D["lp"]

    def fac(label, key, val, b, src):
        bad = st[key] == "bad"
        verdict = {"bad": "基準を下回る", "watch": "やや低い（断定できない）", "ok": "ほぼ基準どおり", "nodata": "データなし"}[st[key]]
        return {"label": label, "value": val, "base": f"基準：{src} {b}", "verdict": verdict, "bad": bad}

    cpc_base = yen(D["mp"]["cpc"]) if D["mp"] else "－"
    cpc_bad = st["cpc"] == "bad"
    factors = [{"label": "クリック単価（CPC）", "value": yen(D["mc"]["cpc"]), "base": f"基準：{D['lp']} {cpc_base}" if D["mp"] else "比べる実績なし",
                "verdict": f"{D['cpc_ratio']:.1f}倍" if D["cpc_ratio"] else "－", "bad": cpc_bad},
               fac("応募開始率", "asr", pct(mj["asr"]), pct(base["asr"]), D["base_src"]["asr"]),
               fac("応募完了率", "acr", pct(mj["acr"]), pct(base["acr"]), D["base_src"]["acr"])]
    worst = [n for n, k in (("クリック率（一覧）", "ctr"), ("クリック単価", "cpc"), ("応募開始率（詳細）", "asr"), ("応募完了率（応募導線）", "acr")) if st[k] == "bad"]
    pts = [f"判定は{on}の数値（クリック率 {pct(mj['ctr'])}：目安5.0%）。" + ("**異常値は「" + "」「".join(worst) + "」**に絞られます" if worst else "はっきりした異常値はありません")]
    if st["ctr"] != "ok":
        pts.append("クリック率が低いと、一覧で選ばれず、同じ予算で得られる応募が減ります。**一覧の見え方（タイトル・画像）**が最初の打ち手です")
    if st["asr"] in ("bad", "watch"):
        pts.append("応募開始率が低いのは、クリック後の本文で**応募を決める材料が足りない**可能性があります")
    if st["acr"] == "bad":
        pts.append("応募完了率が低いのは、**応募フォームの手間**が原因の可能性があります")
    return {"type": "decompose", "title": "課題の構造|応募単価を3つに分けて、異常値を特定", "lead": "基準：クリック率は目安5.0%、応募開始率・完了率は前回実績（ない場合は仮の目安）",
            "factors": factors, "points": pts[:3], "notes": ["件数が少ない段階は95%信頼区間で判定し、断定しない", f"仮の目安：応募開始率{pct(DEFAULT_ASR, 0)}・応募完了率{pct(DEFAULT_ACR, 0)}（過去実績がないとき）"]}


def summary(D, ordered, top):
    mc, st = D["mc"], D["status"]
    key = next((k for k in ("acr", "cpc", "ctr", "asr") if st[k] == "bad"), "ctr")
    kv = {"ctr": ("クリック率", pct(D["mj"]["ctr"]), "目安 5.0%"), "asr": ("応募開始率", pct(D["mj"]["asr"]), f"基準 {pct(D['base']['asr'])}"),
          "acr": ("応募完了率", pct(mc["acr"]), f"基準 {pct(D['base']['acr'])}"), "cpc": ("クリック単価", yen(mc["cpc"]), f"{D['lp']}の約{D['cpc_ratio'] or 0:.1f}倍")}[key]
    cards = [{"label": f"使った費用（{D['lc']}）", "value": yen(mc["cost"]), "sub": f"{D['cur']['days']}日間・1日約{mc['cpd']:,.0f}円"},
             {"label": f"生んだ応募（{D['lc']}）", "value": f"{mc['app']:.0f}件", "sub": f"応募単価 {yen(mc['cpa']) if mc['cpa'] else '算出不可'}", "bad": mc["app"] == 0},
             {"label": f"{kv[0]}（{D['jl']}）", "value": kv[1], "sub": kv[2], "bad": True}]
    findings = []
    if D["prev"]:
        findings.append(f"表示は1日約{D['mp']['ipd']:.0f}回→約{mc['ipd']:.0f}回。クリック率は{pct(D['mp']['ctr'])}→{pct(mc['ctr'])}、クリック単価は{yen(D['mp']['cpc'])}→{yen(mc['cpc'])}")
    else:
        findings.append(f"表示は1日約{mc['ipd']:.0f}回、クリック率は{pct(mc['ctr'])}（目安5.0%）、クリック単価は{yen(mc['cpc'])}")
    findings.append(f"応募開始率は{pct(D['mj']['asr'])}（基準{pct(D['base']['asr'])}）、応募完了率は{pct(D['mj']['acr'])}（基準{pct(D['base']['acr'])}）")
    findings.append("最大の課題は **" + {"ctr": "クリック率（一覧で選ばれていない）", "asr": "応募開始率（本文で決めきれない）",
                                                "acr": "応募完了率（応募の途中で離脱）", "cpc": "クリック単価の上昇"}[key] + "** と考えられます")
    actions = [[f"{c['no']} {c['name']}", "今回原稿", c["purpose"], {"ctr": "クリック率", "cpc": "クリック率・単価", "asr": "応募開始率", "acr": "応募完了率"}[c["stage"]]] for c in ordered]
    return {"type": "summary", "title": "エグゼクティブサマリー", "lead": f"対象：{D['cur']['title'][:40]}（{D['cur']['first']}〜{D['cur']['last']}）",
            "cards": cards, "findings": findings, "actions": actions[:4], "plan_note": "予算は据え置き、求人票側の打ち手"}


def issues(D, ordered, t_catch):
    left = [c for c in ordered if c["stage"] in ("asr", "acr")][:3]
    items = [{"h": c["name"], "d": c["slide"]["panel"]["reasons"][0]} for c in left] or [{"h": "大きな課題なし", "d": "本文・応募導線に、自動で検出できた課題はありません"}]
    ctr_c = next((c for c in ordered if c["stage"] in ("ctr", "cpc")), None)
    if D["prev"]:
        series = [[D["lp"], [D["mp"]["ctr"] or 0, D["mp"]["asr"] or 0]], [D["lc"], [D["mc"]["ctr"] or 0, D["mc"]["asr"] or 0]]]
    else:
        series = [["目安", [DEFAULT_CTR, D["base"]["asr"]]], [D["lc"], [D["mc"]["ctr"] or 0, D["mc"]["asr"] or 0]]]
    return {"type": "issues", "title": "課題は「一覧での選ばれ方」と「応募を決める材料」",
            "left": {"head": "クリック後の課題（応募率）", "items": items},
            "right": {"head": "一覧での課題（クリック率）", "lead": (ctr_c["slide"]["panel"]["reasons"][0] if ctr_c else "一覧での見え方に、大きな課題は見られません"),
                      "categories": ["クリック率", "応募開始率"], "series": series,
                      "note": "件数が少ない期間は参考値（95%信頼区間で判定）"}}


def overview(ordered, top):
    left = [c for c in ordered if c["stage"] in ("ctr", "cpc")]
    right = [c for c in ordered if c["stage"] not in ("ctr", "cpc")]

    def it(c):
        return {"no": c["no"], "name": c["name"][:14], "purpose": c["purpose"][:24], "tag": c["tag"], "confirm": c["confirm"]}

    cols = []
    if left:
        cols.append({"head": "クリック率の改善", "sub": f"提案{left[0]['no']}〜{left[-1]['no']}／一覧", "items": [it(c) for c in left],
                     "footer": ["**進め方**"] + [x for x in order_sentence(ordered).split(" → ")]})
    if right:
        cols.append({"head": "応募率の改善", "sub": f"提案{right[0]['no']}〜{right[-1]['no']}／本文・応募導線", "items": [it(c) for c in right]})
    if len(cols) == 1 and "footer" not in cols[0]:
        cols[0]["footer"] = ["**進め方**"] + order_sentence(ordered).split(" → ")
    return {"type": "overview", "title": f"ご提案の全体像({len(ordered)}つ)", "columns": cols, "notes": [TEXT_ONLY_NOTE]}


def title_ba(chk, emp, t_job, t_catch, ordered):
    cat = next((c for c in ordered if c["id"] == "catch"), None)
    br = next((c for c in ordered if c["id"] == "brand"), None)
    if not (cat or br):
        return None
    job_after = f"**{br['title_job_after']}**" if br else t_job
    job_before = f"~~{t_job}~~" if br else t_job
    catch_before = cat["title_before"] if cat else t_catch
    if any(c["id"] == "overtime" and c["name"].startswith("残業と給与") for c in ordered):
        catch_before = re.sub(r"(?<!~)(残業(?:無し|なし))(?!~)", r"~~\1~~", catch_before)  # 「残業なし」は言い過ぎのため外す
    catch_after = f"**{cat['title_after_catch']}**" if cat else t_catch
    links = [[c["no"], c["name"]] for c in (cat, br) if c]
    return {"type": "title_ba", "title": "提案" + "・".join(str(l[0]) for l in links) + "|タイトルの改善",
            "before": f"{emp}{job_before}｜{catch_before}", "after": f"{emp}{job_after}｜{catch_after}",
            "legend_note": "【雇用形態】は自動で表示され、変更できません", "links": links,
            "notes": ["職種タイトルは30文字まで", "キャッチの表示文字数の上限は未確認"]}


def kpi(D, ordered):
    mc, base, st = D["mc"], D["base"], D["status"]
    mj = D["mj"]

    ctr_t, asr_t = first_target(D, "ctr"), first_target(D, "asr")
    acr_t = min(first_target(D, "acr"), 0.9)
    cvr_t = asr_t * acr_t
    maps = {k: "・".join(f"提案{c['no']}" for c in ordered if (c["stage"] in ((k,) if k != "ctr" else ("ctr", "cpc")))) or "（現状維持）" for k in ("ctr", "asr", "acr")}
    prev_col = D["lp"] or "目安"

    def pv(k):
        if D["mp"]:
            return pct(D["mp"][k])
        return {"ctr": "5.0%", "asr": pct(DEFAULT_ASR, 0) + "（仮）", "acr": pct(DEFAULT_ACR, 0) + "（仮）", "cvr": "－"}[k]

    rows = [["クリック率", pct(mc["ctr"]), pv("ctr"), f"{pct(ctr_t)}以上", maps["ctr"]],
            ["応募開始率", pct(mc["asr"]), pv("asr"), f"{pct(asr_t)}前後", maps["asr"]],
            ["応募完了率", pct(mc["acr"]), pv("acr"), f"{pct(acr_t)}以上", maps["acr"]],
            ["応募率", pct(mc["cvr"]), pv("cvr") if D["mp"] else "－", f"{pct(cvr_t)}以上", "開始率×完了率"]]
    cpc = mc["cpc"] or (D["mp"]["cpc"] if D["mp"] else None)
    month_budget = (mc["cpd"] or 0) * 30
    clicks = month_budget / cpc if cpc else 0
    now_apps = clicks * (D["mj"]["cvr"] or 0)
    tgt_apps = clicks * cvr_t
    steps = [[f"{D['lc']}の実績", yen(mc["cpa"]) if mc["cpa"] else "算出不可", f"応募{mc['app']:.0f}件", False],
             [f"応募率{pct(cvr_t)}の場合", f"約{cpc / cvr_t / 10000:.1f}万円" if cpc and cvr_t else "－", f"クリック単価{yen(cpc)}のまま", True],
             ["月の応募数（同じ予算）", f"約{now_apps:.0f}件→約{tgt_apps:.0f}件", f"月約{month_budget / 10000:.0f}万円・約{clicks:.0f}クリック", False]]
    insight = [f"応募単価 ＝ クリック単価 ÷ 応募率。**応募率を{pct(D['mj']['cvr'])}→{pct(cvr_t)}**にできれば、同じ予算で応募は約{now_apps:.0f}件→約{tgt_apps:.0f}件の見込み（試算）"]
    if st["cpc"] == "bad":
        insight.append(f"クリック単価が{D['lp']}の約{D['cpc_ratio']:.1f}倍のため、**職種名・表示される市場の見直し**もあわせて必要です")
    else:
        insight.append("クリック単価に大きな変化はなく、**課題は単価より「率」**です")
    return {"type": "kpi", "title": f"期待する効果|同じ予算で、応募を月約{now_apps:.0f}件→約{tgt_apps:.0f}件へ",
            "table": {"heads": ["段階", D["lc"], prev_col, "第1目標", "対応する提案"], "rows": rows,
                      "note": "第1目標は、前回実績（ない場合は仮の目安）をもとに設定。実績が出たら見直します"},
            "cpa": {"head": "応募単価の試算", "steps": steps}, "insight": insight,
            "notes": [f"試算：月の予算＝1日の費用×30日、クリック数＝予算÷クリック単価、応募数＝クリック数×応募率", f"判定に使った期間：{D['lc'] if D['judge_on'] is D['cur'] else D['lp']}"]}


def plan(ordered):
    rows = []
    for c in sorted(ordered, key=lambda c: (0 if c["plan"][0].startswith("すぐ") else 1 if "情報" in c["plan"][0] else 2, c["no"])):
        rows.append([c["plan"][0], f"{c['no']} {c['plan'][1]}", "今回原稿", c["slide"]["panel"]["after"][:34], c["plan"][2]])
    rows.append(["反映2週間後", "効果検証", "今回原稿", "変更前後で同じ指標を比べ、次の打ち手を判断", "応募単価"])
    return {"type": "plan", "title": "実行計画とご依頼事項", "lead": "求人票側の修正が中心。予算の変更なしで着手できます（〇〇の情報は確認後に反映）", "rows": rows[:8]}


def goal(ordered):
    pts = []
    if any(c["stage"] in ("ctr", "cpc") for c in ordered):
        pts.append(["一覧で選ばれる理由を出す", "タイトル・画像で、関心の合う方に選ばれるようにする（" + "・".join(f"提案{c['no']}" for c in ordered if c["stage"] in ("ctr", "cpc")) + "）"])
    if any(c["stage"] == "asr" for c in ordered):
        pts.append(["応募を決める材料をそろえる", "条件・休み・収入・この先を、事実で伝える（" + "・".join(f"提案{c['no']}" for c in ordered if c["stage"] == "asr") + "）"])
    if any(c["stage"] == "acr" for c in ordered):
        pts.append(["最後のひと手間をなくす", "応募の途中で止まらないようにする（" + "・".join(f"提案{c['no']}" for c in ordered if c["stage"] == "acr") + "）"])
    return {"type": "goal", "kicker": "目指す状態", "title": "選ばれて、迷わず、\n最後まで応募できる原稿へ", "points": pts[:3]}


def checklist(D, ordered):
    items = [[f"提案{c['no']}", c["checklist"][0], c["checklist"][1]] for c in ordered if c.get("checklist")]
    if D["partial"]:
        items.append(["数値", "月末の確定値", f"{D['lc']}は途中経過。月末の数値で再確認する"])
    return {"type": "checklist", "title": "ご確認事項|反映前にいただきたい情報", "items": items[:7] or [["－", "確認事項なし", ""]]}
