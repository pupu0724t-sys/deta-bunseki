"""使い方:
  python run.py diagnose データ.csv [--past 過去.csv] [-o diagnosis.json]
  python run.py build diagnosis.json analysis.json [-o 出力.pptx]
"""
import argparse
import json
import sys

from indeed_tool.diagnose import diagnose
from indeed_tool.slides import build


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diagnose")
    d.add_argument("csv")
    d.add_argument("--past")
    d.add_argument("-o", default="output/diagnosis.json")
    b = sub.add_parser("build")
    b.add_argument("diagnosis")
    b.add_argument("analysis")
    b.add_argument("-o", default="output/report.pptx")
    p = sub.add_parser("proposal", help="データと原稿から提案書を作る（prepare：下準備／build：組み立て）")
    p.add_argument("action", choices=["prepare", "build"])
    p.add_argument("paths", nargs="+", help="prepare：日別CSV（原稿ごと）／build：作業フォルダ")
    p.add_argument("--pdf", help="原稿PDF（prepare）")
    p.add_argument("--client", default="（顧客名）", help="顧客名（prepare）")
    p.add_argument("--nearby", help="周辺求人のCSV（build）")
    p.add_argument("--forbid-file", help="他のお客様の名前を1行ずつ書いたファイル。含まれていたら作成を中止（build）")
    p.add_argument("--name", default="提案書", help="出力ファイル名（build）")
    p.add_argument("-o", default=None)
    args = ap.parse_args()
    if args.cmd == "proposal":
        from indeed_tool import pipeline
        if args.action == "prepare":
            out = args.o or "data/work"
            r = pipeline.prepare(args.paths, args.pdf, out, args.client)
            print(f"下準備ができました: {out}")
            print(f"  作業メモ: {out}/brief.md\n  提案の中身: {out}/proposal_spec.json（Claudeが書く）\n  補足情報: {out}/staff_meta.json")
        else:
            forbid = []
            if args.forbid_file:
                with open(args.forbid_file, encoding="utf-8-sig") as fh:  # BOMつきでも読める
                    forbid = [ln.strip() for ln in fh if ln.strip()]
            pptx, xlsx, unresolved = pipeline.build_all(args.paths[0], args.o or "output", args.nearby, forbid, args.name)
            print(f"提案書: {pptx}\n担当者向け資料: {xlsx}")
            if unresolved:
                print(f"注意: （要記入）が{unresolved}か所残っています", file=sys.stderr)
        return

    import os
    os.makedirs(os.path.dirname(args.o) or ".", exist_ok=True)
    if args.cmd == "diagnose":
        result = diagnose(args.csv, args.past)
        with open(args.o, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        for r in result["listings"]:
            print(f"■ {r['title']}: {r['issue_label']}")
            for line in r["findings"]:
                print("   ", line)
        print(f"診断結果を保存しました: {args.o}")
    else:
        with open(args.diagnosis, encoding="utf-8") as f:
            dg = json.load(f)
        with open(args.analysis, encoding="utf-8") as f:
            an = json.load(f)
        warns = build(dg, an, args.o)
        for w in warns:
            print("注意:", w, file=sys.stderr)
        print(f"PowerPointを保存しました: {args.o}")


if __name__ == "__main__":
    main()
