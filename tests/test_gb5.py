from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location(
    "guko_bot_gb5_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


class Geekbench5CommandTest(unittest.TestCase):
    def test_low_available_memory_gets_temporary_swap(self):
        command = bot.gb5_remote_command()

        self.assertIn("MemAvailable:", command)
        self.assertIn("SwapFree:", command)
        self.assertIn("memory_headroom_kb", command)
        self.assertIn("-lt 1500000", command)
        self.assertIn("fallocate -l 2G", command)
        self.assertNotIn("MemTotal:", command)
        self.assertNotIn("-lt 900000", command)

    def test_command_tracks_oom_kills_and_is_valid_posix_shell(self):
        command = bot.gb5_remote_command()

        self.assertIn("/proc/vmstat", command)
        self.assertIn(bot.GB5_OOM_MARKER, command)
        checked = subprocess.run(
            ["/bin/sh", "-n"],
            input=command,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_claim_url_is_canonicalized_and_secret_is_removed(self):
        raw = (
            "https://browser.geekbench.com/v5/cpu/24480000\n"
            "https://browser.geekbench.com/v5/cpu/24480000/claim?key=private-value"
        )

        cleaned = bot.sanitize_geekbench5_output(raw)

        self.assertNotIn("claim?key=", cleaned)
        self.assertNotIn("private-value", cleaned)
        self.assertEqual(
            bot.canonical_geekbench5_url(raw),
            "https://browser.geekbench.com/v5/cpu/24480000",
        )
        self.assertEqual(
            bot.parse_geekbench5_scores(raw)["url"],
            "https://browser.geekbench.com/v5/cpu/24480000",
        )

    def test_csv_endpoint_supplies_scores_and_metadata(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = (
            b'ID,24480000\nModel,"QEMU Standard PC"\nProcessor,AMD EPYC\n'
            b'Platform,Linux x86 (64-bit)\nSingle-Core,926\nMulti-Core,1669\n'
        )

        with patch.object(bot.urllib.request, "urlopen", return_value=response) as urlopen:
            scores = bot.fetch_geekbench5_csv_scores(
                "https://browser.geekbench.com/v5/cpu/24480000/claim?key=private-value"
            )

        self.assertEqual(scores["single"], "926")
        self.assertEqual(scores["multi"], "1669")
        self.assertEqual(scores["processor"], "AMD EPYC")
        self.assertEqual(scores["url"], "https://browser.geekbench.com/v5/cpu/24480000")
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://browser.geekbench.com/v5/cpu/24480000.csv")

    def test_result_image_contains_score_card_and_separate_progress_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "gb5.png"
            bot.gb5_result_image(
                {"name": "Hidden server metadata"},
                {
                    "single": "926",
                    "multi": "1669",
                    "url": "https://browser.geekbench.com/v5/cpu/24480000",
                },
                output,
            )
            with bot.Image.open(output) as image:
                self.assertEqual(image.size, (940, 520))
                rgb = image.convert("RGB")
                self.assertEqual(rgb.getpixel((0, 0)), (245, 247, 250))
                self.assertEqual(rgb.getpixel((30, 30)), (255, 255, 255))
                self.assertEqual(rgb.getpixel((30, 310)), (255, 255, 255))
                self.assertEqual(rgb.getpixel((260, 399)), (47, 111, 191))
                self.assertEqual(rgb.getpixel((700, 399)), (219, 234, 254))
                self.assertEqual(rgb.getpixel((750, 464)), (22, 163, 74))


if __name__ == "__main__":
    unittest.main()
