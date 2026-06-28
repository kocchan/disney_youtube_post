---
name: script-writer
description: ディズニー雑学YouTubeショート用の台本JSON(script.json)を生成する。テーマ(例「ディズニーランドのヤバい裏設定5選」)を与えると、scenes(narration/image_query/image_prompt/keywords)を含むスキーマ準拠のJSONを scripts/ に書き出す。ユーザーが「台本を作って」「〜〜の台本」「スクリプト生成」「動画のネタ」等と言ったら使う。
---

# script-writer — 台本JSON生成スキル

ディズニーリゾートの雑学・裏話を題材に、縦型ショート動画パイプライン(`src/pipeline.py`)が
そのまま消費できる `script.json` を生成する。

## 入力

ユーザーから受け取るテーマ。例:
- 「ディズニーランドのヤバい裏設定5選」
- 「シンデレラ城の知られざる秘密」
- 「ディズニーシーのこだわりトリビア」

テーマが曖昧/未指定なら、何本立て(選数)か・ランドかシーか等を1〜2問だけ確認してよい。

## 出力

`scripts/<英数字スラッグ>.json` に**有効なJSON**を書き出す(`Write` ツール)。
スキーマは下記。書き出したら、以下を順番に行う:
1. **TODO.md に新しい行を追加**し、全ステップ列を ❌、状態列を `❌ 未着手` にする。
2. `python src/pipeline.py --script scripts/<file>.json` で動画化できる旨をユーザーに伝える。

### スキーマ

```jsonc
{
  "title": "日本語タイトル({count}選)",   // {count} を使うと platform ごとの実シーン数に自動置換
  "meta": {
    "lang": "ja",
    "tts_provider": "gtts",      // 既定のまま
    "image_provider": "stock",   // 既定のまま
    "bgm": "rotate"              // 3曲使い回し
  },
  "scenes": [
    {
      "id": 1,
      // フックの narration に {count} を使う → youtube で間引かれてもタイトルと一致する
      "narration": "今日は裏設定を{count}個一気に紹介します。",
      "image_query": "english keywords for stock photo",
      "image_prompt": "english prompt for future AI image gen",
      "keywords": ["強調語1", "強調語2"],
      // local_clip: ローカル動画から背景クリップを切り出す（任意）
      // source は assets/video/ 以下のパス、start は開始秒、duration は切り出し秒数
      // シーンの内容に合うクリップを assets/video/tokyo_disney_resort_intro_scenes.md で探して指定する
      "local_clip": {
        "source": "assets/video/tokyo_disney_resort_intro.mp4",
        "start": 2806,
        "duration": 12
      }
    }
  ]
}
```

### local_clip フィールドの使い方

`assets/video/tokyo_disney_resort_intro_scenes.md` にシーン一覧があるので、台本の内容に合うシーンを探して `local_clip` に指定する。

```
# シーン仕様書の読み方
| 35 | 2806 | 0:46:46 | TDL | 空撮 | シンデレラ城空撮（朝・全景） |
       ↑ start(秒)
→ "local_clip": {"source": "assets/video/tokyo_disney_resort_intro.mp4", "start": 2806, "duration": 12}
```

- `duration` は narration 尺 + 2〜3秒の余裕を見て設定する（パイプラインが自動ループするので短すぎても問題なし）。
- `local_clip` を指定しない場合は従来通りフリー素材（Pexels/DuckDuckGo）を使う。
- `image_query` は `local_clip` を指定しても省略不可（サムネイル生成にフォールバック画像が必要）。

### {count} プレースホルダーについて（必須）

- **title・フック(scene 1)の narration・CTA(最終シーン)の narration** に必ず `{count}` を使う。
- パイプラインが「プラットフォームで実際に使うシーン数 − フック − CTA」を算出して `{count}` を置換するため、YouTube で間引きが起きてもタイトルと音声の数字が常に一致する。
- **keywords に `{count}` 由来の語を入れる場合は、置換後の文字列で一致するか確認する**（置換前に keywords を記載すると色が付かない）。置換後の数字が不明なため、count 系の keywords は省略してよい。

## 生成ルール(重要)

### 構成・尺(60秒以上を必達)
- **要件は「1分(60秒)以上」**。音声は **1.2倍速** で読むため、同じ尺でも多めの文字数が要る。
  目安レート ≈ **7.5〜8文字/秒**。→ 60秒には **最低480文字**、安全圏は **合計600〜800文字**。
- 目安: **8〜12シーン**、各 narration は2〜3文・**60〜90文字**。
- **シーン1は強力なフックで掴む**。以下のどれかを使う:
  - **ネガティブ・禁止系**: 「ディズニーで絶対やってはいけないこと」「知らないと損する裏設定」など、見ないと損という心理を突く。
  - **常識覆し系**: 「ミッキーの〇〇、実は〜だった」「みんなが勘違いしている〜の本当の理由」など、"実は"で始めて意外性を提示する。
  - **数字で期待感を持たせる系**: 「今日は〇選、全部知ってたら本物のマニア」など最後まで見る理由を作る。
- **中盤は1シーン=1ネタ**で密度を上げる(下記「深さ」参照)。
- **最終シーンはコメント促進CTA**: 「〇個中何個知っていましたか？コメントで教えてください」のように視聴者に問いかけ、コメントを促す形で締める。「次回もお楽しみに」だけの締めは使わない。
- **ループ構造を意識する**: 最終シーンの締めの言葉が、シーン1の冒頭と自然に繋がるよう設計すると、視聴者がループ再生しやすくなる。
- 生成後、総文字数 ÷ 7.5 で推定尺を概算。**60秒未満なら必ずシーンか具体例を足す**。
  最終的には `python src/pipeline.py` のログ「合計尺」で60秒超を確認する。

### narration(セリフ) — 「深さ」が命(薄い台本を作らない)
- **1シーンに必ず1つ、具体的な“核”を入れる**。次のいずれかを必ず含める:
  - **具体的な数字**(年・個数・距離・割合など。例「約180」「3つの」)
  - **固有の仕組み・名称・専門用語**(例「ウェザリング(意図的な汚し塗装)」)
  - **理由/メカニズム**(「なぜなら〜だから」と一段深く説明する)
  - **意外な対比・ギャップ**(「普通は〜だが、ここでは〜」)
- **NG例(薄い)**: 「園内は緻密に設計されています。」← 抽象的で中身がない。
  **OK例(濃い)**: 「園内の坂道はわずか数度の傾斜で、来園者が自然と次のエリアへ歩くよう計算されています。」
- 1文目で結論・驚き、2文目で根拠・補足、の順だとテンポが出る。
- 自然な話し言葉。難読漢字・特殊記号・英単語の混在は避ける。数字は読みやすく。
- 事実が曖昧なものは「〜と言われています」で断定を避ける(下記「事実性」)。

### image_query(素材検索語) — 著作権の鉄則
- **英語**で、Pexelsで実在しそうな**一般的・雰囲気的**な被写体にする。
- **ディズニー固有の商標・キャラ・固有建造物名は入れない**(例: "Mickey", "Disney", "Cinderella Castle" はNG)。
  代わりに一般語へ言い換える: 城→`fairytale castle`、パーク→`amusement park`、花火→`fireworks night`、
  ポップコーン→`popcorn snack`、夜景→`night cityscape`、星空→`starry night sky` など。
- 縦構図向きの語を選ぶ(人物アップ・縦長の風景など)。

### image_prompt(将来のAI生成用)
- 英語で情景を具体化した1文。こちらもディズニー商標は避け、雰囲気で表現する。

### keywords(強調キーワード)
- 各シーン1〜3語。**必ずその scene の narration に文字どおり含まれる部分文字列**にする
  (字幕の着色は文字列一致で行うため。含まれない語は色が付かない)。
- 視聴者に刺さる名詞・数値・驚きワードを選ぶ。

### 事実性
- 雑学・裏話は**もっともらしさを保ち、確証のない噂を断定しない**。
  断定が危ういものは「〜と言われています」等の柔らかい言い回しにする。

## 生成後の確認
- 書き出したJSONが `python -c "import json;json.load(open('scripts/<file>.json'))"` で読めることを確認する。
- 各 scene の keywords が narration に含まれているかを念のため確認する。

## 例(抜粋)

```json
{
  "title": "ディズニーランドのヤバい裏設定5選",
  "meta": { "lang": "ja", "tts_provider": "gtts", "image_provider": "stock", "bgm": "rotate" },
  "scenes": [
    {
      "id": 1,
      "narration": "実はディズニーランドには、ゲストが気づかない秘密の設定がたくさんあります。今日はそのヤバい裏設定を5つ紹介します。",
      "image_query": "fairytale castle fireworks night",
      "image_prompt": "a grand fairytale castle at night with fireworks, cinematic",
      "keywords": ["秘密の設定", "5つ"]
    }
  ]
}
```
