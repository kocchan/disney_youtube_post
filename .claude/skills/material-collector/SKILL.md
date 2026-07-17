---
name: material-collector
description: assets/materials/ の画像素材ライブラリを恒久的に充実させるスキル。Pexels API・Web検索(DuckDuckGo)で候補画像を集め、ClaudeがVisionで内容を確認して採否を判断し、説明・タグを付けて素材ライブラリに登録する。image_dashboard.py --fetch-only は毎回ライブラリ＋ライブWeb検索の両方を候補として出すが、そのWeb検索結果はその場限りでライブラリには残らないため、繰り返し使う価値がある素材を恒久登録したい時や、ユーザーが「素材を集めて」「〇〇の画像を用意して」と言ったときに使う。
---

# material-collector — 素材ライブラリ収集スキル

`assets/materials/<subject>/` の画像素材と、その内容説明（`meta.json`）を恒久的に充実させる。
`image_dashboard.py` の候補取得は毎回ライブラリ＋その場のWeb検索の両方を行うが、Web検索結果は
その動画1回限りの使用でライブラリには自動登録されない。**繰り返し使う価値のある素材を
Claudeが確認した上でライブラリに残す**のがこのスキルの役割。

---

## いつ使うか

- `python src/image_dashboard.py --script <script> --fetch-only` の結果、
  「⚠️ 候補が0件のシーン」が出た（ライブラリ・Web検索の両方で候補が見つからなかった場合）
- 画像選定中に見つけたWeb検索候補を、今後の動画でも使い回せるようライブラリに残したい
- ユーザーが「〇〇の素材を集めて」「〇〇の画像を追加して」と明示的に依頼した
- 新しいアトラクション・エリアを扱う台本を書く前に、素材が揃っているか確認したい

---

## フロー

### STEP 0 — 既存ライブラリを確認する（重複収集を避ける）

`assets/materials/index.json` を読み、`category`/`subject`/`description`/`tags` を確認する。
近い内容の素材が既にあれば新規収集はスキップし、既存の `subject` フォルダに合流させる
（`index.json` が古い可能性がある場合は `python src/materials.py` で再生成してから読む）。

### STEP 1 — 対象と検索クエリを決める

対象シーン（または依頼内容）から以下を決める:
- `subject` スラッグ（英語、例: `tower_of_terror`）。STEP 0 で見つけた既存の `assets/materials/`
  フォルダがあれば流用し、新規なら短い英語スラッグを新設する。
- **カテゴリ**: `assets/materials/` は `attractions/`（アトラクション別）・`movies/`（映画・キャラクター別）・
  `generic/`（汎用の雰囲気カット・CTA用等）の3分類で運用している。`--subject` には
  `attractions/tower_of_terror` のように `<category>/<subject>` 形式で指定する
  （既存カテゴリに当てはまらない場合はユーザーに確認する）。
- `--query-en`: Pexels用の英語クエリ（一般的な被写体で良い。例: `haunted mansion elevator dark room`）
- `--query-ja`: Web検索用の日本語クエリ。`.claude/memory/feedback_video_design.md` の
  画像選定セクションの `scrape_query` ルールに従う（パーク公式呼称・具体的な固有名詞・
  「行為/状態/感情」に変換したキーワード）。

### STEP 2 — 候補取得 + コンタクトシート生成

```bash
source venv/bin/activate && python src/collect_materials.py fetch \
  --query-en "<英語クエリ>" \
  --query-ja "<日本語クエリ>" \
  --label <subject_slug> \
  --n 8
```

`assets/work/collect_staging/<subject_slug>/manifest.json`（候補一覧）と
`contact_sheet.jpg`（`px0`, `px1`... `web0`, `web1`... とラベル付きのグリッド画像）が生成される。

### STEP 3 — Claudeがコンタクトシートを見て採否を判断する

`contact_sheet.jpg` を Read ツールで確認し、1件ずつ次の基準で判断する:

- **採用**: 実際のディズニーパーク・アトラクションを写した写真、または汎用ストックとして
  自然に使える雰囲気カット。構図が破綻していない。
- **却下**: 映画ポスター・公式ロゴ入り宣伝美術など「二次的著作物」に見えるもの（写真では
  なくグラフィックデザイン）、日本語の派手なテキストが乗ったまとめサイト風サムネイル、
  内容が無関係なもの、低解像度・不鮮明なもの。
- 各候補の出典・URLは `manifest.json` の該当エントリ（`source`, `photographer` 等）で確認できる。

### STEP 4 — 採用した候補を1件ずつ登録する

`manifest.json` から該当パス・出典情報を確認し、Claudeが内容を要約した説明とタグを付けて登録する。

```bash
python src/collect_materials.py commit \
  --staged assets/work/collect_staging/<subject_slug>/s0_px_2.jpg \
  --subject <subject_slug> \
  --filename <わかりやすいファイル名>.jpg \
  --description "<何が写っているか。構図・雰囲気・行為/状態を具体的に日本語で>" \
  --tags "<タグ1>,<タグ2>,<タグ3>" \
  --source Pexels \
  --credit-json '{"photographer": "...", "photographer_url": "...", "photo_url": "..."}'
```

- `--description` は台本の `image_query`/`scrape_query`/`narration` と照合しやすいよう、
  「何を見た視聴者にどう感じてほしいか」が伝わる具体的な日本語文にする
  （`feedback_video_design.md` の scrape_query ルールと同じ考え方）。
- `--tags` は検索マッチング用の短いキーワード（日本語・英語どちらでも可、3〜6個目安）。
- Web検索(`source: DuckDuckGo/Web`)由来の画像は `--source "DuckDuckGo/Web"`、
  `--credit-json` に `page_url`/`title` を入れておくと出典が追える。

Pexels由来は著作権表記義務があるため、`--credit-json` に `photographer`/`photographer_url`/`photo_url`
を必ず含める（`manifest.json` の該当エントリからコピーする）。

`commit` を実行すると `assets/materials/index.json`（集約インデックス）が自動再生成される。
手動で再生成したい場合は `python src/materials.py` を実行する。

### STEP 5 — 完了報告

登録した件数・ファイルをユーザーに報告する。`assets/work/collect_staging/` の未採用ファイルは
残しておいてよい（次回別クエリで見返す可能性があるため自動削除しない）。

---

## 注意事項

- **動画に直接使う一連のフロー（image_dashboard.py / pipeline.py）からはこのスキルを呼ばない。**
  候補ゼロで止まった場合はユーザーに報告し、必要ならこのスキルの実行をユーザーに確認してから行う。
- Pexelsは商用利用可・著作権表記のみでよいが、Web検索(DuckDuckGo)由来の画像は
  「著作権は元の作者に帰属・使用は自己責任」（`CLAUDE.md` の著作権の鉄則を参照）。
  ディズニー公式サイト・ニュース記事等の転載画像を安易に採用しない。
- 素材は事前に縦型(1080×1920)変換済みで保存される（`collect_materials.py` が自動処理）。
- タグ・説明を書くときは実際に画像を見て判断する。ファイル名や検索クエリから推測で書かない。
