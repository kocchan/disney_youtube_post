---
name: video-maker
description: ディズニー雑学YouTubeショート動画を一気通貫で作成するスキル。テーマを受け取り、台本生成→ユーザーレビュー→X用動画生成→ユーザーレビュー→YouTube用・TikTok用生成の順で進める。ユーザーが「動画を作って」「一気に作って」「video-maker」等と言ったら使う。
---

# video-maker — 一気通貫動画生成スキル

テーマを受け取り、以下の **5ステップ** を順番に進める。
各レビューポイントで必ずユーザーの承認を待ち、OKが出るまで次へ進まない。

---

## フロー

### STEP 0 — TODO.md のステータスを `🔄 作業中` に更新（必須・最初に行う）

対象スクリプトが既存の場合（既存番号の動画を作り直す等）、作業開始前に TODO.md の該当行の状態列を `🔄 作業中` に書き換える。
新規スクリプトの場合は STEP 2 で台本を書き出した直後に行う。

```
TODO.md 状態列を更新: #NN → 🔄 作業中
```

### STEP 1 — テーマ確認

ユーザーからテーマを受け取る。未指定なら以下を確認する（1〜2問のみ）:
- 何選にするか（5選・7選・10選など）
- ランドかシーか、または両方か
- 特定のアトラクション・テーマに絞るか

### STEP 2 — 台本生成（script-writer スキルの内容に従う）

`script-writer` スキルのルールに従ってJSONを生成し、`scripts/<スラッグ>.json` に書き出す。
書き出したらユーザーに以下を伝えてレビューを求める:

```
📝 台本を生成しました: scripts/<ファイル名>.json

▼ 内容確認
タイトル: 〇〇
シーン数: 〇
推定尺: 〇〇秒（〇分）

IDEで scripts/<ファイル名>.json を開いて内容を確認してください。
修正があれば直接ファイルを編集するか、ここに修正内容を伝えてください。
問題なければ「OK」と言っていただければ動画生成に進みます。
```

**ここで必ず止まり、ユーザーの返答を待つ。**

ユーザーが修正を伝えてきた場合:
- 内容に応じてJSONを編集し、再度レビューを求める。
- 「OK」が出るまでこのループを繰り返す。

### STEP 3 — X用動画生成（メイン）

「OK」を受け取ったら **X用（BGMあり・フル尺）** を生成する。

```bash
source venv/bin/activate && python src/pipeline.py \
  --script scripts/<ファイル名>.json \
  --allow-scrape \
  --tts gtts \
  --platform x
```

完了したら以下を伝える:

```
🎬 X用動画を生成しました！

出力ファイル:
  動画: output/final_output_x.mp4
  サムネイル: output/thumbnail.jpg
  メタ情報: output/youtube_meta.txt

! open output/final_output_x.mp4    ← 動画確認
! open output/thumbnail.jpg         ← サムネイル確認

動画とサムネイルを確認していただき、OKであれば「OK」と教えてください。
修正があればお知らせください（音量・速度・字幕位置・効果音など）。
OKが出たらYouTube用・TikTok用も続けて生成します。
```

**ここで必ず止まり、ユーザーの返答を待つ。**

### STEP 4 — X用修正対応

ユーザーのフィードバックに応じて修正を行う:

| フィードバック | 対応 |
|---------------|------|
| 「OK」「問題ない」 | STEP 5 へ進む |
| 音量・速度の調整 | config.yaml を更新して `--platform x` で再生成 |
| 台本の一部修正 | JSONを編集して `--no-cache --platform x` で再生成 |
| 画像が合わない | scrape_query を修正して再生成 |

修正後は再度「確認してください」と伝え、OKが出るまでループする。

### STEP 5 — YouTube用・TikTok用を生成

X用のOKが出たら **YouTube用（BGMなし・60秒以下）** と **TikTok用（BGMなし・フル尺）** を続けて生成する。

```bash
# YouTube用
source venv/bin/activate && python src/pipeline.py \
  --script scripts/<ファイル名>.json \
  --allow-scrape \
  --tts gtts \
  --platform youtube

# TikTok用
source venv/bin/activate && python src/pipeline.py \
  --script scripts/<ファイル名>.json \
  --allow-scrape \
  --tts gtts \
  --platform tiktok
```

完了したら以下を伝えて終了:

```
✅ 全プラットフォーム用の動画が完成しました！

📁 output/ フォルダの内容:
  final_output_x.mp4       ← X投稿用（BGMあり・フル尺）
  final_output_youtube.mp4 ← YouTube Shorts用（BGMなし・60秒以下）
  final_output_tiktok.mp4  ← TikTok用（BGMなし・フル尺）
  thumbnail.jpg            ← サムネイル
  youtube_meta.txt         ← タイトル・説明文・ハッシュタグ
```

---

## 注意事項

- **レビューポイント(STEP 2・STEP 4)では絶対に次へ進まない。**
- 動画生成はバックグラウンドで実行し、完了通知を待ってからユーザーに報告する。
- JSONのバリデーション(`python -c "import json;json.load(open('scripts/xxx.json'))"`)は生成後に必ず行う。
- 台本生成のルールは `script-writer` スキルの SKILL.md に従う（フック・深さ・CTA等）。
- スラッグは英数字とアンダースコアのみ（例: `disney_secrets_7`）。
