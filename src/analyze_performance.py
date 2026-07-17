"""YouTube動画パフォーマンス分析 → ナレッジ蓄積スクリプト。

Usage:
    python src/analyze_performance.py

チャンネルの投稿済み動画一覧(uploadsプレイリスト)を取得し、scripts/*.json と
突き合わせて YouTube Analytics API から各動画のライフタイム成績を取得する。
タイトルの型(保存版・数字選・ネガティブフック・ショックワード)やカテゴリ・
シーン数と成績を集計し、.claude/memory/analytics_insights.md にナレッジとして
書き出す(script-writer スキルが次回の台本生成前に参照する)。

初回はチャンネルの動画とscriptsのタイトル文字列で突き合わせ、一致したものは
output/{slug}/youtube_video_id.txt にキャッシュする(以後はキャッシュを優先)。
新規アップロードは upload.py が同ファイルを直接書き出すため、突き合わせ不要になる。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, ROOT, SCRIPTS_DIR
from youtube_meta import _make_title, read_resolved_title

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("YouTube API ライブラリが未インストールです。")
    print("pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)

from youtube_analytics import CORE_METRICS, _get_credentials

JST = timezone(timedelta(hours=9))
MEMORY_DIR = ROOT / ".claude" / "memory"
INSIGHTS_PATH = MEMORY_DIR / "analytics_insights.md"
MEMORY_INDEX_PATH = MEMORY_DIR / "MEMORY.md"

# 判定順=優先順位（先にマッチしたカテゴリが採用される）。
# 2026-07-11 のナラティブ型39本の手動分析で「その他」に44%が溜まっていたのを分解し、
# 新カテゴリ（VIP・特権系／技術メカニズム解説／海外比較系）を追加した。
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "VIP・特権系": ["特典", "ラウンジ", "貸切", "貸し切る", "年パス", "秘密の部屋", "ザ・クラス", "JCB"],
    "海外比較系": ["外国人", "世界のマニア", "嫉妬"],
    "都市伝説・怖い話": ["都市伝説", "怖い", "監視", "秘密結社", "闇", "呪い", "殺人鬼", "花嫁", "謎"],
    "技術メカニズム解説": ["運営の裏側", "レールがない", "変態的な仕組み", "壊れたロボット", "トラックレス"],
    "心理・行動デザイン": ["心理", "動線", "洗脳", "トリック", "錯覚", "デザイン", "BGM", "涙腺", "鳥肌", "勘違い", "ハッキング"],
    "アトラクション考察": ["アトラクション", "ライド", "乗り物", "ツアーズ", "マンション", "タワー", "アクアトピア"],
    "キャラクター考察": ["ミッキー", "ベイマックス", "モンスターズ", "トイ・ストーリー", "ラプンツェル", "ピーターパン", "美女と野獣"],
    "最新情報・速報": ["速報", "周年", "新作", "夏の", "終了"],
}


# ─── 動画発見・突き合わせ ─────────────────────────────────────────────────────

# {count}プレースホルダーの解決結果は生成タイミングによってズレることがある
# （例:「5つの真実」で生成→最終的なシーン数変化で実際は「2つの真実」でアップロード）。
# 突き合わせ時はこの部分を無視して比較する。
_COUNT_PATTERN = re.compile(r"(\{count\}|[0-9〇◯]+)(選|つの|個)")


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", _COUNT_PATTERN.sub("", title))


def _list_channel_uploads(youtube) -> dict[str, dict]:
    """自チャンネルの全アップロード動画を {video_id: {title, uploaded_at, privacy_status}} で返す。"""
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return {}
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos: dict[str, dict] = {}
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            playlistId=uploads_playlist,
            part="snippet,status",
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp.get("items", []):
            snippet = item["snippet"]
            video_id = snippet["resourceId"]["videoId"]
            videos[video_id] = {
                "title": snippet["title"],
                # プレイリストへの追加(=アップロード)日時。予約投稿の公開日時ではない。
                "uploaded_at": snippet["publishedAt"],
                "privacy_status": item.get("status", {}).get("privacyStatus", "unknown"),
            }
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return videos


def _resolve_video_id(
    out_dir: Path,
    script: dict,
    title_to_id: dict[str, str],
    normalized_title_to_id: dict[str, str],
) -> str | None:
    cache_path = out_dir / "youtube_video_id.txt"
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    candidates = []
    resolved = read_resolved_title(out_dir / "youtube_meta.txt")
    if resolved:
        candidates.append(resolved)
    # youtube_meta.txt が無い/古い場合、upload.py 自身のフォールバックと同じロジックで再現する
    candidates.append(_make_title(script.get("title", ""), script.get("scenes", [])))

    for cand in candidates:
        video_id = title_to_id.get(cand)
        if video_id:
            cache_path.write_text(video_id, encoding="utf-8")
            return video_id

    for cand in candidates:
        video_id = normalized_title_to_id.get(_normalize_title(cand))
        if video_id:
            cache_path.write_text(video_id, encoding="utf-8")
            return video_id

    return None


# ─── 特徴量抽出 ───────────────────────────────────────────────────────────────

def extract_title_features(title: str) -> dict[str, bool]:
    return {
        "保存版タグ": "保存版" in title,
        "数字+選/つの": bool(re.search(r"[0-9〇◯]+(選|つの|個)", title)),
        "ネガティブフック": any(w in title for w in ["絶対", "禁止", "知らないと損", "後悔", "厳禁"]),
        "ショックワード": any(w in title for w in ["ヤバい", "衝撃", "驚愕", "怖い", "闇", "洗脳", "残酷"]),
        "疑問形": "？" in title or "?" in title,
    }


def infer_category(title: str, theme: str) -> str:
    text = f"{title} {theme}"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "その他"


# ─── データ収集 ───────────────────────────────────────────────────────────────

def _fetch_lifetime_stats(analytics, video_id: str, start: str, end: str) -> dict | None:
    try:
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics=",".join(CORE_METRICS),
            filters=f"video=={video_id}",
        ).execute()
    except HttpError:
        return None
    rows = resp.get("rows")
    if not rows:
        return None
    return dict(zip(CORE_METRICS, rows[0]))


def collect_records() -> tuple[list[dict], dict[str, list[str]]]:
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)

    uploads = _list_channel_uploads(youtube)
    title_to_id = {v["title"]: vid for vid, v in uploads.items()}
    normalized_title_to_id = {_normalize_title(v["title"]): vid for vid, v in uploads.items()}
    yesterday = (datetime.now(JST).date() - timedelta(days=1)).isoformat()

    diagnostics: dict[str, list[str]] = {
        "no_output": [],          # output/ フォルダ自体が無い(未生成)
        "not_uploaded_yet": [],   # YouTube用動画はあるがまだアップロードしていない
        "video_id_not_found": [], # アップロード済のはずだが動画IDを特定できない(要確認)
        "scheduled_private": [],  # 予約投稿でまだ非公開
        "analytics_pending": [],  # 公開済みだがAnalyticsデータがまだ反映されていない
        "matched": [],            # 分析対象になった
    }

    records: list[dict] = []
    for script_path in sorted(SCRIPTS_DIR.glob("*.json")):
        slug = script_path.stem
        out_dir = OUTPUT_DIR / slug
        if not out_dir.exists():
            diagnostics["no_output"].append(slug)
            continue

        has_youtube_asset = any(out_dir.glob("final_output_youtube*.mp4"))
        if not has_youtube_asset:
            diagnostics["not_uploaded_yet"].append(slug)
            continue

        script = json.loads(script_path.read_text(encoding="utf-8"))
        video_id = _resolve_video_id(out_dir, script, title_to_id, normalized_title_to_id)
        if not video_id or video_id not in uploads:
            diagnostics["video_id_not_found"].append(slug)
            continue

        info = uploads[video_id]
        if info["privacy_status"] == "private":
            diagnostics["scheduled_private"].append(slug)
            continue

        start_date = min(info["uploaded_at"][:10], yesterday)
        stats = _fetch_lifetime_stats(analytics, video_id, start_date, yesterday)
        if not stats or not stats.get("views"):
            diagnostics["analytics_pending"].append(slug)
            continue

        scenes = script.get("scenes", [])
        theme = script.get("meta", {}).get("theme", slug)
        total_chars = sum(len(s.get("narration", "")) for s in scenes)
        views = stats["views"]

        records.append({
            "slug": slug,
            "title": info["title"],
            "theme": theme,
            "category": infer_category(info["title"], theme),
            "scene_count": len(scenes),
            "narration_chars": total_chars,
            "est_duration_sec": round(total_chars / 7.5, 1),
            "title_features": extract_title_features(info["title"]),
            "engagement_rate": round(
                (stats["likes"] + stats["comments"] + stats["shares"]) / views, 4
            ) if views else 0,
            **stats,
        })
        diagnostics["matched"].append(slug)
    return records, diagnostics


# ─── 集計 ─────────────────────────────────────────────────────────────────────

def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _feature_breakdown(records: list[dict]) -> list[dict]:
    feature_names = list(records[0]["title_features"].keys()) if records else []
    breakdown = []
    for name in feature_names:
        with_feature = [r for r in records if r["title_features"][name]]
        without_feature = [r for r in records if not r["title_features"][name]]
        breakdown.append({
            "feature": name,
            "n_with": len(with_feature),
            "n_without": len(without_feature),
            "retention_with": _avg([r["averageViewPercentage"] for r in with_feature]),
            "retention_without": _avg([r["averageViewPercentage"] for r in without_feature]),
            "views_with": _avg([r["views"] for r in with_feature]),
            "views_without": _avg([r["views"] for r in without_feature]),
        })
    return breakdown


def _category_breakdown(records: list[dict]) -> list[dict]:
    categories = sorted({r["category"] for r in records})
    result = []
    for cat in categories:
        rows = [r for r in records if r["category"] == cat]
        result.append({
            "category": cat,
            "n": len(rows),
            "avg_retention": _avg([r["averageViewPercentage"] for r in rows]),
            "avg_views": _avg([r["views"] for r in rows]),
        })
    return sorted(result, key=lambda r: r["avg_retention"], reverse=True)


def _generate_suggestions(feature_breakdown: list[dict], category_breakdown: list[dict]) -> list[dict]:
    """データに基づく提言をリテンション差が大きい順に生成する(N>=2/群のみ採用)。"""
    candidates = []
    for fb in feature_breakdown:
        if fb["n_with"] >= 2 and fb["n_without"] >= 2:
            delta = fb["retention_with"] - fb["retention_without"]
            candidates.append({
                "kind": "title_feature",
                "label": fb["feature"],
                "delta": delta,
                "detail": (
                    f"「{fb['feature']}」あり(n={fb['n_with']})の平均視聴率 {fb['retention_with']}% / "
                    f"なし(n={fb['n_without']})の平均視聴率 {fb['retention_without']}%"
                ),
            })
    candidates.sort(key=lambda c: abs(c["delta"]), reverse=True)
    return candidates[:4]


# ─── Markdown 出力 ────────────────────────────────────────────────────────────

def _render_diagnostics_section(diagnostics: dict[str, list[str]]) -> list[str]:
    total_scripts = sum(len(v) for v in diagnostics.values())
    lines = [
        "## 対象外の内訳（透明性のため毎回記載）",
        "",
        f"scripts/ 内の全 {total_scripts} 本のうち、今回の分析対象になったのは "
        f"{len(diagnostics['matched'])} 本。残りの内訳:",
        "",
    ]
    labels = {
        "not_uploaded_yet": "YouTube未アップロード（X/TikTok版のみ、または制作中）",
        "scheduled_private": "予約投稿でまだ非公開（公開後に自動で取り込まれる）",
        "analytics_pending": "公開済みだがAnalyticsデータ未反映（1〜2日後に自動で取り込まれる）",
        "video_id_not_found": "動画IDを特定できず要確認（タイトル不一致・削除された可能性）",
        "no_output": "output/ 未生成（台本のみ）",
    }
    for key, label in labels.items():
        slugs = diagnostics.get(key, [])
        if not slugs:
            continue
        lines.append(f"- **{label}**: {len(slugs)}本 — {', '.join(slugs)}")
    lines.append("")
    return lines


def render_insights_md(records: list[dict], diagnostics: dict[str, list[str]] | None = None) -> str:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    diagnostics = diagnostics or {}

    if not records:
        diag_lines = _render_diagnostics_section(diagnostics) if diagnostics else []
        diag_block = "\n".join(diag_lines)
        return f"""---
name: analytics-insights
description: YouTube Analyticsから得た動画パフォーマンスの知見。台本生成前に必ず参照する。
metadata:
  type: project
---

# YouTube動画パフォーマンス分析ナレッジ

最終更新: {today}

まだ分析対象の動画データがありません(公開済み動画がないか、Analytics反映待ちの可能性があります)。
`python src/analyze_performance.py` を動画公開後に再実行してください。

{diag_block}
"""

    n = len(records)
    avg_retention = _avg([r["averageViewPercentage"] for r in records])
    avg_views = _avg([r["views"] for r in records])
    avg_engagement = _avg([r["engagement_rate"] for r in records])

    by_retention = sorted(records, key=lambda r: r["averageViewPercentage"], reverse=True)
    top3 = by_retention[:3]
    bottom3 = by_retention[-3:] if n >= 4 else []

    feature_breakdown = _feature_breakdown(records)
    category_breakdown = _category_breakdown(records)
    suggestions = _generate_suggestions(feature_breakdown, category_breakdown)

    lines = [
        "---",
        "name: analytics-insights",
        "description: YouTube Analyticsから得た動画パフォーマンスの知見。台本生成前に必ず参照する。",
        "metadata:",
        "  type: project",
        "---",
        "",
        "# YouTube動画パフォーマンス分析ナレッジ",
        "",
        f"最終更新: {today}（分析対象: 公開済み動画 {n}本、`python src/analyze_performance.py` で自動更新）",
        "",
        *(_render_diagnostics_section(diagnostics) if diagnostics else []),
        "## 全体サマリー",
        "",
        f"- 平均視聴率(averageViewPercentage): {avg_retention}%",
        f"- 平均再生回数: {avg_views:,.0f}",
        f"- 平均エンゲージメント率((高評価+コメント+シェア)/再生数): {avg_engagement}",
        "",
        "## 視聴率トップ3",
        "",
    ]
    for r in top3:
        lines.append(
            f"- **{r['title']}** — 視聴率 {r['averageViewPercentage']}% / 再生 {r['views']:,} "
            f"/ シーン数 {r['scene_count']} / カテゴリ: {r['category']}"
        )

    if bottom3:
        lines += ["", "## 視聴率ワースト3", ""]
        for r in bottom3:
            lines.append(
                f"- **{r['title']}** — 視聴率 {r['averageViewPercentage']}% / 再生 {r['views']:,} "
                f"/ シーン数 {r['scene_count']} / カテゴリ: {r['category']}"
            )

    lines += ["", "## カテゴリ別成績", "", "| カテゴリ | 本数 | 平均視聴率 | 平均再生数 |", "|---|---|---|---|"]
    for cb in category_breakdown:
        lines.append(f"| {cb['category']} | {cb['n']} | {cb['avg_retention']}% | {cb['avg_views']:,.0f} |")

    lines += ["", "## タイトル要素別成績", "", "| 要素 | あり(本数/視聴率/再生数) | なし(本数/視聴率/再生数) |", "|---|---|---|"]
    for fb in feature_breakdown:
        lines.append(
            f"| {fb['feature']} | {fb['n_with']}本 / {fb['retention_with']}% / {fb['views_with']:,.0f} "
            f"| {fb['n_without']}本 / {fb['retention_without']}% / {fb['views_without']:,.0f} |"
        )

    lines += ["", "## 台本生成への提言（Why/How to apply）", ""]
    if suggestions:
        for s in suggestions:
            direction = "効果あり→積極的に使う" if s["delta"] > 0 else "逆効果の可能性→多用を避ける"
            lines.append(f"- **{s['label']}**: {direction}")
            lines.append(f"  - Why: {s['detail']}（視聴率差 {round(s['delta'], 2)}pt）")
            lines.append(
                f"  - How to apply: 台本タイトル・フック設計時に「{s['label']}」の採否を、"
                f"上記の視聴率差を踏まえて判断する。件数が少ないうちは参考程度に留める。"
            )
    else:
        lines.append("- データがまだ少なく、有意な差が出せる比較がありません。動画数が増えたら再実行してください。")

    lines += [
        "",
        "## 注意",
        "",
        "- サンプル数が少ない（本数が一桁〜十数本）ため、統計的な確度は高くありません。傾向の参考値として扱うこと。",
        "- `python src/analyze_performance.py` を新しい動画公開後に再実行すると自動で更新される。",
        "",
    ]
    return "\n".join(lines) + "\n"


def _ensure_memory_index_entry() -> None:
    if not MEMORY_INDEX_PATH.exists():
        return
    content = MEMORY_INDEX_PATH.read_text(encoding="utf-8")
    if "analytics_insights.md" in content:
        return
    entry = (
        "- [YouTube動画パフォーマンス分析ナレッジ](analytics_insights.md) — "
        "視聴率・タイトル型・カテゴリ別の成績を自動集計。台本生成前に必ず参照する\n"
    )
    MEMORY_INDEX_PATH.write_text(content.rstrip("\n") + "\n" + entry, encoding="utf-8")


def main() -> None:
    print("📡 チャンネルの動画一覧とAnalyticsデータを取得中...")
    try:
        records, diagnostics = collect_records()
    except HttpError as e:
        print(f"❌ API エラー: {e}")
        sys.exit(1)

    md = render_insights_md(records, diagnostics)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    INSIGHTS_PATH.write_text(md, encoding="utf-8")
    _ensure_memory_index_entry()

    print(f"✅ {len(records)}本の動画を分析し、{INSIGHTS_PATH} を更新しました。")
    for key in ("not_uploaded_yet", "scheduled_private", "analytics_pending", "video_id_not_found", "no_output"):
        if diagnostics.get(key):
            print(f"   除外({key}): {len(diagnostics[key])}本")
    if records:
        avg_retention = _avg([r["averageViewPercentage"] for r in records])
        print(f"   全体平均視聴率: {avg_retention}%")


if __name__ == "__main__":
    main()
