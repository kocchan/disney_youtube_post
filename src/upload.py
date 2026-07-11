"""YouTube ショート自動アップロードスクリプト。

Usage:
    # 初回認証（ブラウザが開く・1回だけ）
    python src/upload.py --auth

    # 下書き保存（スケジュール投稿）
    python src/upload.py --script scripts/19_palpalooza_psychology.json \\
        --schedule "2026-06-28 20:00"

    # 動画ファイルを直接指定
    python src/upload.py --script scripts/19_palpalooza_psychology.json \\
        --schedule "2026-06-28 20:00" \\
        --video output/19_palpalooza_psychology/final_output_youtube_1080x1920.mp4

公開時刻は JST（日本時間）で指定。スケジュール設定時は非公開で保存し、
指定時刻に YouTube が自動公開する。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, ROOT
from youtube_meta import _make_description, _make_title

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("YouTube API ライブラリが未インストールです。")
    print("pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)

from dotenv import set_key

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET_PATH = ROOT / "client_secret.json"
DOTENV_PATH = ROOT / ".env"
JST = timezone(timedelta(hours=9))

_BASE_TAGS = [
    "ディズニー", "ディズニーランド", "東京ディズニーランド", "TDL",
    "ディズニーシー", "TDS", "ディズニー雑学", "ディズニー裏話",
    "ディズニートリビア", "雑学", "豆知識", "Shorts", "YouTubeShorts",
]


# ─── 認証 ────────────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    client_id     = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")

    if not all([refresh_token, client_id, client_secret]):
        print("❌ 認証情報が .env にありません。先に以下を実行してください:")
        print("   python src/upload.py --auth")
        sys.exit(1)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    if not creds.valid:
        creds.refresh(Request())
    return creds


def do_auth() -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("❌ client_secret.json が見つかりません。")
        print()
        print("【取得手順】")
        print("1. Google Cloud Console (console.cloud.google.com) を開く")
        print("2. 「APIとサービス」→「有効なAPIとサービス」で")
        print('   "YouTube Data API v3" を有効化')
        print("3. 「認証情報」→「認証情報を作成」→「OAuthクライアントID」")
        print("   種類: デスクトップアプリ")
        print(f"4. JSON をダウンロードして {CLIENT_SECRET_PATH} に保存")
        print("5. 再度 python src/upload.py --auth を実行")
        sys.exit(1)

    cs_data = json.loads(CLIENT_SECRET_PATH.read_text(encoding="utf-8"))
    cs = cs_data.get("installed") or cs_data.get("web") or {}

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print("❌ リフレッシュトークンが取得できませんでした。")
        print("   Google Cloud Console > OAuth同意画面 > テストユーザーに自分のアカウントを追加して再実行してください。")
        sys.exit(1)

    DOTENV_PATH.touch(exist_ok=True)
    set_key(str(DOTENV_PATH), "YOUTUBE_CLIENT_ID",     cs["client_id"])
    set_key(str(DOTENV_PATH), "YOUTUBE_CLIENT_SECRET", cs["client_secret"])
    set_key(str(DOTENV_PATH), "YOUTUBE_REFRESH_TOKEN", creds.refresh_token)

    print()
    print(f"✅ 認証完了。リフレッシュトークンを {DOTENV_PATH} に保存しました。")
    print("   次回から --auth は不要です。")


# ─── 時刻変換 ─────────────────────────────────────────────────────────────────

def parse_schedule(schedule_str: str) -> str:
    """'YYYY-MM-DD HH:MM'（JST）→ RFC 3339 UTC 文字列に変換する。"""
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%m/%d %H:%M", "%m-%d %H:%M"):
        try:
            naive = datetime.strptime(schedule_str.strip(), fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(
            f"公開日時の形式が不正です: {schedule_str!r}\n"
            "例: '2026-06-28 20:00'（YYYY-MM-DD HH:MM、日本時間）"
        )

    # 年が省略されていた場合（%m/%d 形式）は今年を補完
    if naive.year == 1900:
        naive = naive.replace(year=datetime.now().year)

    jst_dt = naive.replace(tzinfo=JST)
    utc_dt = jst_dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ─── メタ情報 ─────────────────────────────────────────────────────────────────

def _build_tags(script: dict) -> list[str]:
    tags = list(_BASE_TAGS)
    subject = script.get("meta", {}).get("subject", "")
    if subject:
        tags.append(subject)
    for scene in script.get("scenes", []):
        for kw in scene.get("keywords", []):
            if kw and kw not in tags:
                tags.append(kw)
    return tags[:500]


def _detect_schedule_status_cols(lines: list[str]) -> tuple[int | None, int | None]:
    """ヘッダー行から 📅 列と状態列のセル位置を動的に検出する。

    列の追加・並び替えがあってもハードコードした index に依存しないようにする。
    """
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 2 or cells[1].strip() != "#":
            continue  # コンテンツ制作進捗テーブルのヘッダー行のみ対象（先頭列が "#"）
        sched_idx  = next((i for i, c in enumerate(cells) if "📅" in c), None)
        status_idx = next((i for i, c in enumerate(cells) if c.strip() == "状態"), None)
        return sched_idx, status_idx
    return None, None


def _update_todo_row(script_path: Path, today: str, col7: str | None = None, col8: str | None = None) -> bool:
    """TODO.md の該当行を更新する汎用関数。col7=📅列、col8=状態列。"""
    import re
    todo_path = ROOT / "TODO.md"
    if not todo_path.exists():
        return False

    stem    = script_path.stem
    num_str = stem.split("_")[0].lstrip("0") or "0"
    pattern = re.compile(rf"^\|\s*0*{re.escape(num_str)}\s*\|")

    lines = todo_path.read_text(encoding="utf-8").splitlines(keepends=True)
    sched_idx, status_idx = _detect_schedule_status_cols(lines)

    new_lines = []
    updated   = False

    for line in lines:
        if pattern.match(line) and sched_idx is not None and status_idx is not None:
            parts = line.split("|")
            if len(parts) > max(sched_idx, status_idx):
                if col7 is not None:
                    parts[sched_idx] = f" {col7} "
                if col8 is not None:
                    parts[status_idx] = f" {col8} "
                line = "|".join(parts)
                updated = True
        if line.startswith("> 最終更新:"):
            line = f"> 最終更新: {today}\n"
        new_lines.append(line)

    todo_path.write_text("".join(new_lines), encoding="utf-8")
    return updated


def _update_todo_in_progress(script_path: Path) -> None:
    """アップロード開始時に TODO.md の状態列を 🔄 作業中 にする。"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    stem    = script_path.stem
    num_str = stem.split("_")[0].lstrip("0") or "0"
    updated = _update_todo_row(script_path, today, col8="🔄 作業中")
    if updated:
        print(f"  📋 TODO.md 更新: #{num_str} 状態 → 🔄 作業中")


def _update_todo_scheduled(script_path: Path, publish_jst: datetime) -> None:
    """アップロード完了時に TODO.md の 📅 列と状態列を更新する。"""
    label = f"📅 {publish_jst.strftime('%m/%d %H:%M')} 予約"
    today = publish_jst.strftime("%Y-%m-%d")
    stem    = script_path.stem
    num_str = stem.split("_")[0].lstrip("0") or "0"
    updated = _update_todo_row(script_path, today, col7=label, col8="📅 YT予約済")
    if updated:
        print(f"  📋 TODO.md 更新: #{num_str} ④YouTube → {label}")
    else:
        print(f"  ⚠ TODO.md: #{num_str} の行が見つかりませんでした（手動で更新してください）")


def _find_video(script_path: Path) -> Path:
    slug    = script_path.stem
    out_dir = OUTPUT_DIR / slug

    if not out_dir.exists():
        raise FileNotFoundError(
            f"出力フォルダが見つかりません: {out_dir}\n"
            "先に pipeline.py で動画を生成してください。"
        )

    candidates = sorted(out_dir.glob("final_output_youtube*.mp4"))
    if not candidates:
        candidates = sorted(out_dir.glob("final_output*.mp4"))
    if not candidates:
        raise FileNotFoundError(f"MP4 ファイルが見つかりません: {out_dir}")

    return candidates[-1]


# ─── アップロード ─────────────────────────────────────────────────────────────

def upload(script_path: Path, schedule: str, video_path: Path | None = None) -> str:
    """動画を YouTube にスケジュール投稿（下書き保存）する。返値は動画 ID。

    schedule: 'YYYY-MM-DD HH:MM' 形式の日本時間
    """
    script = json.loads(script_path.read_text(encoding="utf-8"))

    if video_path is None:
        video_path = _find_video(script_path)

    publish_at_utc = parse_schedule(schedule)
    publish_jst    = datetime.fromisoformat(publish_at_utc.replace("Z", "+00:00")).astimezone(JST)

    _update_todo_in_progress(script_path)

    print(f"📹 動画: {video_path}")
    print(f"📝 台本: {script_path.name}")
    print(f"📅 公開日時: {publish_jst.strftime('%Y-%m-%d %H:%M')} JST")

    # youtube_meta.txt があればそこの解決済みタイトルを優先（{count}が置換済み）
    meta_txt = video_path.parent / "youtube_meta.txt"
    if meta_txt.exists():
        lines = meta_txt.read_text(encoding="utf-8").splitlines()
        title = _make_title(script.get("title", ""), script.get("scenes", []))
        for i, line in enumerate(lines):
            if "タイトル" in line and "━" in line:
                # 次の非空行がタイトル
                for candidate in lines[i + 1:]:
                    if candidate.strip():
                        title = candidate.strip()
                        break
                break
    else:
        title = _make_title(script.get("title", ""), script.get("scenes", []))
    credits     = video_path.parent / "credits.json"
    description = _make_description(script, credits if credits.exists() else None)
    tags        = _build_tags(script)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24",
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": "private",      # 下書き保存
            "publishAt": publish_at_utc,     # この時刻に自動公開
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    service = build("youtube", "v3", credentials=_get_credentials())
    media   = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,
    )

    print(f"\n🚀 アップロード開始: {title}")
    request  = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"\r  進捗: {pct}%  ", end="", flush=True)
    except HttpError as e:
        print(f"\n❌ アップロードエラー: {e}")
        raise

    print()
    video_id = response["id"]
    url      = f"https://www.youtube.com/watch?v={video_id}"
    (video_path.parent / "youtube_video_id.txt").write_text(video_id, encoding="utf-8")
    print(f"✅ アップロード完了！下書き保存されました。")
    print(f"   URL: {url}")
    print(f"   タイトル: {title}")
    print(f"   公開予定: {publish_jst.strftime('%Y-%m-%d %H:%M')} JST に自動公開")

    _update_todo_scheduled(script_path, publish_jst)
    return video_id


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube ショート スケジュール投稿")
    parser.add_argument("--auth",     action="store_true", help="初回 OAuth 認証を実行する")
    parser.add_argument("--script",   type=Path,           help="台本 JSON ファイルのパス")
    parser.add_argument("--schedule", type=str,            help="公開日時（JST）例: '2026-06-28 20:00'")
    parser.add_argument("--video",    type=Path,           help="動画ファイルを直接指定（省略時は自動検索）")
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

    if not args.schedule:
        print("❌ --schedule で公開日時を指定してください。")
        print("   例: --schedule '2026-06-28 20:00'")
        sys.exit(1)

    upload(args.script, args.schedule, args.video)


if __name__ == "__main__":
    main()
