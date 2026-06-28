"""設定ローダー: config.yaml と .env を読み込む。

調整値は config.yaml、秘密情報(APIキー)は .env に分離している。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# プロジェクトルート (src/ の一つ上)
ROOT = Path(__file__).resolve().parent.parent

# .env を読み込む(存在しなくてもエラーにしない)
load_dotenv(ROOT / ".env")


def load_config(path: str | Path | None = None) -> dict:
    """config.yaml を辞書として読み込む。"""
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(key: str, default: str | None = None) -> str | None:
    """環境変数(.env 由来)を取得する。"""
    return os.environ.get(key, default)


# よく使うパスを定数化
SCRIPTS_DIR = ROOT / "scripts"
ASSETS_DIR = ROOT / "assets"
BGM_DIR = ASSETS_DIR / "bgm"
FONTS_DIR = ASSETS_DIR / "fonts"
WORK_DIR = ASSETS_DIR / "work"
AUDIO_DIR = WORK_DIR / "audio"
IMAGES_DIR = WORK_DIR / "images"
CLIPS_DIR = WORK_DIR / "clips"   # ローカル動画から切り出したクリップのキャッシュ
OUTPUT_DIR = ROOT / "output"

# 中間生成物フォルダを確実に用意
for _d in (AUDIO_DIR, IMAGES_DIR, CLIPS_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
