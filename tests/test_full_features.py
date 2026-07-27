from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location(
    "guko_bot_full_features_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

import auth


def callbacks(markup):
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


class FullFeatureSurfaceTest(unittest.TestCase):
    def test_callback_data_stays_within_telegram_limit(self):
        long_host = '.'.join(['a' * 60, 'b' * 60, 'c' * 60, 'example']) + '.com'
        self.assertTrue(bot.is_valid_hostname(long_host))
        server = {
            "name": "Long Host",
            "host": long_host,
            "ipv6": "2001:db8::10",
            "country": "hk",
        }
        markups = [
            bot.server_markup(server),
            bot.edit_markup(server),
            bot.tcpquality_markup(server),
            bot.confirm_nq_markup(server, bot.NQ_ALL_MASK, "46"),
            bot.stream_markup(server),
        ]
        markups.extend(bot.proxy_markup(server, kind) for kind in bot.PROXY_TOOLS)
        for markup in markups:
            for callback in callbacks(markup):
                self.assertLessEqual(len(callback.encode()), 64, callback)

    def test_server_panel_exposes_every_enabled_feature(self):
        server = {
            "name": "Test",
            "host": "192.0.2.10",
            "ipv6": "2001:db8::10",
            "country": "hk",
        }
        found = callbacks(bot.server_markup(server))
        sid = bot.server_id(server)
        expected = {
            f"ipq:{sid}",
            f"nqask:{sid}",
            f"tqask:{sid}",
            f"gb5:{sid}",
            f"stream:{sid}",
            f"bgp:{sid}",
            f"ippure:{sid}",
            f"proxy:ss:{sid}",
            f"proxy:anytls:{sid}",
            f"proxy:vless:{sid}",
            f"proxy:snell:{sid}",
            f"jobsrv:{sid}",
            f"hist:{sid}",
            f"testssh:{sid}",
            f"ntask:{sid}",
            f"edit:{sid}",
            f"delask:{sid}",
        }
        self.assertTrue(expected.issubset(found), expected - found)

    def test_every_proxy_tool_has_menu_history_name_and_actions(self):
        server = {"name": "Test", "host": "192.0.2.10"}
        for kind in bot.PROXY_TOOLS:
            with self.subTest(kind=kind):
                self.assertIn(kind, bot.KIND_NAME)
                found = callbacks(bot.proxy_markup(server, kind))
                self.assertIn(f"proxyrun:{kind}:view:{bot.server_id(server)}", found)
                if kind == "vless":
                    self.assertIn(f"vlessmode:plain:{bot.server_id(server)}", found)
                    self.assertIn(f"vlessmode:reality:{bot.server_id(server)}", found)
                else:
                    self.assertIn(f"proxyrun:{kind}:ensure:{bot.server_id(server)}", found)
                self.assertTrue(bot.proxy_answers(kind, 12345, "plain").startswith("12345"))

    def test_bot_command_menu_is_complete(self):
        set_my_commands = AsyncMock()
        app = SimpleNamespace(bot=SimpleNamespace(set_my_commands=set_my_commands))
        asyncio.run(bot.post_init(app))
        commands = set_my_commands.await_args.args[0]
        names = {item.command for item in commands}
        self.assertEqual(
            names,
            {
                "start",
                "list",
                "status",
                "addserver",
                "testssh",
                "testall",
                "exportconfig",
                "info",
                "jobs",
                "history",
                "ip",
                "nexttrace",
                "version",
            },
        )

    def test_all_nodequality_selections_and_protocols(self):
        dual = {"name": "Dual", "host": "192.0.2.10", "ipv6": "2001:db8::10"}
        for mask in range(bot.NQ_ALL_MASK + 1):
            with self.subTest(mask=mask):
                answers = bot.nq_answer_script(mask)
                self.assertEqual(len(answers.splitlines()), len(bot.NQ_ITEMS))
                self.assertEqual(answers.count("y\n"), mask.bit_count())
                markup = callbacks(bot.confirm_nq_markup(dual, mask, "46"))
                self.assertIn(f"nqrun:{bot.server_id(dual)}:{mask}:46", markup)
                self.assertEqual(bot.nq_remote_ipv_arg(dual, "46"), "")
                self.assertEqual(bot.nq_remote_ipv_arg(dual, "4"), "-4")

    def test_all_tcpquality_modes_are_valid_shell_and_menu_paths(self):
        server = {"name": "Dual", "host": "192.0.2.10", "ipv6": "2001:db8::10"}
        menu = callbacks(bot.tcpquality_markup(server))
        self.assertIn(f"tqrun:{bot.server_id(server)}:intl-v4", menu)
        for mode in bot.TCPQUALITY_MODES:
            with self.subTest(mode=mode):
                command = bot.tcpquality_remote_command(mode)
                checked = subprocess.run(
                    ["/bin/sh", "-n"],
                    input=command,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertIn("--no-rootfs", command)
                self.assertTrue(bot.script_command_text("tcpq", mode=mode))

    def test_generated_image_temp_directory_is_cleaned_even_when_delivery_fails(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "generated"
                work.mkdir()
                image = work / "result.png"
                image.write_bytes(b"not-empty-test-image")
                capture = SimpleNamespace(send_photo=AsyncMock(side_effect=RuntimeError("delivery failed")))
                with self.assertRaises(RuntimeError):
                    await bot.send_png_and_cleanup(capture, 1, image, work)
                self.assertFalse(work.exists())

        asyncio.run(exercise())

    def test_proxy_remote_scripts_cleanup_temporary_manager_files(self):
        async def exercise(kind, action):
            with tempfile.TemporaryDirectory() as tmp:
                old_history = bot.HISTORY_JSON
                old_jobs = bot.JOBS
                old_running = bot.RUNNING
                bot.HISTORY_JSON = Path(tmp) / "history.json"
                bot.JOBS = {}
                bot.RUNNING = set()
                server = {"name": "Test", "host": "192.0.2.10"}
                jid, _ = bot.start_job(server, kind, target=action)
                capture = SimpleNamespace(send_message=AsyncMock())
                run = AsyncMock(return_value=(1, f"{kind} 未安装"))
                try:
                    with patch.object(bot, "run_subprocess", run), patch.object(
                        bot, "ssh_args", side_effect=lambda _server, remote, tty=False: ["ssh", remote]
                    ):
                        await bot.run_proxy_tool_task(capture, 1, server, jid, kind, action)
                    remote = run.await_args.args[0][-1]
                    if kind != "vless" or action != "view":
                        self.assertIn("trap 'rm -f \"$tmp\"' EXIT", remote)
                    checked = subprocess.run(
                        ["/bin/bash", "-n"],
                        input=remote,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(checked.returncode, 0, checked.stderr)
                finally:
                    bot.HISTORY_JSON = old_history
                    bot.JOBS = old_jobs
                    bot.RUNNING = old_running

        for kind in bot.PROXY_TOOLS:
            for action in ("view", "ensure"):
                with self.subTest(kind=kind, action=action):
                    asyncio.run(exercise(kind, action))

    def test_stream_button_requires_confirmation_before_launch(self):
        async def exercise():
            server = {"name": "JP", "host": "192.0.2.10", "country": "jp"}
            sid = bot.server_id(server)
            query = SimpleNamespace(
                data=f"stream:{sid}",
                message=SimpleNamespace(chat_id=123),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(),
            )
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=1),
                effective_chat=SimpleNamespace(id=123),
                effective_message=query.message,
                callback_query=query,
            )
            context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
            launch = MagicMock(return_value="job")
            with patch.object(bot, "find_server_by_id", return_value=server), patch.object(
                bot, "launch_job", launch
            ):
                await bot.on_button(update, context)
                launch.assert_not_called()
                markup = query.edit_message_text.await_args.kwargs["reply_markup"]
                self.assertIn(f"streamrun:{sid}", callbacks(markup))

                query.data = f"streamrun:{sid}"
                await bot.on_button(update, context)
                launch.assert_called_once()
                context.bot.send_message.assert_awaited()

        asyncio.run(exercise())

    def test_stream_region_mapping_covers_configured_countries(self):
        expected = {
            "tw": "1",
            "hk": "2",
            "jp": "3",
            "us": "4",
            "br": "5",
            "gb": "6",
            "au": "7",
            "kr": "8",
            "sg": "9",
            "in": "10",
            "za": "11",
        }
        for country, region in expected.items():
            with self.subTest(country=country):
                self.assertEqual(
                    bot.stream_region_for_server(
                        {"name": "Test", "host": "192.0.2.10", "country": country}
                    )[0],
                    region,
                )

    def test_ip_domain_and_host_port_validation(self):
        self.assertEqual(bot.extract_ipv4("target 1.1.1.1 now"), "1.1.1.1")
        self.assertEqual(bot.extract_ipv4("999.1.1.1"), "")
        self.assertEqual(bot.normalize_domain("https://example.com/path"), "example.com")
        self.assertEqual(bot.normalize_domain("not a host"), "")
        self.assertEqual(bot.parse_host_port("example.com:53580"), ("example.com", 53580))
        self.assertTrue(bot.is_valid_hostname("example.com"))
        self.assertFalse(bot.is_valid_hostname("bad host"))


class InventoryAndAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = bot.DATA_DIR
        self.old_servers = bot.SERVERS_JSON
        self.old_keys = bot.KEYS_DIR
        root = Path(self.temp.name)
        bot.DATA_DIR = root
        bot.SERVERS_JSON = root / "servers.json"
        bot.KEYS_DIR = root / "keys"
        bot.SERVERS_JSON.write_text(
            json.dumps(
                {
                    "defaults": {
                        "ssh": {
                            "user": "root",
                            "port": 53580,
                            "key": "/data/keys/default",
                        }
                    },
                    "servers": [],
                }
            )
        )

    def tearDown(self):
        bot.DATA_DIR = self.old_data
        bot.SERVERS_JSON = self.old_servers
        bot.KEYS_DIR = self.old_keys
        self.temp.cleanup()

    def test_single_bulk_update_delete_lifecycle(self):
        single = bot.build_server_item("One", "192.0.2.10", "root", 53580, "key", key="/data/keys/a")
        saved, action = bot.upsert_server(single)
        self.assertEqual(action, "added")
        sid = str(bot.server_id(saved))
        updated = bot.update_server_by_id(sid, {"name": "Renamed", "ssh": {"user": "admin"}})
        self.assertEqual(updated["name"], "Renamed")
        self.assertEqual(updated["ssh"]["user"], "admin")
        removed = bot.delete_server_by_id(str(bot.server_id(updated)))
        self.assertEqual(removed["name"], "Renamed")
        self.assertEqual(bot.load_inventory()["servers"], [])

    def test_bulk_parser_covers_shared_and_per_server_auth(self):
        items, errors = bot.parse_bulk_lines(
            'A 192.0.2.10 root\nB example.com:53580 admin',
            same_port=22,
            auth_mode="password",
            shared_auth="secret",
        )
        self.assertFalse(errors)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["ssh"]["password"] == "secret" for item in items))

        items, errors = bot.parse_bulk_lines(
            'C 192.0.2.11 53580 root key:/data/keys/c\nD 192.0.2.12 22 root',
            auth_mode="per",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(items[0]["ssh"]["key"], "/data/keys/c")

    def test_private_key_validation_and_permissions(self):
        with self.assertRaises(ValueError):
            bot.save_private_key(1, "not a key")
        begin = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        end = "-----END " + "OPENSSH PRIVATE KEY-----"
        path = Path(bot.save_private_key(1, f"{begin}\ntest\n{end}"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_export_redacts_nested_flat_and_default_passwords(self):
        inventory = {
            "defaults": {
                "password": "flat-default-secret",
                "ssh": {"password": "nested-default-secret", "key": "/data/keys/default"},
            },
            "servers": [
                {
                    "name": "A",
                    "host": "192.0.2.10",
                    "password": "flat-server-secret",
                    "ssh": {"password": "nested-server-secret", "key": "/data/keys/a"},
                }
            ],
        }
        exported = bot.redact_inventory(inventory)
        blob = json.dumps(exported)
        for secret in (
            "flat-default-secret",
            "nested-default-secret",
            "flat-server-secret",
            "nested-server-secret",
        ):
            self.assertNotIn(secret, blob)
        self.assertEqual(exported["defaults"]["password"], "***")
        self.assertEqual(exported["defaults"]["ssh"]["password"], "***")

    def test_auth_builds_key_and_password_commands(self):
        inventory = {
            "defaults": {"ssh": {"user": "root", "port": 53580, "key": "/data/keys/default"}}
        }
        key_args = auth.ssh_args({"host": "192.0.2.10"}, "true", inv=inventory)
        self.assertEqual(key_args[0], "ssh")
        self.assertIn("/data/keys/default", key_args)
        password_server = {
            "host": "192.0.2.11",
            "ssh": {"auth": "password", "password": "secret", "user": "admin", "port": 22},
        }
        password_args = auth.ssh_args(password_server, "true", inv=inventory)
        self.assertEqual(password_args[:2], ["sshpass", "-e"])
        self.assertNotIn("secret", " ".join(password_args))


if __name__ == "__main__":
    unittest.main()
