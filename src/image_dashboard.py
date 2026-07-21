"""画像候補取得モジュール。

各シーンの候補を (1) assets/materials/ の素材ライブラリ、(2) Web検索(DuckDuckGo)の
毎回のライブ検索、の両方から取得し、シーンごとのコンタクトシート（候補を1枚のグリッド
画像にまとめたもの）を生成する。Claudeがこのコンタクトシートを見て1シーン1枚選定し、
output/<theme>/image_selections.json を書き出すフローで使う（確認ダッシュボードは
2026-07-18に廃止。画像の良し悪しは完成動画を見て判断し、必要なシーンだけ差し替える）。

素材ライブラリは再利用可能な既知コンテンツの高速な供給源、Web検索は
そのシーン特有の意図（scrape_query）を汲み取った新規候補の供給源として併用する。
気に入った素材フォルダ由来でない画像を繰り返し使う場合は material-collector スキルで
ライブラリに登録すると次回以降ライブラリからも見つかるようになる。

Usage:
    python src/image_dashboard.py --script scripts/xxx.json --fetch-only
    → assets/work/candidates/<stem>/ に manifest.json とコンタクトシートを生成

Pipeline との連携:
    python src/pipeline.py --script scripts/xxx.json \\
        --selections output/<theme>/image_selections.json
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import ROOT, load_config
from images import WebScrapeProvider
from materials import index_blob, load_index

WEB_CANDIDATES_N = 6      # Web検索(DuckDuckGo)候補枚数（トークン節約のため10→6に削減。2026-07-19）
MATERIALS_MAX_IMG = 10    # 素材ライブラリ画像候補の上限（タグ一致数上位のみ。無制限だとコンタクトシートが肥大化）
MATERIALS_MAX_VIDEO = 5   # 素材ライブラリ動画候補の上限

_SHEET_ORDER: list[tuple[str, str]] = [
    ("materials", "cands_materials"),
    ("materials_video", "cands_materials_video"),
    ("web", "cands_web"),
]
MANIFEST_NAME = "manifest.json"


# ─── 素材フォルダ (assets/materials/) とのマッチング ───────────────────────────

def _scene_blob(script: dict, scene: dict) -> str:
    """シーン・台本のテキストを結合した検索用blob（素材とのマッチングに使う）。"""
    meta = script.get("meta", {})
    parts = [
        script.get("title", ""),
        meta.get("subject", ""),
        meta.get("subject_en", ""),
        scene.get("image_query", ""),
        scene.get("scrape_query", ""),
        scene.get("narration", ""),
        " ".join(scene.get("keywords", [])),
    ]
    return " ".join(parts).lower()


def match_materials(blob: str, index: list[dict]) -> tuple[list[dict], list[dict]]:
    """index.json（集約インデックス）の全エントリを blob とマッチングし、
    画像候補(cands_materials)・動画候補(cands_materials_video)を返す。

    タグ一致数でスコアリングし、上位 MATERIALS_MAX_IMG / MATERIALS_MAX_VIDEO 件のみ返す
    （無制限に返すとコンタクトシートが肥大化しVisionトークンを消費しすぎるため）。
    """
    img_scored: list[tuple[int, dict]] = []
    vid_scored: list[tuple[int, dict]] = []
    for entry in index:
        tags = [t.lower() for t in entry.get("tags", [])] + [entry.get("subject", "").replace("_", " ").lower()]
        score = sum(1 for tag in tags if tag and tag in blob)
        if score == 0:
            continue
        cand = {
            "path":        entry["path"],
            "query":       f"{entry['subject']}: {entry.get('description', '')[:40]}",
            "source":      entry.get("source", "materials"),
            "description": entry.get("description", ""),
            "credit":      entry.get("credit", {}),
        }
        if entry.get("type") == "video" or Path(entry["path"]).suffix.lower() == ".mp4":
            vid_scored.append((score, {**cand, "type": "video"}))
        else:
            img_scored.append((score, cand))
    img_scored.sort(key=lambda x: x[0], reverse=True)
    vid_scored.sort(key=lambda x: x[0], reverse=True)
    img_cands = [c for _, c in img_scored[:MATERIALS_MAX_IMG]]
    vid_cands = [c for _, c in vid_scored[:MATERIALS_MAX_VIDEO]]
    return img_cands, vid_cands


def fetch_all_candidates(script: dict, out_dir: Path) -> dict[int, dict]:
    """全シーンについて素材ライブラリ＋Web検索(DuckDuckGo)の候補を返す。

    素材ライブラリは assets/materials/index.json（集約インデックス）を参照する
    （呼び出し前に必ず再生成して最新化する）。Web検索は毎回そのシーンの
    scrape_query でライブに取得し、シーン特有の意図を汲み取った候補を補う。
    """
    result: dict[int, dict] = {}
    index = load_index()
    cfg = load_config()
    w, h = cfg["video"]["width"], cfg["video"]["height"]
    scraper = WebScrapeProvider(width=w, height=h)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"▶ 候補取得中 ({len(script['scenes'])}シーン / 素材インデックス{len(index)}件 + Web検索)…")
    for scene in script["scenes"]:
        sid = scene["id"]
        blob = _scene_blob(script, scene)
        cands_materials, cands_materials_video = match_materials(blob, index)

        web_q = scene.get("scrape_query") or scene.get("image_query") or ""
        print(f"  scene {sid}: 素材{len(cands_materials) + len(cands_materials_video)}件 / Web「{web_q[:30]}」…")
        cands_web = scraper.fetch_candidates(scene, out_dir, WEB_CANDIDATES_N, suffix="_web")

        n = len(cands_materials) + len(cands_materials_video) + len(cands_web)
        mark = "" if n else "  ⚠️ 候補なし"
        if mark:
            print(f"    {mark}")
        result[sid] = {
            "cands_materials":       cands_materials,
            "cands_materials_video": cands_materials_video,
            "cands_web":             cands_web,
        }
    return result


# ─── Vision自動選定 (マニフェスト・コンタクトシート) ────────────────────────────

def save_manifest(candidates_by_scene: dict[int, dict], img_dir: Path) -> Path:
    manifest_path = img_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps({str(k): v for k, v in candidates_by_scene.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _video_frame(path: Path) -> "Image.Image | None":
    """ffmpeg で動画の先頭フレームを抽出してPIL Imageで返す。"""
    tmp = path.with_suffix(".thumbframe.jpg")
    res = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-vframes", "1", "-q:v", "3", str(tmp)],
        capture_output=True,
    )
    if res.returncode == 0 and tmp.exists():
        try:
            img = Image.open(tmp).convert("RGB")
            img.load()
        finally:
            tmp.unlink(missing_ok=True)
        return img
    return None


def build_contact_sheet(data: dict, out_path: Path, cols: int = 4, tile_w: int = 150) -> Path | None:
    """1シーン分の全候補を、ラベル付きグリッド画像1枚にまとめる（Vision選定用）。"""
    tiles: list[tuple[str, "Image.Image"]] = []
    for prefix, key in _SHEET_ORDER:
        for i, c in enumerate(data.get(key, []) or []):
            p = Path(c["path"])
            if not p.exists():
                continue
            try:
                img = _video_frame(p) if p.suffix.lower() == ".mp4" else Image.open(p).convert("RGB")
            except Exception:
                continue
            if img is None:
                continue
            tiles.append((f"{prefix}{i}", img))

    if not tiles:
        return None

    tile_h = int(tile_w * 16 / 9)
    label_h = 26
    cols_n = min(cols, len(tiles))
    rows = math.ceil(len(tiles) / cols_n)
    sheet = Image.new("RGB", (cols_n * tile_w, rows * (tile_h + label_h)), (20, 20, 30))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(ROOT / "assets/fonts/NotoSansJP-Bold.ttf"), 18)
    except Exception:
        font = ImageFont.load_default()

    for idx, (label, img) in enumerate(tiles):
        r, c = divmod(idx, cols_n)
        x, y = c * tile_w, r * (tile_h + label_h)
        thumb = img.copy()
        thumb.thumbnail((tile_w, tile_h))
        ox = x + (tile_w - thumb.width) // 2
        oy = y + (tile_h - thumb.height) // 2
        sheet.paste(thumb, (ox, oy))
        draw.rectangle([x, y + tile_h, x + tile_w, y + tile_h + label_h], fill=(10, 10, 16))
        draw.text((x + 6, y + tile_h + 4), label, fill=(255, 220, 80), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=85)
    return out_path


def fetch_only(script_path: str | Path) -> tuple[Path, dict[int, Path]]:
    """素材ライブラリ＋Web検索の候補取得とコンタクトシート生成のみ行う（ブラウザは開かない）。

    候補0件のシーンがあれば警告を表示する。
    """
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    folder = Path(script_path).stem

    img_dir = ROOT / "assets" / "work" / "candidates" / folder
    img_dir.mkdir(parents=True, exist_ok=True)

    candidates_by_scene = fetch_all_candidates(script, img_dir)
    manifest_path = save_manifest(candidates_by_scene, img_dir)

    sheets: dict[int, Path] = {}
    empty_scenes: list[int] = []
    for scene in script["scenes"]:
        sid = scene["id"]
        data = candidates_by_scene.get(sid, {})
        if not data.get("cands_materials") and not data.get("cands_materials_video") and not data.get("cands_web"):
            empty_scenes.append(sid)
            continue
        sheet_path = img_dir / f"contact_s{sid:02d}.jpg"
        built = build_contact_sheet(data, sheet_path)
        if built:
            sheets[sid] = built

    print(f"✅ マッチング完了 → {manifest_path}")
    print(f"   コンタクトシート ({len(sheets)}枚):")
    for sid, p in sorted(sheets.items()):
        print(f"     scene {sid}: {p}")
    if empty_scenes:
        print(f"⚠️  候補が0件のシーン: {', '.join(str(s) for s in empty_scenes)}")
        print("   material-collector スキルで assets/materials/ に素材を追加してから再実行してください。")
    return manifest_path, sheets


# ─── エントリポイント ─────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="画像候補取得（素材ライブラリ＋Web検索）")
    p.add_argument("--script", required=True, help="台本 JSON のパス")
    p.add_argument("--fetch-only", action="store_true",
                   help="（互換性のため残置。指定の有無に関わらず候補取得のみ行う）")
    args = p.parse_args()
    fetch_only(args.script)


if __name__ == "__main__":
    main()
