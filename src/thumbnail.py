"""サムネイル生成モジュール。

背景画像を全面に敷き、下部グラデーションオーバーレイの上に
タイトルを2行で重ねる。output/thumbnail.jpg に書き出す。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _fill_crop(img: Image.Image, w: int, h: int, anchor: str = "center") -> Image.Image:
    """画像をアスペクト比を保ちつつ w×h にクロップ。

    anchor: "center"(既定) / "top" / "bottom"
    """
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    if anchor == "top":
        top = 0
    elif anchor == "bottom":
        top = nh - h
    else:
        top = (nh - h) // 2
    top = max(0, min(top, nh - h))
    return img.crop((left, top, left + w, top + h))


def _wrap_title(text: str, max_chars: int = 10) -> list[str]:
    """タイトルを2行に分割。中点に最も近い自然な区切り位置で分割する。"""
    if len(text) <= max_chars:
        return [text]
    mid = len(text) // 2
    break_chars = "のはがでをにもとや・　ーっ！？、"
    best_i: int | None = None
    best_dist = len(text)
    for i, ch in enumerate(text):
        if ch in break_chars:
            dist = abs((i + 1) - mid)
            if dist < best_dist:
                best_dist = dist
                best_i = i
    if best_i is not None:
        return [text[:best_i + 1], text[best_i + 1:]]
    return [text[:mid], text[mid:]]


def generate_thumbnail(
    title: str,
    image_path: str | Path,
    out_path: str | Path,
    font_path: str | Path,
    width: int = 1080,
    height: int = 1920,
    image_path_2: str | Path | None = None,  # 後方互換のため残すが未使用
) -> Path:
    """サムネイルを生成して out_path に保存する。

    image_path を全面背景として使用し、下部グラデーションの上に
    タイトルを2行で中央揃えで描画する。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --- 背景: 全面クロップ(上寄り = 城の上部が映りやすい) ---
    bg = _fill_crop(Image.open(image_path).convert("RGB"), width, height, anchor="top")

    # --- グラデーションオーバーレイ: 全体を薄く暗くしつつ下部をより暗く ---
    base_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 90))
    bg_rgba = Image.alpha_composite(bg.convert("RGBA"), base_overlay)

    grad = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    grad_start = height // 2
    for row in range(grad_start, height):
        alpha = int(160 * (row - grad_start) / (height - grad_start))
        grad_draw.line([(0, row), (width, row)], fill=(0, 0, 0, alpha))

    bg_rgba = Image.alpha_composite(bg_rgba, grad)
    bg = bg_rgba.convert("RGB")
    draw = ImageDraw.Draw(bg)

    # --- タイトルを2行に分割 ---
    lines = _wrap_title(title, max_chars=10)

    # --- フォントサイズを自動調整(最長行が width-100 以内に収まるまで) ---
    font_size = 120
    font = ImageFont.truetype(str(font_path), font_size)
    while font_size > 60:
        font = ImageFont.truetype(str(font_path), font_size)
        max_w = max(font.getbbox(ln)[2] - font.getbbox(ln)[0] for ln in lines)
        if max_w <= width - 100:
            break
        font_size -= 4

    line_h = int(font_size * 1.45)
    total_h = line_h * len(lines)

    y = (height - total_h) // 2

    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        tw = bbox[2] - bbox[0]
        x = (width - tw) // 2
        color = _hex("#FFD400") if i == 0 else _hex("#FFFFFF")
        draw.text((x, y), line, font=font, fill=color,
                  stroke_width=8, stroke_fill=(0, 0, 0))
        y += line_h

    bg.save(out_path, quality=95)
    return out_path
