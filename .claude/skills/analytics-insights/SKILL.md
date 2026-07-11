---
name: analytics-insights
description: YouTube Analytics APIから動画パフォーマンス(視聴率・再生数・高評価等)を取得し、台本設計に活かせるナレッジとして .claude/memory/analytics_insights.md に蓄積する。ユーザーが「分析して」「パフォーマンス分析して」「アナリティクス見て」「動画の成績どう」「ナレッジ更新して」「レポート見せて」等、動画の成績・分析に関することを言ったら必ず使う。
---

# analytics-insights — パフォーマンス分析 → ナレッジ蓄積スキル

YouTube Analytics API の実データを使って、公開済み動画の成績を自動集計し、
次回以降の台本生成に活かせる知見として蓄積するスキル。

## ループ構造

```
YouTube Analytics API
   → src/analyze_performance.py（成績取得・タイトル型/カテゴリ別集計）
   → .claude/memory/analytics_insights.md（ナレッジ蓄積）
   → script-writer スキル（次回台本生成前に必ず参照）
   → 新しい動画が公開される
   → upload.py が video_id を output/{slug}/youtube_video_id.txt に保存
   → 次回の analyze_performance.py 実行時に自動で取り込まれる
   → ループ継続
```

台本の改善点が「勘」ではなくデータに基づいて蓄積され続ける仕組み。

## 実行手順

1. **認証確認**: `.env` に `YOUTUBE_ANALYTICS_REFRESH_TOKEN` がなければ先に案内する。
   ```bash
   python src/youtube_analytics.py --auth
   ```
2. **分析実行**:
   ```bash
   source .venv/bin/activate && python src/analyze_performance.py
   ```
   - チャンネルのuploadsプレイリストから全動画を取得し、`scripts/*.json` と突き合わせる
   - 突き合わせは `output/{slug}/youtube_video_id.txt`（upload.py が自動保存）を優先し、
     なければ `youtube_meta.txt` の解決済みタイトルで一致するものを探してキャッシュする
   - 各動画についてYouTube Analyticsから公開日〜前日までのライフタイム成績を取得
   - タイトルの型（保存版タグ・数字+選・ネガティブフック・ショックワード・疑問形）や
     推定カテゴリ（心理・都市伝説・アトラクション考察・キャラクター考察・速報系）ごとに
     視聴率・再生数を集計し、差が大きい要素から提言を生成する
3. **結果反映**: `.claude/memory/analytics_insights.md` が上書き更新される
   （`.claude/memory/MEMORY.md` インデックスへの追記も自動）。
4. **ユーザーにレポートとして報告する（必須・毎回このフォーマットで）**:
   実行しただけで終わらせず、`.claude/memory/analytics_insights.md` の内容を読み、
   必ず以下の構成でチャットに要約レポートを提示する（生データの丸貼りではなく、
   一目で分かる短い日本語コメントを添えること）:

   ```
   📊 YouTube動画パフォーマンスレポート（分析対象: N本 / 最終更新: YYYY-MM-DD）

   ■ 全体サマリー
     平均視聴率: XX.X%　平均再生数: X,XXX　平均エンゲージメント率: X.XX
     （前回分析から変化があれば「前回比 +X.Xpt」のように触れる）

   ■ 好調な動画 TOP3
     1. タイトル（視聴率XX% / 再生X,XXX）
     2. ...
     3. ...

   ■ 不調な動画 WORST3
     1. タイトル（視聴率XX%）— 一言で推定原因
     ...

   ■ カテゴリ別の傾向
     一番強いカテゴリ／弱いカテゴリを一言コメント付きで

   ■ タイトル・フックの型で分かったこと
     効果があった型／逆効果だった型を1〜2行ずつ、データの数字付きで

   ■ 次回の台本に活かすポイント（提言）
     箇条書きで2〜4個。断定しすぎず「サンプルN件のため参考」等の留保も添える
   ```

   - 数字だけ並べず、「なぜそうなっていそうか」の一言解釈を必ず添える。
   - サンプル数が少ない項目は言い切らず「参考値」であることを明示する。

## 台本生成への接続（必須）

`script-writer` スキルは新しい台本を書く前に、必ず `.claude/memory/analytics_insights.md` の
「台本生成への提言」セクションを参照し、過去データで効果が確認されている
タイトル・フックの型を優先する（CLAUDE.md のメモリ管理ルールに準拠）。

## 注意

- 動画公開直後はYouTube Analyticsのデータ反映に1〜2日かかるため、直近すぎる動画は
  再生数0件としてスキップされる（次回実行時に自動で取り込まれる）。
- サンプル数が少ないうち（一桁〜十数本）は提言の統計的信頼度は低いので、
  ナレッジ内の数値は参考値として扱う。
- 定期的に自動実行したい場合は `/schedule` や `/loop` で
  `python src/analyze_performance.py` を週次実行するよう設定できる（ユーザーの明示指示があれば設定する）。
