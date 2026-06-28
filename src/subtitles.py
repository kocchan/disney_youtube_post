"""字幕(テロップ)モジュール。

セリフを短く分割し、画面中央下部に配置する(全文ベタ貼りしない)。
keywords に一致する語は色を変えて強調する。
Pillow で各キャプションを透過画像として描画し、MoviePy の ImageClip にする。
"""
from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _hex(c: str) -> tuple[int, int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)


def split_captions(text: str, max_chars: int) -> list[str]:
    """セリフを句読点で区切り、1キャプション(=1画面)ぶんに束ねる。

    1キャプションは最大 2 行ぶん(= max_chars * 2 文字)を目安にする。
    """
    parts = re.split(r"(?<=[。！？、])", text)
    parts = [p.strip() for p in parts if p.strip()]
    captions: list[str] = []
    cur = ""
    for p in parts:
        if not cur or len(cur) + len(p) <= max_chars * 2:
            cur += p
        else:
            captions.append(cur)
            cur = p
    if cur:
        captions.append(cur)
    return captions


def wrap_lines(caption: str, max_chars: int) -> list[str]:
    """1キャプションを max_chars 文字ごとに改行する(句読点位置を優先)。"""
    lines: list[str] = []
    s = caption
    while len(s) > max_chars:
        window = s[:max_chars]
        idx = max(window.rfind("、"), window.rfind("。"))
        cut = idx + 1 if idx >= max_chars // 2 else max_chars
        lines.append(s[:cut])
        s = s[cut:]
    if s:
        lines.append(s)
    return lines


def _keyword_mask(line: str, keywords: list[str]) -> list[bool]:
    """各文字が強調キーワードに含まれるかの真偽配列を返す。"""
    mask = [False] * len(line)
    for kw in keywords or []:
        if not kw:
            continue
        start = 0
        while True:
            i = line.find(kw, start)
            if i < 0:
                break
            for j in range(i, i + len(kw)):
                mask[j] = True
            start = i + len(kw)
    return mask


def wrap_with_mask(caption: str, keywords: list[str], max_chars: int) -> list[tuple[str, list[bool]]]:
    """キャプションを行に分割し、各行に「強調マスク」を割り当てて返す。

    句読点(。、)は分割位置の計算には使うが、表示テキストからは除去する。
    """
    mask = _keyword_mask(caption, keywords)
    lines = wrap_lines(caption, max_chars)
    out: list[tuple[str, list[bool]]] = []
    pos = 0
    for ln in lines:
        line_mask = mask[pos:pos + len(ln)]
        # 句読点を表示から除去（マスクも同期して削除）
        clean_ln = ""
        clean_mask: list[bool] = []
        for ch, m in zip(ln, line_mask):
            if ch not in "。、":
                clean_ln += ch
                clean_mask.append(m)
        out.append((clean_ln, clean_mask))
        pos += len(ln)
    return out


def render_caption(lines_with_mask: list[tuple[str, list[bool]]], size: tuple[int, int], cfg: dict, y_offset: int = 0) -> np.ndarray:
    """キャプション(複数行＋強調マスク)を全画面サイズの透過RGBA画像として描画する。

    y_offset: レターボックスの上帯高さ。center配置の基準をコンテンツエリア内にずらす。
    """
    W, H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(cfg["font"]), cfg["font_size"])

    normal, hi, stroke = _hex(cfg["color"]), _hex(cfg["highlight_color"]), _hex(cfg["stroke_color"])
    sw = int(cfg["stroke_width"])
    line_h = int(cfg["font_size"] * 1.35)

    total_h = line_h * len(lines_with_mask)
    content_h = H - y_offset - int(cfg.get("bottom_bar", 0))
    if cfg.get("position", "bottom") == "center":
        y0 = y_offset + (content_h - total_h) // 2
    else:
        y0 = H - int(cfg["bottom_margin"]) - total_h

    for li, (line, mask) in enumerate(lines_with_mask):
        widths = [font.getlength(ch) for ch in line]
        x = (W - sum(widths)) / 2
        y = y0 + li * line_h
        for ch, w, is_kw in zip(line, widths, mask):
            draw.text(
                (x, y), ch, font=font,
                fill=hi if is_kw else normal,
                stroke_width=sw, stroke_fill=stroke, anchor="la",
            )
            x += w
    return np.array(img)


def _wrap_by_width(text: str, font, max_w: int) -> list[str]:
    """ピクセル幅ベースでテキストを折り返す。各行が max_w 以内に収まるよう保証する。"""
    break_chars = "のはがでをにもとや・　—】！。、」"
    lines = []
    remaining = text
    while remaining:
        # max_w に収まる最大文字数を二分探索
        lo, hi = 1, len(remaining)
        while lo < hi:
            m = (lo + hi + 1) // 2
            w = font.getbbox(remaining[:m])[2] - font.getbbox(remaining[:m])[0]
            if w <= max_w:
                lo = m
            else:
                hi = m - 1
        cut = lo
        # まだ残りがある場合、自然な区切り文字を後ろから探してそこで切る
        if cut < len(remaining):
            for i in range(lo, max(lo // 2, 0), -1):
                if remaining[i - 1] in break_chars:
                    cut = i
                    break
        lines.append(remaining[:cut])
        remaining = remaining[cut:]
    return lines


def render_title_overlay(title: str, size: tuple[int, int], cfg: dict) -> np.ndarray:
    """タイトルを上部黒帯の下端に寄せて常時表示する全画面透過 RGBA 画像を生成する。"""
    W, H = size
    font_size = int(cfg.get("font_size", 80))
    text_color = _hex(cfg.get("color", "#FFD400"))
    stroke_color = _hex(cfg.get("stroke_color", "#000000"))
    stroke_width = int(cfg.get("stroke_width", 8))
    bg_alpha = int(cfg.get("bg_alpha", 180))
    padding = int(cfg.get("padding", 30))
    top_bar = int(cfg.get("top_bar", 0))

    # stroke込みで収まる最大テキスト幅
    max_text_w = W - stroke_width * 2 - 80

    # フォントサイズを縮小しながら3行以内に収まる折り返しを探す
    font = ImageFont.truetype(str(cfg["font"]), font_size)
    lines = _wrap_by_width(title, font, max_text_w)
    while len(lines) > 3 and font_size > 36:
        font_size -= 4
        font = ImageFont.truetype(str(cfg["font"]), font_size)
        lines = _wrap_by_width(title, font, max_text_w)

    line_h = int(font_size * 1.3)
    text_total_h = line_h * len(lines)
    strip_h = text_total_h + padding * 2

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bar_h = top_bar if top_bar > 0 else strip_h
    bg = Image.new("RGBA", (W, bar_h), (0, 0, 0, bg_alpha))
    img.alpha_composite(bg, (0, 0))
    draw = ImageDraw.Draw(img)

    y = bar_h - text_total_h - padding
    for line in lines:
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        x = (W - text_w) // 2
        draw.text(
            (x, y), line, font=font, fill=text_color,
            stroke_width=stroke_width, stroke_fill=stroke_color,
        )
        y += line_h

    return np.array(img)


def get_caption_times(scene: dict, dur: float, max_chars: int) -> list[tuple[float, bool]]:
    """各キャプションの (開始時刻, キーワード含有フラグ) リストを返す。

    build_subtitle_clips と同じ分割ロジックを使うため、SFX タイミングが字幕と一致する。
    """
    captions = split_captions(scene.get("narration", ""), max_chars)
    keywords = scene.get("keywords", [])
    lengths = [len(c) for c in captions]
    total_len = sum(lengths) or 1
    result: list[tuple[float, bool]] = []
    t = 0.0
    for cap, ln in zip(captions, lengths):
        has_kw = any(kw and kw in cap for kw in keywords)
        result.append((t, has_kw))
        t += dur * ln / total_len
    return result


def build_subtitle_clips(scene: dict, dur: float, size: tuple[int, int], cfg: dict, y_offset: int = 0) -> list:
    """1シーンぶんの字幕クリップ群(開始時刻・尺つき)を返す。"""
    from moviepy import ImageClip

    captions = split_captions(scene.get("narration", ""), int(cfg["max_chars_per_line"]))
    if not captions:
        return []
    keywords = scene.get("keywords", [])
    lengths = [len(c) for c in captions]
    total_len = sum(lengths)

    clips = []
    t = 0.0
    for cap, ln in zip(captions, lengths):
        seg = dur * ln / total_len
        lines_with_mask = wrap_with_mask(cap, keywords, int(cfg["max_chars_per_line"]))
        arr = render_caption(lines_with_mask, size, cfg, y_offset=y_offset)
        clip = ImageClip(arr, transparent=True).with_start(t).with_duration(seg)
        clips.append(clip)
        t += seg
    return clips
