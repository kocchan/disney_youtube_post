"""TTS(テキスト読み上げ)モジュール。

TTSProvider 抽象を介して実装を差し替えられる(Strategy パターン)。
- GTTSProvider  : 無料・既定(gTTS = Google翻訳の非公式API)
- OpenAITTSProvider / ElevenLabsProvider : 将来の差し替え枠

各 provider は synthesize(text, out_path) で mp3 を生成する。
音声の尺(秒)は get_duration() で計測する。
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

_DEVNULL = subprocess.DEVNULL


def _retempo(mp3_path: Path, speed: float) -> None:
    """mp3 の再生速度を speed 倍に変える(音程は維持・ffmpeg atempo)。"""
    if abs(speed - 1.0) < 1e-3:
        return
    tmp = mp3_path.with_suffix(".tmp.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-filter:a", f"atempo={speed}", str(tmp)],
        check=True, stdout=_DEVNULL, stderr=_DEVNULL,
    )
    tmp.replace(mp3_path)


def _available_say_voices() -> set[str]:
    """say で利用可能な音声名の集合。"""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    except Exception:
        return set()
    return {line.split()[0] for line in out.splitlines() if line.strip()}


class TTSProvider(ABC):
    """TTS 実装の共通インターフェース。"""

    @abstractmethod
    def synthesize(self, text: str, out_path: str | Path) -> Path:
        """text を読み上げた mp3 を out_path に生成し、そのパスを返す。"""
        raise NotImplementedError


class GTTSProvider(TTSProvider):
    """gTTS による無料 TTS(声の選択は不可)。speed で再生速度のみ調整可。"""

    def __init__(self, lang: str = "ja", speed: float = 1.0):
        self.lang = lang
        self.speed = float(speed)

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        from gtts import gTTS

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        gTTS(text=text, lang=self.lang).save(str(out_path))
        _retempo(out_path, self.speed)
        return out_path


class SayTTSProvider(TTSProvider):
    """macOS の say による TTS。男性ボイス(Otoya等)選択 + 速度調整に対応。

    速度は ffmpeg atempo で正確に speed 倍にする(音程を保つ)。
    指定 voice が未導入なら男性ボイスにフォールバックする。
    """

    def __init__(self, voice: str = "Otoya", speed: float = 1.0, fallback: str = "Grandpa"):
        self.speed = float(speed)
        available = _available_say_voices()
        if voice in available:
            self.voice = voice
        else:
            self.voice = fallback if fallback in available else (next(iter(available), "Kyoko"))
            print(f"  [warn] 音声 '{voice}' が未導入 → '{self.voice}' で代用"
                  f"(Otoyaはシステム設定>アクセシビリティ>読み上げコンテンツ からDL可)")

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        aiff = out_path.with_suffix(".say.aiff")
        subprocess.run(["say", "-v", self.voice, "-o", str(aiff), text],
                       check=True, stdout=_DEVNULL, stderr=_DEVNULL)
        # AIFF → mp3 + 速度変更
        af = f"atempo={self.speed}" if abs(self.speed - 1.0) >= 1e-3 else "anull"
        subprocess.run(["ffmpeg", "-y", "-i", str(aiff), "-filter:a", af, str(out_path)],
                       check=True, stdout=_DEVNULL, stderr=_DEVNULL)
        aiff.unlink(missing_ok=True)
        return out_path


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS(将来の差し替え枠)。実装は M7 以降。"""

    def __init__(self, voice: str = "alloy", model: str = "tts-1"):
        self.voice = voice
        self.model = model

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        raise NotImplementedError("OpenAITTSProvider は未実装(後で差し替え)")


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs TTS(将来の差し替え枠)。実装は M7 以降。"""

    def __init__(self, voice_id: str | None = None):
        self.voice_id = voice_id

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        raise NotImplementedError("ElevenLabsProvider は未実装(後で差し替え)")


def get_tts_provider(name: str, lang: str = "ja", voice: str | None = None, speed: float = 1.0) -> TTSProvider:
    """プロバイダ名から実装インスタンスを返すファクトリ。"""
    name = (name or "gtts").lower()
    if name == "gtts":
        return GTTSProvider(lang=lang, speed=speed)
    if name == "say":
        return SayTTSProvider(voice=voice or "Otoya", speed=speed)
    if name == "openai":
        return OpenAITTSProvider(voice=voice or "onyx")
    if name == "elevenlabs":
        return ElevenLabsProvider(voice_id=voice)
    raise ValueError(f"未知の TTS provider: {name}")


def get_duration(audio_path: str | Path) -> float:
    """音声ファイルの尺(秒)を返す。"""
    from moviepy import AudioFileClip

    with AudioFileClip(str(audio_path)) as clip:
        return float(clip.duration)
