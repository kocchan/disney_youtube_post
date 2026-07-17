"""素材ライブラリ (assets/materials/) の管理ユーティリティ。

運用ルール:
  assets/materials/<category>/<subject>/ 配下に、事前に用意した画像（縦型変換済み）・
  トリミング済み動画クリップを置く。<category> は大分類（例: attractions / movies / generic）、
  <subject> は具体的な対象の自由な英語スラッグ（例: tower_of_terror）。
  カテゴリ分けをしない場合は assets/materials/<subject>/ の1階層でもよい
  （meta.json を直接持つフォルダなら深さを問わず素材フォルダとして認識する）。

  meta.json が唯一の索引で、ファイル名ごとに
  {type, description, tags, source, credit} を記録する。
  description・tags は Claude が内容を理解して選定・マッチングするために使う。

動画生成パイプラインはこのフォルダ以外から画像・動画を取得しない
（Web検索・API取得は material-collector スキルでライブラリを充実させる時のみ使う）。
"""
from __future__ import annotations

import json
from pathlib import Path

from config import ROOT

MATERIALS_DIR = ROOT / "assets" / "materials"
META_FILENAME = "meta.json"


def list_subject_dirs(materials_dir: Path = MATERIALS_DIR) -> list[Path]:
    """meta.json を直接持つフォルダを深さを問わず列挙する（フラット/カテゴリ分け両対応）。"""
    if not materials_dir.exists():
        return []
    return sorted(p.parent for p in materials_dir.rglob(META_FILENAME))


def load_meta(subject_dir: Path) -> dict[str, dict]:
    """<subject>/meta.json を読み込む。存在しなければ空dict。"""
    p = subject_dir / META_FILENAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_meta(subject_dir: Path, meta: dict[str, dict]) -> None:
    subject_dir.mkdir(parents=True, exist_ok=True)
    p = subject_dir / META_FILENAME
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def add_entry(
    subject_dir: Path,
    filename: str,
    *,
    description: str,
    tags: list[str],
    type_: str = "image",
    source: str = "user",
    credit: dict | None = None,
) -> None:
    """1ファイル分のメタ情報を meta.json に追記/更新する。"""
    meta = load_meta(subject_dir)
    meta[filename] = {
        "type": type_,
        "description": description,
        "tags": tags,
        "source": source,
        "credit": credit or {},
    }
    save_meta(subject_dir, meta)


def entry_blob(subject_dir: Path, filename: str, entry: dict) -> str:
    """1ファイル分のメタ情報からマッチング用テキストblobを作る。"""
    parts = [
        subject_dir.name.replace("_", " ").replace("-", " "),
        entry.get("description", ""),
        " ".join(entry.get("tags", [])),
    ]
    if subject_dir.parent != MATERIALS_DIR:
        parts.append(subject_dir.parent.name.replace("_", " ").replace("-", " "))
    return " ".join(parts).lower()


def iter_entries(materials_dir: Path = MATERIALS_DIR):
    """全サブフォルダの全エントリを (subject_dir, filename, entry) で列挙する。"""
    for subject_dir in list_subject_dirs(materials_dir):
        meta = load_meta(subject_dir)
        for filename, entry in meta.items():
            fp = subject_dir / filename
            if fp.exists():
                yield subject_dir, filename, entry


# ─── 集約インデックス (assets/materials/index.json) ────────────────────────────
#
# 全サブフォルダの meta.json を1ファイルに集約したマップ。動画作成時の候補マッチング
# (image_dashboard.py) はこのインデックスを参照する（毎回全フォルダを走査しない）。
# material-collector で素材を追加した際・動画作成の候補取得を実行した際に自動再生成される。

INDEX_FILENAME = "index.json"


def rebuild_index(materials_dir: Path = MATERIALS_DIR) -> Path:
    """全 meta.json を集約した index.json を再生成して返す。"""
    entries = []
    for subject_dir, filename, entry in iter_entries(materials_dir):
        rel_parts = subject_dir.relative_to(materials_dir).parts
        category = rel_parts[0] if len(rel_parts) > 1 else ""
        subject = rel_parts[-1]
        entries.append({
            "category": category,
            "subject": subject,
            "filename": filename,
            "path": str(subject_dir / filename),
            "type": entry.get("type", "image"),
            "description": entry.get("description", ""),
            "tags": entry.get("tags", []),
            "source": entry.get("source", ""),
        })
    index_path = materials_dir / INDEX_FILENAME
    index_path.write_text(
        json.dumps({"count": len(entries), "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index_path


def load_index(materials_dir: Path = MATERIALS_DIR, *, refresh: bool = True) -> list[dict]:
    """index.json を読み込む。refresh=True（既定）なら参照前に必ず再生成して最新化する。"""
    if refresh or not (materials_dir / INDEX_FILENAME).exists():
        rebuild_index(materials_dir)
    try:
        data = json.loads((materials_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        return data.get("entries", [])
    except Exception:
        rebuild_index(materials_dir)
        data = json.loads((materials_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        return data.get("entries", [])


def index_blob(entry: dict) -> str:
    """index.json の1エントリからマッチング用テキストblobを作る。"""
    parts = [
        entry.get("category", "").replace("_", " "),
        entry.get("subject", "").replace("_", " "),
        entry.get("description", ""),
        " ".join(entry.get("tags", [])),
    ]
    return " ".join(parts).lower()


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="素材ライブラリの index.json を再生成する")
    p.parse_args()
    path = rebuild_index()
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    by_cat: dict[str, int] = {}
    for e in entries:
        by_cat[e["category"] or "(uncategorized)"] = by_cat.get(e["category"] or "(uncategorized)", 0) + 1
    print(f"✅ index.json 再生成 → {path} ({len(entries)}件)")
    for cat, n in sorted(by_cat.items()):
        print(f"   {cat}: {n}件")


if __name__ == "__main__":
    main()
