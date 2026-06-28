"""BGM モジュール。

assets/bgm/ の音源を「使い回し」ながら動画尺ぶんの BGM 帯を作る。
- selection: "rotate" … 3曲を順番につなぎ、尺に足りなければ先頭へループ
              "random" … プール from 1曲を選んでループ
              <パス>   … 指定ファイルをループ
ナレーションより小さい音量(bgm_gain_db)に絞り、末尾はフェードアウトする。
"""
from __future__ import annotations

from pathlib import Path

from config import BGM_DIR


def _pool() -> list[Path]:
    """assets/bgm/ 内の音源ファイル一覧(名前順)。"""
    exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
    return sorted(p for p in BGM_DIR.glob("*") if p.suffix.lower() in exts)


def _db_to_factor(db: float) -> float:
    return 10 ** (db / 20)


def build_bgm_bed(total_dur: float, cfg: dict, fade_out: float = 2.0):
    """動画尺(total_dur)ぶんの BGM AudioClip を返す。BGM が無ければ None。"""
    from moviepy import AudioFileClip, concatenate_audioclips
    from moviepy.audio.fx import AudioFadeOut, MultiplyVolume

    pool = _pool()
    if not pool:
        return None

    selection = str(cfg.get("selection", "rotate"))
    if selection == "rotate":
        order = pool
    elif selection == "random":
        # 乱数を使わず先頭1曲(決定的)。必要なら順序を変えるだけ。
        order = [pool[0]]
    else:
        # 明示パス(絶対 or プロジェクト相対)
        p = Path(selection)
        if not p.is_absolute():
            p = BGM_DIR / Path(selection).name
        order = [p] if p.exists() else pool

    # 尺を満たすまで順番につなぐ(足りなければ先頭へループ)
    clips = []
    acc = 0.0
    i = 0
    guard = 0
    while acc < total_dur and guard < 1000:
        src = order[i % len(order)]
        c = AudioFileClip(str(src))
        clips.append(c)
        acc += c.duration
        i += 1
        guard += 1

    bed = concatenate_audioclips(clips).subclipped(0, total_dur)
    factor = _db_to_factor(float(cfg.get("bgm_gain_db", -18.0)))
    effects = [MultiplyVolume(factor)]
    if fade_out and total_dur > fade_out:
        effects.append(AudioFadeOut(fade_out))
    return bed.with_effects(effects)
