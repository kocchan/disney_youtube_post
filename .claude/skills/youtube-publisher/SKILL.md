---
name: youtube-publisher
description: 完成した動画をYouTubeにスケジュール投稿（下書き保存）する。ユーザーが「YouTubeに投稿」「アップロード」「公開して」「スケジュール」等と言ったら使う。
---

# youtube-publisher — YouTube スケジュール投稿スキル

完成済みの動画（`output/<slug>/final_output_youtube*.mp4`）を YouTube にアップロードし、
指定した日時に自動公開されるよう下書き保存する。

## 手順

### 0. TODO.md のステータスを `🔄 作業中` に更新（必須・最初に行う）

アップロードを開始する前に、TODO.md の該当行の状態列を `🔄 作業中` に書き換える。

```
TODO.md 状態列を更新: #NN → 🔄 作業中
```

### 1. 投稿する動画を特定する

ユーザーの発言からスクリプトファイルを特定する。

- 「19番を投稿して」→ `scripts/19_palpalooza_psychology.json`
- 「パルパルーザをアップ」→ `scripts/` を `ls` して対応ファイルを見つける
- 複数指定された場合は1本ずつ順番に処理する

### 2. 公開日時を確認する（必須・毎回）

**必ず**ユーザーに公開日時を確認すること。省略・推測・前回の値の流用は禁止。

```
📅 公開日時を教えてください。（日本時間で入力）
例: 2026-06-28 20:00
```

ユーザーが「今日の20時」「明日の朝7時」など自然言語で答えた場合は、
本日の日付（`currentDate` 変数）を参照して `YYYY-MM-DD HH:MM` 形式に変換する。

### 3. 動画ファイルの存在確認

```bash
ls output/<slug>/final_output_youtube*.mp4
```

ファイルが存在しない場合はその旨を伝え、先に動画生成を促す。

### 4. アップロード実行

```bash
.venv/bin/python src/upload.py \
    --script scripts/<slug>.json \
    --schedule "YYYY-MM-DD HH:MM"
```

### 5. 完了後の報告

アップロード完了後、以下をユーザーに伝える：

- YouTube URL（`https://www.youtube.com/watch?v=<id>`）
- タイトル
- 公開予定日時（JST）
- 「YouTubeスタジオで確認できます」

### 6. TODO.md の更新確認

`upload.py` がアップロード完了後に **自動で** TODO.md を更新する。

- ④ YouTube 列 → `📅 MM/DD HH:MM`（予約日時）に書き換え
- `最終更新: YYYY-MM-DD` も自動更新

Claude がさらに手動で行うこと:
- ③ TikTok 列まで ✅ が揃っていれば、状態列も `✅` にして残タスクセクションから削除する

---

## 注意事項

- `--schedule` の公開日時は **JST（日本時間）** で指定する。内部で UTC に自動変換される。
- アップロード後は YouTube に「非公開（スケジュール済み）」として保存される。指定時刻に自動公開。
- 認証エラーが出た場合: `.venv/bin/python src/upload.py --auth` を実行するよう案内する。
- `final_output_youtube*.mp4` が複数ある場合は最新のファイルが使われる。

## エラー対応

| エラー | 対処 |
|--------|------|
| `❌ 認証情報が .env にありません` | `--auth` を再実行するよう案内 |
| `❌ 出力フォルダが見つかりません` | `pipeline.py` で動画を先に生成するよう案内 |
| `❌ MP4 ファイルが見つかりません` | `pipeline.py --platform youtube` で YouTube 版を生成するよう案内 |
| `HttpError 403` | YouTube API の quota 超過の可能性。翌日再試行を案内 |
