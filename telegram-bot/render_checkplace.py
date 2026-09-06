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
import math
import os
import re
import unicodedata
import warnings
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEFAULT_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
DEFAULT_LATIN_ITALIC = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf"
DEFAULT_LATIN_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
DEFAULT_LATIN_BOLD_ITALIC = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf"
DEFAULT_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
DEFAULT_CJK_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
DEFAULT_SYMBOLS = "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf"

FG = {
    "fa0": (0, 0, 0),
    "fa1": (255, 112, 112),
    "fa2": (100, 255, 116),
    "fa3": (255, 232, 96),
    "fa4": (96, 170, 255),
    "fa5": (220, 120, 230),
    "fa6": (96, 245, 245),
    "fa7": (246, 246, 246),
}
BG = {
    "ba1": (178, 22, 22),
    "ba2": (14, 150, 28),
    "ba3": (166, 146, 22),
    "ba4": (25, 55, 145),
    "ba5": (125, 25, 125),
    "ba6": (0, 115, 115),
    "ba7": (225, 225, 225),
}

TERMINAL_BG = (8, 10, 14)


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
    latin = {
        (False, False): ImageFont.truetype(DEFAULT_LATIN, font_size),
        (False, True): ImageFont.truetype(DEFAULT_LATIN_ITALIC, font_size),
        (True, False): ImageFont.truetype(DEFAULT_LATIN_BOLD, font_size),
        (True, True): ImageFont.truetype(DEFAULT_LATIN_BOLD_ITALIC, font_size),
    }
    cjk = {False: ImageFont.truetype(DEFAULT_CJK, font_size),
           True: ImageFont.truetype(DEFAULT_CJK_BOLD, font_size)}
    try:
        symbols = ImageFont.truetype(DEFAULT_SYMBOLS, font_size)
    except OSError:
        symbols = latin[False, False]

    # xyBarMono is NOT redistributable under this project's license. A private,
    # operator-supplied TTF may be mounted read-only; never download report fonts.
    graph = None
    graph_path = os.environ.get("CHECKPLACE_GRAPH_FONT")
    if "xyBarMono" in svg:
        if graph_path:
            graph = ImageFont.truetype(graph_path, font_size)
        else:
            warnings.warn("xyBarMono not configured: graph glyphs use Noto Symbols; "
                          "set CHECKPLACE_GRAPH_FONT for original report bars", stacklevel=2)
    missing_graph = bytes(graph.getmask("\U0010ffff")) if graph else None  # type: ignore[arg-type]

    @lru_cache(maxsize=2048)
    def glyph(ch: str, bold: bool, italic: bool):
        # The upstream cmap is sparse: do not feed arbitrary Unicode to xyBarMono.
        is_graph = is_braille(ch) or 0x2500 <= ord(ch) <= 0x259F or ch in "✔✘"
        source_graph = (graph is not None and is_graph
                        and bytes(graph.getmask(ch)) != missing_graph)  # type: ignore[arg-type]
        if source_graph:
            assert graph is not None
            font = graph
        elif is_braille(ch):
            font = symbols
        elif is_cjk(ch):
            font = cjk[bold]
        else:
            font = latin[bold, italic]
        stroke = max(1, font_size // 28) if bold and is_graph else 0
        shear = 0.20 if italic and (is_cjk(ch) or is_graph) else 0
        # Fit advances, not ink bboxes: retain side bearings, punctuation position
        # and original graph geometry. CJK stays exactly two terminal cells.
        if is_braille(ch) and not source_graph:
            scale_x = 1.0
        else:
            advance = font.getlength(ch) if source_graph or is_cjk(ch) else font.getlength("0")
            scale_x = cells(ch) * cell_w / advance if advance else 1.0
        left, top, right, bottom = map(int, font.getbbox(ch, anchor="ls", stroke_width=stroke))
        if right <= left or bottom <= top:
            return None
        mask = Image.new("L", (right - left, bottom - top))
        ImageDraw.Draw(mask).text((-left, -top), ch, font=font, anchor="ls",
                                  fill=255, stroke_width=stroke)
        out_left = math.floor(scale_x * (left - shear * bottom))
        out_right = math.ceil(scale_x * (right - shear * top))
        if scale_x != 1 or shear:
            mask = mask.transform(
                (out_right - out_left, bottom - top), Image.Transform.AFFINE,
                (1 / scale_x, shear, out_left / scale_x + shear * top - left, 0, 1, 0),
                resample=Image.Resampling.BICUBIC,
            )
        return mask, out_left, top

    # Store positions in one grid; only translate the whole scene if edge ink
    # overhangs a zero/small padding. Never clip individual glyphs to their cells.
    rectangles = []
    background_ranges: dict[int, list[tuple[float, float, tuple[int, int, int]]]] = {}
    rect_re = re.compile(
        r'<rect x="([0-9.]+)ch" y="([0-9.]+)em" width="([0-9.]+)ch" height="1em" class="(ba\d)"'
    )
    for m in rect_re.finditer(svg):
        x, y, w, cls = float(m[1]), float(m[2]), float(m[3]), m[4]
        color = BG.get(cls)
        if color is None:
            continue
        width_cells = max(width_cells, math.ceil(x + w))
        height_cells = max(height_cells, math.ceil(y + 1))
        background_ranges.setdefault(int(y), []).append((x, x + w, color))
        rectangles.append((round(pad + x * cell_w), round(pad + y * cell_h),
                           round(pad + (x + w) * cell_w), round(pad + (y + 1) * cell_h), color))

    def background_at(row: int, column: int) -> tuple[int, int, int] | None:
        for start, end, color in reversed(background_ranges.get(row, [])):
            if start <= column < end:
                return color
        return None

    ascent, descent = latin[False, False].getmetrics()
    baseline_offset = (ascent - descent) / 2
    text_re = re.compile(r'<text x="0ch" y="([0-9.]+)em">(.*?)</text>', re.S)
    span_re = re.compile(r'<tspan(?: class="([^"]*)")?>(.*?)</tspan>', re.S)
    ink = []
    underlines = []
    for tm in text_re.finditer(svg):
        y = float(tm[1])
        baseline = pad + round(y * cell_h + baseline_offset)
        height_cells = max(height_cells, math.ceil(y + 0.5))
        col = 0
        for sp in span_re.finditer(tm[2]):
            classes = (sp[1] or "").split()
            # SVG preserved whitespace normalizes line breaks/tabs to spaces.
            # The leading newline is a real cell: highlight x coordinates include
            # it (hardware CPU label is 10 cells plus this one). CRLF is one break.
            text = html.unescape(re.sub(r"<.*?>", "", sp[2]))
            text = re.sub(r"\r\n|[\r\n\t]", " ", text)
            color = next((FG[cls] for cls in reversed(classes) if cls in FG), FG["fa7"])
            for ch in text:
                x = pad + col * cell_w
                draw_color = readable_foreground(color, background_at(int(y), col))
                rendered = glyph(ch, "bold" in classes, "italic" in classes)
                if rendered:
                    mask, left, top = rendered
                    ink.append((x + left, baseline + top, mask, draw_color))
                span = cells(ch)
                if "underline" in classes and ch != " ":
                    underline_y = baseline + max(1, font_size // 14)
                    underlines.append((x, underline_y, x + span * cell_w,
                                       underline_y + max(1, font_size // 20), draw_color))
                col += span
        width_cells = max(width_cells, col)

    x0 = min([0] + [x for x, _, _, _ in ink])
    y0 = min([0] + [y for _, y, _, _ in ink])
    x1 = max([pad * 2 + width_cells * cell_w] + [x + mask.width for x, _, mask, _ in ink])
    y1 = max([pad * 2 + height_cells * cell_h] + [y + mask.height for _, y, mask, _ in ink]
             + [bottom for _, _, _, bottom, _ in underlines])
    image = Image.new("RGB", (x1 - x0, y1 - y0), TERMINAL_BG)
    draw = ImageDraw.Draw(image)
    for left, top, right, bottom, color in rectangles + underlines:
        # Pillow rectangle endpoints are inclusive, SVG cell bounds are half-open.
        if right > left and bottom > top:
            draw.rectangle((left - x0, top - y0, right - x0 - 1, bottom - y0 - 1), fill=color)
    for x, y, mask, color in ink:
        image.paste(color, (x - x0, y - y0), mask)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, optimize=False, compress_level=4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Check.Place SVG to terminal-like PNG")
    parser.add_argument("svg", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cell-w", type=int, default=14, help="terminal cell width in px (source 7px at 2x)")
    parser.add_argument("--cell-h", type=int, default=28, help="terminal cell height in px (source 14px at 2x)")
    parser.add_argument("--font-size", type=int, default=28, help="font size in px (source 14px at 2x)")
    parser.add_argument("--pad", type=int, default=10, help="padding in px")
    args = parser.parse_args()
    render(args.svg, args.output, cell_w=args.cell_w, cell_h=args.cell_h, font_size=args.font_size, pad=args.pad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
