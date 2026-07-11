"""TikTok ショート自動投稿スクリプト（Content Posting API / Direct Post）。

Usage:
    # 初回認証（ブラウザが開く・1回だけ）
    python src/tiktok_upload.py --auth

    # 投稿（審査完了までは自動的に非公開 SELF_ONLY）
    python src/tiktok_upload.py --script scripts/19_palpalooza_psychology.json

    # 動画ファイルを直接指定
    python src/tiktok_upload.py --script scripts/19_palpalooza_psychology.json \\
        --video output/19_palpalooza_psychology/final_output_tiktok_1080x1920.mp4

重要: TikTok Content Posting API には YouTube の publishAt に相当する
「未来時刻に自動公開」機能が存在しない。呼び出した瞬間に投稿処理が実行される。
指定時刻に投稿したい場合は、このコマンドをその時刻に実行するよう
Claude Code の schedule 機能（cron）等で予約すること。
--schedule はログ・TODO記録用の入力であり、実際の投稿タイミングは制御しない。

未審査（unaudited）アプリはプライベート（SELF_ONLY）投稿のみ可能。
一般公開したい場合は TikTok for Developers でアプリ審査（video.publish スコープ）
を申請する必要がある。
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from datetime import timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, ROOT

from dotenv import set_key

DOTENV_PATH = ROOT / ".env"
JST = timezone(timedelta(hours=9))

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_BASE = "https://open.tiktokapis.com/v2"
SCOPES = "video.publish,video.upload"
REDIRECT_URI = "http://127.0.0.1:8722/callback"
CALLBACK_PORT = 8722

_HASHTAGS = (
    "#ディズニー #ディズニーランド #東京ディズニーランド #TDL "
    "#ディズニー雑学 #ディズニー裏話 #雑学 #豆知識 #fyp"
)


# ─── 認証 ────────────────────────────────────────────────────────────────────

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        # 認証成功後にブラウザがfavicon.ico等の無関係なリクエストを送ることがあるため、
        # 既にcode/errorが確定済みなら以降のリクエストは無視する
        if _CallbackHandler.code is not None or _CallbackHandler.error is not None:
            self.send_response(204)
            self.end_headers()
            return

        qs = parse_qs(urlparse(self.path).query)
        if "code" in qs:
            _CallbackHandler.code = qs["code"][0]
            body = "認証完了。このタブは閉じて構いません。"
        elif "error" in qs or "error_description" in qs:
            _CallbackHandler.error = qs.get("error_description", qs.get("error", ["不明なエラー"]))[0]
            body = f"認証エラー: {_CallbackHandler.error}"
        else:
            # code/errorどちらも無いリクエスト（favicon.ico等）は無視する
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><p>{body}</p></body></html>".encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def do_auth() -> None:
    client_key = os.getenv("TIKTOK_CLIENT_KEY")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")

    if not client_key or not client_secret:
        print("❌ TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET が .env にありません。")
        print()
        print("【取得手順】")
        print("1. https://developers.tiktok.com/ で開発者アカウントを作成")
        print("2. 'Manage apps' → 'Connect an app' でアプリを新規登録")
        print("3. アプリの 'Products' で 'Content Posting API' を追加")
        print("4. アプリ設定の Redirect URI に以下を追加登録:")
        print(f"     {REDIRECT_URI}")
        print("5. 発行された Client key / Client secret を .env に設定:")
        print("     TIKTOK_CLIENT_KEY=...")
        print("     TIKTOK_CLIENT_SECRET=...")
        print("6. 審査完了までは Sandbox/未審査状態のため、投稿は")
        print("   自分のTikTokアカウントに対して SELF_ONLY（非公開）でのみ可能。")
        print("7. 再度 python src/tiktok_upload.py --auth を実行する。")
        sys.exit(1)

    # TikTok Desktop Login Kitは標準PKCE(base64url)ではなく、
    # code_challengeをSHA256のhexダイジェストで生成する仕様
    _VERIFIER_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    code_verifier = "".join(secrets.choice(_VERIFIER_CHARS) for _ in range(64))
    code_challenge = hashlib.sha256(code_verifier.encode("utf-8")).hexdigest()

    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": "tiktok_upload_auth",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTH_URL}?{urlencode(params)}"

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"ブラウザで認可ページを開きます:\n  {url}")
    webbrowser.open(url)

    timeout = time.time() + 300
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        if time.time() > timeout:
            server.shutdown()
            print("❌ タイムアウトしました。もう一度実行してください。")
            sys.exit(1)
        time.sleep(0.5)
    server.shutdown()

    if _CallbackHandler.error:
        print(f"❌ 認可エラー: {_CallbackHandler.error}")
        sys.exit(1)

    code = _CallbackHandler.code
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
    )
    data = resp.json()
    if "refresh_token" not in data:
        print(f"❌ トークン取得に失敗しました: {data}")
        sys.exit(1)

    DOTENV_PATH.touch(exist_ok=True)
    set_key(str(DOTENV_PATH), "TIKTOK_REFRESH_TOKEN", data["refresh_token"])

    print()
    print(f"✅ 認証完了。リフレッシュトークンを {DOTENV_PATH} に保存しました。")
    print("   次回から --auth は不要です。")


def _get_access_token() -> str:
    client_key = os.getenv("TIKTOK_CLIENT_KEY")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    refresh_token = os.getenv("TIKTOK_REFRESH_TOKEN")

    if not all([client_key, client_secret, refresh_token]):
        print("❌ 認証情報が .env にありません。先に以下を実行してください:")
        print("   python src/tiktok_upload.py --auth")
        sys.exit(1)

    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    data = resp.json()
    if "access_token" not in data:
        print(f"❌ アクセストークン更新に失敗しました: {data}")
        sys.exit(1)

    # リフレッシュトークンが更新されていれば保存し直す（TikTokは再発行されることがある）
    if data.get("refresh_token") and data["refresh_token"] != refresh_token:
        set_key(str(DOTENV_PATH), "TIKTOK_REFRESH_TOKEN", data["refresh_token"])

    return data["access_token"]


# ─── メタ情報 ─────────────────────────────────────────────────────────────────

def _make_caption(script: dict) -> str:
    title = script.get("title", "")
    return f"{title}\n\n{_HASHTAGS}"


def _find_video(script_path: Path) -> Path:
    slug = script_path.stem
    out_dir = OUTPUT_DIR / slug

    if not out_dir.exists():
        raise FileNotFoundError(
            f"出力フォルダが見つかりません: {out_dir}\n"
            "先に pipeline.py で動画を生成してください。"
        )

    candidates = sorted(out_dir.glob("final_output_tiktok*.mp4"))
    if not candidates:
        candidates = sorted(out_dir.glob("final_output*.mp4"))
    if not candidates:
        raise FileNotFoundError(f"MP4 ファイルが見つかりません: {out_dir}")

    return candidates[-1]


# ─── 投稿 ─────────────────────────────────────────────────────────────────────

def _query_creator_info(access_token: str) -> dict:
    resp = requests.post(
        f"{API_BASE}/post/publish/creator_info/query/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
    )
    data = resp.json()
    if data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"creator_info/query 失敗: {data}")
    return data["data"]


def _resolve_privacy_level(requested: str, creator_info: dict) -> str:
    options = creator_info.get("privacy_level_options", [])
    if requested in options:
        return requested
    if "SELF_ONLY" in options:
        print(f"⚠ '{requested}' はこのアカウントで選択できないため SELF_ONLY にフォールバックします。")
        return "SELF_ONLY"
    if options:
        print(f"⚠ '{requested}' は利用不可。'{options[0]}' にフォールバックします。")
        return options[0]
    raise RuntimeError("利用可能な privacy_level_options がありません。")


def _poll_status(access_token: str, publish_id: str, timeout_sec: int = 120) -> str:
    deadline = time.time() + timeout_sec
    last_status = "PROCESSING_UPLOAD"
    while time.time() < deadline:
        resp = requests.post(
            f"{API_BASE}/post/publish/status/fetch/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
        )
        data = resp.json().get("data", {})
        last_status = data.get("status", last_status)
        if last_status in ("PUBLISH_COMPLETE", "FAILED"):
            if last_status == "FAILED":
                raise RuntimeError(f"投稿に失敗しました: {data}")
            return last_status
        time.sleep(3)
    print(f"⚠ ステータス確認がタイムアウトしました（最終状態: {last_status}）。TikTok側で処理中の可能性があります。")
    return last_status


def upload(script_path: Path, video_path: Path | None = None, privacy_level: str = "SELF_ONLY") -> str:
    """動画を TikTok に Direct Post する。返値は publish_id。"""
    script = json.loads(script_path.read_text(encoding="utf-8"))

    if video_path is None:
        video_path = _find_video(script_path)

    access_token = _get_access_token()

    print(f"📹 動画: {video_path}")
    print(f"📝 台本: {script_path.name}")

    creator_info = _query_creator_info(access_token)
    resolved_privacy = _resolve_privacy_level(privacy_level, creator_info)
    print(f"🔒 公開範囲: {resolved_privacy}")

    caption = _make_caption(script)
    video_size = video_path.stat().st_size

    init_body = {
        "post_info": {
            "title": caption,
            "privacy_level": resolved_privacy,
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,
            "total_chunk_count": 1,
        },
    }

    resp = requests.post(
        f"{API_BASE}/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=init_body,
    )
    init_data = resp.json()
    if init_data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"投稿initに失敗しました: {init_data}")

    publish_id = init_data["data"]["publish_id"]
    upload_url = init_data["data"]["upload_url"]

    print(f"\n🚀 アップロード開始: publish_id={publish_id}")
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    put_resp = requests.put(
        upload_url,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
        },
        data=video_bytes,
    )
    if put_resp.status_code not in (200, 201):
        raise RuntimeError(f"動画アップロードに失敗しました: {put_resp.status_code} {put_resp.text}")

    status = _poll_status(access_token, publish_id)
    print(f"✅ 投稿処理完了。ステータス: {status}")
    if resolved_privacy == "SELF_ONLY":
        print("   ⚠ 非公開（SELF_ONLY）投稿です。TikTokアプリの下書き/プライベート投稿から確認してください。")
    print(f"   publish_id: {publish_id}")

    return publish_id


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="TikTok Direct Post スクリプト")
    parser.add_argument("--auth", action="store_true", help="初回 OAuth 認証を実行する")
    parser.add_argument("--script", type=Path, help="台本 JSON ファイルのパス")
    parser.add_argument("--video", type=Path, help="動画ファイルを直接指定（省略時は自動検索）")
    parser.add_argument(
        "--privacy",
        type=str,
        default="SELF_ONLY",
        help="privacy_level（PUBLIC_TO_EVERYONE等。審査完了前は自動的にSELF_ONLYへフォールバック）",
    )
    parser.add_argument(
        "--schedule",
        type=str,
        help="（記録用のみ）投稿予定時刻 'YYYY-MM-DD HH:MM' JST。"
             "TikTok APIには予約公開機能が無いため、実際にこの時刻に投稿したい場合は"
             "このコマンド自体をその時刻に実行されるようスケジュールすること。",
    )
    args = parser.parse_args()

    if args.auth:
        do_auth()
        return

    if not args.script:
        parser.print_help()
        sys.exit(1)

    if not args.script.exists():
        print(f"❌ 台本ファイルが見つかりません: {args.script}")
        sys.exit(1)

    if args.schedule:
        print("ℹ️  --schedule は記録用です。この時刻に自動投稿されるわけではありません。")
        print(f"   '{args.schedule}' に実行されるよう Claude Code の schedule 機能等で予約してください。")

    upload(args.script, args.video, args.privacy)


if __name__ == "__main__":
    main()
