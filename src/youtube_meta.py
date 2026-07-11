"""YouTube ショート用メタ情報生成モジュール。

台本(script.json)の内容からタイトル・説明文・ハッシュタグを生成し
output/youtube_meta.txt に書き出す。
"""
from __future__ import annotations

from pathlib import Path


_HASHTAGS = (
    "#ディズニー #ディズニーランド #東京ディズニーランド #TDL "
    "#ディズニー雑学 #ディズニー裏話 #ディズニートリビア "
    "#shorts #YouTubeShorts #雑学 #豆知識"
)


def _make_title(script_title: str, scenes: list[dict]) -> str:
    """YouTube用タイトルを生成する(32文字以内推奨)。"""
    # 台本タイトルをそのまま使いつつ、頭に刺さるプレフィックスを付ける
    base = script_title
    # 「〇選」が含まれていれば数字を前に出す
    for word in ["10選", "7選", "5選", "3選"]:
        if word in base:
            return f"【{word}】" + base.replace(word, "").strip("　 ")
    return f"【保存版】{base}"


def _make_description(script: dict, credits_path: Path | None = None) -> str:
    """YouTube用説明文を生成する。"""
    title = script.get("title", "")
    scenes = script.get("scenes", [])

    # 各シーンのnarrationから1文目を抜粋してインデックスを作る
    lines = [f"▶ {title}\n"]
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📌 この動画の内容")
    for i, s in enumerate(scenes[1:-1], 1):  # フックと締めは除く
        narr = s.get("narration", "")
        first = narr.split("。")[0].replace("\n", "")[:40]
        lines.append(f"  {i}. {first}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💬 何個知ってましたか？コメントで教えてください！")
    lines.append("")
    lines.append("👍 参考になったらいいね＆チャンネル登録お願いします！")
    lines.append("")

    # Pexelsクレジット
    if credits_path and credits_path.exists():
        import json
        try:
            data = json.loads(credits_path.read_text(encoding="utf-8"))
            pexels = [c for c in data.get("image_credits", []) if c.get("source") == "Pexels"]
            if pexels:
                lines.append("━━━━━━━━━━━━━━━━━━━━")
                lines.append("📷 Photo credits (Pexels)")
                for c in pexels:
                    name = c.get("photographer", "")
                    url = c.get("photographer_url", "")
                    if name:
                        lines.append(f"  {name} - {url}")
        except Exception:
            pass

    lines.append("")
    lines.append(_HASHTAGS)
    return "\n".join(lines)


def read_resolved_title(meta_txt_path: Path) -> str | None:
    """youtube_meta.txt から解決済み({count}置換済み)タイトルを読み取る。"""
    if not meta_txt_path.exists():
        return None
    lines = meta_txt_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "タイトル" in line and "━" in line:
            for candidate in lines[i + 1:]:
                if candidate.strip():
                    return candidate.strip()
    return None


def write_youtube_meta(script: dict, out_path: Path, credits_path: Path | None = None) -> Path:
    """YouTube用メタ情報を out_path に書き出す。"""
    yt_title = _make_title(script.get("title", ""), script.get("scenes", []))
    description = _make_description(script, credits_path)

    content = f"""# YouTube ショート用メタ情報
# ※この内容をコピーしてYouTube投稿時に貼り付けてください

━━━━━ タイトル ━━━━━
{yt_title}

━━━━━ 説明文 ━━━━━
{description}
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return out_path
