"""TODO.md のコンテンツ制作進捗表を自動更新するユーティリティ。

スクリプト stem（例: "21_summer_survival"）から行番号を特定し、
指定列（画像/TikTok/YouTube）を ✅ に書き換える。
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
TODO_PATH = ROOT / "TODO.md"

# 列を判定するための見出しセル内の目印文字（ヘッダー行から動的に列位置を検出する）
_COL_MARKERS = {
    "image":   "①",
    "tiktok":  "②",
    "youtube": "③",
}


def _script_num(stem: str) -> str | None:
    """'21_summer_survival' → '21'"""
    m = re.match(r"^(\d+)_", stem)
    return m.group(1) if m else None


def _detect_col_index(lines: list[str], column: str) -> int | None:
    """ヘッダー行（| # | ネタ | ① 画像 | ... |）から column に対応するセル位置を検出する。

    列の追加・並び替えがあってもハードコードした index に依存しないようにする。
    """
    marker = _COL_MARKERS.get(column)
    if marker is None:
        return None
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 2 or cells[1].strip() != "#":
            continue  # コンテンツ制作進捗テーブルのヘッダー行のみ対象（先頭列が "#"）
        for idx, cell in enumerate(cells):
            if marker in cell:
                return idx
        return None  # ヘッダー行は見つかったがマーカー不一致
    return None


def update_todo(stem: str, column: str) -> bool:
    """
    TODO.md の stem に対応する行の column を ✅ に更新する。

    Parameters
    ----------
    stem   : スクリプトファイルの stem (例: "21_summer_survival")
    column : "image" / "tiktok" / "youtube"

    Returns
    -------
    bool : 更新できた場合 True
    """
    if not TODO_PATH.exists():
        return False

    num = _script_num(stem)
    if num is None:
        return False

    lines = TODO_PATH.read_text(encoding="utf-8").splitlines(keepends=True)

    col_idx = _detect_col_index(lines, column)
    if col_idx is None:
        return False

    updated = False
    for i, line in enumerate(lines):
        # テーブル行かつ先頭列が num と一致
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) <= col_idx:
            continue
        if cells[1].strip() != num:
            continue

        # 対象列を ✅ に置換（🔄 / ❌ / 既存の ✅ にかかわらず）
        old_val = cells[col_idx].strip()
        if old_val == "✅":
            break  # すでに完了
        cells[col_idx] = f" ✅ "
        lines[i] = "|".join(cells)
        updated = True
        break

    if updated:
        TODO_PATH.write_text("".join(lines), encoding="utf-8")
        print(f"  [todo] #{num} {column} → ✅")

    return updated
