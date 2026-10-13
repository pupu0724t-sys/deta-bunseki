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
    args = ap.parse_args()

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
