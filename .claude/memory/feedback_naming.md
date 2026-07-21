---
name: feedback-naming
description: scripts/ と output/ の命名規則、および TODO.md 自動更新ルール
metadata:
  type: feedback
---

## scripts/ 命名ルール

スクリプトファイルは必ず `{NN:02d}_{スラッグ}.json` 形式で命名する（例: `08_eparade_25th.json`）。
番号なしファイルは絶対に作らない。

**Why:** 時系列順・テーマ別の整理のため。番号なしが混在すると管理が煩雑になる。  
**How to apply:** 新規スクリプト作成前に `ls scripts/` で最大番号を確認し、+1 した番号を付ける。

---

## output/ 命名ルール

output フォルダ名は **スクリプトファイルの stem をそのまま使う**。`meta.theme` はフォルダ名に使わない。

- `src/pipeline.py` と `src/image_dashboard.py` に実装済み（`folder = Path(script_path).stem`）
- 例: `scripts/08_eparade_25th.json` → `output/08_eparade_25th/`

**Why:** scripts/ と output/ の対応を一目で分かるようにするため。ユーザーが明示的に要求。  
**How to apply:** パイプラインが自動で処理するので追加作業は不要。`meta.theme` をフォルダ用途で使うコードを書かない。

---

## TODO.md 自動更新ルール

スクリプト作成・動画生成のたびに `TODO.md` のコンテンツ制作進捗表を更新する。**作業後に必ず更新する。忘れない。**

| トリガー | 更新内容 |
|----------|----------|
| スクリプト新規作成 | 対象行を追加し、全列を ❌ にする |
| 画像の自動選定完了（image_selections.json） | ① 列を ✅ |
| TikTok版生成（メイン。サムネ/メタ情報もここで生成） | ② 列を ✅ |
| YouTube版生成 | ③ 列を ✅ |
| 全列 ✅（または 📅） | 状態列を `✅`、残タスクから削除 |

（X向け出力は廃止済み。詳細なトリガー表・列定義は `CLAUDE.md` の「TODO.md 自動更新ルール」を正とする）

更新後は `最終更新: YYYY-MM-DD` の日付も書き換える。

**Why:** 制作物が増えるにつれて何がどこまで進んでいるか把握できなくなるため、ユーザーが明示的にルール化を要求。  
**How to apply:** 動画生成コマンドが成功した直後、TODO.md を開いて該当行の列を ✅ に変更する。
