from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location("guko_bot_under_test", ROOT / "telegram-bot" / "bot.py")
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


class TcpQualityHelpersTest(unittest.TestCase):
    def test_source_and_command_point_to_official_project(self):
        self.assertEqual(
            bot.source_repo("tcpq"),
            "https://github.com/ibsgss/TcpQuality",
        )
        command = bot.script_command_text("tcpq", mode="v4")
        self.assertIn("939674a8309fb9ee26958ad1ddf9fe08665630b9", command)
        self.assertNotIn("TcpQuality/main/runTcpQuality.sh", command)
        self.assertIn("-v4", command)

    def test_report_url_parser_keeps_exact_ten_character_token(self):
        text = (
            "\x1b[32m报告链接：https://tcpquality.ibsgss.uk/r/CWzOTTDR6-\x1b[0m"
            "100  100  100"
        )
        self.assertEqual(
            bot.tcpquality_url(text),
            "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-",
        )
        self.assertIsNone(bot.tcpquality_url("https://example.com/r/CWzOTTDR6-"))
        self.assertEqual(
            bot.validated_tcpquality_url("https://tcpquality.ibsgss.uk/r/CWzOTTDR6-"),
            "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-",
        )
        self.assertIsNone(
            bot.validated_tcpquality_url("https://evil.example/tcpquality.ibsgss.uk/r/CWzOTTDR6-")
        )

    def test_modes_build_expected_arguments_and_report_sections(self):
        self.assertEqual(bot.tcpquality_mode("v4")["args"], ("-v4",))
        self.assertEqual(bot.tcpquality_mode("v4")["sections"], ("ipv4",))
        self.assertEqual(bot.tcpquality_mode("v6")["args"], ("-v6",))
        self.assertEqual(bot.tcpquality_mode("v6")["sections"], ("ipv6",))
        self.assertEqual(bot.tcpquality_mode("all")["args"], ("--all",))
        self.assertEqual(
            bot.tcpquality_mode("all")["sections"],
            ("ipv4", "ipv6", "cernet", "speedtest"),
        )
        with self.assertRaises(ValueError):
            bot.tcpquality_mode("unknown")

    def test_server_panel_and_mode_menu_expose_tcpquality(self):
        server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
        panel = bot.server_markup(server)
        callbacks = [
            button.callback_data
            for row in panel.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("tqask:test-node", callbacks)

        menu = bot.tcpquality_markup(server)
        mode_callbacks = [button.callback_data for row in menu.inline_keyboard for button in row]
        self.assertIn("tqrun:test-node:v4", mode_callbacks)
        self.assertIn("tqrun:test-node:all", mode_callbacks)
        self.assertNotIn("tqrun:test-node:v6", mode_callbacks)

        ipv6_server = {**server, "ipv6": "2001:db8::10"}
        ipv6_menu = bot.tcpquality_markup(ipv6_server)
        ipv6_callbacks = [button.callback_data for row in ipv6_menu.inline_keyboard for button in row]
        self.assertIn("tqrun:test-node:v6", ipv6_callbacks)


class FakeBot:
    def __init__(self, *, fail_message=False, fail_photo=False):
        self.messages = []
        self.photos = []
        self.fail_message = fail_message
        self.fail_photo = fail_photo

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail_message:
            raise RuntimeError("telegram message delivery failed")
        self.messages.append((chat_id, text, kwargs))

    async def send_photo(self, chat_id, photo, **kwargs):
        if self.fail_photo:
            raise RuntimeError("telegram photo delivery failed")
        self.photos.append((chat_id, photo.read(), kwargs))


class TcpQualityExecutionTest(unittest.TestCase):
    def test_remote_command_pins_and_verifies_the_upstream_script(self):
        command = bot.tcpquality_remote_command("v4")
        self.assertIn("939674a8309fb9ee26958ad1ddf9fe08665630b9", command)
        self.assertIn("59041032e173e97d30055461e375605fef8638b2c9b4db8479f3a62625d950e8", command)
        self.assertIn("sha256sum -c", command)
        self.assertNotIn("TcpQuality/main/runTcpQuality.sh", command)
        self.assertNotIn("https://tcpquality.ibsgss.uk/run", command)
        self.assertIn("trap", command)
        self.assertIn('bash "$script" -v4', command)

    def test_generic_svg_renderer_produces_a_real_png(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                svg = root / "report.svg"
                png = root / "report.png"
                svg.write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
                    '<rect width="20" height="10" fill="#123456"/></svg>'
                )
                await bot.render_tcpquality_png(svg.as_uri(), png)
                self.assertTrue(png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

        asyncio.run(scenario())

    def test_successful_task_persists_image_and_reports_link(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {
                "id": "test-node",
                "name": "Test",
                "host": "192.0.2.10",
                "ssh": {"user": "root", "port": 22, "key": "/tmp/test-key"},
            }
            report = "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-"
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                old_results, old_history = bot.RESULTS_DIR, bot.HISTORY_JSON
                setattr(bot, "RESULTS_DIR", root / "results")
                setattr(bot, "HISTORY_JSON", root / "history.json")
                jid = bot.create_job(server, "tcpq")

                async def fake_render(url, output):
                    self.assertEqual(url, report + ".png?section=ipv4")
                    Path(output).write_bytes(b"\x89PNG\r\n\x1a\nfixture")

                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(0, f"报告链接：{report}")),
                    ), patch.object(bot, "render_tcpquality_png", fake_render):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "v4")

                    self.assertEqual(bot.JOBS[jid]["status"], "done")
                    self.assertEqual(len(fake_bot.photos), 1)
                    self.assertTrue(any(report in text for _chat, text, _kwargs in fake_bot.messages))
                    saved = bot.JOBS[jid]["media_paths"]
                    self.assertEqual(len(saved), 1)
                    self.assertTrue(Path(saved[0]).is_file())
                finally:
                    setattr(bot, "RESULTS_DIR", old_results)
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_task_without_report_is_failed(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                old_results, old_history = bot.RESULTS_DIR, bot.HISTORY_JSON
                setattr(bot, "RESULTS_DIR", root / "results")
                setattr(bot, "HISTORY_JSON", root / "history.json")
                jid = bot.create_job(server, "tcpq")
                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(1, "upstream failed without a report")),
                    ):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "v4")
                    self.assertEqual(bot.JOBS[jid]["status"], "failed")
                    self.assertEqual(fake_bot.photos, [])
                    self.assertTrue(any("没拿到报告链接" in text for _chat, text, _kwargs in fake_bot.messages))
                finally:
                    setattr(bot, "RESULTS_DIR", old_results)
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_all_mode_keeps_report_when_command_is_nonzero_and_some_images_fail(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {
                "id": "test-node",
                "name": "Test",
                "host": "192.0.2.10",
                "ipv6": "2001:db8::10",
            }
            report = "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-"
            attempted_sections = []
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                old_results, old_history = bot.RESULTS_DIR, bot.HISTORY_JSON
                setattr(bot, "RESULTS_DIR", root / "results")
                setattr(bot, "HISTORY_JSON", root / "history.json")
                jid = bot.create_job(server, "tcpq")

                async def fake_render(url, output):
                    section = url.rsplit("=", 1)[-1]
                    attempted_sections.append(section)
                    if section in {"ipv6", "speedtest"}:
                        raise RuntimeError(f"{section} unavailable")
                    Path(output).write_bytes(b"\x89PNG\r\n\x1a\nfixture")

                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(7, f"报告链接：{report}")),
                    ), patch.object(bot, "render_tcpquality_png", fake_render):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "all")
                    self.assertEqual(bot.JOBS[jid]["status"], "done")
                    self.assertEqual(attempted_sections, ["ipv4", "ipv6", "cernet", "speedtest"])
                    self.assertEqual(len(fake_bot.photos), 2)
                    final = fake_bot.messages[-1][1]
                    self.assertIn(report, final)
                    self.assertIn("退出码", final)
                    self.assertIn("部分报告图未生成", final)
                finally:
                    setattr(bot, "RESULTS_DIR", old_results)
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_ipv6_mode_without_ipv6_fails_before_remote_execution(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            with tempfile.TemporaryDirectory() as td:
                old_history = bot.HISTORY_JSON
                setattr(bot, "HISTORY_JSON", Path(td) / "history.json")
                jid = bot.create_job(server, "tcpq")
                remote = AsyncMock()
                try:
                    with patch.object(bot, "run_subprocess", remote):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "v6")
                    remote.assert_not_awaited()
                    self.assertEqual(bot.JOBS[jid]["status"], "failed")
                    self.assertTrue(any("没有配置 IPv6" in text for _chat, text, _kwargs in fake_bot.messages))
                finally:
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_success_survives_final_telegram_message_failure_and_cleans_temp_files(self):
        async def scenario():
            fake_bot = FakeBot(fail_message=True)
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            report = "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-"
            rendered_parents = []
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                old_results, old_history = bot.RESULTS_DIR, bot.HISTORY_JSON
                setattr(bot, "RESULTS_DIR", root / "results")
                setattr(bot, "HISTORY_JSON", root / "history.json")
                jid = bot.create_job(server, "tcpq")

                async def fake_render(_url, output):
                    output = Path(output)
                    rendered_parents.append(output.parent)
                    output.write_bytes(b"\x89PNG\r\n\x1a\nfixture")

                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(0, f"报告链接：{report}")),
                    ), patch.object(bot, "render_tcpquality_png", fake_render):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "v4")

                    self.assertEqual(bot.JOBS[jid]["status"], "done")
                    self.assertEqual(bot.JOBS[jid]["report_url"], report)
                    self.assertIn(report, bot.JOBS[jid]["log"])
                    self.assertTrue(rendered_parents)
                    self.assertTrue(all(not parent.exists() for parent in rendered_parents))
                finally:
                    setattr(bot, "RESULTS_DIR", old_results)
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_failed_history_is_not_replayed_as_success(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            item = {
                "status": "failed",
                "kind": "tcpq",
                "urls": ["https://evil.example/tcpquality.ibsgss.uk/r/CWzOTTDR6-"],
                "media_paths": [],
                "log_tail": "upstream failed",
            }
            with patch.object(bot, "history_item_for", return_value=item):
                sent = await bot.send_history_result(fake_bot, 100, server, "tcpq")
            self.assertFalse(sent)
            self.assertTrue(fake_bot.messages)
            self.assertFalse(any("✅" in text for _chat, text, _kwargs in fake_bot.messages))
            self.assertFalse(any("evil.example" in text for _chat, text, _kwargs in fake_bot.messages))

        asyncio.run(scenario())

    def test_untrusted_history_url_is_not_treated_as_tcpquality_report(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            item = {
                "status": "done",
                "kind": "tcpq",
                "urls": ["https://evil.example/tcpquality.ibsgss.uk/r/CWzOTTDR6-"],
                "media_paths": [],
                "selected": "IPv4 全国三网",
                "target": "v4",
            }
            with patch.object(bot, "history_item_for", return_value=item):
                sent = await bot.send_history_result(fake_bot, 100, server, "tcpq")
            self.assertFalse(sent)
            self.assertFalse(any("evil.example" in text for _chat, text, _kwargs in fake_bot.messages))

        asyncio.run(scenario())

    def test_history_photo_failure_still_delivers_the_official_report_link(self):
        async def scenario():
            fake_bot = FakeBot(fail_photo=True)
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            report = "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-"
            with tempfile.TemporaryDirectory() as td:
                png = Path(td) / "latest-ipv4.png"
                png.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
                item = {
                    "status": "done",
                    "kind": "tcpq",
                    "report_url": report,
                    "urls": [report],
                    "media_paths": [str(png)],
                    "selected": "IPv4 全国三网",
                    "target": "v4",
                }
                with patch.object(bot, "history_item_for", return_value=item):
                    sent = await bot.send_history_result(fake_bot, 100, server, "tcpq")
            self.assertTrue(sent)
            self.assertTrue(any(report in text for _chat, text, _kwargs in fake_bot.messages))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
