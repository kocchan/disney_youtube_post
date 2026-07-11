---
name: tiktok-publisher
description: 完成した動画をTikTokに投稿（Content Posting API経由）する。ユーザーが「TikTokに投稿」「TikTokにアップロード」「TikTok予約投稿」等と言ったら使う。
---

# tiktok-publisher — TikTok 投稿スキル

完成済みの動画（`output/<slug>/final_output_tiktok*.mp4`）を TikTok に
Content Posting API（Direct Post）でアップロードする。

## 前提知識（必読）

YouTubeと違い、TikTok Content Posting API には
**「未来の時刻に自動公開」する仕組み（YouTubeの`publishAt`相当）が存在しない**。
API呼び出しは即座に投稿処理される。そのため「予約投稿」は
**このマシン側で指定時刻に `tiktok_upload.py` を実行する**ことで実現する
（Claude Codeの `schedule` スキル / CronCreate を使う）。

また、TikTok Developerアプリが**審査未完了（unaudited）の間は
非公開（`SELF_ONLY`）投稿しかできない**。公開したい場合はユーザーに
TikTok for Developers でのアプリ審査状況を確認する。

## 手順

### 1. 投稿する動画を特定する

ユーザーの発言からスクリプトファイルを特定する（`ls scripts/` で確認）。
複数指定された場合は1本ずつ順番に処理する。

### 2. 投稿タイミングを確認する（必須・毎回）

**必ず**ユーザーに次のどちらかを確認する。省略・推測は禁止。

- **今すぐ投稿する**か
- **未来の日時に投稿したい**か（例: `2026-07-10 20:00` JST）

未来の日時の場合、その時刻に実行されるよう `schedule` スキル（または
`CronCreate`）で1回限りの実行を予約する旨をユーザーに伝える。

### 3. 動画ファイルの存在確認

```bash
ls output/<slug>/final_output_tiktok*.mp4
```

ファイルが存在しない場合はその旨を伝え、先に動画生成を促す
（`pipeline.py --platform tiktok`）。

### 4. 認証確認

`.env` に `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` / `TIKTOK_REFRESH_TOKEN`
が無い場合は、まず以下を案内する（ブラウザでの認可が必要）。

```bash
.venv/bin/python src/tiktok_upload.py --auth
```

### 5. 投稿実行

**今すぐ投稿する場合:**

```bash
.venv/bin/python src/tiktok_upload.py --script scripts/<slug>.json
```

**未来の日時を予約する場合:**

`schedule` スキルを使い、指定JST日時に以下のコマンドを1回だけ実行するよう登録する。

```bash
.venv/bin/python src/tiktok_upload.py --script scripts/<slug>.json --schedule "YYYY-MM-DD HH:MM"
```

（`--schedule` は記録用の引数で投稿タイミングは制御しない。実行時刻そのものを
スケジューラ側で指定時刻に合わせること。）

### 6. 完了後の報告

- `publish_id`
- 公開範囲（`SELF_ONLY` の場合はその旨と、TikTokアプリの下書き/プライベートから
  確認するよう案内する）
- 予約実行した場合はその日時

## 注意事項

- 審査完了前は `SELF_ONLY`（非公開）に自動フォールバックする。一般公開したい場合は
  TikTok for Developers でのアプリ審査（`video.publish`スコープ）状況をユーザーに確認する。
- `final_output_tiktok*.mp4` が複数ある場合は最新のファイルが使われる。

## エラー対応

| エラー | 対処 |
|--------|------|
| `❌ TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET が .env にありません` | アプリ未登録。`--auth` 実行時の案内に従いdevelopers.tiktok.comでアプリ登録するよう案内 |
| `❌ 認証情報が .env にありません` | `--auth` を再実行するよう案内 |
| `❌ 出力フォルダが見つかりません` | `pipeline.py` で動画を先に生成するよう案内 |
| `❌ MP4 ファイルが見つかりません` | `pipeline.py --platform tiktok` で TikTok 版を生成するよう案内 |
| `creator_info/query 失敗` / `投稿initに失敗しました` | トークン期限切れやスコープ不足の可能性。`--auth` の再実行を案内 |
