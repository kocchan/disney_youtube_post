---
name: project-tiktok-api
description: TikTok Content Posting API連携の状態（Sandbox稼働中・本番審査提出済み）と設定詳細
metadata:
  type: project
---

TikTok自動投稿（`src/tiktok_upload.py`, `.claude/skills/tiktok-publisher/`）は2026-07-05に実装。
TikTok Developerアプリ名は "disney"（developers.tiktok.com、app id 7658852334201718805）。

## 現在の状態（2026-07-05時点）

- **本番(Production)タブ**: App Review を submit 済み。審査結果待ち（TikTok公称2〜6週間）。
  承認されると `video.publish` スコープが本番アプリに付与される。
- **Sandboxタブ**: 審査不要ですぐ使える。Target User に `maidota77`（テスト用TikTokアカウント）を登録済み。
  このアカウントは**非公開アカウントに設定変更済み**（unaudited appはprivateアカウントにしか投稿できない制約のため）。
- `.env` は現在Sandbox用のClient Key/Secretが有効（本番用はコメントアウトして保管）。

## Why
TikTok Content Posting APIはYouTubeの`publishAt`のような予約公開機能が無く、また未審査アプリは
`SELF_ONLY`（非公開）投稿しかできない。将来の一般公開に備えてProduction審査を提出したが、
承認が下りるまでは実運用（一般公開投稿）はできず、Sandboxでのテスト運用のみ可能。

## How to apply
- 審査結果が来るまでは、TikTokへの実投稿は基本的に見送るか、Sandbox経由でSELF_ONLYテストのみに留める。
- 承認された場合の切替手順は [[project_tiktok_api]] 本ファイル末尾のTODOと、プロジェクトのTask #11
  （.envを本番Client Key/Secretに戻す→`tiktok_upload.py --auth`で再認証→TikTokアカウントの非公開設定を
  解除→`--privacy PUBLIC_TO_EVERYONE`で投稿確認）を参照。
- TikTokのOAuthはDesktopプラットフォームの場合PKCE必須。ただし標準のbase64url形式ではなく
  **code_challengeをSHA256のhexダイジェストで生成する**独自仕様（`src/tiktok_upload.py`の
  `do_auth()`に実装済み）。他のTikTok連携作業をする際もこの点に注意。
- Redirect URIはローカルコールバック `http://127.0.0.1:8722/callback`（Desktop向けに登録済み）。
- ToS/Privacy Policy/トップページはGitHub Pages（`docs/`フォルダ、kocchan/disney_youtube_post リポジトリ）
  で公開: `https://kocchan.github.io/disney_youtube_post/{terms,privacy,index}.html`

## 未完了タスク
- Task #11: 審査承認後の本番切り替え作業（このメモリファイルとあわせて確認すること）
