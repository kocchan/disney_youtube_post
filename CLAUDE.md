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
| X版動画を生成した（`final_output_x*.mp4` 生成） | 対象行の ② 列を ✅ にする |
| TikTok版動画を生成した（`final_output_tiktok*.mp4` 生成） | 対象行の ③ 列を ✅ にする |
| YouTube版動画を生成した（`final_output_youtube*.mp4` 生成） | 対象行の ④ 列を ✅ にする |
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

**台本生成・scrape_query 設計・ダッシュボード画像選定を行う前に必ず `feedback_video_design.md` の画像選定セクションを参照すること。**

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
- **プロバイダ抽象（Strategy）**: TTS と画像はインターフェースで差し替え可能にする。
  - `TTSProvider`: `GTTSProvider`(既定) / `OpenAITTSProvider` / `ElevenLabsProvider`
  - `ImageProvider`: `StockImageProvider`(既定/Pexels) / `WebScrapeProvider`(`--allow-scrape`時のみ)
- **設定の外出し**: APIキーは `.env`、調整値は `config.yaml`。コードに秘密情報を直書きしない。
- **冪等性**: 音声・画像はキャッシュし再生成を避ける。
- **失敗耐性**: 1シーンの画像取得失敗で全体を止めず、プレースホルダにフォールバック。

---

## ⚠️ 著作権の鉄則

- ディズニー固有の被写体（キャラクター・城・パーク写真）は権利が極めて強い。**既定はフリー素材API（雰囲気カット）**。
- Webスクレイピング画像は収益化動画でBANリスクがあるため、`--allow-scrape` の明示指定時のみ有効化する自己責任オプションとして分離。
- 取得画像のライセンス／クレジットは `credits.json` に記録する。

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
├── assets/{bgm,fonts,work}/
├── output/              # final_output.mp4
├── src/                 # pipeline.py / tts.py / images.py / subtitles.py / video.py / config.py
├── .claude/skills/script-writer/
└── .claude/memory/          # セッション間メモリ（MEMORY.md + feedback_*.md）
```

---

## scripts/ 命名ルール（必須）

- **ファイル名**: `{連番:02d}_{スラッグ}.json`（例: `08_eparade_25th.json`）
- **連番**: 既存の最大番号 + 1。`ls scripts/` で確認してから採番する。
- **同一テーマの派生ファイル**: メインを `NN_xxx_main.json`、派生を `NN+1_xxx_yt1.json` のように連続した番号で並べる。
- 番号なしファイルは作らない。スクリプト生成後、必ず `ls scripts/` で確認する。

現在の最終番号: **33**（次は `34_...`）

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
