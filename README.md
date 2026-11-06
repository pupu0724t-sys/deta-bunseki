# Indeed 効果分析ツール

Indeedの効果CSVを診断し、お客様向けPowerPointを作る。

## 仕組み
1. `diagnose`：CSVを職種タイトルごとに集計し、表示→クリック→応募の率で診断する（コードが行う）
2. 原稿PDFの読み解き・改善案3パターン・他社の工夫は、Claudeが `analysis.json` に書く
3. `build`：1と2からPowerPointを作る

## 使い方
```
pip install -r requirements.txt
python run.py diagnose データ.csv [--past 過去実績.csv] -o output/diagnosis.json
python run.py build output/diagnosis.json analysis.json -o output/report.pptx
```
`analysis.json` の書式は `samples/sample_analysis.json`（ダミー）を参照。

## 提案書の作り方（現在の運用）
CSVと原稿PDFをClaudeに渡し、`docs/提案書作成プロンプト.md` の内容で依頼する。
数値の診断（`run.py diagnose`）は、計算の確認用として使える。

## データと原稿から提案書を作る（メインの使い方）
```
# 1) 下準備：CSVの集計・診断、原稿PDFの全文抽出と自動チェック、現状スライドの下書き、作業メモ
python run.py proposal prepare データ1.csv データ2.csv --pdf 原稿.pdf --client "顧客名" -o data/work
# 2) 提案の中身を書く：Claudeが data/work/brief.md と原稿.txt を読み、proposal_spec.json に書く（手順は CLAUDE.md）
# 3) 組み立て：提案書(pptx)と担当者向け資料(xlsx)
python run.py proposal build data/work -o output --name 提案書 [--nearby data/nearby.csv] [--forbid-file data/forbid.txt]
```
- 提案の文章は外部のAI（API）に送らず、Claudeがこの場で書く（顧客情報を外に出さない・従量課金を避けるため）。
- `--forbid-file`：他のお客様の名前を1行ずつ書く。提案書に含まれていたら作成を中止する。
- 提案の中身の書式は `samples/sample_proposal_spec.json`（架空）を参照。

## 提案書・担当者向け資料・周辺求人の比較（個別に使う場合）
```
# 提案書（図中心のスライド）。中身は data/ 配下の JSON に書く
python -m indeed_tool.proposal_deck data/proposal_spec.json -o output/提案書.pptx

# 周辺求人の給与を月給に換算して集計（平均・中央値・貴社の順位）
python -m indeed_tool.nearby data/nearby.csv --client 250700
python -m indeed_tool.nearby data/nearby.txt --client 250700     # 検索結果画面をコピーしたテキスト（簡易）

# 担当者向け資料（Excel・10シート）。--nearby を付けると「5.周辺比較」に自動で記入
python -m indeed_tool.staff_workbook data/combined.csv data/proposal_spec.json data/staff_meta.json --nearby data/nearby.csv -o output/担当者向け資料.xlsx
```
- 周辺求人のCSVの列は `samples/nearby_template.csv`（架空のデータ）を参照。給与は「月給25万〜30万円」などの原文のままでよい
- 年収は÷12で月給に換算。時給・日給は集計から除外（`--include-hourly` で 8時間×21日として含める）
- 求人サイトからの自動取得（スクレイピング）は利用規約で禁止されているため行わない。人が集めた情報を読み取って集計する

## 判定のルール
- 基準：過去実績があればそれ。なければ クリック率5%・応募率1.5%
- 件数が少ないときは断定しない（95%信頼区間が基準をまたぐ場合は「判断保留」）
- 率（クリック率・応募率）で判断し、件数の多少だけでは判断しない

## 注意
- CSV・PDF・出力されたPowerPointは取引先の情報を含むため、GitHubに入れない（`.gitignore` 済み）
- スライドに署名・社名は入れていない（提出前に追記する）
