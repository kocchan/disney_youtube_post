"""共通ユーティリティ: 生成物キャッシュ。

出力ファイルの隣に .key サイドカーを置き、入力キー(narration/queryのハッシュ)が
一致すれば再生成をスキップする。--no-cache で無効化できる。
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def key_of(*parts: str) -> str:
    """入力要素からキャッシュキー(sha1)を作る。"""
    payload = "|".join(str(p) for p in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _keyfile(out_path: Path) -> Path:
    return out_path.with_suffix(out_path.suffix + ".key")


def is_cached(out_path: str | Path, key: str) -> bool:
    """out_path が存在し、サイドカーキーが一致すれば True。"""
    out_path = Path(out_path)
    kf = _keyfile(out_path)
    return out_path.exists() and kf.exists() and kf.read_text(encoding="utf-8").strip() == key


def mark_cached(out_path: str | Path, key: str) -> None:
    """out_path に対応するキーを記録する。"""
    _keyfile(Path(out_path)).write_text(key, encoding="utf-8")
