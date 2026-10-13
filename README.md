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

## 判定のルール
- 基準：過去実績があればそれ。なければ クリック率5%・応募率1.5%
- 件数が少ないときは断定しない（95%信頼区間が基準をまたぐ場合は「判断保留」）
- 率（クリック率・応募率）で判断し、件数の多少だけでは判断しない

## 注意
- CSV・PDF・出力されたPowerPointは取引先の情報を含むため、GitHubに入れない（`.gitignore` 済み）
- スライドに署名・社名は入れていない（提出前に追記する）
