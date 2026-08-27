from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "telegram-bot" / "render_checkplace.py"
spec = importlib.util.spec_from_file_location("guko_checkplace_renderer", RENDERER)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class CheckPlaceRendererTest(unittest.TestCase):
    def test_cli_defaults_use_the_bright_nodequality_style_grid(self):
        svg_text = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="10ch" height="2em">'
            '<rect x="5ch" y="0em" width="2ch" height="1em" class="ba7"/>'
            '<text x="0ch" y="0.5em"><tspan class="fa7">A中</tspan></text>'
            '</svg>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svg = root / "report.svg"
            output = root / "report.png"
            svg.write_text(svg_text)
            completed = subprocess.run(
                [sys.executable, str(RENDERER), str(svg), str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with Image.open(output) as image:
                self.assertEqual(image.size, (170, 80))
                rgb = image.convert("RGB")
                self.assertEqual(rgb.getpixel((0, 0)), renderer.TERMINAL_BG)
                self.assertEqual(rgb.getpixel((90, 10)), renderer.BG["ba7"])

    def test_terminal_colors_cover_all_report_highlights_and_remain_non_bold(self):
        self.assertEqual(renderer.FG["fa2"], (100, 255, 116))
        self.assertEqual(renderer.FG["fa7"], (246, 246, 246))
        for ansi in (4, 5, 6, 7):
            self.assertIn(f"fa{ansi}", renderer.FG)
            self.assertIn(f"ba{ansi}", renderer.BG)
        self.assertNotIn("Bold", renderer.DEFAULT_LATIN)
        self.assertNotIn("Bold", renderer.DEFAULT_CJK)

    def test_highlight_text_is_forced_to_readable_contrast(self):
        for foreground_name in ("fa2", "fa5", "fa6", "fa7"):
            color = renderer.readable_foreground(
                renderer.FG[foreground_name], renderer.BG["ba7"]
            )
            self.assertGreaterEqual(
                renderer.contrast_ratio(color, renderer.BG["ba7"]),
                4.5,
            )

    def test_network_colored_blocks_keep_their_original_ansi_text_colors(self):
        for foreground_name, background_name in (("fa2", "ba2"), ("fa3", "ba3"), ("fa7", "ba4")):
            self.assertEqual(
                renderer.readable_foreground(
                    renderer.FG[foreground_name], renderer.BG[background_name]
                ),
                renderer.FG[foreground_name],
            )

    def test_braille_latency_graph_uses_symbols_font_when_installed(self):
        self.assertTrue(renderer.is_braille("⣀"))
        symbols_path = Path(renderer.DEFAULT_SYMBOLS)
        if not symbols_path.is_file():
            self.skipTest("Noto Symbols font is provided by the GUKO image")
        symbols = renderer.ImageFont.truetype(str(symbols_path), 20)
        braille = bytes(symbols.getmask("⣀"))
        missing = bytes(symbols.getmask("\U0010ffff"))
        self.assertNotEqual(braille, missing)


if __name__ == "__main__":
    unittest.main()
