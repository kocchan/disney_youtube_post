"""YouTube Analytics 取得スクリプト。

Usage:
    # 初回認証（ブラウザが開く・1回だけ。upload.py の認証とは別トークン）
    python src/youtube_analytics.py --auth

    # チャンネル全体のサマリー（直近28日）
    python src/youtube_analytics.py --days 28

    # 動画別ランキング（再生数順）
    python src/youtube_analytics.py --days 28 --top 10

    # 特定動画の詳細
    python src/youtube_analytics.py --video <VIDEO_ID> --days 28

    # JSON で出力（他ツールに渡す用）
    python src/youtube_analytics.py --days 28 --top 10 --json

データは通常 1〜2 日遅れで反映される（当日・前日のデータは未確定/欠落することがある）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import ROOT

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("YouTube API ライブラリが未インストールです。")
    print("pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)

from dotenv import set_key

# upload.py の YOUTUBE_REFRESH_TOKEN（youtube.upload スコープのみ）とは
# 別のトークンとして管理する。同じ client_secret.json（OAuthクライアント）を使い回す。
SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
CLIENT_SECRET_PATH = ROOT / "client_secret.json"
DOTENV_PATH = ROOT / ".env"
JST = timezone(timedelta(hours=9))

CORE_METRICS = [
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
]


# ─── 認証 ────────────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    import os

    refresh_token = os.getenv("YOUTUBE_ANALYTICS_REFRESH_TOKEN")
    client_id     = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")

    if not all([refresh_token, client_id, client_secret]):
        print("❌ 認証情報が .env にありません。先に以下を実行してください:")
        print("   python src/youtube_analytics.py --auth")
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
        print("   （upload.py --auth で使っているものと同じファイルです）")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=False
    )

    if not creds.refresh_token:
        print("❌ リフレッシュトークンが取得できませんでした。")
        print("   Google Cloud Console > OAuth同意画面 > テストユーザーに自分のアカウントを追加して再実行してください。")
        sys.exit(1)

    DOTENV_PATH.touch(exist_ok=True)
    set_key(str(DOTENV_PATH), "YOUTUBE_ANALYTICS_REFRESH_TOKEN", creds.refresh_token)

    print()
    print(f"✅ 認証完了。リフレッシュトークンを {DOTENV_PATH} に保存しました。")
    print("   次回から --auth は不要です。")
    print()
    print("   ※ 収益データ（estimatedRevenue等）はチャンネルがAdSenseと連携・")
    print("     収益化されていない場合は取得できません（エラーにはならず空になります）。")


# ─── データ取得 ───────────────────────────────────────────────────────────────

def _date_range(days: int) -> tuple[str, str]:
    """直近 N 日分の (start, end) を 'YYYY-MM-DD' で返す。当日は除く(未確定データのため)。"""
    end = datetime.now(JST).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def fetch_channel_summary(analytics, start: str, end: str) -> dict:
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics=",".join(CORE_METRICS),
    ).execute()

    rows = resp.get("rows") or [[0] * len(CORE_METRICS)]
    values = dict(zip(CORE_METRICS, rows[0]))
    values["startDate"] = start
    values["endDate"] = end
    return values


def fetch_top_videos(analytics, youtube, start: str, end: str, top: int) -> list[dict]:
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics=",".join(CORE_METRICS),
        dimensions="video",
        sort="-views",
        maxResults=top,
    ).execute()

    rows = resp.get("rows") or []
    video_ids = [r[0] for r in rows]
    titles = _resolve_titles(youtube, video_ids)

    results = []
    for row in rows:
        entry = dict(zip(["video", *CORE_METRICS], row))
        entry["title"] = titles.get(entry["video"], "(不明)")
        results.append(entry)
    return results


def fetch_video_detail(analytics, youtube, video_id: str, start: str, end: str) -> dict:
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics=",".join(CORE_METRICS),
        filters=f"video=={video_id}",
    ).execute()

    rows = resp.get("rows") or [[0] * len(CORE_METRICS)]
    values = dict(zip(CORE_METRICS, rows[0]))
    values["video"] = video_id
    values["title"] = _resolve_titles(youtube, [video_id]).get(video_id, "(不明)")
    values["startDate"] = start
    values["endDate"] = end
    return values


def _resolve_titles(youtube, video_ids: list[str]) -> dict[str, str]:
    if not video_ids:
        return {}
    titles: dict[str, str] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = youtube.videos().list(part="snippet", id=",".join(chunk)).execute()
        for item in resp.get("items", []):
            titles[item["id"]] = item["snippet"]["title"]
    return titles


# ─── 表示 ─────────────────────────────────────────────────────────────────────

def _print_summary(values: dict) -> None:
    print(f"\n📊 チャンネルサマリー ({values['startDate']} 〜 {values['endDate']})")
    print(f"   再生回数:         {values['views']:,}")
    print(f"   総再生時間(分):   {values['estimatedMinutesWatched']:,}")
    print(f"   平均視聴時間(秒): {values['averageViewDuration']}")
    print(f"   平均視聴率:       {values['averageViewPercentage']}%")
    print(f"   高評価:           {values['likes']:,}")
    print(f"   コメント:         {values['comments']:,}")
    print(f"   シェア:           {values['shares']:,}")
    print(f"   新規登録者:       {values['subscribersGained']:,}")


def _print_top_videos(results: list[dict]) -> None:
    print(f"\n🏆 動画別ランキング（再生数順・上位{len(results)}件）")
    for i, r in enumerate(results, 1):
        print(f"\n {i}. {r['title']}")
        print(f"    ID: {r['video']}  https://www.youtube.com/watch?v={r['video']}")
        print(f"    再生: {r['views']:,}  視聴時間(分): {r['estimatedMinutesWatched']:,}  "
              f"平均視聴率: {r['averageViewPercentage']}%  高評価: {r['likes']:,}")


def _print_video_detail(values: dict) -> None:
    print(f"\n📹 {values['title']}")
    print(f"   ID: {values['video']}  期間: {values['startDate']} 〜 {values['endDate']}")
    print(f"   再生回数:         {values['views']:,}")
    print(f"   総再生時間(分):   {values['estimatedMinutesWatched']:,}")
    print(f"   平均視聴時間(秒): {values['averageViewDuration']}")
    print(f"   平均視聴率:       {values['averageViewPercentage']}%")
    print(f"   高評価:           {values['likes']:,}")
    print(f"   コメント:         {values['comments']:,}")
    print(f"   シェア:           {values['shares']:,}")
    print(f"   新規登録者:       {values['subscribersGained']:,}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Analytics 取得")
    parser.add_argument("--auth", action="store_true", help="初回 OAuth 認証を実行する")
    parser.add_argument("--days", type=int, default=28, help="集計期間（日数、既定28日）")
    parser.add_argument("--top", type=int, help="動画別ランキングを上位N件表示")
    parser.add_argument("--video", type=str, help="特定動画IDの詳細を表示")
    parser.add_argument("--json", action="store_true", help="JSON で出力する")
    args = parser.parse_args()

    if args.auth:
        do_auth()
        return

    start, end = _date_range(args.days)
    creds = _get_credentials()

    try:
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
        youtube = build("youtube", "v3", credentials=creds)

        if args.video:
            result = fetch_video_detail(analytics, youtube, args.video, start, end)
            print(json.dumps(result, ensure_ascii=False, indent=2)) if args.json else _print_video_detail(result)
        elif args.top:
            result = fetch_top_videos(analytics, youtube, start, end, args.top)
            print(json.dumps(result, ensure_ascii=False, indent=2)) if args.json else _print_top_videos(result)
        else:
            result = fetch_channel_summary(analytics, start, end)
            print(json.dumps(result, ensure_ascii=False, indent=2)) if args.json else _print_summary(result)
    except HttpError as e:
        print(f"❌ API エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
