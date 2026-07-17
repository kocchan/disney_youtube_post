# CLAUDE.md — ディズニー雑学 YouTube ショート自動生成パイプライン

このファイルは Claude Code がこのリポジトリで作業する際の運用ルール。詳細な要件は `REQUIREMENTS.md` を参照。

---

## プロジェクト概要

台本(`script.json`)を入力すると、TTS音声生成・画像取得・字幕付与・BGM合成を自動で行い、YouTubeショート用の縦型MP4(`output/final_output.mp4` / 1080x1920 / 9:16)を書き出すパイプライン。コンテンツはディズニーリゾートの雑学・裏話。

---

## TODO 管理の運用ルール（必読）

このプロジェクトでは、Claude Code が **2025年4月末にリリースした TodoWrite 由来の TODO リスト機能**（本 harness では後継の **Task ツール**）でタスクを管理する。**Task ツールが正（ソース・オブ・トゥルース）**。`TODO.md` は人間が読みやすいようにそれをミラーした派生ファイルで、Task の状態が変わったら再生成する（ユーザーが「TODO.md を更新して」と言ったとき、または各マイルストーン完了時）。

### 運用ルール

1. **多段タスク（3ステップ以上）に着手する前に必ず `TaskCreate` でタスク化する。**
2. **作業を始めるタスクは、開始前に `TaskUpdate` で `in_progress` にする。** 同時に in_progress にするのは原則1つ。
3. **完全に終わったら即 `TaskUpdate` で `completed` にする。** テスト失敗・実装が部分的・未解決エラーがある場合は completed にしない（in_progress のまま）。
4. **作業中に新しくやることが判明したら、その場で `TaskCreate` で追加する。**
5. **順序関係は `addBlockedBy` で依存を張る。** 次に何をやるかは `TaskList` を見て、ブロックされていない最小IDから着手する。
6. 不要になったタスクは `deleted` にする。古いタスクは放置せず整理する。
7. **タスク完了のたびに `TODO.md` を確認し、完了状態を反映して更新する。** 放置しない。

### TODO.md 自動更新ルール（必須）

**以下のアクションを実行したら、必ず `TODO.md` のコンテンツ制作進捗表を更新する。例外なし。**

| トリガー | 更新内容 |
|----------|----------|
| **コンテンツ制作に着手する（画像選択・pipeline実行・upload実行のいずれかを開始する）** | **対象行の状態列を `🔄 作業中` にする（最優先・必ず最初に行う）** |
| `scripts/NN_*.json` を新規作成した | 対象行を追加し、全列を ❌、状態を `❌ 未着手` にする |
| ダッシュボードで画像選択が完了した（`image_selections.json` 生成） | 対象行の ① 列を ✅ にする |
| TikTok版動画を生成した（`final_output_tiktok*.mp4` 生成。メイン・サムネ/メタ情報もここで生成） | 対象行の ② 列を ✅ にする |
| ユーザーがTikTokに**手動投稿**した後、投稿完了のスクリーンショットを見せてくれた | 対象行の 📱 TikTok投稿 列を `📱 MM/DD 投稿済み` に更新（TikTok本番審査が通り自動投稿に切り替わるまでは手動運用） |
| YouTube版動画を生成した（`final_output_youtube*.mp4` 生成） | 対象行の ③ 列を ✅ にする |
| `upload.py` で YouTube 予約投稿した | 対象行の 📅 列を `📅 MM/DD HH:MM 予約` に更新（**自動**: `upload.py` が実行）、状態列を `📅 YT予約済` にする |
| 全列が ✅（または 📅）になった | 状態列を `✅` に変更し、残タスクセクションから削除する |

更新後は `最終更新: YYYY-MM-DD` の日付も書き換えること。

### YouTube 投稿スケジュールルール（必須）

- **投稿頻度**: 1日2本、**18:00 と 20:00（JST）**
- **開始日**: 2026-06-29 以降
- **スロット割り当て**: 既存の予約状況を `TODO.md` で確認し、空いている最も近い日時に割り当てる
- `upload.py --schedule` の引数は必ず `YYYY-MM-DD HH:MM` 形式（18:00 または 20:00）を使う
- 新しい動画を予約投稿する際は、上記ルールに従って次の空きスロットを自動で割り当てること

### メモリ管理ルール（必読）

**メモリの正はプロジェクト内の `.claude/memory/` フォルダ**。セッション開始時に必ずここを読むこと。

- **インデックス**: `.claude/memory/MEMORY.md`（何があるかの一覧）
- **フィードバック**: `.claude/memory/feedback_video_design.md`（デザイン・動画・**画像選定**に関するユーザー指摘まとめ）
- **パフォーマンス分析**: `.claude/memory/analytics_insights.md`（YouTube Analytics APIから自動集計した視聴率・タイトル型・カテゴリ別成績。`python src/analyze_performance.py`／`analytics-insights` スキルで更新）
- **画像選定ナレッジ**: `.claude/memory/image_selection_knowledge.md`（Claudeの自動選定とユーザーの最終選択が異なった事例の分析結果。`assets/work/image_selection_diffs.jsonl` を元にClaudeが分析して蓄積する）

**台本生成・scrape_query 設計・ダッシュボード画像選定を行う前に必ず `feedback_video_design.md` の画像選定セクション・`analytics_insights.md` の「台本生成への提言」セクション・`image_selection_knowledge.md` を参照すること。**

**ダッシュボードでの画像選択完了後は、`assets/work/image_selection_diffs.jsonl` にこの台本の未分析(`analyzed: false`)エントリがないか必ず確認する。** あれば自動選定画像とユーザー選択画像を見比べて理由を分析し、`image_selection_knowledge.md` にルール化して追記する（手順は同ファイル参照）。

ユーザーから初めて指摘・修正を受けたときは、**同じミスを繰り返さないために必ずメモリに記録する**。

- 記録先: `.claude/memory/feedback_video_design.md`（動画・デザイン系）または適切なファイル
- 記録内容: ルール本文 ＋ **Why**（なぜそうするか）＋ **How to apply**（どう適用するか）
- システムの自動メモリ（`~/.claude/projects/.../memory/`）は**使わない**。`.claude/memory/` だけを使う。

### 現在のマイルストーン（Task ID 対応）

| ID | マイルストーン | 依存 |
|----|----------------|------|
| 1 | M0: 環境構築（venv・依存・フォルダ雛形） | — |
| 2 | M1: TTS（gTTSで音声生成＋尺計測） | 1 |
| 3 | M2: 画像取得（StockImageProvider/Pexels） | 1 |
| 4 | M3: 動画合成（画像＋音声で縦型MP4） | 2,3 |
| 5 | M4: 字幕（分割＋強調キーワード着色） | 4 |
| 6 | M5: BGM合成（ローカルbgmフォルダ） | 4 |
| 7 | M6: 台本生成スキル（テーマ→script.json） | — |
| 8 | M7: 仕上げ（キャッシュ・失敗耐性・CLI統合） | 5,6 |

---

## アーキテクチャ方針

- **疎結合**: 台本生成（Claudeスキル）と動画化パイプラインは分離。パイプラインは `script.json` を消費するだけ。
- **画像選定はライブラリ＋ライブWeb検索のハイブリッド（2026-07-12〜）**: `image_dashboard.py` の候補取得は毎回 (1) `assets/materials/` の素材ライブラリ（`src/materials.py` の `index.json` 経由）と (2) その場でのWeb検索（DuckDuckGo、`scrape_query`使用）の両方を行い、両方を候補として並べる。ライブラリは高速・再利用可能な供給源、Web検索はそのシーン特有の意図を汲み取るための供給源として役割分担する（ライブラリだけでは「シーンの意図を汲み取れない」画像しか出せないことがあるため）。`pipeline.py` 自体は取得を行わず、`--selections`（必須）で確定した画像/動画をコピーするだけ。
  - ライブラリの充実（再利用に足る良質な素材の恒久登録）は専用スキル `material-collector` が担当（Pexels/Web検索 → Claude Visionが採否判断 → 説明・タグを付けて登録）。
  - `TTSProvider`: `GTTSProvider`(既定) / `OpenAITTSProvider` / `ElevenLabsProvider`
  - `src/images.py` の `WebScrapeProvider` は `image_dashboard.py`（毎回のライブ検索）と `material-collector` スキル（`src/collect_materials.py`、恒久登録用の収集）の両方から使われる。`pipeline.py` からは呼ばない。
- **設定の外出し**: APIキーは `.env`、調整値は `config.yaml`。コードに秘密情報を直書きしない。
- **冪等性**: 音声はキャッシュし再生成を避ける。
- **失敗耐性**: 選択されたシーン1件の処理失敗で全体を止めず、そのシーンをスキップする。

---

## ⚠️ 著作権の鉄則

- ディズニー固有の被写体（キャラクター・城・パーク写真）は権利が極めて強い。動画生成の候補取得は **`assets/materials/` の素材ライブラリ＋その場のWeb検索（DuckDuckGo）** のハイブリッドで行う。Web検索由来の画像は著作権が元作者に帰属し使用は自己責任（`image_dashboard.py` のUIにも「※著作権注意」と明示）。
- 素材ライブラリへの**恒久的な追加**（次回以降も使い回す素材）は `material-collector` スキル経由のみ。Pexels（商用利用可）とWeb検索の双方を使うが、Claudeが内容をVisionで確認し、映画ポスター等の二次的著作物や無関係なものは弾いてから登録する。一方、`image_dashboard.py` のその場のWeb検索候補は当該動画の1シーン限りの使用で、ライブラリには自動登録されない。
- `assets/materials/` に置く動画クリップは**ユーザー本人が権利者から適法に入手/撮影したもの**に限る（ディズニー公式YouTube等の無断ダウンロードは不可。詳細は `.claude/memory/feedback_video_design.md`）。
- 取得画像のライセンス／クレジットは素材ライブラリの `meta.json`（`credit`フィールド）と動画ごとの `credits.json` に記録する。

---

## ディレクトリ構成

```
326_disneyYoutube/
├── REQUIREMENTS.md      # 要件定義書
├── CLAUDE.md            # 本書（運用ルール）
├── config.yaml          # 解像度/音量/フォント/プロバイダ既定値
├── .env                 # APIキー（gitignore）
├── requirements.txt
├── scripts/             # 台本JSON — 必ず {連番:02d}_{スラッグ}.json で命名
├── assets/{bgm,fonts,work,materials}/
├── output/              # final_output.mp4
├── src/                 # pipeline.py / tts.py / images.py / materials.py / collect_materials.py / subtitles.py / video.py / config.py
├── .claude/skills/{script-writer,material-collector,video-maker}/
└── .claude/memory/          # セッション間メモリ（MEMORY.md + feedback_*.md）
```

### assets/materials/ — 動画生成が使う唯一の画像・動画ソース（2026-07-11〜）

- `assets/materials/<category>/<subject>/` に画像（縦型変換済み）・動画クリップ（トリミング済みmp4）を置く。`<category>` は大分類（`attractions`＝アトラクション別 / `movies`＝映画・キャラクター別 / `generic`＝汎用の雰囲気カット・CTA用等）、`<subject>` は自由な英語スラッグ（例: `attractions/tower_of_terror`）。カテゴリ分けせず `assets/materials/<subject>/` の1階層でも動く（`meta.json` を直接持つフォルダを深さ問わず自動検出する）。
- 各サブフォルダの **`meta.json`** がファイル名ごとの索引（`src/materials.py` が管理）:
  ```json
  {
    "elevator_dark_interior.jpg": {
      "type": "image",
      "description": "タワー・オブ・テラーのエレベーター内部、暗闇に浮かぶ非常灯",
      "tags": ["タワー・オブ・テラー", "エレベーター", "暗闇"],
      "source": "Pexels",
      "credit": {"photographer": "...", "photographer_url": "...", "photo_url": "..."}
    }
  }
  ```
- `description`/`tags` は**Claudeが内容を見て書いたもの**。動画生成時のシーン⇔素材マッチング（`image_dashboard.py`）と、次回以降の検索精度の両方に使われる。
- **ライブラリへの追加は `material-collector` スキルのみが行う**（Pexels/Web検索 → Claude Visionが採否判断 → 説明・タグを付けて登録）。`pipeline.py`・`image_dashboard.py` 自体はWeb検索・APIを一切呼ばない。
- **`assets/materials/index.json`** は全サブフォルダの `meta.json` を1ファイルに集約した索引（`src/materials.py` の `rebuild_index()`/`load_index()` が管理）。`image_dashboard.py` の候補マッチングは毎回全フォルダを走査せず、この `index.json` を参照する（`fetch_all_candidates()` 実行時に自動再生成されるため常に最新）。ライブラリ全体を素早く見渡したい時（例: 台本を書く前に「このアトラクションの素材は既にあるか」を確認する時）は `python src/materials.py` で再生成 + カテゴリ別件数を表示できるほか、`index.json` を直接読めば `category`/`subject`/`description`/`tags` 一覧が得られる。
- `assets/materials/` は容量が大きく著作権上リポジトリにコミットしないため `.gitignore` 対象。ローカル保管のみ。

---

## scripts/ 命名ルール（必須）

- **ファイル名**: `{連番:02d}_{スラッグ}.json`（例: `08_eparade_25th.json`）
- **連番**: 既存の最大番号 + 1。`ls scripts/` で確認してから採番する。
- **同一テーマの派生ファイル**: メインを `NN_xxx_main.json`、派生を `NN+1_xxx_yt1.json` のように連続した番号で並べる。
- 番号なしファイルは作らない。スクリプト生成後、必ず `ls scripts/` で確認する。

現在の最終番号: **55**（次は `56_...`）

---

## output/ 命名ルール（必須）

- **フォルダ名はスクリプトファイルの stem がそのまま使われる**（`src/pipeline.py` と `src/image_dashboard.py` に実装済み）。
  - 例: `scripts/08_eparade_25th.json` → `output/08_eparade_25th/`
  - 例: `scripts/12_baymax_cooldown.json` → `output/12_baymax_cooldown/`
- `meta.theme` は表示・メタ情報用。フォルダ名には**使わない**。
- `--out` で明示的にパスを指定した場合のみ上記ルールを上書きできる。
- 新規スクリプトを追加したら output フォルダ名が一致するか確認すること。

---

## 開発環境メモ

- Python 3.13 / ffmpeg 8.1（導入済み）。
- MoviePy 2.x は字幕描画に Pillow を使うため **ImageMagick は不要**。
- 日本語字幕には日本語TTF（Noto Sans JP推奨）を `assets/fonts/` に配置する。
- 秘密情報（APIキー等）はコミットしない。`.env` は `.gitignore` 対象。
