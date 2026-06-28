"""シーン切り替え効果音モジュール。

assets/sfx/ にカスタムファイル(swoosh.wav 等)があればそれを使い、
なければ numpy でスウッシュ音を自動生成して transition.wav にキャッシュする。
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

_SFX_DIR = Path(__file__).parent.parent / "assets" / "sfx"
_CACHE = _SFX_DIR / "transition.wav"
_PON_CACHE = _SFX_DIR / "pon.wav"
_DON_CACHE = _SFX_DIR / "don.wav"
_CUSTOM_NAMES = ("swoosh.wav", "swoosh.mp3", "transition_custom.wav", "transition_custom.mp3")


def _write_wav_mono(path: Path, pcm_bytes: bytes, sr: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(pcm_bytes)))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(pcm_bytes)))
        f.write(pcm_bytes)


def _write_pon(path: Path, sr: int = 44100) -> None:
    """テロップ出現音: 高音の短い「ポン」"""
    n = int(0.12 * sr)
    t = np.linspace(0, 0.12, n)
    wave = np.sin(2 * np.pi * 1100 * t)
    env = np.exp(-t * 40)
    pcm = (wave * env * 0.55 * 32767).astype(np.int16).tobytes()
    _write_wav_mono(path, pcm, sr)


def _write_don(path: Path, sr: int = 44100) -> None:
    """強調音: 低音の「ドン」"""
    n = int(0.45 * sr)
    t = np.linspace(0, 0.45, n)
    wave = np.sin(2 * np.pi * 75 * t) + 0.6 * np.sin(2 * np.pi * 110 * t)
    env = np.exp(-t * 10)
    pcm = (np.clip(wave * env * 0.4, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    _write_wav_mono(path, pcm, sr)


def _write_swoosh(path: Path, duration: float = 0.35, sr: int = 44100) -> None:
    """高→低スイープのスウッシュ音を WAV(モノ16bit)に書き出す。"""
    n = int(duration * sr)
    t = np.linspace(0, duration, n)
    freq = np.linspace(1200.0, 200.0, n)
    phase = np.cumsum(freq / sr)
    wave = np.sin(2 * np.pi * phase)
    env = np.exp(-t * 10) * (1 - np.exp(-t * 50))
    pcm_data = (np.clip(wave * env * 0.5, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    _write_wav_mono(path, pcm_data, sr)


def get_sfx_path(sfx_cfg: dict) -> Path | None:
    """シーン切り替え音のパスを返す。和太鼓でドドン.mp3 を優先し、なければ生成。"""
    if not sfx_cfg.get("enabled", True):
        return None
    # 和太鼓でドドン → カスタム名 → 生成済みキャッシュ の優先順
    for fname in ("和太鼓でドドン.mp3", *_CUSTOM_NAMES):
        p = _SFX_DIR / fname
        if p.exists():
            return p
    if not _CACHE.exists():
        _write_swoosh(_CACHE)
    return _CACHE


def get_caption_sfx_paths(sfx_cfg: dict) -> tuple[list[Path] | None, Path | None]:
    """(ポン音リスト, ドン音パス) を返す。caption_enabled=False なら (None, None)。

    ポン音は決定ボタンを押す*.mp3 をすべて収集し、テロップ出現ごとにローテーションする。
    ドン音は和太鼓でカカッ.mp3 を使い、なければ生成済み don.wav にフォールバック。
    """
    if not sfx_cfg.get("caption_enabled", True):
        return None, None

    # ポン: 決定ボタン系を名前順で収集
    pon_list = sorted(_SFX_DIR.glob("決定ボタンを押す*.mp3"))
    if not pon_list:
        if not _PON_CACHE.exists():
            _write_pon(_PON_CACHE)
        pon_list = [_PON_CACHE]

    # ドン: 和太鼓でカカッ
    don = _SFX_DIR / "和太鼓でカカッ.mp3"
    if not don.exists():
        if not _DON_CACHE.exists():
            _write_don(_DON_CACHE)
        don = _DON_CACHE

    return pon_list, don
