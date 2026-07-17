"""素材収集ツール（material-collector スキルの裏方スクリプト）。

Pexels API + DuckDuckGo Web検索で画像候補を取得し、1枚のコンタクトシートに
まとめる。Claude Code セッション内でこれを見て採否・説明・タグを判断し、
--commit で assets/materials/<subject>/ に登録する（この2段階はセットで使う）。

このツールは「素材ライブラリを充実させる」ためだけに使う。
動画生成パイプライン(pipeline.py)はここでのWeb/API取得を直接使わず、
できあがったライブラリ（assets/materials/）のみを参照する。

Usage:
    # 1. 候補取得 + コンタクトシート生成
    python src/collect_materials.py fetch \\
        --query-en "Tower of Terror DisneySea dark elevator" \\
        --query-ja "タワー・オブ・テラー 内部 暗闇" \\
        --label tower_of_terror --n 8

    # 2. Claude がコンタクトシートを見て採用を決めたら、1件ずつ登録
    python src/collect_materials.py commit \\
        --staged assets/work/collect_staging/tower_of_terror/px_2.jpg \\
        --subject tower_of_terror \\
        --filename elevator_dark_interior.jpg \\
        --description "タワー・オブ・テラーのエレベーター内部、暗闇に浮かぶ非常灯" \\
        --tags "タワー・オブ・テラー,エレベーター,暗闇,内部" \\
        --source Pexels
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import ROOT, load_config
from images import StockImageProvider, WebScrapeProvider

import materials

STAGING_DIR = ROOT / "assets" / "work" / "collect_staging"


def fetch_candidates(query_en: str, query_ja: str, n: int, out_dir: Path) -> list[dict]:
    cfg = load_config()
    w, h = cfg["video"]["width"], cfg["video"]["height"]
    pexels = StockImageProvider(width=w, height=h)
    scraper = WebScrapeProvider(width=w, height=h)

    cands: list[dict] = []
    if query_en:
        print(f"▶ Pexels「{query_en[:50]}」…")
        cands += pexels.fetch_candidates({"id": 0, "image_query": query_en}, out_dir, n, suffix="_px")
    if query_ja:
        print(f"▶ Web「{query_ja[:50]}」…")
        cands += scraper.fetch_candidates({"id": 0, "scrape_query": query_ja}, out_dir, n, suffix="_web")
    return cands


def build_sheet(cands: list[dict], out_path: Path, cols: int = 4, tile_w: int = 220) -> Path | None:
    """候補を1枚のラベル付きグリッド画像にまとめる（Vision採否判断用）。"""
    tiles: list[tuple[str, Image.Image]] = []
    px_i = web_i = 0
    for c in cands:
        p = Path(c["path"])
        if not p.exists():
            continue
        try:
            img = Image.open(p).convert("RGB")
        except Exception:
            continue
        if c.get("source") == "Pexels":
            label = f"px{px_i}"
            px_i += 1
        else:
            label = f"web{web_i}"
            web_i += 1
        tiles.append((label, img))

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


def cmd_fetch(args: argparse.Namespace) -> None:
    out_dir = STAGING_DIR / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    cands = fetch_candidates(args.query_en, args.query_ja, args.n, out_dir)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")

    sheet_path = out_dir / "contact_sheet.jpg"
    built = build_sheet(cands, sheet_path)

    print(f"✅ {len(cands)}件取得 → {manifest_path}")
    if built:
        print(f"   コンタクトシート: {built}")
        print("   ラベル(px0, web0 等)は manifest.json の順序（Pexels→Web）に対応。")
    else:
        print("   [warn] 候補が0件のためコンタクトシートは生成されませんでした。")


def cmd_commit(args: argparse.Namespace) -> None:
    staged = Path(args.staged)
    if not staged.exists():
        raise SystemExit(f"素材が見つかりません: {staged}")

    subject_dir = materials.MATERIALS_DIR / args.subject
    subject_dir.mkdir(parents=True, exist_ok=True)
    dst = subject_dir / args.filename
    shutil.copy2(staged, dst)

    credit = json.loads(args.credit_json) if args.credit_json else {}
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    materials.add_entry(
        subject_dir, args.filename,
        description=args.description,
        tags=tags,
        type_="image",
        source=args.source or "user",
        credit=credit,
    )
    materials.rebuild_index()
    print(f"✅ 追加: {dst}")
    print(f"   説明: {args.description}")
    print(f"   タグ: {', '.join(tags)}")


def main() -> None:
    p = argparse.ArgumentParser(description="素材収集ツール（material-collector スキルの裏方）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="Pexels/Web検索で候補を取得しコンタクトシートを作る")
    pf.add_argument("--query-en", default="", help="Pexels検索クエリ（英語）")
    pf.add_argument("--query-ja", default="", help="Web検索クエリ（日本語・具体的に）")
    pf.add_argument("--n", type=int, default=8, help="各ソースの取得件数")
    pf.add_argument("--label", required=True, help="ステージングフォルダ名（英語スラッグ）")
    pf.set_defaults(func=cmd_fetch)

    pc = sub.add_parser("commit", help="採用した1枚を素材ライブラリに登録する")
    pc.add_argument("--staged", required=True, help="ステージング済み画像のパス")
    pc.add_argument("--subject", required=True, help="assets/materials/<subject>/ のスラッグ")
    pc.add_argument("--filename", required=True, help="登録後のファイル名")
    pc.add_argument("--description", required=True, help="内容の説明（日本語）")
    pc.add_argument("--tags", required=True, help="カンマ区切りのタグ")
    pc.add_argument("--source", default=None, help="出典 (Pexels / DuckDuckGo/Web 等)")
    pc.add_argument("--credit-json", default=None, help="帰属情報のJSON文字列（Pexels等）")
    pc.set_defaults(func=cmd_commit)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
