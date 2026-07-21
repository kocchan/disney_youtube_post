# ディズニー雑学 YouTube ショート 自動生成パイプライン

台本 JSON を入力すると、TTS 音声・フリー画像・字幕・BGM・効果音を自動合成し、  
YouTube ショート用の縦型 MP4（1080×1920 / 9:16）を書き出すツール。

---

## 必要環境

| ツール | バージョン |
|--------|-----------|
| Python | 3.13+ |
| ffmpeg | 8.x |

---

## セットアップ

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`.env` にAPIキーを設定（省略時はPexelsフォールバックなし）:
```
PEXELS_API_KEY=your_key_here
```

日本語フォントを配置:
```
assets/fonts/NotoSansJP-Bold.ttf   # 字幕・タイトル用
```

BGMファイルを配置（1〜複数枚OK）:
```
assets/bgm/bgm1.mp3
assets/bgm/bgm2.mp3
...
```

---

## 基本的な使い方

### 1. 台本を生成する（Claude スキル）

```
/script-writer テーマ: 東京ディズニーシーの裏話10選
```

→ `scripts/` フォルダに JSON が生成される。

### 2. 画像候補を取得し、選定結果を書き出す

```bash
source venv/bin/activate
python src/image_dashboard.py --script scripts/disney_urabanashi10.json --fetch-only
```

→ `assets/materials/`（素材ライブラリ）とWeb検索(DuckDuckGo)の両方から候補を取得し、
シーンごとのコンタクトシートを生成する。Claude がこれを見て1シーン1枚選び、
`output/{スクリプト名}/image_selections.json` を書き出す（詳細は `video-maker` スキル参照）。

### 3. 動画を生成する（TikTok 用から作る・メイン）

```bash
python src/pipeline.py \
  --script scripts/disney_urabanashi10.json \
  --tts gtts \
  --platform tiktok \
  --selections output/disney_urabanashi10/image_selections.json
```

出力先: `output/{スクリプト名}/final_output_tiktok.mp4`（サムネイル・YouTube用メタ情報もここで生成）

### 4. レビュー後に YouTube 用を生成

```bash
# YouTube用（BGMあり・60秒以下に自動カット）
python src/pipeline.py --script scripts/disney_urabanashi10.json --tts gtts --platform youtube --selections output/disney_urabanashi10/image_selections.json
```

---

## CLIオプション一覧

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--script` | 台本JSONのパス | `scripts/sample.json` |
| `--out` | 出力MP4のパス（省略時は自動） | — |
| `--tts` | TTSプロバイダ: `gtts` / `say` | configの値 |
| `--bgm` | BGM選択: `rotate` / `random` / `none` / ファイルパス | `rotate` |
| `--platform` | 出力先: `tiktok`（メイン・フル尺） / `youtube`（60秒以下） | `tiktok` |
| `--selections` | `image_dashboard.py --fetch-only` の選定結果 JSON（必須） | — |
| `--no-cache` | キャッシュを使わず全シーン再生成 | off |
| `--no-ken-burns` | Ken Burnsズームを無効化（高速書き出し） | off |

---

## プラットフォーム別の出力仕様

| プラットフォーム | BGM | 最大尺 | サフィックス |
|----------------|-----|--------|------------|
| `tiktok`（メイン） | あり | フル尺（60秒以上を推奨） | `_tiktok` |
| `youtube` | あり | 60秒（自動カット） | `_youtube` |

---

## 出力ファイル

`output/{スクリプト名}/` フォルダ内に生成される:

| ファイル | 内容 |
|---------|------|
| `image_selections.json` | 画像選定結果（`--selections` に渡すもの） |
| `final_output_tiktok.mp4` | TikTok向け動画（メイン） |
| `final_output_youtube.mp4` | YouTube向け動画 |
| `thumbnail.jpg` | サムネイル（TikTok用生成時に作成） |
| `youtube_meta.txt` | タイトル・説明文・ハッシュタグ |
| `*.credits.json` | 画像クレジット（Pexels帰属義務）|

---

## 台本 JSON の形式

```json
{
  "title": "ディズニーランドの知られざる裏設定10選",
  "meta": {
    "tts_provider": "gtts",
    "lang": "ja",
    "speed": 1.5
  },
  "scenes": [
    {
      "id": 1,
      "narration": "実は、ディズニーランドのゴミ箱は…",
      "image_query": "tokyo disneyland entrance",
      "scrape_query": "東京ディズニーランド 入口",
      "keywords": ["ゴミ箱", "30歩"]
    }
  ]
}
```

---

## 設定ファイル（config.yaml）

主要な調整値:

```yaml
letterbox:
  enabled: true
  top_bar: 450      # 上部黒帯の高さ（タイトル表示エリア）
  bottom_bar: 200   # 下部黒帯の高さ

tts:
  provider: gtts
  speed: 1.5

subtitle:
  font_size: 72
  position: center  # コンテンツエリア中央

title_overlay:
  font_size: 80
  color: "#FFD400"

bgm:
  narration_gain_db: 1.9   # ナレーション音量（1.25倍相当）
```

---

## 動画素材（ローカル映像）

`assets/materials/<subject>/` に、ユーザー本人が撮影/適法に入手した動画クリップを置く（著作権クリアな自前素材のみ）。詳細は `CLAUDE.md` の「assets/materials/」セクションを参照。

---

## ディレクトリ構成

```
326_disneyYoutube/
├── config.yaml              # 解像度・フォント・BGM等の設定
├── .env                     # APIキー（gitignore対象）
├── requirements.txt
├── scripts/                 # 台本JSON
├── assets/
│   ├── bgm/                 # BGM MP3ファイル
│   ├── fonts/               # 日本語フォント（TTF）
│   ├── sfx/                 # 効果音 MP3ファイル
│   ├── video/               # ローカル動画素材
│   └── work/                # 音声・画像キャッシュ
├── output/
│   └── {スクリプト名}/      # 制作物ごとにフォルダ分け
├── src/                     # パイプライン本体
│   ├── pipeline.py          # エントリポイント
│   ├── tts.py               # 音声合成
│   ├── images.py            # 画像取得
│   ├── subtitles.py         # 字幕生成
│   ├── video.py             # 動画合成
│   ├── sfx.py               # 効果音
│   ├── bgm.py               # BGM合成
│   ├── thumbnail.py         # サムネイル生成
│   └── youtube_meta.py      # YouTubeメタ情報生成
└── .claude/skills/
    ├── script-writer/       # 台本生成スキル
    └── video-maker/         # 動画作成一気通貫スキル
```
