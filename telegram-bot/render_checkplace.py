#!/usr/bin/env python3
"""Render Check.Place/IPQuality SVG reports into Telegram-friendly PNG images.

This intentionally does not rely on browser/SVG font metrics. Check.Place SVGs use
terminal cells (ch/em) plus colored background rectangles; normal SVG converters
often misalign mixed CJK/Latin text. This script parses the SVG and renders it as a
native terminal-like screenshot with a fixed cell grid and CJK fallback.
"""
from __future__ import annotations

import argparse
import html
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEFAULT_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
DEFAULT_LATIN_ITALIC = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf"
DEFAULT_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
DEFAULT_SYMBOLS = "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf"

FG = {
    "fa0": (0, 0, 0),
    "fa1": (210, 55, 55),
    "fa2": (45, 205, 65),
    "fa3": (190, 170, 45),
    "fa4": (75, 110, 210),
    "fa5": (180, 70, 180),
    "fa6": (45, 190, 190),
    "fa7": (205, 205, 205),
}
BG = {
    "ba1": (145, 0, 0),
    "ba2": (0, 125, 0),
    "ba3": (135, 118, 0),
    "ba4": (25, 55, 145),
    "ba5": (125, 25, 125),
    "ba6": (0, 115, 115),
    "ba7": (205, 205, 205),
}


def cells(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF) or (0xFF00 <= o <= 0xFFEF)


def is_braille(ch: str) -> bool:
    return 0x2800 <= ord(ch) <= 0x28FF


def relative_luminance(color: tuple[int, int, int]) -> float:
    channels = []
    for value in color:
        component = value / 255
        channels.append(component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def readable_foreground(
    color: tuple[int, int, int], background: tuple[int, int, int] | None
) -> tuple[int, int, int]:
    # Keep the report's original ANSI foreground colors on dark/colored blocks.
    # Only light highlight blocks (notably ba7) need a forced dark foreground.
    if (
        background is None
        or relative_luminance(background) < 0.55
        or contrast_ratio(color, background) >= 4.5
    ):
        return color
    candidates = ((10, 15, 24), (238, 242, 247))
    return max(candidates, key=lambda candidate: contrast_ratio(candidate, background))


def parse_svg_size(svg: str) -> tuple[int, int]:
    m = re.search(r'<svg[^>]*width="([0-9.]+)ch"[^>]*height="([0-9.]+)em"', svg)
    if not m:
        return 74, 47
    return int(float(m.group(1))), int(float(m.group(2)))


def render(svg_path: Path, out_path: Path, *, cell_w: int, cell_h: int, font_size: int, pad: int) -> None:
    svg = svg_path.read_text("utf-8", errors="ignore")
    width_cells, height_cells = parse_svg_size(svg)

    latin = ImageFont.truetype(DEFAULT_LATIN, font_size)
    latin_italic = ImageFont.truetype(DEFAULT_LATIN_ITALIC, font_size)
    cjk = ImageFont.truetype(DEFAULT_CJK, font_size)
    try:
        symbols = ImageFont.truetype(DEFAULT_SYMBOLS, font_size)
    except OSError:
        symbols = latin

    image = Image.new(
        "RGB",
        (pad * 2 + width_cells * cell_w, pad * 2 + height_cells * cell_h),
        (0, 0, 0),
    )
    draw = ImageDraw.Draw(image)

    # Draw terminal background highlight blocks first, using the same cell metrics as text.
    rect_re = re.compile(
        r'<rect x="([0-9.]+)ch" y="([0-9.]+)em" width="([0-9.]+)ch" height="1em" class="(ba\d)"'
    )
    background_ranges: dict[int, list[tuple[float, float, tuple[int, int, int]]]] = {}
    for m in rect_re.finditer(svg):
        x, y, w, cls = float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)
        color = BG.get(cls)
        if not color:
            continue
        background_ranges.setdefault(int(y), []).append((x, x + w, color))
        draw.rectangle(
            [
                pad + x * cell_w,
                pad + y * cell_h,
                pad + (x + w) * cell_w,
                pad + (y + 1) * cell_h,
            ],
            fill=color,
        )

    def background_at(row: int, column: int) -> tuple[int, int, int] | None:
        for start, end, color in background_ranges.get(row, []):
            if start <= column < end:
                return color
        return None

    text_re = re.compile(r'<text x="0ch" y="([0-9.]+)em">(.*?)</text>', re.S)
    span_re = re.compile(r'<tspan(?: class="([^"]+)")?>(.*?)</tspan>', re.S)

    for tm in text_re.finditer(svg):
        y = float(tm.group(1))
        row = int(y)
        top = pad + y * cell_h - cell_h / 2
        col = 0
        for sp in span_re.finditer(tm.group(2)):
            classes = (sp.group(1) or "").split()
            text = html.unescape(re.sub(r"<.*?>", "", sp.group(2))).replace("\r", "")
            color = FG["fa7"]
            italic = "italic" in classes
            underline = "underline" in classes
            for cls in classes:
                if cls in FG:
                    color = FG[cls]
            for ch in text:
                span = cells(ch)
                x = pad + col * cell_w
                if is_braille(ch):
                    font = symbols
                elif is_cjk(ch):
                    font = cjk
                else:
                    font = latin_italic if italic else latin
                draw_color = readable_foreground(color, background_at(row, col))
                bbox = draw.textbbox((0, 0), ch, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                tx = x + (span * cell_w - text_w) / 2 - bbox[0]
                ty = top + (cell_h - text_h) / 2 - bbox[1]
                draw.text((tx, ty), ch, font=font, fill=draw_color)
                if underline and ch != " ":
                    draw.line(
                        (x, top + cell_h - 3, x + span * cell_w, top + cell_h - 3),
                        fill=draw_color,
                        width=1,
                    )
                col += span

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Check.Place SVG to terminal-like PNG")
    parser.add_argument("svg", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cell-w", type=int, default=12, help="terminal cell width in px; proven Telegram value: 12")
    parser.add_argument("--cell-h", type=int, default=24, help="terminal cell height in px; proven Telegram value: 24")
    parser.add_argument("--font-size", type=int, default=20, help="font size in px; proven Telegram value: 20")
    parser.add_argument("--pad", type=int, default=8, help="black padding in px")
    args = parser.parse_args()
    render(args.svg, args.output, cell_w=args.cell_w, cell_h=args.cell_h, font_size=args.font_size, pad=args.pad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
