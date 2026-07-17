---
name: video-maker
description: ディズニー雑学YouTubeショート動画を一気通貫で作成するスキル。テーマを受け取り、台本生成→ユーザーレビュー→素材ライブラリからのVision自動選定・確認→TikTok用動画生成(メイン)→ユーザーレビュー→YouTube用生成の順で進める。ユーザーが「動画を作って」「一気に作って」「video-maker」等と言ったら使う。
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

### STEP 2.5 — 画像選定（素材ライブラリからVision自動選定＋確認ダッシュボード）

台本がOKになったら、動画生成の前に画像を選定する。**候補は毎回 (1) `assets/materials/` の素材ライブラリ と (2) その場のWeb検索（DuckDuckGo）の両方から取得する。** ライブラリはシーン意図にぴったり合うとは限らないため、Web検索でシーン特有の候補を補う。

0. （任意・台本執筆段階で素材の有無を先に確認したい場合）`assets/materials/index.json` を読むと、既存ライブラリの `category`/`subject`/`description`/`tags` を一括で見渡せる。台本の `image_query`/`scrape_query` を書く前にこれを参照すると、既存素材にマッチしやすいキーワードを選びやすい。

1. **候補取得のみ実行**（ブラウザは開かない。素材ライブラリのマッチング＋Web検索のライブ取得を行うためネットワークアクセスあり）:

```bash
source venv/bin/activate && python src/image_dashboard.py \
  --script scripts/<ファイル名>.json \
  --fetch-only
```

完了すると `assets/work/candidates/<ファイル名>/` に `manifest.json`（素材ライブラリ・Web検索双方の候補のパス・説明・出典）と、シーンごとの `contact_s{NN}.jpg`（候補を1枚のグリッド画像にまとめたコンタクトシート）が生成される。

**候補が0件のシーンがあれば（ライブラリ・Web検索とも失敗した場合のみ）、ターミナルに `⚠️ 候補が0件のシーン: 3, 5` のように表示される。** その場合はここで止まり、`scrape_query` を見直すか `material-collector` スキルで素材を集めてから再度この手順1をやり直す。

2. **各シーンのコンタクトシートをReadツールで確認し、1枚選ぶ。** 選定基準は `.claude/memory/feedback_video_design.md` の画像選定セクションと `.claude/memory/image_selection_knowledge.md`（過去の自動選定ミスから学んだナレッジ）に従う。特に:
   - ナレーションの「行為・状態・感情」を映しているか、構図が破綻していないかを見る
   - `materials`（ライブラリ）候補は `manifest.json` の `description` フィールド（登録時にClaudeが書いた説明文）も判断材料にする
   - `web`（Web検索）候補はそのシーンの意図に最も忠実な傾向があるが、映画ポスター等の二次的著作物・無関係な画像が混ざることがあるので内容をよく見て選ぶ
   - `materials_video`（動画クリップ）候補は、コンタクトシートの先頭フレームだけで判断しない。`ffmpeg -y -i <mp4> -ss 3 -vframes 1 -q:v 3 /tmp/check.jpg` で中間フレームを抽出しReadで内容確認してから採否を決める（先頭フレームは暗転/不鮮明なことがある）
   - 気に入ったWeb検索候補を今後も使い回したい場合は、選定後に `material-collector` スキルでライブラリに登録することを検討する（このステップ自体はライブラリに自動登録しない）

3. 選んだ候補を `manifest.json` の該当エントリから引き、`output/<ファイル名>/image_selections.json` を書き出す（Writeツール）。スキーマ:

```json
{
  "1": {"image_path": "<manifestのpath>", "variant": "materials", "credit": {<manifestのcandidateそのもの>}},
  "2": {"image_path": "...", "variant": "web", "credit": {...}}
}
```

サムネイル用の画像も選べる場合は `"thumbnail": {"image_path": "..."}` を追加する（任意）。

4. **確認ダッシュボードを開く**（事前選定済みの状態でハイライトされる）:

```bash
source venv/bin/activate && python src/image_dashboard.py \
  --script scripts/<ファイル名>.json \
  --preselect output/<ファイル名>/image_selections.json
```

ユーザーに次のように伝えて待つ:

```
🖼 各シーンの画像を素材ライブラリからClaudeが自動選定しました（🤖マーク）。
ブラウザで内容を確認し、問題なければそのまま「✅ この画像で動画生成する」を、
変更したい場合は該当シーンをクリックし直してから送信してください。
```

**ここで必ず止まり、ダッシュボードでの送信完了（ターミナルに `✅ 選択完了` が出力される）を待つ。**

5. **送信完了後、`assets/work/image_selection_diffs.jsonl` にこの台本の未分析(`"analyzed": false`)エントリがないか確認する。** ユーザーがClaudeの自動選定と違う画像を選んだシーンがあれば、`auto_pick.path`（Claudeが選んだ画像）と `user_pick.path`（ユーザーが選んだ画像）を両方Readして見比べ、「何が違ったか」「なぜユーザーはこちらを選んだと考えられるか」を分析し、`.claude/memory/image_selection_knowledge.md` の「蓄積されたナレッジ」に一般化したルール（Why/How to apply形式）として追記する。分析済みのエントリは `"analyzed": true` に書き換える。差分がなければ何もしない。

### STEP 3 — TikTok用動画生成（メイン）

画像選定が完了したら **TikTok用（BGMあり・フル尺）** を生成する。TikTokがメインプラットフォームで、サムネイル・YouTube用メタ情報もここで生成される。`--selections` に STEP 2.5 で確定した `image_selections.json` を渡す。

```bash
source venv/bin/activate && python src/pipeline.py \
  --script scripts/<ファイル名>.json \
  --tts gtts \
  --platform tiktok \
  --selections output/<ファイル名>/image_selections.json
```

完了したら以下を伝える:

```
🎬 TikTok用動画を生成しました！

出力ファイル:
  動画: output/<ファイル名>/final_output_tiktok.mp4
  サムネイル: output/<ファイル名>/thumbnail.jpg
  メタ情報: output/<ファイル名>/youtube_meta.txt

! open output/<ファイル名>/final_output_tiktok.mp4    ← 動画確認
! open output/<ファイル名>/thumbnail.jpg               ← サムネイル確認

動画とサムネイルを確認していただき、OKであれば「OK」と教えてください。
修正があればお知らせください（音量・速度・字幕位置・効果音など）。
OKが出たらYouTube用も続けて生成します。
```

**ここで必ず止まり、ユーザーの返答を待つ。**

### STEP 4 — TikTok用修正対応

ユーザーのフィードバックに応じて修正を行う:

| フィードバック | 対応 |
|---------------|------|
| 「OK」「問題ない」 | STEP 5 へ進む |
| 音量・速度の調整 | config.yaml を更新して `--platform tiktok` で再生成 |
| 台本の一部修正 | JSONを編集して `--no-cache --platform tiktok` で再生成 |
| 画像が合わない | scrape_query を修正して再生成 |

修正後は再度「確認してください」と伝え、OKが出るまでループする。

### STEP 5 — YouTube用を生成

TikTok用のOKが出たら **YouTube用（60秒以下）** を生成する。

```bash
source venv/bin/activate && python src/pipeline.py \
  --script scripts/<ファイル名>.json \
  --tts gtts \
  --platform youtube \
  --selections output/<ファイル名>/image_selections.json
```

完了したら以下を伝えて終了:

```
✅ 全プラットフォーム用の動画が完成しました！

📁 output/<ファイル名>/ フォルダの内容:
  final_output_tiktok.mp4  ← TikTok投稿用（BGMあり・フル尺）
  final_output_youtube.mp4 ← YouTube Shorts用（60秒以下）
  thumbnail.jpg            ← サムネイル
  youtube_meta.txt         ← タイトル・説明文・ハッシュタグ
```

---

## 注意事項

- **レビューポイント(STEP 2・STEP 2.5・STEP 4)では絶対に次へ進まない。**
- 動画生成はバックグラウンドで実行し、完了通知を待ってからユーザーに報告する。
- JSONのバリデーション(`python -c "import json;json.load(open('scripts/xxx.json'))"`)は生成後に必ず行う。
- 台本生成のルールは `script-writer` スキルの SKILL.md に従う（フック・深さ・CTA等）。
- 画像選定のルールは `.claude/memory/feedback_video_design.md` の画像選定セクションに従う（`image_dashboard.py --fetch-only`/`--preselect` の使い方は STEP 2.5 参照）。
- **画像はすべて `assets/materials/` の素材ライブラリからのみ選ぶ。** STEP 2.5 で候補が0件のシーンがあれば `material-collector` スキルで素材を追加してから進める。`pipeline.py` はWeb検索・APIを一切呼ばず、`--selections` の指定が必須。
- スラッグは英数字とアンダースコアのみ（例: `disney_secrets_7`）。
