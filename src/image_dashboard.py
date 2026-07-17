"""画像選択ダッシュボード。

各シーンの候補を (1) assets/materials/ の素材ライブラリ、(2) Web検索(DuckDuckGo)を
毎回のライブ検索、の両方から取得し、ブラウザで表示してユーザーが選んだ画像/動画を
image_selections.json に保存する。

素材ライブラリは再利用可能な既知コンテンツの高速な供給源、Web検索は
そのシーン特有の意図（scrape_query）を汲み取った新規候補の供給源として併用する。
気に入った素材フォルダ由来でない画像を繰り返し使う場合は material-collector スキルで
ライブラリに登録すると次回以降ライブラリからも見つかるようになる。

Usage:
    python src/image_dashboard.py --script scripts/xxx.json
    → ブラウザが開く → 選択 → output/<theme>/image_selections.json を生成

Vision自動選定との連携（--fetch-only / --preselect）:
    1. python src/image_dashboard.py --script scripts/xxx.json --fetch-only
       → 素材ライブラリ＋Web検索の候補取得とコンタクトシート生成を行う
    2. Claude Code セッション内でコンタクトシートを確認し、image_selections.json を書き出す
    3. python src/image_dashboard.py --script scripts/xxx.json --preselect <selections.json>
       → 手順1のキャッシュを再利用し、選定済みセルを事前ハイライトしたダッシュボードを開く
         （ユーザーはワンクリック確認 or 変更できる）

Pipeline との連携:
    python src/pipeline.py --script scripts/xxx.json \\
        --selections output/<theme>/image_selections.json
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, ROOT, load_config
from images import WebScrapeProvider
from materials import MATERIALS_DIR, index_blob, load_index, rebuild_index
from todo_updater import update_todo

WEB_CANDIDATES_N = 10  # Web検索(DuckDuckGo)候補枚数

_server_done: threading.Event = threading.Event()

_VARIANT_MAP: dict[str, str] = {
    "materials":       "cands_materials",
    "materials_video": "cands_materials_video",
    "web":             "cands_web",
}
_SHEET_ORDER: list[tuple[str, str]] = [
    ("materials", "cands_materials"),
    ("materials_video", "cands_materials_video"),
    ("web", "cands_web"),
]
MANIFEST_NAME = "manifest.json"
DIFF_LOG_PATH = ROOT / "assets" / "work" / "image_selection_diffs.jsonl"


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
    画像候補(cands_materials)・動画候補(cands_materials_video)を返す。"""
    img_cands: list[dict] = []
    vid_cands: list[dict] = []
    for entry in index:
        ent_blob = index_blob(entry)
        tags = [t.lower() for t in entry.get("tags", [])] + [entry.get("subject", "").replace("_", " ").lower()]
        if not any(tag and tag in blob for tag in tags):
            continue
        cand = {
            "path":        entry["path"],
            "query":       f"{entry['subject']}: {entry.get('description', '')[:40]}",
            "source":      entry.get("source", "materials"),
            "description": entry.get("description", ""),
            "credit":      entry.get("credit", {}),
        }
        if entry.get("type") == "video" or Path(entry["path"]).suffix.lower() == ".mp4":
            vid_cands.append({**cand, "type": "video"})
        else:
            img_cands.append(cand)
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


def load_manifest(img_dir: Path) -> dict[int, dict] | None:
    manifest_path = img_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    except Exception:
        return None


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


def build_contact_sheet(data: dict, out_path: Path, cols: int = 4, tile_w: int = 220) -> Path | None:
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


def selections_to_preselect(selections: dict, candidates_by_scene: dict[int, dict]) -> dict:
    """image_selections.json の内容から、ダッシュボード事前ハイライト用の
    {sid: {"idx", "path", "variant"}} と thumbnail path を組み立てる。"""
    preselect: dict[int, dict] = {}
    for sid_str, v in selections.items():
        if sid_str == "thumbnail" or not isinstance(v, dict):
            continue
        try:
            sid = int(sid_str)
        except ValueError:
            continue
        variant = v.get("variant", "materials")
        key = _VARIANT_MAP.get(variant, "cands_materials")
        cands = candidates_by_scene.get(sid, {}).get(key, [])
        target = v.get("image_path")
        idx = next((i for i, c in enumerate(cands) if c.get("path") == target), None)
        if idx is None:
            continue
        preselect[sid] = {
            "idx": idx, "path": target, "variant": variant,
            "description": cands[idx].get("description", ""),
        }

    thumb = selections.get("thumbnail")
    if thumb and thumb.get("image_path"):
        preselect["thumbnail"] = {"path": thumb["image_path"]}
    return preselect


def log_selection_diffs(
    script_name: str,
    script: dict,
    preselect: dict | None,
    result: dict[str, dict],
) -> int:
    """Claudeの自動選定(preselect)とユーザーの最終選択(result)が異なるシーンを
    assets/work/image_selection_diffs.jsonl に追記する。Claude Code セッション内で
    後から両画像を見比べて理由を分析し、.claude/memory/image_selection_knowledge.md
    にナレッジとして蓄積するための元データ。"""
    if not preselect:
        return 0
    scenes_by_id = {s["id"]: s for s in script.get("scenes", [])}
    entries = []
    for sid, psel in preselect.items():
        if sid == "thumbnail":
            continue
        final = result.get(str(sid))
        if not final:
            continue
        auto_path = psel.get("path")
        final_path = final.get("image_path")
        if not auto_path or not final_path or auto_path == final_path:
            continue
        scene = scenes_by_id.get(sid, {})
        entries.append({
            "date": time.strftime("%Y-%m-%d"),
            "script": script_name,
            "scene_id": sid,
            "narration": scene.get("narration", ""),
            "auto_pick": {
                "path": auto_path,
                "variant": psel.get("variant"),
                "description": (psel.get("description") or ""),
            },
            "user_pick": {
                "path": final_path,
                "variant": final.get("variant"),
                "description": ((final.get("credit") or {}).get("description", "")),
            },
            "analyzed": False,
        })
    if not entries:
        return 0
    DIFF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DIFF_LOG_PATH.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"  [diff] 自動選定と異なる選択が{len(entries)}件 → {DIFF_LOG_PATH}")
    return len(entries)


# ─── HTML 生成 ────────────────────────────────────────────────────────────────

def _grid(scene_id: int, candidates: list[dict], variant: str, sel_idx: int | None = None) -> str:
    if not candidates:
        return '<p class="noc">候補なし — material-collector スキルで素材を追加してください</p>'
    items = ""
    for i, c in enumerate(candidates):
        fname = Path(c["path"]).name
        is_video = c.get("type") == "video" or fname.endswith(".mp4")
        if is_video:
            media = (
                f'<video class="vmedia" src="/img/{fname}" muted loop playsinline preload="metadata"'
                f' onmouseenter="this.play()" onmouseleave="{{this.pause();this.currentTime=0}}">'
                f'</video>'
            )
            extra_cls = " vcw"
        else:
            media = f'<img src="/img/{fname}" loading="eager" alt="候補{i+1}">'
            extra_cls = ""
        if sel_idx == i:
            extra_cls += " sel"
        desc = c.get("description", "")
        thumb_btn = (
            f'<button class="thumbbtn" onclick="event.stopPropagation();pickThumb(\'{c["path"]}\')"'
            f' title="サムネにする">🖼</button>'
        ) if not is_video else ""
        items += (
            f'<div class="cw{extra_cls}" data-sid="{scene_id}" data-idx="{i}" data-var="{variant}"'
            f' data-path="{c["path"]}"'
            f' onclick="pick({scene_id},{i},\'{c["path"]}\',\'{variant}\')">'
            f'<div class="cw-media">{media}<div class="chk">✓</div>{thumb_btn}</div>'
            f'<div class="desc" title="{desc}">{desc[:40]}</div>'
            f'</div>'
        )
    grid_cls = "grid-v" if any(c.get("type") == "video" or Path(c["path"]).suffix == ".mp4"
                               for c in candidates) else "grid"
    return f'<div class="{grid_cls}">{items}</div>'


def _group(label: str, scene_id: int, candidates: list[dict], variant: str,
           badge: str = "", sel_idx: int | None = None) -> str:
    badge_html = f'<span class="gbadge">{badge}</span>' if badge else ""
    return (
        f'<div class="vg">'
        f'<div class="vl">{label}{badge_html}</div>'
        f'{_grid(scene_id, candidates, variant, sel_idx=sel_idx)}'
        f'</div>'
    )


def _render_scene(scene: dict, data: dict, preselect: dict | None = None) -> str:
    sid = scene["id"]
    nr = scene.get("narration", "")
    kws = scene.get("keywords", [])

    psel = (preselect or {}).get(sid)

    def _sel_idx(variant: str) -> int | None:
        return psel["idx"] if psel and psel.get("variant") == variant else None

    kw_html = "".join(f'<span class="kw">{k}</span>' for k in kws)
    badges = f'<span class="sn">Scene {sid}</span>'
    if psel:
        badges += '<span class="badge auto">🤖 自動選定済</span>'

    body = ""
    body += _group("⭐ 素材フォルダ（画像）", sid, data.get("cands_materials", []), "materials",
                   sel_idx=_sel_idx("materials"))
    if data.get("cands_materials_video"):
        body += _group("🎬 素材フォルダ（動画）", sid, data["cands_materials_video"],
                       "materials_video", sel_idx=_sel_idx("materials_video"))
    body += _group("🌐 Web検索 (DuckDuckGo) ※著作権注意", sid, data.get("cands_web", []), "web",
                   sel_idx=_sel_idx("web"))

    return (
        f'<div class="card" data-sid="{sid}">'
        f'<div class="hd">'
        f'<div class="hd-top">{badges}</div>'
        f'<p class="nr">「{nr}」</p>'
        f'<div class="kws">{kw_html}</div>'
        f'</div>'
        f'{body}'
        f'</div>'
    )


def generate_html(script: dict, candidates_by_scene: dict, preselect: dict | None = None) -> str:
    scenes_html = "".join(
        _render_scene(s, candidates_by_scene.get(s["id"], {}), preselect=preselect)
        for s in script["scenes"]
    )
    title = script.get("title", "")
    n = len(script["scenes"])

    preselect = preselect or {}
    sel_init = {
        str(sid): {"idx": v["idx"], "path": v["path"], "variant": v["variant"]}
        for sid, v in preselect.items() if sid != "thumbnail"
    }
    thumb_init = preselect.get("thumbnail")
    sel_init_js = json.dumps(sel_init, ensure_ascii=False)
    thumb_init_js = json.dumps(thumb_init, ensure_ascii=False) if thumb_init else "null"
    init_count = len(sel_init)
    thumb_prev_html = (
        f'<img class="thumb-prev" id="thumb-prev" alt="サムネ" src="/img/{Path(thumb_init["path"]).name}"'
        f' style="display:block">'
    ) if thumb_init else '<img class="thumb-prev" id="thumb-prev" alt="サムネ">'
    thumb_status_text = f'🖼 {Path(thumb_init["path"]).name}' if thumb_init else '🖼 サムネ未選択'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>画像選択ダッシュボード（素材ライブラリ）</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d0d16;color:#dde;font-family:-apple-system,'Hiragino Kaku Gothic ProN',sans-serif;padding:20px 24px 100px}}
h1{{font-size:1.3rem;color:#b090ff;margin-bottom:4px}}
.sub{{color:#667;font-size:.82rem;margin-bottom:28px}}
.card{{background:#13131e;border:1px solid #252535;border-radius:12px;padding:18px;margin-bottom:20px}}
.hd{{margin-bottom:14px}}
.hd-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
.sn{{font-size:.7rem;font-weight:700;color:#778;letter-spacing:1px;text-transform:uppercase}}
.badge{{font-size:.68rem;padding:2px 8px;border-radius:20px;margin-left:6px}}
.auto{{background:#2a2408;color:#ffd76a}}
.nr{{font-size:.88rem;line-height:1.65;color:#bbc;margin:8px 0 6px}}
.kws{{display:flex;flex-wrap:wrap;gap:5px}}
.kw{{background:#1a1a2e;color:#9090cc;font-size:.72rem;padding:2px 8px;border-radius:4px;border:1px solid #303048}}
.vg{{margin-bottom:16px}}
.vl{{font-size:.75rem;color:#889;border-bottom:1px solid #252535;padding-bottom:6px;margin-bottom:10px;display:flex;align-items:center;gap:8px}}
.gbadge{{background:#2a1a4a;color:#c090ff;font-size:.65rem;padding:1px 7px;border-radius:10px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
.cw{{display:flex;flex-direction:column;cursor:pointer;border-radius:8px;overflow:hidden;border:3px solid transparent;transition:border-color .15s,transform .1s}}
.cw:hover{{transform:scale(1.03);border-color:#6040aa}}
.cw.sel{{border-color:#a060ff}}
.cw-media{{position:relative;flex-shrink:0}}
.cw-media img{{width:100%;aspect-ratio:9/16;object-fit:cover;display:block;background:#111}}
.cw.vcw{{grid-column:1/-1}}
.vmedia{{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;display:block}}
.chk{{display:none;position:absolute;top:5px;right:5px;background:#a060ff;color:#fff;border-radius:50%;width:20px;height:20px;text-align:center;line-height:20px;font-size:11px;font-weight:bold}}
.cw.sel .chk{{display:block}}
.desc{{background:#0d0d1a;padding:4px 6px;font-size:10.5px;color:#889;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.grid-v{{display:grid;grid-template-columns:1fr;gap:8px}}
.noc{{color:#c66;font-size:.8rem;padding:20px;text-align:center;border:1px dashed #442;border-radius:8px}}
.thumbbtn{{position:absolute;bottom:5px;left:5px;background:rgba(0,0,0,.75);border:1px solid #443;border-radius:4px;color:#ffd;font-size:11px;padding:2px 6px;cursor:pointer;z-index:2;line-height:1}}
.thumbbtn:hover{{background:#4a3020;border-color:#ffd700}}
.cw.thumb .cw-media::after{{content:'🖼';position:absolute;top:5px;left:5px;background:#ffd700;color:#000;font-size:10px;padding:1px 5px;border-radius:3px;font-weight:bold}}
.thumb-info{{display:flex;align-items:center;gap:8px;font-size:.78rem;color:#aab;margin-left:auto}}
.thumb-prev{{width:28px;height:50px;object-fit:cover;border-radius:3px;border:1px solid #ffd700;display:none}}
.bar{{position:fixed;bottom:0;left:0;right:0;background:#0d0d16;border-top:1px solid #252535;padding:12px 24px;display:flex;align-items:center;gap:16px;z-index:100}}
.btn{{background:#6030cc;color:#fff;border:none;padding:12px 36px;border-radius:8px;font-size:.95rem;font-weight:700;cursor:pointer;transition:background .15s}}
.btn:hover{{background:#7040dd}}
.btn:disabled{{background:#333;cursor:default}}
.st{{font-size:.82rem;color:#667}}
</style>
</head>
<body>
<h1>🎬 画像選択ダッシュボード（素材ライブラリのみ）</h1>
<p class="sub">台本: {title} | {n}シーン ｜ assets/materials/ の素材のみを候補として表示{'（🤖 自動選定済 — 確認して問題なければそのまま送信できます）' if preselect else ''}</p>
{scenes_html}
<div class="bar">
  <button class="btn" id="okbtn" onclick="doConfirm()">✅ この画像で動画生成する</button>
  <span class="st" id="st">{init_count} / {n} シーン選択済</span>
  <div class="thumb-info">
    {thumb_prev_html}
    <span id="thumb-status" style="color:#667">{thumb_status_text}</span>
  </div>
</div>
<script>
const SEL={sel_init_js};const TOTAL={n};let THUMB={thumb_init_js};
function pick(sid,idx,path,variant){{
  document.querySelectorAll('.cw[data-sid="'+sid+'"]').forEach(e=>e.classList.remove('sel'));
  const el=document.querySelector('.cw[data-sid="'+sid+'"][data-idx="'+idx+'"][data-var="'+variant+'"]');
  if(el)el.classList.add('sel');
  SEL[sid]={{idx,path,variant}};
  document.getElementById('st').textContent=Object.keys(SEL).length+' / '+TOTAL+' シーン選択済';
}}
function pickThumb(path){{
  document.querySelectorAll('.cw').forEach(e=>e.classList.remove('thumb'));
  document.querySelectorAll('.cw[data-path="'+path+'"]').forEach(e=>e.classList.add('thumb'));
  THUMB={{path}};
  const fname=path.split('/').pop();
  const prev=document.getElementById('thumb-prev');
  prev.src='/img/'+fname+'?t='+Date.now();
  prev.style.display='block';
  document.getElementById('thumb-status').textContent='🖼 '+fname;
}}
function doConfirm(){{
  const missing=[];
  document.querySelectorAll('.card').forEach(c=>{{const sid=parseInt(c.dataset.sid);if(!SEL[sid])missing.push(sid);}});
  if(missing.length){{alert('未選択: シーン '+missing.join(', '));return;}}
  const btn=document.getElementById('okbtn');
  btn.disabled=true;btn.textContent='送信中…';
  fetch('/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{selections:SEL,thumbnail:THUMB}})
  }}).then(r=>r.json()).then(d=>{{
    btn.textContent='✅ 完了！このウィンドウを閉じてください';
    document.getElementById('st').textContent='保存: '+d.path;
  }}).catch(e=>{{btn.disabled=false;btn.textContent='エラー — 再試行';alert(e);}});
}}
</script>
</body>
</html>"""


# ─── HTTP サーバー ────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    html: str = ""
    img_dir: Path = Path(".")
    selections_path: Path = Path(".")
    script_name: str = ""
    candidates_by_scene: dict = {}
    script: dict = {}
    preselect: dict | None = None

    def do_GET(self):
        if self.path in ("/", ""):
            data = self.html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/img/"):
            fname = self.path[5:].split("?")[0]
            fp = self.img_dir / fname
            if not fp.exists() and MATERIALS_DIR.exists():
                # 素材フォルダ (assets/materials/**) 配下のファイルはimg_dir外にあるため探索
                fp = next(MATERIALS_DIR.rglob(fname), fp)
            if fp.exists():
                ctype = "video/mp4" if fp.suffix == ".mp4" else "image/jpeg"
                data = fp.read_bytes()
                size = len(data)
                rng = self.headers.get("Range", "")
                if rng and fp.suffix == ".mp4":
                    import re as _re
                    m = _re.match(r"bytes=(\d+)-(\d*)", rng)
                    start = int(m.group(1)) if m else 0
                    end   = int(m.group(2)) if m and m.group(2) else size - 1
                    end   = min(end, size - 1)
                    chunk = data[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", len(chunk))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    try:
                        self.wfile.write(chunk)
                    except OSError:
                        pass
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", size)
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    try:
                        self.wfile.write(data)
                    except OSError:
                        pass
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        if self.path == "/confirm":
            self._handle_confirm(body)
        else:
            self.send_error(404)

    def _handle_confirm(self, body: dict):
        sels = body.get("selections", {})
        thumbnail = body.get("thumbnail")  # {"path": "..."}

        result: dict[str, dict] = {}
        for sid_str, v in sels.items():
            sid = int(sid_str)
            d = self.candidates_by_scene.get(sid, {})
            variant = v.get("variant", "materials")
            key = _VARIANT_MAP.get(variant, "cands_materials")
            cands = d.get(key, [])
            idx = v.get("idx", 0)
            credit = cands[idx] if idx < len(cands) else None
            result[sid_str] = {
                "image_path": v["path"],
                "variant": variant,
                "credit": credit,
            }

        if thumbnail and thumbnail.get("path") and Path(thumbnail["path"]).exists():
            result["thumbnail"] = {"image_path": thumbnail["path"]}

        self.selections_path.parent.mkdir(parents=True, exist_ok=True)
        self.selections_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        log_selection_diffs(self.script_name, self.script, self.preselect, result)

        resp = json.dumps({
            "ok": True,
            "path": str(self.selections_path),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(resp))
        self.end_headers()
        self.wfile.write(resp)
        _server_done.set()

    def log_message(self, *_):
        pass


# ─── エントリポイント ─────────────────────────────────────────────────────────

def run_dashboard(script_path: str | Path, preselect_path: str | Path | None = None,
                   refresh: bool = False) -> Path:
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    folder = Path(script_path).stem  # 例: 08_eparade_25th

    img_dir = ROOT / "assets" / "work" / "candidates" / folder
    img_dir.mkdir(parents=True, exist_ok=True)
    selections_path = OUTPUT_DIR / folder / "image_selections.json"

    candidates_by_scene = None if refresh else load_manifest(img_dir)
    if candidates_by_scene is not None:
        print(f"▶ 候補キャッシュを再利用 → {img_dir / MANIFEST_NAME}")
    else:
        candidates_by_scene = fetch_all_candidates(script, img_dir)
        save_manifest(candidates_by_scene, img_dir)

    preselect = None
    if preselect_path:
        try:
            selections = json.loads(Path(preselect_path).read_text(encoding="utf-8"))
            preselect = selections_to_preselect(selections, candidates_by_scene)
            print(f"▶ 事前選択を読み込み: {preselect_path} ({len(preselect)}シーン)")
        except Exception as e:
            print(f"  [warn] preselect 読み込み失敗: {e}")

    html = generate_html(script, candidates_by_scene, preselect=preselect)

    class _ReuseServer(HTTPServer):
        allow_reuse_address = True

    PORT = 8765
    _Handler.html = html
    _Handler.img_dir = img_dir
    _Handler.selections_path = selections_path
    _Handler.script_name = folder
    _Handler.candidates_by_scene = candidates_by_scene
    _Handler.script = script
    _Handler.preselect = preselect

    server = _ReuseServer(("localhost", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://localhost:{PORT}"
    print(f"▶ ダッシュボード起動: {url}")
    time.sleep(0.4)
    webbrowser.open(url)
    print("  ブラウザで各シーンの画像を選んで「✅ この画像で動画生成する」をクリックしてください…")

    _server_done.wait()
    server.shutdown()
    print(f"✅ 選択完了 → {selections_path}")
    update_todo(folder, "image")
    return selections_path


def main():
    p = argparse.ArgumentParser(description="画像選択ダッシュボード（素材ライブラリのみ）")
    p.add_argument("--script", required=True, help="台本 JSON のパス")
    p.add_argument("--fetch-only", action="store_true",
                   help="素材ライブラリとのマッチングとコンタクトシート生成のみ行い、ブラウザを開かない")
    p.add_argument("--preselect", default=None, metavar="PATH",
                   help="事前選択するimage_selections.json相当のパス（Vision自動選定の結果を事前ハイライト）")
    p.add_argument("--refresh", action="store_true",
                   help="候補キャッシュ(manifest.json)を無視して再マッチングする")
    args = p.parse_args()
    if args.fetch_only:
        fetch_only(args.script)
    else:
        run_dashboard(args.script, preselect_path=args.preselect, refresh=args.refresh)


if __name__ == "__main__":
    main()
