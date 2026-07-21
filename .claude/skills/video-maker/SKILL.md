---
name: video-maker
description: ディズニー雑学YouTubeショート動画を一気通貫で作成するスキル。テーマを受け取り、台本生成→画像のVision自動選定（Web検索＋素材ライブラリ／ダッシュボードなし）→TikTok用動画生成(メイン)→YouTube用生成まで、ユーザーの確認を待たず連続実行する。完了後にユーザーが指摘した修正（画像差し替え含む）にはその都度対応する。ユーザーが「動画を作って」「一気に作って」「video-maker」等と言ったら使う。
---

# video-maker — 一気通貫動画生成スキル

テーマを受け取り、以下の **5ステップ** を順番に進める。
**台本レビュー・完成動画OK確認のいずれも待たず、途中で止まらずに STEP 5（YouTube用生成）まで一気通貫で実行する（2026-07-19〜）。** ユーザーが後から台本や画像の修正を指摘したら、そのタイミングで個別に対応する（対応方法は STEP 4「画像差し替えループ」参照）。

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
書き出したら以下を簡潔に伝え、**ユーザーの返答を待たずそのまま STEP 2.5 へ進む**:

```
📝 台本を生成しました: scripts/<ファイル名>.json（タイトル: 〇〇 / シーン数: 〇 / 推定尺: 〇〇秒）
画像選定→動画生成まで続けます。
```

ユーザーが生成後に台本の修正を指摘してきた場合は、その時点でJSONを編集し `--no-cache` で該当プラットフォームを再生成する（STEP 4 と同様の対応）。

### STEP 2.5 — 画像自動選定（ダッシュボードなし・Claudeが選んでそのまま生成）

台本がOKになったら、動画生成の前に画像を選定する。**候補は毎回 (1) `assets/materials/` の素材ライブラリ と (2) その場のWeb検索（DuckDuckGo）の両方から取得する。** ライブラリはシーン意図にぴったり合うとは限らないため、Web検索でシーン特有の候補を補う。

**確認ダッシュボード（`--preselect`）は使わない（2026-07-18〜）。** Claudeがコンタクトシートを見て自動選定したら、ユーザーの事前確認を挟まず**そのまま STEP 3 の動画生成に進む**。画像の良し悪しは STEP 4 で**完成動画を見て**判断し、おかしいシーンだけ差し替える（後述）。HTMLダッシュボードを開く手間をなくすための運用。

0. （任意・台本執筆段階で素材の有無を先に確認したい場合）`assets/materials/index.json` を読むと、既存ライブラリの `category`/`subject`/`description`/`tags` を一括で見渡せる。台本の `image_query`/`scrape_query` を書く前にこれを参照すると、既存素材にマッチしやすいキーワードを選びやすい。

1. **候補取得のみ実行**（ブラウザは開かない。素材ライブラリのマッチング＋Web検索のライブ取得を行うためネットワークアクセスあり）:

```bash
source venv/bin/activate && python src/image_dashboard.py \
  --script scripts/<ファイル名>.json \
  --fetch-only
```

完了すると `assets/work/candidates/<ファイル名>/` に `manifest.json`（素材ライブラリ・Web検索双方の候補のパス・説明・出典）と、シーンごとの `contact_s{NN}.jpg`（候補を1枚のグリッド画像にまとめたコンタクトシート）が生成される。

**候補が0件のシーンがあれば（ライブラリ・Web検索とも失敗した場合のみ）、ターミナルに `⚠️ 候補が0件のシーン: 3, 5` のように表示される。** その場合はここで止まり、`scrape_query` を見直すか `material-collector` スキルで素材を集めてから再度この手順1をやり直す。

2. **各シーンのコンタクトシートをReadツールで確認し、1枚選ぶ。** 選定基準は `.claude/memory/feedback_video_design.md` の画像選定セクションと `.claude/memory/image_selection_knowledge.md`（過去の差し替え指摘から学んだナレッジ）に従う。特に:
   - ナレーションの「行為・状態・感情」を映しているか、構図が破綻していないかを見る
   - `materials`（ライブラリ）候補は `manifest.json` の `description` フィールド（登録時にClaudeが書いた説明文）も判断材料にする
   - `web`（Web検索）候補はそのシーンの意図に最も忠実な傾向があるが、映画ポスター等の二次的著作物・無関係な画像が混ざることがあるので内容をよく見て選ぶ
   - `materials_video`（動画クリップ）候補は、コンタクトシートの先頭フレームだけで判断しない。`ffmpeg -y -i <mp4> -ss 3 -vframes 1 -q:v 3 /tmp/check.jpg` で中間フレームを抽出しReadで内容確認してから採否を決める（先頭フレームは暗転/不鮮明なことがある）
   - 候補が多いシーンでは目視でグリッドを数えず、`manifest.json` を読んで `variant+idx: description/title` のテキスト一覧で最終決定する（数え間違い防止）
   - 気に入ったWeb検索候補を今後も使い回したい場合は、選定後に `material-collector` スキルでライブラリに登録することを検討する（このステップ自体はライブラリに自動登録しない）

3. 選んだ候補を `manifest.json` の該当エントリから引き、`output/<ファイル名>/image_selections.json` を書き出す（Writeツール）。スキーマ:

```json
{
  "1": {"image_path": "<manifestのpath>", "variant": "materials", "credit": {<manifestのcandidateそのもの>}},
  "2": {"image_path": "...", "variant": "web", "credit": {...}}
}
```

サムネイル用の画像も選べる場合は `"thumbnail": {"image_path": "..."}` を追加する（任意）。

4. **`image_selections.json` を書き出したら、そのまま STEP 3（動画生成）へ進む。** ダッシュボードでの事前確認は行わない。

### STEP 3 — TikTok用動画生成（メイン）

画像選定が完了したら **TikTok用（BGMあり・フル尺）** を生成する。TikTokがメインプラットフォームで、サムネイル・YouTube用メタ情報もここで生成される。`--selections` に STEP 2.5 で確定した `image_selections.json` を渡す。

```bash
source venv/bin/activate && python src/pipeline.py \
  --script scripts/<ファイル名>.json \
  --tts gtts \
  --platform tiktok \
  --selections output/<ファイル名>/image_selections.json
```

完了したら以下を伝え、**ユーザーの返答を待たずそのまま STEP 5（YouTube用生成）へ進む**:

```
🎬 TikTok用動画を生成しました！ output/<ファイル名>/final_output_tiktok.mp4（サムネイル・メタ情報も生成済み）
続けてYouTube用を生成します。
```

### STEP 4 — 事後の修正対応（画像差し替えループ含む）

STEP 5 完了後にユーザーが動画・サムネイルを見て修正を指摘してきた場合に対応する（能動的にレビューを求めることはしない）:

| フィードバック | 対応 |
|---------------|------|
| 音量・速度の調整 | config.yaml を更新して該当プラットフォームで再生成 |
| 台本の一部修正 | JSONを編集して `--no-cache` で該当プラットフォームを再生成 |
| **特定シーンの画像が合わない** | 下記「画像差し替えループ」で該当シーンだけ差し替えて再生成 |

修正後は再度確認を促す。TikTok/YouTube両方に影響する修正は両プラットフォーム分を再生成する。

#### 画像差し替えループ（ダッシュボード廃止に伴う新運用・2026-07-18〜）

**完成動画を見てユーザーが気になったシーンをここで差し替える。** 再レンダリングのコストを抑えるため、**指摘は必ずまとめて受け、1ラウンドにつき再レンダリングは1回だけ**にする。

1. ユーザーに「画像を変えたいシーンがあれば**まとめて**教えてください（例: 3と6）」と促し、対象シーンを受け取る。
2. 対象シーンごとに `assets/work/candidates/<ファイル名>/manifest.json` を読み、**現在選ばれている候補以外**の候補を確認する。必要なら候補画像を Read で見て、STEP 2.5 の選定基準（`feedback_video_design.md` / `image_selection_knowledge.md`）で選び直す。候補が尽きていれば `scrape_query` を見直して手順1（`--fetch-only`）からやり直すか `material-collector` で素材を足す。
3. `output/<ファイル名>/image_selections.json` の該当シーンのエントリだけを書き換える（Editツール。他シーンは触らない）。
4. **対象シーンをすべて差し替えてから**、`--platform tiktok` で**1回だけ**再生成する（音声はキャッシュされるので再エンコード中心）。
5. 再生成した動画を確認してもらい、OKが出るまで1〜4を繰り返す。

**差し替えが発生したら学習する:** あるシーンで自動選定（元の pick）とユーザー指摘後の差し替え（新しい pick）が食い違ったら、両方の画像を Read で見比べ、「なぜ最初の自動選定が外したか」「なぜ差し替え先が正解か」を分析し、`.claude/memory/image_selection_knowledge.md` の「蓄積されたナレッジ」に一般化ルール（Why / How to apply形式）として追記する（手順は同ファイル参照）。差し替えがなければ何もしない。

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

- **STEP 1〜5のどこでもユーザーの返答を待たない。** 台本生成・画像自動選定・TikTok生成・YouTube生成を連続実行し、最後にまとめて完成報告する。ユーザーが後から台本・画像の修正を指摘したら STEP 4 の要領でその都度対応する。
- 動画生成はバックグラウンドで実行し、完了通知を待ってからユーザーに報告する。
- JSONのバリデーション(`python -c "import json;json.load(open('scripts/xxx.json'))"`)は生成後に必ず行う。
- 台本生成のルールは `script-writer` スキルの SKILL.md に従う（フック・深さ・CTA等）。
- 画像選定のルールは `.claude/memory/feedback_video_design.md` の画像選定セクションと `.claude/memory/image_selection_knowledge.md` に従う（`image_dashboard.py --fetch-only` の使い方は STEP 2.5、差し替えループは STEP 4 参照）。**確認ダッシュボードは2026-07-19にコードごと削除済み**（`image_dashboard.py`は候補取得・コンタクトシート生成のみ）。
- **候補は `assets/materials/` の素材ライブラリ＋その場のWeb検索の両方から取る。** STEP 2.5 で候補が0件のシーンがあれば `material-collector` スキルで素材を追加するか `scrape_query` を見直してから進める。`pipeline.py` 自体はWeb検索・APIを呼ばず、`--selections` の指定が必須（取得済みの候補をコピーするだけ）。
- スラッグは英数字とアンダースコアのみ（例: `disney_secrets_7`）。
