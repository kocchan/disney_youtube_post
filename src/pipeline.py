"""パイプライン本体(オーケストレータ / エントリポイント)。

script.json を読み込み、TTS音声生成 → 画像取得 → 字幕付き動画合成 → BGM合成を実行して
output/final_output.mp4 を書き出す。

使い方:
    python src/pipeline.py [--script scripts/sample.json] [--out output/final_output.mp4]
                           [--tts gtts] [--bgm rotate|random|none|<path>]
                           [--allow-scrape] [--no-cache] [--no-ken-burns]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bgm import build_bgm_bed
from config import AUDIO_DIR, CLIPS_DIR, IMAGES_DIR, OUTPUT_DIR, ROOT, load_config
from images import get_image_provider
from sfx import get_caption_sfx_paths, get_sfx_path
from thumbnail import generate_thumbnail
from todo_updater import update_todo
from youtube_meta import write_youtube_meta
from tts import get_duration, get_tts_provider
from util import is_cached, key_of, mark_cached
from video import build_video


_PLATFORM_DEFAULTS = {
    # platform: (bgm_enabled, max_duration_sec, suffix, speed_factor)
    # max_duration_sec=None → フル尺
    # speed_factor=1.0 → 速度変更なし(プラットフォームで速度を変えることは禁止)
    "x":       (True,  None, "_x",       1.0),
    "youtube": (True,  60.0, "_youtube", 1.0),
    "tiktok":  (True,  None, "_tiktok",  1.0),
}


def _select_scenes_for_duration(prepared: list[dict], max_sec: float) -> list[dict]:
    """合計尺が max_sec 以下になるよう先頭と末尾を必ず含めて中盤を間引く。"""
    if not prepared:
        return prepared
    total = sum(get_duration(s["audio_path"]) for s in prepared)
    if total <= max_sec:
        return prepared
    # 先頭・末尾は必須、中盤を等間隔で間引き
    must = [prepared[0], prepared[-1]]
    middle = prepared[1:-1]
    result = list(must)
    acc = sum(get_duration(s["audio_path"]) for s in must)
    for s in middle:
        d = get_duration(s["audio_path"])
        if acc + d <= max_sec:
            result.append(s)
            acc += d
    # シーンIDでソート
    result.sort(key=lambda s: s["scene"]["id"])
    return result


def _resolve_count(prepared: list[dict], script: dict) -> int:  # noqa: ARG001
    """トリビアシーン数(フック+CTAを除く)を返す。

    {count} プレースホルダーをタイトル・narration に埋め込んでおくと
    プラットフォームごとの実トリビア数に自動で合わせられる。
    例: 10シーン(hook+8トリビア+CTA) → count=8、YouTube間引き6シーン → count=4
    """
    return max(1, len(prepared) - 2)


def _apply_count(text: str, count: int) -> str:
    """テキスト中の {count} を実数に置換する。"""
    return text.replace("{count}", str(count))


_LANDMARK_KEYWORDS = ("castle", "landmark", "tower", "palace", "fairytale", "magic", "kingdom")
_THUMBNAIL_BG = ROOT / "assets" / "thumbnail" / "bg.jpg"


def _pick_thumbnail_image(prepared: list[dict]) -> Path:
    """サムネイル用画像を選ぶ。assets/thumbnail/bg.jpg が存在すれば最優先で使う。"""
    if _THUMBNAIL_BG.exists():
        return _THUMBNAIL_BG
    for entry in prepared:
        q = entry["scene"].get("image_query", "").lower()
        if any(kw in q for kw in _LANDMARK_KEYWORDS):
            return entry["image_path"]
    return prepared[len(prepared) // 2]["image_path"]


def run(
    script_path: str | Path,
    out_path: str | Path | None = None,
    *,
    tts_override: str | None = None,
    bgm_override: str | None = None,
    allow_scrape: bool = False,
    use_cache: bool = True,
    ken_burns: bool | None = None,
    platform: str | None = None,
    selections_path: str | Path | None = None,
) -> Path:
    cfg = load_config()
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    meta = script.get("meta", {})
    w, h = cfg["video"]["width"], cfg["video"]["height"]
    stem = Path(script_path).stem
    script_audio_dir = AUDIO_DIR / stem
    script_audio_dir.mkdir(parents=True, exist_ok=True)

    tts_name = tts_override or meta.get("tts_provider", cfg["tts"]["provider"])
    lang = meta.get("lang", cfg["tts"]["lang"])
    voice = meta.get("voice", cfg["tts"].get("voice"))
    speed = float(meta.get("speed", cfg["tts"].get("speed", 1.0)))
    img_name = meta.get("image_provider", cfg["image"]["provider"])

    tts = get_tts_provider(tts_name, lang=lang, voice=voice, speed=speed)
    img = get_image_provider(img_name, w, h, allow_scrape=allow_scrape)

    # 画像選択JSONを読み込む (--selections 指定時)
    selections: dict = {}
    if selections_path:
        try:
            selections = json.loads(Path(selections_path).read_text(encoding="utf-8"))
            print(f"▶ 画像選択: {selections_path} ({len(selections)}シーン選択済)")
        except Exception as e:
            print(f"  [warn] selections 読み込み失敗: {e}")

    print(f"▶ 台本: {script.get('title', '(無題)')} / {len(script['scenes'])} シーン"
          f"  (tts={tts_name}, voice={voice}, speed={speed}x)")

    n_total = len(script["scenes"])
    # Phase 1 では {count} を「全シーン数 - 2」の暫定値で解決してから合成する。
    # こうすることで gTTS に "{count}" が文字として渡されるのを防ぎ、
    # 正確な尺と自然な読み上げが得られる。
    # Phase 2 (プラットフォーム間引き後) で実際のカウントと異なれば再生成する。
    pre_count = max(1, n_total - 2)
    prepared = []
    total = 0.0
    print(f"▶ シーン前処理 (TTS + 画像) — 全 {n_total} シーン (暫定count={pre_count})")
    for scene in script["scenes"]:
        sid = scene["id"]
        t0 = time.time()
        print(f"  [{sid}/{n_total}] シーン {sid} 処理中…", flush=True)
        try:
            # M1: 音声(キャッシュ対応)
            # {count} プレースホルダーを事前に解決してから合成する(garbled audio 防止)
            ap = script_audio_dir / f"scene_{sid:02d}.mp3"
            pre_narr = _apply_count(scene["narration"], pre_count)
            akey = key_of("tts", tts_name, lang, str(voice), str(speed), pre_narr)
            if use_cache and is_cached(ap, akey):
                cached_a = True
            else:
                tts.synthesize(pre_narr, ap)
                mark_cached(ap, akey)
                cached_a = False
            dur = get_duration(ap)

            # M2: 画像(キャッシュ対応)。クレジットはサイドカーに保存し、キャッシュ時も復元する
            ip = IMAGES_DIR / f"scene_{sid:02d}.jpg"
            ikey = key_of("img", img_name, f"{w}x{h}", scene.get("image_query", ""))
            credit_side = ip.with_suffix(".credit.json")
            sel = selections.get(str(sid))
            sel_variant = sel.get("variant", "base") if sel else None
            sel_is_video = sel_variant == "video"

            if sel and not sel_is_video and Path(sel["image_path"]).exists():
                # 静止画選択: ip にコピー。local_clip より優先する
                import shutil
                shutil.copy2(sel["image_path"], ip)
                if sel.get("credit"):
                    _add_credit(img, {**sel["credit"], "scene_id": sid})
                    credit_side.write_text(json.dumps(sel["credit"], ensure_ascii=False), encoding="utf-8")
                mark_cached(ip, ikey)
                print(f"  scene {sid}: 選択済み画像を使用 ({Path(sel['image_path']).name})")
            elif sel and sel_is_video:
                # 動画選択: image_path はフォールバック用にキャッシュから取得するだけ
                if not (use_cache and is_cached(ip, ikey)):
                    try:
                        img.fetch(scene, ip)
                        mark_cached(ip, ikey)
                    except Exception:
                        pass
                print(f"  scene {sid}: 選択済みビデオを使用 ({Path(sel['image_path']).name})")
            elif use_cache and is_cached(ip, ikey):
                if credit_side.exists():  # キャッシュ画像のクレジットを復元
                    _add_credit(img, json.loads(credit_side.read_text(encoding="utf-8")))
            else:
                img.fetch(scene, ip)
                mark_cached(ip, ikey)
                last = getattr(img, "credits", [])
                if last:  # 取得したクレジットをサイドカーに保存
                    credit_side.write_text(json.dumps(last[-1], ensure_ascii=False), encoding="utf-8")

            # M2-B: ローカル動画クリップ
            # - ユーザーが動画バリアントを選択 → 選択ファイルをそのまま使う
            # - ユーザーが静止画バリアントを選択 → local_clip を無視（選択を優先）
            # - 未選択 → local_clip があれば抽出
            clip_path = None
            if sel and sel_is_video and Path(sel["image_path"]).exists():
                clip_path = Path(sel["image_path"])
            elif not (sel and not sel_is_video):
                local_clip_cfg = scene.get("local_clip")
                if local_clip_cfg:
                    src = ROOT / local_clip_cfg["source"]
                    start = float(local_clip_cfg.get("start", 0))
                    clip_dur = float(local_clip_cfg.get("duration", dur + 3))
                    cp = CLIPS_DIR / f"scene_{sid:02d}.mp4"
                    ckey = key_of("clip", str(src), str(start), f"{clip_dur:.1f}")
                    if use_cache and is_cached(cp, ckey):
                        pass
                    else:
                        import subprocess
                        result = subprocess.run(
                            ["ffmpeg", "-y",
                             "-ss", str(start), "-i", str(src),
                             "-t", str(clip_dur), "-an",
                             "-vf", "setpts=PTS-STARTPTS",
                             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                             str(cp)],
                            capture_output=True,
                        )
                        if result.returncode != 0:
                            print(f"  [warn] scene {sid} clip 切り出し失敗、静止画にフォールバック")
                        else:
                            mark_cached(cp, ckey)
                            clip_path = cp
                    if clip_path is None and is_cached(cp, ckey):
                        clip_path = cp

        except Exception as e:  # noqa: BLE001 - 1シーン失敗で全体を止めない
            print(f"  [error] scene {sid} スキップ: {e}")
            continue

        total += dur
        prepared.append({"audio_path": ap, "image_path": ip, "clip_path": clip_path, "scene": scene})
        tag = "(cache)" if cached_a else ""
        print(f"  [{sid}/{n_total}] ✓ {dur:5.2f}s  ({time.time()-t0:.1f}s){tag}", flush=True)

    if not prepared:
        raise RuntimeError("有効なシーンが1つもありません(全シーン失敗)")

    # 字幕設定(フォントパスを絶対化)
    sub_cfg = dict(cfg["subtitle"])
    sub_cfg["font"] = str((ROOT / sub_cfg["font"]).resolve())
    lb = cfg.get("letterbox", {})
    if lb.get("enabled"):
        sub_cfg["bottom_bar"] = int(lb.get("bottom_bar", 0))

    # タイトルオーバーレイ設定
    title_cfg = dict(cfg.get("title_overlay", {}))
    title_cfg["font"] = sub_cfg["font"]  # 字幕と同じフォント
    if lb.get("enabled"):
        title_cfg["top_bar"] = int(lb.get("top_bar", 0))  # 帯の下端にテキストを寄せる

    # 効果音
    sfx_cfg = dict(cfg.get("sfx", {}))
    sfx_path = get_sfx_path(sfx_cfg)
    sfx_volume_db = float(sfx_cfg.get("volume_db", -10.0))
    caption_sfx = get_caption_sfx_paths(sfx_cfg)
    caption_sfx_volume_db = float(sfx_cfg.get("caption_volume_db", -14.0))
    print(f"▶ SFX: {'あり' if sfx_path else 'なし'} / テロップ音: {'あり' if caption_sfx[0] else 'なし'}")

    # プラットフォーム設定を適用
    plat = (platform or "x").lower()

    # 出力フォルダを事前に確定（TikTok early-exit で使うため）
    _folder = Path(script_path).stem if script_path else (meta.get("theme") or "output")
    out_dir = Path(out_path).parent if out_path else OUTPUT_DIR / _folder

    # TikTok版 = X版と同一のため、X版が存在する場合はコピーして終了
    if plat == "tiktok":
        import shutil as _shutil
        x_out = out_dir / "final_output_x.mp4"
        tiktok_out = out_dir / "final_output_tiktok.mp4"
        if x_out.exists():
            _shutil.copy2(x_out, tiktok_out)
            x_credits = out_dir / "final_output_x.credits.json"
            if x_credits.exists():
                _shutil.copy2(x_credits, out_dir / "final_output_tiktok.credits.json")
            update_todo(Path(script_path).stem, "tiktok")
            print(f"📋 TikTok版: X版からコピー → {tiktok_out.name}")
            return tiktok_out
        else:
            print("  [warn] X版が未生成のためTikTokをX設定で通常生成します")
            plat = "x"

    plat_bgm, plat_max_dur, plat_suffix, plat_speed_factor = _PLATFORM_DEFAULTS.get(plat, (True, None, "", 1.0))
    if abs(plat_speed_factor - 1.0) > 1e-3:
        raise RuntimeError(
            f"プラットフォーム '{plat}' に speed_factor={plat_speed_factor} が設定されています。"
            "プラットフォームごとに速度を変えることは禁止されています。"
            "_PLATFORM_DEFAULTS の speed_factor はすべて 1.0 にしてください。"
        )
    if plat_max_dur:
        prepared = _select_scenes_for_duration(prepared, plat_max_dur)
        total = sum(get_duration(s["audio_path"]) for s in prepared)
        print(f"▶ プラットフォーム: {plat} / 使用シーン: {len(prepared)} / 尺: {total:.1f}s / speed: {speed}x")
    else:
        print(f"▶ プラットフォーム: {plat} / speed: {speed}x")

    # {count} 置換: 間引き後の実トリビア数でタイトルと narration を更新し、TTS を再生成
    count = _resolve_count(prepared, script)
    resolved_title = _apply_count(script.get("title", ""), count)
    for entry in prepared:
        scene = entry["scene"]
        raw_narr = scene.get("narration", "")
        if "{count}" not in raw_narr:
            continue
        resolved_narr = _apply_count(raw_narr, count)
        scene = dict(scene, narration=resolved_narr)
        entry["scene"] = scene
        # {count} が変わった narration は必ず TTS 再生成(キャッシュキーに count を含める)
        sid = scene["id"]
        ap = script_audio_dir / f"scene_{sid:02d}.mp3"
        akey = key_of("tts", tts_name, lang, str(voice), str(speed), resolved_narr)
        if not (use_cache and is_cached(ap, akey)):
            print(f"  [count={count}] scene {sid} narration 再生成中…")
            tts.synthesize(resolved_narr, ap)
            mark_cached(ap, akey)
        entry["audio_path"] = ap
    if resolved_title != script.get("title", ""):
        print(f"  [count={count}] タイトル置換: {resolved_title}")
    total = sum(get_duration(s["audio_path"]) for s in prepared)

    # BGM: プラットフォーム設定 > CLI > 台本meta > config の優先で selection を決定
    bgm_clip = None
    bgm_cfg = dict(cfg["bgm"])
    if not plat_bgm:
        bgm_cfg["enabled"] = False
    else:
        selection = bgm_override or meta.get("bgm") or bgm_cfg.get("selection")
        if selection == "none":
            bgm_cfg["enabled"] = False
        else:
            bgm_cfg["selection"] = selection
    selection = bgm_cfg.get("selection", "rotate")
    if bgm_cfg.get("enabled", True):
        bgm_clip = build_bgm_bed(total, bgm_cfg)
    print(f"▶ BGM: {'合成あり' if bgm_clip is not None else 'なし'} / mode={selection}")

    # 出力パス: スクリプトファイル stem (例: 08_eparade_25th) をフォルダ名に使う
    if out_path:
        out_path = Path(out_path)
    else:
        folder = Path(script_path).stem if script_path else (meta.get("theme") or "output")
        variant = meta.get("variant", "")
        prod_dir = OUTPUT_DIR / folder
        prod_dir.mkdir(parents=True, exist_ok=True)
        variant_suffix = f"_{variant}" if variant else ""
        out_path = prod_dir / f"final_output{plat_suffix}{variant_suffix}.mp4"

    # BGMがない場合はナレーションブーストを適用しない(クリッピング防止)
    narr_gain_db = float(cfg["bgm"].get("narration_gain_db", 0.0)) if plat_bgm else 0.0

    kb = cfg["video"].get("ken_burns", True) if ken_burns is None else ken_burns
    print(f"▶ 動画合成開始 — {len(prepared)} シーン / 合計尺 {total:.1f}s ({total/60:.1f}分)", flush=True)
    print(f"  ステップ: クリップ構築 → 連結 → ffmpegエンコード", flush=True)
    t0 = time.time()
    build_video(
        prepared,
        out_path,
        size=(w, h),
        fps=cfg["video"]["fps"],
        codec=cfg["video"]["codec"],
        ken_burns=kb,
        subtitle_cfg=sub_cfg,
        bgm_clip=bgm_clip,
        preset=cfg["video"].get("preset", "veryfast"),
        title=resolved_title,
        title_cfg=title_cfg,
        sfx_path=sfx_path,
        sfx_volume_db=sfx_volume_db,
        caption_sfx_paths=caption_sfx,
        caption_sfx_volume_db=caption_sfx_volume_db,
        narration_volume=10 ** (narr_gain_db / 20),
        letterbox=cfg.get("letterbox"),
    )
    print(f"✅ 書き出し完了: {out_path}  ({time.time()-t0:.1f}s)")
    update_todo(Path(script_path).stem, plat)

    # クレジット記録(Pexels帰属義務)
    write_credits(script, img, out_path)

    # TikTok版 = X版と同一なのでコピーのみ
    if plat == "x":
        import shutil as _shutil
        tiktok_out = out_path.with_name("final_output_tiktok.mp4")
        _shutil.copy2(out_path, tiktok_out)
        credits_src = out_path.with_name(out_path.stem + ".credits.json")
        if credits_src.exists():
            _shutil.copy2(credits_src, out_path.with_name("final_output_tiktok.credits.json"))
        update_todo(Path(script_path).stem, "tiktok")
        print(f"📋 TikTok版: X版からコピー → {tiktok_out.name}")

    # サムネイル・メタ情報はX用(メイン)のみ生成
    if prepared and plat == "x":
        try:
            thumb_path = out_path.with_name("thumbnail.jpg")
            # ダッシュボードで選択済みのサムネがあれば優先
            sel_thumb = selections.get("thumbnail", {})
            if sel_thumb and Path(sel_thumb.get("image_path", "")).exists():
                thumb_img = Path(sel_thumb["image_path"])
                print(f"  サムネ: 選択済み画像を使用 ({thumb_img.name})")
            else:
                thumb_img = _pick_thumbnail_image(prepared)
            generate_thumbnail(
                title=resolved_title,
                image_path=thumb_img,
                out_path=thumb_path,
                font_path=ROOT / sub_cfg["font"],
                width=w,
                height=h,
            )
            print(f"🖼  サムネイル生成: {thumb_path.name}")
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] サムネイル生成失敗: {e}")

    # YouTube用メタ情報生成(X用のみ)
    if plat == "x":
        try:
            meta_path = out_path.with_name("youtube_meta.txt")
            credits_path = out_path.with_name(out_path.stem + ".credits.json")
            resolved_script = dict(script, title=resolved_title)
            write_youtube_meta(resolved_script, meta_path, credits_path if credits_path.exists() else None)
            print(f"📋 YouTube用メタ情報: {meta_path.name}")
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] YouTube用メタ情報生成失敗: {e}")

    return out_path


def _add_credit(img_provider, credit: dict) -> None:
    """キャッシュ画像のクレジットを provider.credits に復元する。"""
    if hasattr(img_provider, "credits"):
        img_provider.credits.append(credit)


def write_credits(script: dict, img_provider, out_path: Path) -> None:
    """画像の撮影者クレジットを credits.json に保存する。"""
    credits = getattr(img_provider, "credits", None)
    if not credits:
        return
    data = {
        "title": script.get("title"),
        "video": str(out_path.name),
        "image_credits": credits,
        "note": "Photos provided by Pexels. 概要欄に撮影者名とPexelsリンクを記載してください。",
    }
    cpath = out_path.with_name(out_path.stem + ".credits.json")
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    used = [c for c in credits if c.get("source") == "Pexels"]
    print(f"📝 クレジット記録: {cpath.name} (Pexels {len(used)}枚)")


def main():
    p = argparse.ArgumentParser(description="ディズニー雑学ショート動画パイプライン")
    p.add_argument("--script", default="scripts/sample.json", help="台本JSONのパス")
    p.add_argument("--out", default=None, help="出力MP4のパス")
    p.add_argument("--tts", default=None, help="TTSプロバイダ上書き (gtts|openai|elevenlabs)")
    p.add_argument("--bgm", default=None, help="BGM上書き (rotate|random|none|<path>)")
    p.add_argument("--allow-scrape", action="store_true", help="スクレイピング画像を許可(自己責任)")
    p.add_argument("--no-cache", action="store_true", help="キャッシュを使わず再生成する")
    p.add_argument("--no-ken-burns", action="store_true", help="Ken Burnsズームを無効化(高速)")
    p.add_argument("--platform", default="x", choices=["x", "youtube", "tiktok"],
                   help="出力プラットフォーム: x(BGMあり・フル尺) / youtube(BGMなし・60秒) / tiktok(BGMなし・フル尺)")
    p.add_argument("--selections", default=None, metavar="PATH",
                   help="image_dashboard.py が生成した image_selections.json のパス")
    args = p.parse_args()
    run(
        args.script,
        args.out,
        tts_override=args.tts,
        bgm_override=args.bgm,
        allow_scrape=args.allow_scrape,
        use_cache=not args.no_cache,
        ken_burns=False if args.no_ken_burns else None,
        platform=args.platform,
        selections_path=args.selections,
    )


if __name__ == "__main__":
    main()
