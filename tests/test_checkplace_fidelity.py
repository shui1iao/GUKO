"""Pixel regressions; optional private font is never fetched or redistributed."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
import warnings
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("checkplace_fidelity", ROOT / "telegram-bot/render_checkplace.py")
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class FidelityTest(unittest.TestCase):
    def render(self, spans, *, rects="", width=16, height=2, pad=10, graph=False, y=0.5):
        style = '<style>/* xyBarMono.woff */</style>' if graph else ''
        svg = (f'<svg width="{width}ch" height="{height}em">{style}{rects}'
               f'<text x="0ch" y="{y}em">{spans}</text></svg>')
        with tempfile.TemporaryDirectory(prefix="guko-fidelity-") as tmp:
            source, output = Path(tmp) / "report.svg", Path(tmp) / "report.png"
            source.write_text(svg)
            renderer.render(source, output, cell_w=14, cell_h=28, font_size=28, pad=pad)
            with Image.open(output) as image:
                return image.convert("RGB")

    def ink(self, image):
        return ImageChops.difference(image, Image.new("RGB", image.size, renderer.TERMINAL_BG)).convert("L")

    def test_latin_bold_changes_pixels_and_increases_ink(self):
        regular = self.render('<tspan class="fa7">Abgy</tspan>')
        bold = self.render('<tspan class="bold fa7">Abgy</tspan>')
        self.assertIsNotNone(ImageChops.difference(regular, bold).getbbox())
        self.assertGreater(sum(self.ink(bold).tobytes()), sum(self.ink(regular).tobytes()))

    def test_cjk_bold_changes_pixels_and_increases_ink(self):
        regular = self.render('<tspan class="fa7">中文测试</tspan>')
        bold = self.render('<tspan class="bold fa7">中文测试</tspan>')
        self.assertIsNotNone(ImageChops.difference(regular, bold).getbbox())
        self.assertGreater(sum(self.ink(bold).tobytes()), sum(self.ink(regular).tobytes()))

    def test_cjk_italic_changes_pixels_without_changing_grid(self):
        regular = self.render('<tspan class="fa7">中文，</tspan><tspan>X</tspan>')
        italic = self.render('<tspan class="italic fa7">中文，</tspan><tspan>X</tspan>')
        self.assertIsNotNone(ImageChops.difference(regular, italic).getbbox())
        # The following Latin glyph starts at the same column, not the sheared ink width.
        self.assertIsNone(ImageChops.difference(regular.crop((100, 0, 130, 48)), italic.crop((100, 0, 130, 48))).getbbox())

    def test_bold_italic_is_distinct_from_each_single_style(self):
        for text in ("Ag", "中文"):
            with self.subTest(text=text):
                both = self.render(f'<tspan class="bold italic">{text}</tspan>')
                for style in ("bold", "italic"):
                    single = self.render(f'<tspan class="{style}">{text}</tspan>')
                    self.assertIsNotNone(ImageChops.difference(both, single).getbbox())

    def test_empty_class_span_keeps_text_and_column(self):
        normal = self.render('<tspan>A中</tspan><tspan class="fa2">X</tspan>')
        empty = self.render('<tspan class="">A中</tspan><tspan class="fa2">X</tspan>')
        self.assertIsNone(ImageChops.difference(normal, empty).getbbox())

    def test_svg_newlines_normalize_to_one_space_including_crlf(self):
        normal = self.render('<tspan>  A中</tspan>')
        for newline in ('\n', '\r\n', '\r', '\t'):
            with self.subTest(newline=repr(newline)):
                formatted = self.render(f'<tspan>{newline} A中</tspan>')
                self.assertIsNone(ImageChops.difference(normal, formatted).getbbox())

    def test_hardware_cpu_black_first_glyph_is_inside_highlight(self):
        # Real hardware SVG row 20.5: newline + CPU label occupies 11 cells;
        # its matching ba7 rectangle starts at 11ch. Text is sanitized only.
        rect = '<rect x="11ch" y="0em" width="12ch" height="1em" class="ba7"/>'
        spans = ('<tspan>\n</tspan><tspan class="fa6">CPU：     </tspan>'
                 '<tspan class="bold underline fa0">AMD EPYC</tspan>')
        image = self.render(spans, rects=rect, width=24)
        expected = self.render(spans.replace('\n', ' '), rects=rect, width=24)
        self.assertIsNone(ImageChops.difference(image, expected).getbbox())
        first_cell = image.crop((164, 10, 178, 38))
        self.assertIn(renderer.FG['fa0'], set(first_cell.get_flattened_data()))
        before = image.crop((150, 10, 164, 38))
        self.assertNotIn(renderer.FG['fa0'], set(before.get_flattened_data()))

    def test_highlight_rectangles_have_exact_half_open_cell_bounds(self):
        image = self.render('<tspan> </tspan>', rects='<rect x="3ch" y="0em" width="2ch" height="1em" class="ba2"/>')
        self.assertEqual(image.getpixel((52, 10)), renderer.BG['ba2'])
        self.assertEqual(image.getpixel((79, 37)), renderer.BG['ba2'])
        self.assertEqual(image.getpixel((80, 10)), renderer.TERMINAL_BG)
        self.assertEqual(image.getpixel((52, 38)), renderer.TERMINAL_BG)

    def test_mixed_cjk_latin_share_baseline_not_ink_center(self):
        image = self.ink(self.render('<tspan>A中g，.</tspan>'))
        a = image.crop((10, 0, 24, 48)).getbbox()
        comma = image.crop((66, 0, 94, 48)).getbbox()
        period = image.crop((94, 0, 108, 48)).getbbox()
        assert a and comma and period
        self.assertGreater(comma[1], a[1] + 10)
        self.assertGreater(period[1], a[1] + 10)
        # Independent Pillow anchor reference for Chinese: Latin A's bottom is the baseline.
        reference = Image.new('L', (28, 48))
        font = ImageFont.truetype(renderer.DEFAULT_CJK, 28)
        ImageDraw.Draw(reference).text((0, a[3]), '中', font=font, fill=255, anchor='ls')
        actual = image.crop((24, 0, 52, 48))
        self.assertEqual(actual.getbbox(), reference.getbbox())

    def test_wide_text_and_rectangles_are_not_truncated_to_bad_svg_width(self):
        image = self.render('<tspan>中文ABCDE</tspan>', width=3,
                            rects='<rect x="0ch" y="1em" width="11ch" height="1em" class="ba4"/>')
        self.assertEqual(image.width, 20 + 11 * 14)
        self.assertEqual(image.getpixel((10 + 11 * 14 - 1, 50)), renderer.BG['ba4'])

    def test_edge_bold_italic_ink_is_not_clipped(self):
        spans = '<tspan class="bold italic">Á中g</tspan>'
        padded = self.ink(self.render(spans, width=4, height=1, pad=30))
        tight = self.ink(self.render(spans, width=4, height=1, pad=0))
        self.assertEqual(padded.crop(padded.getbbox()).tobytes(), tight.crop(tight.getbbox()).tobytes())

    def test_original_graph_font_has_connected_bars_and_keeps_advance(self):
        font_path = os.environ.get('CHECKPLACE_GRAPH_FONT')
        if not font_path:
            self.skipTest('需 CHECKPLACE_GRAPH_FONT 指向获准私用的 xyBarMono TTF；不随源码分发')
        image = self.ink(self.render('<tspan>⣀⣀</tspan>', graph=True))
        original = ImageFont.truetype(font_path, 28)
        reference = Image.new('L', (28, 48))
        ImageDraw.Draw(reference).text((0, 34), '⣀⣀', font=original, fill=255, anchor='ls')
        actual = image.crop(image.getbbox())
        expected = reference.crop(reference.getbbox())
        self.assertEqual(actual.size, expected.size)
        # Strongest row connects across the cell boundary, unlike generic Braille dots.
        self.assertTrue(any(all(actual.tobytes()[y * actual.width + x] > 100 for x in range(actual.width)) for y in range(actual.height)))

    def test_original_check_and_cross_use_source_glyph_pixels(self):
        font_path = os.environ.get('CHECKPLACE_GRAPH_FONT')
        if not font_path:
            self.skipTest('需私用 xyBarMono TTF')
        font = ImageFont.truetype(font_path, 28)
        for char in ('✔', '✘'):
            with self.subTest(char=char):
                actual = self.render(f'<tspan>{char}</tspan>', graph=True)
                expected = Image.new('RGB', actual.size, renderer.TERMINAL_BG)
                ImageDraw.Draw(expected).text((10, 34), char, font=font, fill=renderer.FG['fa7'], anchor='ls')
                actual_ink, expected_ink = self.ink(actual), self.ink(expected)
                self.assertEqual(actual_ink.crop(actual_ink.getbbox()).tobytes(),
                                 expected_ink.crop(expected_ink.getbbox()).tobytes())

    def test_padding_only_translates_the_grid_and_baseline(self):
        even = self.render('<tspan>A中g</tspan>', pad=10)
        odd = self.render('<tspan>A中g</tspan>', pad=11)
        self.assertIsNone(ImageChops.difference(even, odd.crop((1, 1, odd.width - 1, odd.height - 1))).getbbox())

    def test_unknown_braille_falls_back_instead_of_missing_glyph(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            image = self.ink(self.render('<tspan>⠁</tspan>', graph=True))
        if not os.environ.get('CHECKPLACE_GRAPH_FONT'):
            self.assertTrue(any('xyBarMono not configured' in str(w.message) for w in caught))
        font = ImageFont.truetype(renderer.DEFAULT_SYMBOLS, 28)
        expected = font.getmask('⠁').getbbox()
        actual = image.getbbox()
        assert actual and expected
        self.assertEqual(actual[2] - actual[0], expected[2] - expected[0])


if __name__ == '__main__':
    unittest.main()
