"""動画合成モジュール(MoviePy 2.x)。

各シーンの画像＋音声から固定サイズ(縦型)のクリップを作り、連結して MP4 を書き出す。
この段階では字幕・BGM は付けない(M4/M5 で追加)。
"""
from __future__ import annotations

from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    concatenate_videoclips,
)


def make_scene_clip(
    image_path: str | Path | None,
    audio_path: str | Path,
    size: tuple[int, int],
    ken_burns: bool = True,
    scene: dict | None = None,
    subtitle_cfg: dict | None = None,
    narration_volume: float = 1.0,
    letterbox: dict | None = None,
    clip_path: str | Path | None = None,
):
    """1シーン分のクリップを作る。

    clip_path が渡された場合はその動画を背景に使う（音声はミュート・尺に合わせてトリム/ループ）。
    なければ image_path の静止画 + Ken Burns ズームを使う。
    letterbox が有効なら上下黒帯を入れ、映像を中央エリアに収める。
    """
    audio = AudioFileClip(str(audio_path))
    if abs(narration_volume - 1.0) > 1e-3:
        from moviepy.audio.fx import MultiplyVolume
        audio = audio.with_effects([MultiplyVolume(narration_volume)])
    dur = float(audio.duration)

    W, H = size
    top_bar = int((letterbox or {}).get("top_bar", 0)) if letterbox and letterbox.get("enabled") else 0
    bot_bar = int((letterbox or {}).get("bottom_bar", 0)) if letterbox and letterbox.get("enabled") else 0
    content_h = H - top_bar - bot_bar  # 映像が表示される縦幅

    content_size = (W, content_h)

    if clip_path and Path(clip_path).exists():
        # ── ローカル動画クリップを背景に使う ──
        from moviepy import VideoFileClip
        from moviepy import concatenate_videoclips as _cat
        raw = VideoFileClip(str(clip_path), audio=False)
        # 尺が短い場合はループして narration に合わせる
        if raw.duration < dur - 0.05:
            n = int(dur / raw.duration) + 2
            raw = _cat([raw] * n)
        raw = raw.subclipped(0, dur)
        # content_size に収まるようスケール→中央クロップ
        scale = max(W / raw.w, content_h / raw.h)
        raw = raw.resized(scale)
        cx = int((raw.w - W) / 2)
        cy = int((raw.h - content_h) / 2)
        raw = raw.cropped(x1=cx, y1=cy, x2=cx + W, y2=cy + content_h)
        content_clip = raw.with_position((0, top_bar))
    else:
        # ── 静止画 + Ken Burns ──
        img = ImageClip(str(image_path)).with_duration(dur)
        if ken_burns:
            img = img.resized(lambda t: 1.0 + 0.06 * t / dur)
        img = img.with_position(("center", "center"))
        content_clip = CompositeVideoClip([img], size=content_size).with_duration(dur)
        content_clip = content_clip.with_position((0, top_bar))

    # 黒背景の全画面に映像エリアを貼る
    from moviepy import ColorClip
    bg = ColorClip(size=size, color=(0, 0, 0)).with_duration(dur)
    layers = [bg, content_clip]

    # 字幕は映像エリア内の座標で描画されるよう subtitle_cfg を調整して渡す
    if scene is not None and subtitle_cfg is not None:
        from subtitles import build_subtitle_clips
        adjusted_cfg = dict(subtitle_cfg)
        if subtitle_cfg.get("position", "bottom") == "center":
            # センター配置: 映像エリアの中央 → 全画面座標に換算
            pass  # render_caption 内で position=center は全画面Hで計算するため上書き
        # render_caption は全画面サイズで描画するため size をそのまま渡す
        layers += build_subtitle_clips(scene, dur, size, adjusted_cfg, y_offset=top_bar)

    clip = CompositeVideoClip(layers, size=size).with_duration(dur)
    clip = clip.with_audio(audio)
    return clip


def build_video(
    scenes: list[dict],
    out_path: str | Path,
    size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    codec: str = "libx264",
    ken_burns: bool = True,
    subtitle_cfg: dict | None = None,
    bgm_clip=None,
    preset: str = "veryfast",
    threads: int | None = None,
    title: str | None = None,
    title_cfg: dict | None = None,
    sfx_path: str | Path | None = None,
    sfx_volume_db: float = -10.0,
    caption_sfx_paths: tuple | None = None,
    caption_sfx_volume_db: float = -14.0,
    narration_volume: float = 1.0,
    letterbox: dict | None = None,
):
    """各シーン(image_path/audio_path を持つ dict)を連結して MP4 を書き出す。

    title + title_cfg が渡された場合は上部にタイトルオーバーレイを焼き込む。
    sfx_path が渡された場合はシーン切り替えごとに効果音を挿入する。
    """
    n_scenes = len(scenes)
    clips = []
    for i, s in enumerate(scenes, 1):
        sid = s.get("scene", {}).get("id", i)
        print(f"  [{i}/{n_scenes}] シーン {sid} クリップ構築中…", flush=True)
        clips.append(make_scene_clip(
            s["image_path"], s["audio_path"], size, ken_burns,
            scene=s.get("scene"), subtitle_cfg=subtitle_cfg,
            narration_volume=narration_volume,
            letterbox=letterbox,
            clip_path=s.get("clip_path"),
        ))
    print(f"  全 {n_scenes} シーン構築完了、エンコード開始…", flush=True)
    final = concatenate_videoclips(clips, method="chain")

    # タイトルオーバーレイ(動画全体の上に常時表示)
    if title and title_cfg and title_cfg.get("enabled", True):
        from subtitles import render_title_overlay
        title_arr = render_title_overlay(title, size, title_cfg)
        title_clip = ImageClip(title_arr, transparent=True).with_duration(final.duration)
        final = CompositeVideoClip([final, title_clip], size=size)

    # BGM + シーン切り替え効果音を合成
    audio_layers = []
    if final.audio is not None:
        audio_layers.append(final.audio)
    if bgm_clip is not None:
        audio_layers.append(bgm_clip)
    from moviepy.audio.fx import MultiplyVolume

    # シーン切り替えスウッシュ音
    if sfx_path and len(clips) > 1:
        factor = 10 ** (sfx_volume_db / 20)
        t = 0.0
        for clip in clips[:-1]:
            t += clip.duration
            sfx = AudioFileClip(str(sfx_path))
            sfx = sfx.with_effects([MultiplyVolume(factor)]).with_start(t)
            audio_layers.append(sfx)

    # テロップ出現音（ポン×ローテーション）・強調音（ドン）
    if caption_sfx_paths and subtitle_cfg:
        pon_paths, don_path = caption_sfx_paths
        cap_factor = 10 ** (caption_sfx_volume_db / 20)
        max_chars = int(subtitle_cfg.get("max_chars_per_line", 13))
        from subtitles import get_caption_times
        scene_start = 0.0
        pon_idx = 0
        for s, clip in zip(scenes, clips):
            scene_data = s.get("scene", {})
            for cap_t, has_kw in get_caption_times(scene_data, clip.duration, max_chars):
                if has_kw:
                    sfx_file = don_path
                else:
                    sfx_file = pon_paths[pon_idx % len(pon_paths)] if pon_paths else None
                    pon_idx += 1
                if sfx_file:
                    cap_sfx = AudioFileClip(str(sfx_file))
                    cap_sfx = cap_sfx.with_effects([MultiplyVolume(cap_factor)]).with_start(scene_start + cap_t)
                    audio_layers.append(cap_sfx)
            scene_start += clip.duration

    if audio_layers:
        final = final.with_audio(CompositeAudioClip(audio_layers))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import os

    final.write_videofile(
        str(out_path),
        fps=fps,
        codec=codec,
        audio_codec="aac",
        preset=preset,                       # エンコード速度/サイズの兼ね合い
        threads=threads or os.cpu_count(),   # 全コア使用で高速化
        logger="bar",                        # ffmpegエンコード進捗を表示
    )

    final.close()
    for c in clips:
        c.close()
    return out_path
