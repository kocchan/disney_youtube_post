# 要件定義書 — ディズニー雑学 YouTube ショート自動生成パイプライン

最終更新: 2026-06-23

---

## 1. プロジェクト概要

| 項目 | 内容 |
|---|---|
| 目的 | 台本(JSON)を入力するだけで、音声生成・画像取得・字幕付与・動画編集を自動実行し、YouTube ショート用の縦型 MP4 を出力する |
| コンテンツ | ディズニーリゾートの雑学・裏話（例:「ディズニーランドのヤバい裏設定5選」） |
| 成果物 | `output/final_output.mp4`（1080x1920 / 9:16 / 60秒以上） |
| 開発言語 | Python 3.13 |
| 動画基盤 | MoviePy 2.x + ffmpeg（インストール済み） |

---

## 2. 確定した方針（ヒアリング結果）

1. **画像ソース**: フリー素材API（主軸）＋ Web検索スクレイピング（補助）の併用。`ImageProvider` 抽象で切替可能に。
2. **台本作成**: Claude のスキルで生成。パイプラインは生成済み `script.json` を読み込むだけの疎結合構成。
3. **TTS**: まず無料の gTTS。`TTSProvider` 抽象で OpenAI TTS / ElevenLabs に差し替え可能に。
4. **BGM**: ローカル `assets/bgm/` フォルダから選択（指定 or ランダム）。

---

## 3. ⚠️ リスク・前提（重要）

- **著作権/商標（最重要）**: ディズニー固有の被写体（キャラクター・城・パーク写真）は権利が極めて強い。Web スクレイピング画像を収益化動画に使うと **Content ID による収益化剥奪・動画削除・チャンネルBAN** のリスクがある。
  - 対策: 既定はフリー素材API（雰囲気カット）。スクレイピングは `--allow-scrape` 等の明示フラグでのみ有効化し、**自己責任の選択肢**として分離する。取得元のライセンス情報を `credits.json` に記録する。
- **TTS の商用利用**: gTTS は Google 翻訳の非公式APIを叩くため不安定・商用グレーになりうる。本番は OpenAI TTS / ElevenLabs（商用可）への切替を想定。
- **フォント**: 日本語字幕には日本語TTFが必要（macOS の Hiragino は .ttc）。`assets/fonts/` に明示的にTTFを置く運用とする。

---

## 4. 機能要件

### F-1. 台本読み込み
- `script.json`（後述スキーマ）を読み込み、バリデーションする。
- `.txt`（1行=1セリフ）も簡易対応（画像クエリ・強調語は自動補完 or 空）。

### F-2. 音声生成（TTS）
- 各シーンの `narration` から mp3 を生成（`assets/work/audio/scene_XX.mp3`）。
- `TTSProvider` インターフェース: `synthesize(text, out_path) -> path`。実装: `GTTSProvider`（既定）/ `OpenAITTSProvider` / `ElevenLabsProvider`。

### F-3. 画像取得
- 各シーンの `image_query`（素材API用キーワード）/ `image_prompt`（将来のAI生成用）から画像を取得し `assets/work/images/scene_XX.jpg` に保存。
- `ImageProvider` インターフェース: `fetch(scene) -> image_path`。実装: `StockImageProvider`（既定: Pexels等）/ `WebScrapeProvider`（明示フラグ時のみ）。
- 取得失敗時はプレースホルダ画像にフォールバック。

### F-4. 尺計測とクリップ生成
- 生成 mp3 の長さ(秒)を計測し、その尺だけ対応画像を表示するクリップを作成。
- 画像は縦型(1080x1920)にリサイズ＋センタークロップ。軽いズーム(Ken Burns)を任意で付与。

### F-5. 字幕（テロップ）
- セリフを **理解を促進する短い字幕**として中央下部に配置（全文ベタ貼りしない／適切に分割）。
- `keywords` に一致する語は **色を変えて強調**（既定: 通常=白、強調=黄、縁取り黒）。

### F-6. 合成・書き出し
- 全シーンのクリップを連結。
- `assets/bgm/` の BGM を背景に合成（ナレーションより低音量、自動ダッキング/音量比は設定値）。
- `output/final_output.mp4`（H.264 / 縦型 / 30fps）を書き出す。

---

## 5. 非機能要件

- **拡張性**: TTS/画像はプロバイダ差し替えのみで切替可能（Strategy パターン）。
- **設定の外出し**: APIキー・音量・解像度・フォント等は `config.yaml` / `.env` に集約。
- **冪等性/キャッシュ**: 同一シーンの音声・画像はキャッシュし再生成を避ける。
- **失敗耐性**: 1シーンの画像取得失敗で全体を止めずフォールバック。
- **ログ**: 各工程の進捗と所要時間を標準出力に。

---

## 6. データ仕様（script.json スキーマ）

```jsonc
{
  "title": "ディズニーランドのヤバい裏設定5選",
  "meta": {
    "lang": "ja",
    "tts_provider": "gtts",        // gtts | openai | elevenlabs
    "image_provider": "stock",     // stock | scrape
    "bgm": "random"                 // "random" | "assets/bgm/xxx.mp3"
  },
  "scenes": [
    {
      "id": 1,
      "narration": "実はシンデレラ城の地下には秘密の通路があるんです。",
      "image_query": "fairytale castle night",   // 素材API検索語(英語推奨)
      "image_prompt": "a grand fairytale castle at night, dramatic",  // 将来のAI生成用
      "keywords": ["シンデレラ城", "秘密の通路"]   // 強調する語
    }
  ]
}
```

---

## 7. ディレクトリ構成（案）

```
326_disneyYoutube/
├── REQUIREMENTS.md          # 本書
├── config.yaml              # 解像度/音量/フォント/プロバイダ既定値
├── .env                     # APIキー(gitignore)
├── requirements.txt         # Python依存
├── scripts/                 # 台本JSON置き場
│   └── sample.json
├── assets/
│   ├── bgm/                 # ローカルBGM(ユーザー配置)
│   ├── fonts/               # 日本語TTF
│   └── work/                # 中間生成物(audio/images, gitignore)
├── output/                  # final_output.mp4
├── src/
│   ├── pipeline.py          # オーケストレータ(エントリポイント)
│   ├── config.py            # 設定読込
│   ├── tts.py               # TTSProvider 抽象+実装
│   ├── images.py            # ImageProvider 抽象+実装
│   ├── subtitles.py         # 字幕生成(分割・強調)
│   └── video.py             # MoviePy合成・書き出し
└── .claude/
    └── skills/
        └── script-writer/   # 台本生成スキル(テーマ→script.json)
```

---

## 8. 処理フロー

```
[Claudeスキル] テーマ → script.json 生成
        ↓
1. pipeline.py が script.json 読込・検証
2. 各シーン: narration → TTS → scene_XX.mp3
3. 各シーン: image_query → ImageProvider → scene_XX.jpg
4. mp3 の尺を計測 → 画像クリップ(縦型)を尺ぶん生成
5. 字幕(分割・強調キーワード着色)を中央下部に焼き込み
6. 全クリップ連結 + BGM合成 → output/final_output.mp4
```

---

## 9. 技術スタック

| 領域 | 採用 | 備考 |
|---|---|---|
| 言語 | Python 3.13 | インストール済 |
| 動画 | MoviePy 2.x | 字幕は Pillow ベース(ImageMagick不要) |
| エンコード | ffmpeg 8.1 | インストール済 |
| TTS(初期) | gTTS | 無料・差替前提 |
| TTS(本番) | OpenAI TTS / ElevenLabs | 商用可 |
| 画像(主) | Pexels API 等 | 商用利用可・要APIキー(無料枠) |
| 画像(補) | スクレイピング | 明示フラグ時のみ・自己責任 |
| 設定 | PyYAML / python-dotenv | |

---

## 10. 実装ステップ（マイルストーン）

- **M0 環境構築**: venv 作成、`requirements.txt`、フォルダ雛形、サンプル `script.json`、フォント配置。
- **M1 TTS**: gTTS で mp3 生成 + 尺計測（最小動作確認）。
- **M2 画像**: StockImageProvider（Pexels）でシーン画像取得＋縦型加工。
- **M3 動画合成**: 画像+音声で無音字幕なし MP4 を書き出し（縦型確認）。
- **M4 字幕**: 分割ロジック＋強調キーワード着色を焼き込み。
- **M5 BGM**: ローカルBGM合成・音量バランス。
- **M6 台本スキル**: テーマ→script.json 生成スキル。
- **M7 仕上げ**: キャッシュ・失敗耐性・CLI 引数（`--allow-scrape` 等）。

---

## 11. 未確定/今後の確認事項

- フリー素材APIの選定（Pexels 推奨: 無料枠大・商用可・APIキー取得が容易）。APIキー取得は可能か？
- 日本語フォントの指定（推奨: Noto Sans JP を `assets/fonts/` に配置）。
- 1動画あたりのシーン数・目標尺（60〜90秒なら 6〜10 シーン程度が目安）。
- 字幕の分割粒度（句読点単位 / 文字数上限）。
```
