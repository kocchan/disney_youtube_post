---
name: feedback-video-design
description: 動画デザイン・レイアウトに関するフィードバック（タイトル位置・字幕・効果音・プラットフォーム別設定）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f5101ddf-0f41-4baa-be23-5a61d1e01385
---

タイトルオーバーレイは黒帯の**下端に寄せる**。上端に置くとスマホで見切れる。
**Why:** スマホ視聴時に画面上部のUIで隠れてしまうため。
**How to apply:** `render_title_overlay` で `y = bar_h - text_total_h - padding` とし、帯の下端基準にする。

上の黒帯は **450px**（1.5倍）以上にする。300pxだとタイトルが上端ギリギリになる。
**Why:** スマホで上部が見切れるため、余裕を持たせる。
**How to apply:** `config.yaml` の `letterbox.top_bar: 450`。

字幕は**画面中央**（`position: center`）に配置する。下部だと見づらい。

効果音は**3/4音量**（`volume_db: -12.5`, `caption_volume_db: -16.5`）が適切。デフォルトより下げる。

BGM音量は **`bgm_gain_db: -21.0`** が適切（`config.yaml` に設定済み）。`-18.0` だと大きすぎる。
**Why:** ユーザーから「BGMが少し大きい」と指摘を受けた。
**How to apply:** `config.yaml` の `bgm.bgm_gain_db` を `-21.0` のまま変えない。変更しない限り全スクリプトに適用される。

タイトル文字の左右見切れは **`margin = stroke_width * 2 + 80`** で防ぐ（`src/subtitles.py` の `render_title_overlay` に実装済み）。`margin = 60` では stroke 込みでの幅が足りずに見切れる。
**Why:** stroke_width=8 のとき左右各8px + 余白が不足して文字が画面端にかかる。
**How to apply:** `render_title_overlay` の margin 計算はこの式を維持する。

ナレーション音量は**1.25倍**（`narration_gain_db: 1.9`）が適切。

TTS は **gTTS**（Google女性声）、速度 **1.5倍** を使う。`--tts gtts` を明示する。
**Why:** sayコマンドのOtoya未導入環境でGrandpa(男性)になってしまうため、gttsを明示する。

画像取得は **DuckDuckGo scrape**（`--allow-scrape`）を使うと実際のディズニー写真が取れる。
各シーンの `scrape_query` に日本語の具体的なキーワードを設定する。

`scrape_query` は**パーク公式呼称・口語固定ワードをフルネームで**使う（例: 「ディズニーびしょ濡れEパレ」「エレクトリカルパレード 夜」）。英語ジェネリック語では固有の実写が取れない。
**Why:** 英語stock queryは雰囲気写真しか取れないが、日本語固有名詞Web検索は実際のパーク写真が取れる。
**How to apply:** 台本生成時点で `scrape_query` に固有名詞を入れる。同じイベントを扱う複数シーンは同じキーワードで束ねる（シーン6・7が同じイベントなら両方に同じワードを入れる）。

`scrape_query` は**ナレーションの「主語（何を感じさせたいか）」から逆算**して設定する。「素材・物体」で引かず「行為・状態・感情」に変換する。
**Why:** 例: 「イマジニアの執念」→「悩む人/設計者」が正解。「豆電球 vs LED 比較」（素材）は執念を映せない。「GPSと連動」→「GPS 位置情報 スマートフォン 信号 音楽」（システムの行為）が正解。「GPS」単体では連動感が伝わらない。
**How to apply:** 台本各シーンの `scrape_query` は "何を見た視聴者にどう感じてほしいか" を起点に設定する。

アトラクション体験そのものを映したい場合は**ユーザー写真（スクリーンショット）を最初から用意**する。
**Why:** Pexels・Webスクレイプでは著作権クリアなアトラクション内部・体験写真は取れない。
**How to apply:** `assets/work/candidates/<theme>/user/s{sid:02d}_*.jpg` に縦型変換して置き、ダッシュボードの⭐レーンから選択する。シーン計画時点で「この場面は実写必須」と判断したら、ユーザーに写真提供を依頼する。

プラットフォーム別の出力順: **X用を先に生成してレビュー** → OK後にYouTube用・TikTok用を生成。

最終シーンは「何個知っていましたか？コメントで教えてください」形式のCTAにする。「次回もお楽しみに」だけの締めは使わない。

サムネにバッジ（「知っていたら本物のマニア」等）は入れない。シンプルに画像＋タイトルのみ。

字幕の句読点ルール: 「。」「、」は**表示テキストから削除**する。字幕の分割タイミング（何文字で区切るか）は句読点で切る従来通りの方法を維持する。
**Why:** 動画で句読点は視覚ノイズ。ただし分割ロジックは変えない。
**How to apply:** `wrap_with_mask` の中で `ch not in "。、"` で除去する（`split_captions`・`wrap_lines` は元のロジックのまま）。

台本の「〇選」「〇個」はプレースホルダ `{count}` で書く。YouTube用に間引くとタイトル・音声の数字がズレるため。
**Why:** YouTube 60秒制限でシーンを間引いても「10選」タイトルのまま、「10個中何個？」の締めのままになって数が合わない問題が発生した。
**How to apply:** `title`・フック(scene 1)・CTA(最終シーン)の narration に `{count}` を使う。`pipeline.py` が間引き後の実数で自動置換・TTS 再生成する。`_resolve_count = len(prepared) - 2`（hook+CTAを除くトリビア数）。

サムネイルのタイトルテキストは**垂直方向の中央**に配置する。`y = (height - total_h) // 2`。
**Why:** 下寄り（`height * 0.65`）だとバランスが悪い。
**How to apply:** `thumbnail.py` の `generate_thumbnail` 内で `y = (height - total_h) // 2`。

サムネイルは**シンデレラ城など城・ランドマーク系の画像を全面背景**に使う。2枚分割レイアウトは廃止。
**Why:** 分割レイアウトだと城が見切れ、テキストも3行に割れて読みにくかった。
**How to apply:** `thumbnail.py` は1枚全面背景＋グラデーションオーバーレイ。`_pick_thumbnail_image` で image_query に "castle"/"fairytale"等を含むシーンを自動選択。タイトルは2行（max_chars=10）、font_size は自動縮小で幅内に収める。

サムネイルの `_wrap_title` は**必ず2行**で折り返す。`while len(lines) < 2` ループ＋残余テキスト append という実装は3行になるので絶対に使わない。
**Why:** "知らなきゃ損！ディズニーランドの設計の秘密4選"（23文字）をmax_chars=10で切ると「ディズ/ニーランドの設計の/秘密4選」の3行になり、単語が途中で割れて見苦しかった。
**How to apply:** `_wrap_title` は「テキスト中点に最も近い自然な区切り文字（の/は/ー/！等）で1か所だけ分割」するアルゴリズム。実装: `mid = len(text)//2` → 全文字スキャンして `abs((i+1)-mid)` が最小の break_chars 位置で split → `[text[:i+1], text[i+1:]]` を返す。

YouTube/TikTok 用サムネイルは**動画ごとに異なる背景画像**を使う。同じ城画像を使い回さない。
**Why:** Vol.1（設計系）と Vol.2（感覚系）で内容が異なるため、背景も内容に合わせる。
**How to apply:** `assets/thumbnail/bg_vol1.jpg`（昼間の城・建築）、`assets/thumbnail/bg_vol2.jpg`（夜のパーク）を別途用意して `generate_thumbnail` に渡す。

BGMなしのプラットフォーム（YouTube/TikTok）では **`narration_gain_db` を適用しない**。
**Why:** `narration_gain_db: 1.9` はBGMに対するナレーションのブースト値。BGMがないと過剰増幅になり音声バグの原因になる。
**How to apply:** `pipeline.py` で `narr_gain_db = ... if plat_bgm else 0.0`。

台本の `scrape_query` は**ユーザーが実際に検索するような具体的な日本語フレーズ**にする。抽象的なクエリより直接的な方が結果が良い。
**Why:** 「ディズニーランド ゴミ箱」「ディズニーランド 壁 わざと汚す」「ディズニーランド ポップコーンワゴン」のような具体的クエリの方が、「カラフル」「ウェザリング」等を付けた抽象クエリより実際のパーク写真が取れる。
**How to apply:** 台本生成時の `scrape_query` は「ディズニーランド ＋ 被写体の具体名」形式を優先。Pexelsの `image_query` は英語で一般的な被写体（ガム→`chewing gum sticky closeup`）。ナレーション内容に登場する具体物をそのまま検索語にする。

出力フォルダは**テーマごとに1つ**にまとめる。プラットフォーム別ファイルは同フォルダ内に並べる。
**Why:** platform別にフォルダが分かれると管理しづらい。
**How to apply:** `meta.theme` でフォルダ名、`meta.variant`（vol1/vol2等）でファイル名サフィックスを制御。出力: `output/{theme}/final_output_{platform}_{variant}.mp4`。

~~**異なるスクリプト同士の並列実行禁止**~~ → **解消済み**（2026-06-28）。`pipeline.py` が `assets/work/audio/{stem}/` にスクリプト別サブフォルダを作るよう修正したため、並列実行しても音声ファイルが競合しない。

**ダッシュボード起動・pipeline実行・upload実行のいずれかを開始する前に、必ずTODO.mdの対象行を `🔄 作業中` に更新する。** これが最優先。
**Why:** 作業に着手したのに ❌ 未着手 のまま放置すると、ユーザーが現状を把握できない。
**How to apply:** ダッシュボード起動コマンドを実行する前の最初のアクションとして必ずTODO.md編集を行う。pipeline/uploadも同様。
