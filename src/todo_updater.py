"""TODO.md のコンテンツ制作進捗表を自動更新するユーティリティ。

スクリプト stem（例: "21_summer_survival"）から行番号を特定し、
指定列（画像/X版/TikTok/YouTube）を ✅ に書き換える。
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
TODO_PATH = ROOT / "TODO.md"

# 列インデックス（| # | ネタ | ① 画像 | ② X版 | ③ TikTok | ④ YouTube | ...）
_COL = {
    "image":   2,
    "x":       3,
    "tiktok":  4,
    "youtube": 5,
}


def _script_num(stem: str) -> str | None:
    """'21_summer_survival' → '21'"""
    m = re.match(r"^(\d+)_", stem)
    return m.group(1) if m else None


def update_todo(stem: str, column: str) -> bool:
    """
    TODO.md の stem に対応する行の column を ✅ に更新する。

    Parameters
    ----------
    stem   : スクリプトファイルの stem (例: "21_summer_survival")
    column : "image" / "x" / "tiktok" / "youtube"

    Returns
    -------
    bool : 更新できた場合 True
    """
    if not TODO_PATH.exists():
        return False

    col_idx = _COL.get(column)
    if col_idx is None:
        return False

    num = _script_num(stem)
    if num is None:
        return False

    lines = TODO_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    updated = False
    for i, line in enumerate(lines):
        # テーブル行かつ先頭列が num と一致
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        # cells[0]='' cells[1]='# ' cells[2]='ネタ' ...
        if len(cells) <= col_idx + 1:
            continue
        if cells[1].strip() != num:
            continue

        # 対象列を ✅ に置換（🔄 / ❌ / 既存の ✅ にかかわらず）
        old_val = cells[col_idx + 1].strip()
        if old_val == "✅":
            break  # すでに完了
        cells[col_idx + 1] = f" ✅ "
        lines[i] = "|".join(cells)
        updated = True
        break

    if updated:
        TODO_PATH.write_text("".join(lines), encoding="utf-8")
        print(f"  [todo] #{num} {column} → ✅")

    return updated
