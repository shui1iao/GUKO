from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location(
    "guko_bot_unlockscope_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


def result_payload():
    return [
        {
            "id": "netflix",
            "service": "Netflix",
            "category": "streaming",
            "regions": [],
            "region": "jp",
            "state": "available",
            "note": "公开页面可访问；结果为启发式判断",
            "duration_ms": 42,
            "checked_at": "2026-08-16T00:00:00Z",
        },
        {
            "id": "claude",
            "service": "Claude",
            "category": "ai",
            "regions": [],
            "state": "unknown",
            "duration_ms": 17,
            "checked_at": "2026-08-16T00:00:00Z",
        },
        {
            "id": "steam-store",
            "service": "Steam Store",
            "category": "games",
            "regions": [],
            "region": "jp",
            "state": "region_only",
            "note": "仅确认地区商店可访问",
            "duration_ms": 33,
            "checked_at": "2026-08-16T00:00:00Z",
        },
    ]


class UnlockScopeStreamTest(unittest.TestCase):
    def test_json_contract_accepts_optional_region_and_note(self):
        payload = result_payload()
        decoded = bot.stream_json_results(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(decoded, payload)
        self.assertEqual(bot.parse_stream_results(json.dumps(payload)), payload)

    def test_json_contract_rejects_text_and_unknown_state(self):
        self.assertIsNone(bot.stream_json_results("Netflix: Yes"))
        malformed = result_payload()
        malformed[0]["state"] = "maybe"
        self.assertIsNone(bot.stream_json_results(json.dumps(malformed)))
        self.assertEqual(bot.parse_stream_results("{}"), [])

    def test_summary_uses_unlockscope_states_and_escapes_notes(self):
        payload = result_payload()
        payload[0]["note"] = "<script>alert(1)</script>"
        text = bot.format_stream_summary(
            {"name": "Tokyo"}, json.dumps(payload), "IPv4", "全球 + 日本", "jp"
        )
        self.assertIn("UnlockScope v0.1.1", text)
        self.assertIn("可用 1 / 不可用 0 / 其他 2", text)
        self.assertIn("<b>Streaming</b>", text)
        self.assertIn("<b>AI</b>", text)
        self.assertIn("<b>Games / Stores</b>", text)
        self.assertIn("Netflix：✅ <code>可用（JP）</code>", text)
        self.assertIn("Claude：⚠️", text)
        self.assertIn("Steam Store：🟡 <code>仅地区可用（JP）</code>", text)
        self.assertIn("探测地区：JP", text)
        self.assertEqual(bot.stream_status_label("unavailable", "jp"), "不可用")
        self.assertEqual(bot.stream_status_label("unknown", "jp"), "未知（JP）")
        self.assertEqual(bot.STREAM_CATEGORY_LABELS["knowledge"], "Knowledge & Community")
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_result_image_renders_json_payload_with_cjk_section_font(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            bot, "load_font", wraps=bot.load_font
        ) as load_font:
            path = Path(tmp) / "stream.png"
            rendered = bot.stream_result_image(
                {"name": "Tokyo"}, json.dumps(result_payload()), "IPv4", "全球 + 日本", "jp", path
            )
            self.assertEqual(rendered, path)
            self.assertTrue(path.is_file())
            with Image.open(path) as image:
                self.assertEqual(image.width, 1120)
                self.assertGreater(image.height, 500)
                pixels = image.load()
                status_colors = [(22, 163, 74), (202, 138, 4), (124, 58, 237)]
                right_edges = [
                    max(
                        x
                        for y in range(image.height)
                        for x in range(image.width)
                        if pixels[x, y] == color
                    )
                    for color in status_colors
                ]
                self.assertLessEqual(max(right_edges) - min(right_edges), 1)

            image_source = inspect.getsource(bot.stream_result_image)
            self.assertNotIn("source_repo('stream')", image_source)
            self.assertNotIn("UNLOCKSCOPE_VERSION", image_source)
            self.assertIn("status_right = table_right - 12", image_source)
            self.assertIn("status_font.getmask(status).getbbox()", image_source)
            self.assertIn("status_right - status_ink_right", image_source)

            fonts_at_section_size = [
                call.args[0] for call in load_font.call_args_list if call.args[1] == 24
            ]
            self.assertEqual(len(fonts_at_section_size), 1)
            section_font = bot.load_font(fonts_at_section_size[-1], 24)
            self.assertIn("Noto Sans CJK", section_font.getname()[0])
            self.assertNotEqual(bytes(section_font.getmask("流")), bytes(section_font.getmask("媒")))

    def test_region_mapping_matches_unlockscope_groups(self):
        self.assertEqual(bot.stream_region_for_server({"country": "jp"}), ("jp", "全球 + 日本"))
        self.assertEqual(bot.stream_region_for_server({"country": "mx"}), ("na", "全球 + 北美"))
        self.assertEqual(bot.stream_region_for_server({"country": "za"}), ("af", "全球 + 非洲"))
        self.assertEqual(bot.stream_region_for_server({"country": "sg"}), ("", "全球平台（自动识别）"))

    def test_remote_command_is_pinned_json_and_shell_valid(self):
        command = bot.unlockscope_remote_command("4", "jp")
        self.assertIn("https://unlock.shuijiao.de", command)
        self.assertIn("UnlockScope/v0.1.1/install.sh", command)
        self.assertIn("UNLOCKSCOPE_VERSION=v0.1.1", command)
        self.assertIn("--scope auto --json", command)
        self.assertIn("--ip 4", command)
        self.assertIn("--region jp", command)
        self.assertIn("--total-timeout 120s", command)
        old_host = "check" + ".unlock.media"
        old_owner = "lmc" + "999"
        self.assertNotIn(old_host, command)
        self.assertNotIn(old_owner, command)
        checked = subprocess.run(["sh", "-n", "-c", command], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_user_visible_command_includes_installer_and_json(self):
        command = bot.script_command_text("stream", ip_mode="6", region_id="eu")
        self.assertIn("bash <(curl -Ls https://unlock.shuijiao.de)", command)
        self.assertIn("unlockscope --scope auto --json", command)
        self.assertIn("--ip 6", command)
        self.assertIn("--region eu", command)

    def test_invalid_ip_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            bot.unlockscope_remote_command("46", "jp")


if __name__ == "__main__":
    unittest.main()
