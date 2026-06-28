"""画像選択ダッシュボード。

各シーンの候補画像をブラウザで表示し、ユーザーが選んだ画像を
image_selections.json に保存する。

候補ソース:
  1. Pexels 通常クエリ (4枚)
  2. Pexels Disney クエリ  "Disney " + 元クエリ  (4枚)
  3. TDR映像フレーム  local_clip のある場面のみ (3枚)

A/B テスト(Scene 1・2):
  Style A = Pexels 元クエリ、Style B = Pexels "Disney" 付きクエリ。
  好みを記録 → assets/work/ab_results.json に蓄積 → 次回以降に反映。

Usage:
    python src/image_dashboard.py --script scripts/xxx.json
    → ブラウザが開く → 選択 → output/<theme>/image_selections.json を生成

Pipeline との連携:
    python src/pipeline.py --script scripts/xxx.json \\
        --selections output/<theme>/image_selections.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, ROOT, load_config
from images import StockImageProvider, WebScrapeProvider, to_vertical
from todo_updater import update_todo

CANDIDATES_N    = 4    # 通常シーンの候補枚数(Pexels 通常 / Disney 各)
WEB_CANDIDATES_N = 12  # Web(DuckDuckGo)候補枚数
VIDEO_FRAMES_N  = 3    # TDR映像フレーム枚数
AB_SCENES       = [1, 2]

AB_RESULTS_PATH  = ROOT / "assets" / "work" / "ab_results.json"
AB_HINTS_PATH    = ROOT / "assets" / "work" / "ab_style_hints.json"
FEEDBACK_PATH    = ROOT / "assets" / "work" / "image_feedback.json"

_server_done: threading.Event = threading.Event()

# variant名 → candidates_by_scene キーのマッピング（refine時に動的追加される）
_VARIANT_MAP: dict[str, str] = {
    "user":    "cands_user",
    "base":    "cands_base",
    "subject": "cands_subject",
    "web":     "cands_web",
    "video":   "cands_video",
}


# ─── A/B ヒント ───────────────────────────────────────────────────────────────

def _load_ab_hints() -> dict:
    if AB_HINTS_PATH.exists():
        try:
            return json.loads(AB_HINTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_ab_result(script_name: str, scene_id: int, preferred: str,
                    query_a: str, query_b: str) -> None:
    results: list[dict] = []
    if AB_RESULTS_PATH.exists():
        try:
            results = json.loads(AB_RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    results.append({
        "date": date.today().isoformat(),
        "script": script_name,
        "scene_id": scene_id,
        "query_a": query_a,
        "query_b": query_b,
        "preferred": preferred,
    })
    AB_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AB_RESULTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    a_wins = sum(1 for r in results if r.get("preferred") == "a")
    b_wins = sum(1 for r in results if r.get("preferred") == "b")
    hints = _load_ab_hints()
    hints.update({"a_wins": a_wins, "b_wins": b_wins,
                  "dominant": "a" if a_wins >= b_wins else "b"})
    AB_HINTS_PATH.write_text(
        json.dumps(hints, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  [ab] scene {scene_id} → {preferred.upper()} 記録 (A={a_wins} B={b_wins})")


def _save_feedback(
    script_name: str,
    feedback_raw: dict[str, str],
    sels: dict,
    candidates_by_scene: dict,
) -> int:
    """画像ごとのFBを FEEDBACK_PATH に追記保存。返値は保存件数。"""
    if not feedback_raw:
        return 0
    existing: list[dict] = []
    if FEEDBACK_PATH.exists():
        try:
            existing = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    sel_set = {f"s{sid}_{v['variant']}_{v['idx']}" for sid, v in
               ((int(s), sv) for s, sv in sels.items())}

    new_entries: list[dict] = []
    for key, comment in feedback_raw.items():
        if not comment.strip():
            continue
        # key format: "s{sid}_{variant}_{idx}"
        parts = key.lstrip("s").split("_", 2)
        if len(parts) < 3:
            continue
        sid_str, variant, idx_str = parts
        sid = int(sid_str)
        idx = int(idx_str)
        vkey = _VARIANT_MAP.get(variant, "cands_base")
        cands = candidates_by_scene.get(sid, {}).get(vkey, [])
        img_path = cands[idx]["path"] if idx < len(cands) else ""
        query = cands[idx].get("query", "") if idx < len(cands) else ""
        source = cands[idx].get("source", "") if idx < len(cands) else ""
        new_entries.append({
            "date": date.today().isoformat(),
            "script": script_name,
            "scene_id": sid,
            "variant": variant,
            "idx": idx,
            "selected": key in sel_set,
            "image_path": img_path,
            "source": source,
            "query": query,
            "feedback": comment.strip(),
        })

    all_entries = existing + new_entries
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(
        json.dumps(all_entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  [fb] {len(new_entries)} 件のフィードバックを {FEEDBACK_PATH} に保存")
    return len(new_entries)


# ─── FBベースのクエリ改善 ─────────────────────────────────────────────────────

_JP_EN_MAP: list[tuple[str, str]] = [
    ("暗", "dark dramatic moody"),
    ("明る", "bright vivid colorful"),
    ("怖", "horror eerie scary"),
    ("不気味", "uncanny mysterious eerie"),
    ("廃墟", "abandoned ruins decay"),
    ("古い", "vintage antique aged"),
    ("豪華", "luxurious grand opulent"),
    ("霧", "fog misty atmospheric"),
    ("夜", "night dark atmospheric"),
    ("人物", "portrait close-up person"),
    ("人", "people silhouette"),
    ("誰もいな", "empty desolate abandoned"),
    ("ホテル", "hotel grand interior"),
    ("城", "castle gothic tower"),
    ("エレベーター", "elevator shaft"),
    ("階段", "staircase dramatic"),
    ("窓", "window dramatic light"),
    ("雰囲気", "cinematic atmospheric mood"),
    ("笑顔", "smile face portrait"),
    ("呪い", "cursed dark occult"),
    ("恐怖", "terror horror fear"),
]

def _improve_query_from_fb(fb_text: str) -> str:
    """日本語FBから英語の追加キーワードを抽出。"""
    extras: list[str] = []
    for jp, en in _JP_EN_MAP:
        if jp in fb_text and en not in extras:
            extras.append(en)
    return " ".join(extras)


# ─── TDR映像クリップ抽出 ──────────────────────────────────────────────────────

def _extract_clip(src: Path, start: float, duration: float, dst: Path) -> bool:
    """ffmpeg で映像クリップを切り出す（音声なし・再エンコード）。"""
    res = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-i", str(src),
         "-t", str(duration), "-an",
         "-vf", "setpts=PTS-STARTPTS",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         str(dst)],
        capture_output=True,
    )
    return res.returncode == 0 and dst.exists()


def fetch_video_clips(scene: dict, out_dir: Path) -> list[dict]:
    """local_clip の範囲をMP4クリップとして切り出し、候補リストを返す。"""
    lc = scene.get("local_clip")
    if not lc:
        return []
    src = ROOT / lc["source"]
    if not src.exists():
        print(f"  [warn] 映像ファイルなし: {src}")
        return []
    start  = float(lc.get("start", 0))
    dur    = float(lc.get("duration", 10))
    sid    = scene.get("id", 0)
    dst    = out_dir / f"s{sid:02d}_vid.mp4"
    if _extract_clip(src, start, dur, dst):
        return [{
            "path":   str(dst),
            "type":   "video",
            "query":  f"TDR映像 {start:.0f}–{start+dur:.0f}秒",
            "source": "TDR映像",
        }]
    return []


# ─── 候補取得 ─────────────────────────────────────────────────────────────────

def fetch_all_candidates(script: dict, out_dir: Path, cfg: dict) -> dict[int, dict]:
    """全シーンの候補を取得。各シーン: Pexels通常 / Pexels 固有名詞 / Web検索 / TDR映像クリップ。"""
    w, h = cfg["video"]["width"], cfg["video"]["height"]
    pexels  = StockImageProvider(width=w, height=h)
    scraper = WebScrapeProvider(width=w, height=h)
    meta = script.get("meta", {})
    subject_ja = meta.get("subject", "")           # 例: "タワー・オブ・テラー"
    subject_en = meta.get("subject_en", "Disney")  # 例: "Tower of Terror DisneySea"
    result: dict[int, dict] = {}

    # ユーザー指定画像ディレクトリ: out_dir/user/s{sid:02d}_*.jpg
    user_dir = out_dir / "user"

    def _load_user_cands(sid: int) -> list[dict]:
        if not user_dir.exists():
            return []
        cands: list[dict] = []
        for fp in sorted(user_dir.glob(f"s{sid:02d}_*.jpg")):
            cands.append({
                "path": str(fp),
                "query": "ユーザー指定画像",
                "source": "user",
            })
        return cands

    print(f"▶ 候補取得中 ({len(script['scenes'])}シーン)…")
    print(f"  対象: {subject_ja} / {subject_en}")
    for scene in script["scenes"]:
        sid = scene["id"]
        base_q    = scene.get("image_query", "background")
        # Pexels: 英語固有名詞 + 元クエリ
        subject_q = f"{subject_en} {base_q}"
        # Web: 日本語固有名詞 + 元クエリ（scrape_query があれば優先）
        web_q     = scene.get("scrape_query") or f"{subject_ja} {base_q}"

        print(f"  scene {sid}: Pexels通常…")
        cands_base    = pexels.fetch_candidates(scene, out_dir, CANDIDATES_N, suffix="_base")
        print(f"  scene {sid}: Pexels「{subject_en[:20]}」…")
        cands_subject = pexels.fetch_candidates(
            {**scene, "image_query": subject_q}, out_dir, CANDIDATES_N, suffix="_subj"
        )
        print(f"  scene {sid}: Web「{web_q[:30]}」…")
        cands_web     = scraper.fetch_candidates(
            {**scene, "scrape_query": web_q}, out_dir, WEB_CANDIDATES_N, suffix="_web"
        )
        print(f"  scene {sid}: TDR映像クリップ…")
        cands_video   = fetch_video_clips(scene, out_dir)

        result[sid] = {
            "is_ab":         sid in AB_SCENES,
            "cands_user":    _load_user_cands(sid),
            "cands_base":    cands_base,
            "cands_subject": cands_subject,
            "cands_web":     cands_web,
            "cands_video":   cands_video,
            "query_base":    base_q,
            "query_subject": subject_q,
        }
    return result


# ─── HTML 生成 ────────────────────────────────────────────────────────────────

def _grid(scene_id: int, candidates: list[dict], variant: str, ts: int = 0) -> str:
    if not candidates:
        return '<p class="noc">候補なし</p>'
    items = ""
    qs = f"?t={ts}" if ts else ""
    for i, c in enumerate(candidates):
        fname = Path(c["path"]).name
        is_video = c.get("type") == "video" or fname.endswith(".mp4")
        if is_video:
            media = (
                f'<video class="vmedia" src="/img/{fname}{qs}" muted loop playsinline preload="metadata"'
                f' onmouseenter="this.play()" onmouseleave="{{this.pause();this.currentTime=0}}">'
                f'</video>'
            )
            extra_cls = " vcw"
        else:
            media = f'<img src="/img/{fname}{qs}" loading="eager" alt="候補{i+1}">'
            extra_cls = ""
        fb_key = f"s{scene_id}_{variant}_{i}"
        thumb_btn = (
            f'<button class="thumbbtn" onclick="event.stopPropagation();pickThumb(\'{c["path"]}\')"'
            f' title="サムネにする">🖼</button>'
        ) if not is_video else ""
        items += (
            f'<div class="cw{extra_cls}" data-sid="{scene_id}" data-idx="{i}" data-var="{variant}"'
            f' data-path="{c["path"]}"'
            f' onclick="pick({scene_id},{i},\'{c["path"]}\',\'{variant}\')">'
            f'<div class="cw-media">{media}<div class="chk">✓</div>{thumb_btn}</div>'
            f'<div class="fbwrap" onclick="event.stopPropagation()">'
            f'<textarea class="fbinput" placeholder="FB..." rows="2"'
            f' oninput="saveFB(\'{fb_key}\',this.value)"></textarea>'
            f'</div>'
            f'</div>'
        )
    grid_cls = "grid-v" if any(c.get("type") == "video" or Path(c["path"]).suffix == ".mp4"
                               for c in candidates) else "grid"
    return f'<div class="{grid_cls}">{items}</div>'


def _group(label: str, scene_id: int, candidates: list[dict], variant: str,
           badge: str = "", ts: int = 0) -> str:
    badge_html = f'<span class="gbadge">{badge}</span>' if badge else ""
    return (
        f'<div class="vg">'
        f'<div class="vl">{label}{badge_html}</div>'
        f'{_grid(scene_id, candidates, variant, ts=ts)}'
        f'</div>'
    )


def _render_scene(scene: dict, data: dict, ts: int = 0) -> str:
    sid = scene["id"]
    nr = scene.get("narration", "")
    kws = scene.get("keywords", [])
    has_clip = bool(scene.get("local_clip"))

    kw_html = "".join(f'<span class="kw">{k}</span>' for k in kws)
    badges = f'<span class="sn">Scene {sid}</span>'
    if data.get("is_ab"):
        badges += '<span class="badge ab">🔬 A/B</span>'
    if has_clip:
        badges += '<span class="badge clip">🎬 映像あり</span>'

    body = ""
    if data.get("cands_user"):
        body += _group("⭐ ユーザー指定画像", sid, data["cands_user"], "user",
                       badge="⭐ 指定", ts=ts)
    body += _group("Pexels — 通常クエリ", sid, data["cands_base"], "base", ts=ts)
    body += _group("Pexels — 固有名詞クエリ", sid, data.get("cands_subject", []), "subject",
                   badge="✨ 固有名詞", ts=ts)
    body += _group("Web 検索 (DuckDuckGo)", sid, data.get("cands_web", []), "web",
                   badge="🌐 Web ※著作権注意", ts=ts)
    if data["cands_video"]:
        body += _group("TDR 実映像フレーム", sid, data["cands_video"], "video",
                       badge="🎥 実映像", ts=ts)

    if data.get("is_ab"):
        body += (
            f'<div class="abp">'
            f'<span class="abl">A/B 好み:</span>'
            f'<label><input type="radio" class="abr" name="ab{sid}" value="a" data-sid="{sid}">'
            f' 通常クエリが好み</label>'
            f'<label><input type="radio" class="abr" name="ab{sid}" value="b" data-sid="{sid}">'
            f' Disney クエリが好み</label>'
            f'</div>'
        )

    refine_ctrl = (
        f'<div class="refine-ctrl">'
        f'<input class="refine-input" id="refine_q_{sid}" type="text"'
        f' placeholder="検索クエリ（例: タワー・オブ・テラー キャスト）">'
        f'<button class="refine-btn" id="refine_{sid}" onclick="doRefine({sid})">'
        f'🔄 再検索</button>'
        f'</div>'
    )
    cls = "card ab-card" if data.get("is_ab") else "card"
    return (
        f'<div class="{cls}" data-sid="{sid}">'
        f'<div class="hd">'
        f'<div class="hd-top">{badges}</div>'
        f'<p class="nr">「{nr}」</p>'
        f'<div class="kws">{kw_html}</div>'
        f'{refine_ctrl}</div>'
        f'{body}'
        f'</div>'
    )


def generate_html(script: dict, candidates_by_scene: dict, startup_ts: int = 0) -> str:
    scenes_html = "".join(
        _render_scene(s, candidates_by_scene.get(s["id"], {}), ts=startup_ts)
        for s in script["scenes"]
    )
    title = script.get("title", "")
    n = len(script["scenes"])

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>画像選択ダッシュボード</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d0d16;color:#dde;font-family:-apple-system,'Hiragino Kaku Gothic ProN',sans-serif;padding:20px 24px 100px}}
h1{{font-size:1.3rem;color:#b090ff;margin-bottom:4px}}
.sub{{color:#667;font-size:.82rem;margin-bottom:28px}}
.card{{background:#13131e;border:1px solid #252535;border-radius:12px;padding:18px;margin-bottom:20px}}
.ab-card{{background:#110d1c;border-color:#3d2060}}
.hd{{margin-bottom:14px}}
.hd-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
.sn{{font-size:.7rem;font-weight:700;color:#778;letter-spacing:1px;text-transform:uppercase}}
.badge{{font-size:.68rem;padding:2px 8px;border-radius:20px;margin-left:6px}}
.ab{{background:#3d2060;color:#c090ff}}
.clip{{background:#0d2a1a;color:#50b070}}
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
.fbwrap{{background:#0d0d1a;padding:4px}}
.fbinput{{width:100%;box-sizing:border-box;background:#111827;color:#bbb;border:1px solid #2d2d45;border-radius:4px;padding:4px 6px;font-size:11px;resize:none;font-family:inherit;display:block}}
.fbinput:focus{{outline:none;border-color:#7050cc;background:#161628}}
.grid-v{{display:grid;grid-template-columns:1fr;gap:8px}}
.abp{{display:flex;align-items:center;gap:14px;margin-top:10px;padding-top:10px;border-top:1px solid #252535}}
.abl{{font-size:.78rem;color:#778}}
.abp label{{font-size:.8rem;color:#99a;cursor:pointer;display:flex;align-items:center;gap:5px}}
.abp input[type=radio]{{accent-color:#a060ff}}
.noc{{color:#445;font-size:.8rem;padding:20px;text-align:center}}
.refine-ctrl{{display:flex;gap:6px;align-items:center;margin-top:10px}}
.refine-input{{flex:1;background:#111827;color:#ccc;border:1px solid #2a4060;border-radius:6px;padding:5px 10px;font-size:.82rem;font-family:inherit}}
.refine-input:focus{{outline:none;border-color:#5080cc}}
.refine-input::placeholder{{color:#446}}
.refine-btn{{background:#1a3050;color:#70b0ff;border:1px solid #2a4060;padding:5px 14px;border-radius:6px;font-size:.82rem;cursor:pointer;transition:background .15s;white-space:nowrap}}
.refine-btn:hover{{background:#1e3a60;border-color:#3a5080}}
.refine-btn:disabled{{background:#1a1a2a;color:#446;cursor:default}}
.refine-group{{border:1px solid #1a3050;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1520}}
.refine-group .vl{{color:#70b0ff}}
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
<h1>🎬 画像選択ダッシュボード</h1>
<p class="sub">台本: {title} | {n}シーン ｜ 各シーンから1枚選んでください</p>
{scenes_html}
<div class="bar">
  <button class="btn" id="okbtn" onclick="doConfirm()">✅ この画像で動画生成する</button>
  <span class="st" id="st">0 / {n} シーン選択済</span>
  <div class="thumb-info">
    <img class="thumb-prev" id="thumb-prev" alt="サムネ">
    <span id="thumb-status" style="color:#667">🖼 サムネ未選択</span>
  </div>
</div>
<script>
const SEL={{}};const ABP={{}};const FB={{}};const TOTAL={n};let THUMB=null;
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
function saveFB(key,val){{
  if(val.trim())FB[key]=val.trim();
  else delete FB[key];
}}
function doRefine(sid){{
  const customQ=(document.getElementById('refine_q_'+sid)||{{}}).value?.trim()||'';
  const fbs={{}};
  for(const [k,v] of Object.entries(FB)){{if(k.startsWith('s'+sid+'_'))fbs[k]=v;}}
  if(!customQ&&!Object.keys(fbs).length){{
    alert('検索クエリを入力するか、画像のFB欄に感想を書いてから再検索してください');return;
  }}
  const btn=document.getElementById('refine_'+sid);
  btn.disabled=true;btn.textContent='🔄 検索中…';
  const ts=Date.now();
  fetch('/refine',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{scene_id:sid,fbs,ts,custom_query:customQ}})
  }}).then(r=>{{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}})
  .then(d=>{{
    btn.disabled=false;btn.textContent='🔄 再検索';
    const card=btn.closest('.card');
    const old=card.querySelector('.refine-group');
    if(old)old.remove();
    const firstVg=card.querySelector('.vg');
    if(firstVg){{firstVg.insertAdjacentHTML('beforebegin',d.html);}}
    else{{card.querySelector('.hd').insertAdjacentHTML('afterend',d.html);}}
  }}).catch(e=>{{btn.disabled=false;btn.textContent='🔄 再検索';
    const card=btn.closest('.card');
    const errDiv=document.createElement('div');
    errDiv.style='color:#f66;font-size:.8rem;padding:6px';
    errDiv.textContent='再検索エラー: '+e;
    card.querySelector('.hd').insertAdjacentElement('afterend',errDiv);
    setTimeout(()=>errDiv.remove(),5000);
  }});
}}
function doConfirm(){{
  const missing=[];
  document.querySelectorAll('.card').forEach(c=>{{const sid=parseInt(c.dataset.sid);if(!SEL[sid])missing.push(sid);}});
  if(missing.length){{alert('未選択: シーン '+missing.join(', '));return;}}
  document.querySelectorAll('.abr:checked').forEach(r=>{{ABP[r.dataset.sid]=r.value;}});
  const btn=document.getElementById('okbtn');
  btn.disabled=true;btn.textContent='送信中…';
  fetch('/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{selections:SEL,abPrefs:ABP,feedback:FB,thumbnail:THUMB}})
  }}).then(r=>r.json()).then(d=>{{
    btn.textContent='✅ 完了！このウィンドウを閉じてください';
    document.getElementById('st').textContent='保存: '+d.path+(d.fb_count?' | FB '+d.fb_count+'件':'');
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
    _script: dict = {}
    _cfg: dict = {}

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
        elif self.path == "/refine":
            self._handle_refine(body)
        else:
            self.send_error(404)

    def _handle_confirm(self, body: dict):
        sels = body.get("selections", {})
        ab_prefs = body.get("abPrefs", {})
        feedback_raw = body.get("feedback", {})  # {"s1_web_2": "コメント文", ...}

        for sid_str, pref in ab_prefs.items():
            sid = int(sid_str)
            d = self.candidates_by_scene.get(sid, {})
            if d.get("is_ab"):
                _save_ab_result(
                    self.script_name, sid, pref,
                    d.get("query_base", ""), d.get("query_subject", ""),
                )

        thumbnail = body.get("thumbnail")  # {"path": "..."}

        result: dict[str, dict] = {}
        for sid_str, v in sels.items():
            sid = int(sid_str)
            d = self.candidates_by_scene.get(sid, {})
            variant = v.get("variant", "base")
            key = _VARIANT_MAP.get(variant, "cands_base")
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

        fb_count = _save_feedback(
            self.script_name, feedback_raw, sels, self.candidates_by_scene
        )

        resp = json.dumps({
            "ok": True,
            "path": str(self.selections_path),
            "fb_count": fb_count,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(resp))
        self.end_headers()
        self.wfile.write(resp)
        _server_done.set()

    def _handle_refine(self, body: dict):
        import time as _time
        sid = int(body.get("scene_id", 0))
        fbs: dict[str, str] = body.get("fbs", {})
        ts  = int(body.get("ts", _time.time() * 1000))

        scene = next((s for s in self._script.get("scenes", []) if s["id"] == sid), None)
        if not scene:
            self.send_error(404)
            return

        custom_query = body.get("custom_query", "").strip()
        combined_fb  = " ".join(v.strip() for v in fbs.values() if v.strip())
        meta         = self._script.get("meta", {})
        subject_en   = meta.get("subject_en", "Disney")
        base_q       = scene.get("image_query", "background")

        if custom_query:
            # カスタムクエリ優先: 日本語クエリはWebに直接、Pexelsには英語部分だけ補完
            new_web_q    = custom_query
            new_pexels_q = f"{subject_en} {custom_query}"
        else:
            subject_ja   = meta.get("subject", "")
            new_pexels_q = f"{subject_en} {base_q} {_improve_query_from_fb(combined_fb)}".strip()
            new_web_q    = f"{subject_ja} {base_q} {combined_fb}".strip()

        print(f"  [refine] scene {sid} ts={ts}")
        print(f"    Pexels: {new_pexels_q[:70]}")
        print(f"    Web   : {new_web_q[:70]}")

        cfg = self._cfg
        w, h = cfg["video"]["width"], cfg["video"]["height"]
        pexels  = StockImageProvider(width=w, height=h)
        scraper = WebScrapeProvider(width=w, height=h)

        # タイムスタンプをsuffixに含めて毎回新しいファイルを生成（ブラウザキャッシュ回避）
        sfx = str(ts)[-6:]  # 末尾6桁
        new_pexels = pexels.fetch_candidates(
            {**scene, "image_query": new_pexels_q}, self.img_dir, CANDIDATES_N,
            suffix=f"_rfnp{sfx}"
        )
        new_web = scraper.fetch_candidates(
            {**scene, "scrape_query": new_web_q}, self.img_dir, WEB_CANDIDATES_N,
            suffix=f"_rfnw{sfx}"
        )

        vkey_p, vkey_w = f"cands_rfnp{sfx}", f"cands_rfnw{sfx}"
        d = self.candidates_by_scene.setdefault(sid, {})
        d[vkey_p] = new_pexels
        d[vkey_w] = new_web

        # variant マッピングを動的に更新
        _VARIANT_MAP[f"rfnp{sfx}"] = vkey_p
        _VARIANT_MAP[f"rfnw{sfx}"] = vkey_w

        html_frag = (
            f'<div class="refine-group" id="rg_{sid}">'
            + _group(f"📨 FB再検索 — Pexels ({new_pexels_q[:35]}…)",
                     sid, new_pexels, f"rfnp{sfx}", ts=ts)
            + _group(f"📨 FB再検索 — Web ({new_web_q[:35]}…)",
                     sid, new_web, f"rfnw{sfx}", ts=ts)
            + "</div>"
        )

        resp = json.dumps({"ok": True, "html": html_frag}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(resp))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *_):
        pass


# ─── エントリポイント ─────────────────────────────────────────────────────────

def run_dashboard(script_path: str | Path) -> Path:
    cfg = load_config()
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    folder = Path(script_path).stem  # 例: 08_eparade_25th

    img_dir = ROOT / "assets" / "work" / "candidates" / folder
    img_dir.mkdir(parents=True, exist_ok=True)
    selections_path = OUTPUT_DIR / folder / "image_selections.json"

    candidates_by_scene = fetch_all_candidates(script, img_dir, cfg)
    startup_ts = int(time.time() * 1000)
    html = generate_html(script, candidates_by_scene, startup_ts=startup_ts)

    class _ReuseServer(HTTPServer):
        allow_reuse_address = True

    PORT = 8765
    _Handler.html = html
    _Handler.img_dir = img_dir
    _Handler.selections_path = selections_path
    _Handler.script_name = folder
    _Handler.candidates_by_scene = candidates_by_scene
    _Handler._script = script
    _Handler._cfg = cfg

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
    p = argparse.ArgumentParser(description="画像選択ダッシュボード")
    p.add_argument("--script", required=True, help="台本 JSON のパス")
    args = p.parse_args()
    run_dashboard(args.script)


if __name__ == "__main__":
    main()
