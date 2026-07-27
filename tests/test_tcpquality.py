from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
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
        self.assertIn("676789de0df20cc6ade95680c79969b637e3f8fa", command)
        self.assertNotIn("TcpQuality/main/runTcpQuality.sh", command)
        self.assertIn("--no-rootfs", command)
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

    def test_text_output_strips_osc_c0_and_unterminated_osc_in_linear_pass(self):
        text = (
            "\x1b]0;window title\x07北京 电信 163\x00\n"
            "\x1b]8;;https://example.com\x1b\\上海 联通 4837\n"
            "保留这一行\n\x1b]0;" + ("x" * 10000)
        )
        self.assertEqual(
            bot.tcpquality_text_output(text),
            "北京 电信 163\n上海 联通 4837\n保留这一行",
        )

    def test_modes_build_expected_arguments_and_report_sections(self):
        self.assertEqual(bot.tcpquality_mode("v4")["args"], ("-v4",))
        self.assertEqual(bot.tcpquality_mode("v4")["sections"], ("ipv4",))
        self.assertEqual(bot.tcpquality_mode("v4")["family"], "v4")
        self.assertTrue(bot.tcpquality_mode("v4")["report_required"])
        self.assertEqual(bot.tcpquality_mode("v6")["args"], ("-v6",))
        self.assertEqual(bot.tcpquality_mode("v6")["sections"], ("ipv6",))
        self.assertEqual(bot.tcpquality_mode("intl-v4")["args"], ("--intl",))
        self.assertEqual(bot.tcpquality_mode("intl-v4")["sections"], ("intl",))
        self.assertEqual(bot.tcpquality_mode("intl-v4")["family"], "v4")
        self.assertEqual(bot.tcpquality_mode("route-v4")["args"], ("--route", "-v4"))
        self.assertEqual(bot.tcpquality_mode("route-v6")["args"], ("--route", "-v6"))
        self.assertFalse(bot.tcpquality_mode("route-v4")["report_required"])
        self.assertFalse(bot.tcpquality_mode("route-v6")["report_required"])
        self.assertEqual(bot.tcpquality_mode("speedtest")["args"], ("--only-speedtest",))
        self.assertEqual(bot.tcpquality_mode("speedtest")["sections"], ("speedtest",))
        self.assertEqual(
            bot.tcpquality_mode("all")["args"],
            ("-v4", "-v6", "--intl", "--speedtest"),
        )
        self.assertEqual(
            bot.tcpquality_mode("all")["sections"],
            ("ipv4", "ipv6", "intl", "speedtest"),
        )
        with self.assertRaises(ValueError):
            bot.tcpquality_mode("unknown")

    def test_server_panel_and_mode_menu_expose_five_focused_entries(self):
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
        category_callbacks = [button.callback_data for row in menu.inline_keyboard for button in row]
        self.assertIn("tqmode:test-node:full", category_callbacks)
        self.assertIn("tqmode:test-node:route", category_callbacks)
        self.assertIn("tqrun:test-node:intl-v4", category_callbacks)
        self.assertIn("tqmode:test-node:speedtest", category_callbacks)
        self.assertIn("tqmode:test-node:complete", category_callbacks)
        self.assertNotIn("tqrun:test-node:speedtest", category_callbacks)
        self.assertNotIn("tqrun:test-node:all", category_callbacks)
        self.assertFalse(any("cernet" in callback for callback in category_callbacks))
        self.assertNotIn("tqmode:test-node:intl", category_callbacks)
        self.assertNotIn("教育网", bot.tcpquality_menu_text(server))

    def test_family_menu_hides_unavailable_ipv6_and_international_ipv6(self):
        server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
        full_menu = bot.tcpquality_family_markup(server, "full")
        full_callbacks = [button.callback_data for row in full_menu.inline_keyboard for button in row]
        self.assertIn("tqrun:test-node:v4", full_callbacks)
        self.assertNotIn("tqrun:test-node:v6", full_callbacks)

        legacy_intl_menu = bot.tcpquality_family_markup(server, "intl")
        legacy_intl_callbacks = [
            button.callback_data for row in legacy_intl_menu.inline_keyboard for button in row
        ]
        self.assertIn("tqrun:test-node:intl-v4", legacy_intl_callbacks)

        speedtest_menu = bot.tcpquality_family_markup(server, "speedtest")
        speedtest_buttons = [button for row in speedtest_menu.inline_keyboard for button in row]
        self.assertTrue(any(button.text == "🚀 开始三网测速" for button in speedtest_buttons))
        self.assertTrue(any(button.callback_data == "tqrun:test-node:speedtest" for button in speedtest_buttons))
        self.assertIn("消耗较多流量", bot.tcpquality_family_menu_text(server, "speedtest"))
        self.assertIn("确认后开始执行", bot.tcpquality_family_menu_text(server, "speedtest"))

        complete_menu = bot.tcpquality_family_markup(server, "complete")
        complete_buttons = [button for row in complete_menu.inline_keyboard for button in row]
        self.assertTrue(any(button.text == "🧪 开始完整检测" for button in complete_buttons))
        self.assertTrue(any(button.callback_data == "tqrun:test-node:all" for button in complete_buttons))
        self.assertIn("耗时较长", bot.tcpquality_family_menu_text(server, "complete"))
        self.assertIn("确认后开始执行", bot.tcpquality_family_menu_text(server, "complete"))

        ipv6_server = {**server, "ipv6": "2001:db8::10"}
        full_ipv6_menu = bot.tcpquality_family_markup(ipv6_server, "full")
        full_ipv6_callbacks = [button.callback_data for row in full_ipv6_menu.inline_keyboard for button in row]
        self.assertIn("tqrun:test-node:v6", full_ipv6_callbacks)

        route_ipv6_menu = bot.tcpquality_family_markup(ipv6_server, "route")
        route_ipv6_callbacks = [button.callback_data for row in route_ipv6_menu.inline_keyboard for button in row]
        self.assertIn("tqrun:test-node:route-v4", route_ipv6_callbacks)
        self.assertIn("tqrun:test-node:route-v6", route_ipv6_callbacks)


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
        self.assertIn("676789de0df20cc6ade95680c79969b637e3f8fa", command)
        self.assertIn("acb8b306725ed496549a01b878a9d1313482dd38c98f294d0492055b202e12d3", command)
        self.assertIn("6b9800a822c06bfbcc091730522506baf5b1557fb2718e77f4a578d9c4d9247f", command)
        self.assertIn("sha256sum -c", command)
        self.assertNotIn("TcpQuality/main/runTcpQuality.sh", command)
        self.assertNotIn("https://tcpquality.ibsgss.uk/run", command)
        self.assertIn("trap", command)
        self.assertIn('bash "$bundle/runTcpQuality.sh" --no-rootfs -v4', command)

        intl_command = bot.tcpquality_remote_command("intl-v4")
        self.assertIn('bash "$bundle/runTcpQuality.sh" --no-rootfs --intl', intl_command)
        route_v6_command = bot.tcpquality_remote_command("route-v6")
        self.assertIn('bash "$bundle/runTcpQuality.sh" --no-rootfs --route -v6', route_v6_command)
        speedtest_command = bot.tcpquality_remote_command("speedtest")
        self.assertIn('bash "$bundle/runTcpQuality.sh" --no-rootfs --only-speedtest', speedtest_command)
        all_command = bot.tcpquality_remote_command("all")
        self.assertIn(
            'bash "$bundle/runTcpQuality.sh" --no-rootfs -v4 -v6 --intl --speedtest',
            all_command,
        )

    def test_all_remote_commands_are_valid_posix_shell(self):
        for mode in bot.TCPQUALITY_MODES:
            command = bot.tcpquality_remote_command(mode)
            result = subprocess.run(
                ["/bin/sh", "-n", "-c", command],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{mode}: {result.stderr}")

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

    def test_official_svg_is_compacted_and_converted_to_light_theme(self):
        source = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200" '
            'viewBox="0 0 800 200">'
            '<rect width="100%" height="100%" fill="#1f1e2a"/>'
            '<style>text{font-size:14px}</style>'
            '<text x="400" y="28.21" fill="#75b8a6">TcpQuality TCP 重传检测</text>'
            '<text x="400" y="52.08" fill="#8d887b">特价 VPS 广告</text>'
            '<line x1="40" x2="760" y1="75.95" y2="75.95" stroke="#8d887b"/>'
            '<text x="400" y="99.82" fill="#8d887b">报告时间</text>'
            '<text x="40" y="141.05" fill="#d8d2b8">IPv4 统计摘要</text>'
            '<text x="180" y="141.05" fill="#87d88d">零丢包</text>'
            '<text x="330" y="141.05" fill="#d8b96f">一般</text>'
            '<text x="470" y="141.05" fill="#dc646d">异常</text>'
            '</svg>'
        ).encode()

        rendered = bot.prepare_tcpquality_svg(source)
        root = ET.fromstring(rendered)
        texts = [''.join(node.itertext()) for node in root.iter() if node.tag.endswith('text')]
        self.assertNotIn('TcpQuality TCP 重传检测', texts)
        self.assertNotIn('特价 VPS 广告', texts)
        self.assertIn('报告时间', texts)
        self.assertEqual(root.get('height'), '128')
        self.assertEqual(root.get('viewBox'), '0 0 800 128')
        self.assertFalse(any(node.tag.endswith('line') for node in root.iter()))

        fills = {node.get('fill') for node in root.iter() if node.get('fill')}
        self.assertIn('#ffffff', fills)
        self.assertIn('#1f2937', fills)
        self.assertIn('#15803d', fills)
        self.assertIn('#a16207', fills)
        self.assertIn('#dc2626', fills)
        groups = [node for node in root if node.tag.endswith('g')]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get('transform'), 'translate(0,-72)')
        styles = [node.text or '' for node in root if node.tag.endswith('style')]
        self.assertTrue(any('letter-spacing:0.6px' in css for css in styles))
        self.assertFalse(any('letter-spacing:0;' in css for css in styles))

    def test_official_svg_renderer_outputs_white_compact_png(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                svg = root / 'report.svg'
                png = root / 'report.png'
                svg.write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200" '
                    'viewBox="0 0 800 200">'
                    '<rect width="100%" height="100%" fill="#1f1e2a"/>'
                    '<text x="400" y="28" fill="#75b8a6">TcpQuality TCP 重传检测</text>'
                    '<text x="400" y="52" fill="#8d887b">推广信息</text>'
                    '<line x1="40" x2="760" y1="76" y2="76" stroke="#8d887b"/>'
                    '<text x="40" y="100" fill="#d8d2b8">报告时间</text>'
                    '</svg>'
                )
                await bot.render_tcpquality_png(svg.as_uri(), png)
                with bot.Image.open(png) as image:
                    self.assertEqual(image.size, (1600, 256))
                    self.assertEqual(image.convert('RGB').getpixel((0, 0)), (255, 255, 255))
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

    def test_international_mode_renders_the_upstream_intl_report_section(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {
                "id": "test-node",
                "name": "Test",
                "host": "192.0.2.10",
                "ssh": {"user": "root", "port": 22, "key": "/tmp/test-key"},
            }
            report = "https://tcpquality.ibsgss.uk/r/CWzOTTDR6-"
            rendered_urls = []
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                old_results, old_history = bot.RESULTS_DIR, bot.HISTORY_JSON
                setattr(bot, "RESULTS_DIR", root / "results")
                setattr(bot, "HISTORY_JSON", root / "history.json")
                jid = bot.create_job(server, "tcpq")

                async def fake_render(url, output):
                    rendered_urls.append(url)
                    Path(output).write_bytes(b"\x89PNG\r\n\x1a\nfixture")

                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(0, f"报告链接：{report}")),
                    ), patch.object(bot, "render_tcpquality_png", fake_render):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "intl-v4")

                    self.assertEqual(bot.JOBS[jid]["status"], "done")
                    self.assertEqual(rendered_urls, [report + ".png?section=intl"])
                    self.assertEqual(len(fake_bot.photos), 1)
                finally:
                    setattr(bot, "RESULTS_DIR", old_results)
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_route_mode_succeeds_without_a_report_and_sends_plain_output(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            route_output = (
                "\x1b[36m探测进度\x1b[0m 1/2\r"
                "\x1b[36m探测进度\x1b[0m 2/2\r\n"
                "\x1b[36m北京 电信 163\x1b[0m\n上海 联通 4837"
            )
            with tempfile.TemporaryDirectory() as td:
                old_history = bot.HISTORY_JSON
                setattr(bot, "HISTORY_JSON", Path(td) / "history.json")
                jid = bot.create_job(server, "tcpq")
                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(0, route_output)),
                    ):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "route-v4")

                    self.assertEqual(bot.JOBS[jid]["status"], "done")
                    self.assertIsNone(bot.JOBS[jid]["report_url"])
                    delivered = "\n".join(text for _chat, text, _kwargs in fake_bot.messages)
                    self.assertIn("北京 电信 163", delivered)
                    self.assertNotIn("\x1b[36m", delivered)
                    self.assertNotIn("探测进度", delivered)
                    self.assertTrue(any("回程线路" in text for _chat, text, _kwargs in fake_bot.messages))
                finally:
                    setattr(bot, "HISTORY_JSON", old_history)
                    bot.JOBS.pop(jid, None)
                    bot.RUNNING.discard((bot.server_id(server), "tcpq"))

        asyncio.run(scenario())

    def test_route_mode_nonzero_exit_is_failed_even_without_a_report(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            with tempfile.TemporaryDirectory() as td:
                old_history = bot.HISTORY_JSON
                setattr(bot, "HISTORY_JSON", Path(td) / "history.json")
                jid = bot.create_job(server, "tcpq")
                try:
                    with patch.object(
                        bot,
                        "run_subprocess",
                        AsyncMock(return_value=(9, "route failed")),
                    ):
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "route-v4")
                    self.assertEqual(bot.JOBS[jid]["status"], "failed")
                    self.assertTrue(any("退出码" in text for _chat, text, _kwargs in fake_bot.messages))
                finally:
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
                    self.assertEqual(
                        attempted_sections,
                        ["ipv4", "ipv6", "intl", "speedtest"],
                    )
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

    def test_ipv6_route_mode_without_ipv6_fails_before_remote_execution(self):
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
                        await bot.run_tcpquality_task(fake_bot, 100, server, jid, "route-v6")
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

    def test_route_history_replays_successful_text_without_a_report_url(self):
        async def scenario():
            fake_bot = FakeBot()
            server = {"id": "test-node", "name": "Test", "host": "192.0.2.10"}
            item = {
                "status": "done",
                "kind": "tcpq",
                "report_url": None,
                "urls": [],
                "media_paths": [],
                "selected": "仅识别三网回程 · IPv4",
                "target": "route-v4",
                "log_tail": "北京 电信 163\n上海 联通 4837",
            }
            with patch.object(bot, "history_item_for", return_value=item):
                sent = await bot.send_history_result(fake_bot, 100, server, "tcpq")
            self.assertTrue(sent)
            delivered = "\n".join(text for _chat, text, _kwargs in fake_bot.messages)
            self.assertIn("北京 电信 163", delivered)
            self.assertIn("仅识别三网回程", delivered)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
