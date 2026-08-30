from __future__ import annotations

import asyncio
import gzip
import importlib.util
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

fetch_spec = importlib.util.spec_from_file_location(
    "guko_bgp_fetch_under_test", ROOT / "telegram-bot" / "tools" / "bgp_fetch.py"
)
assert fetch_spec and fetch_spec.loader
bgp = importlib.util.module_from_spec(fetch_spec)
fetch_spec.loader.exec_module(bgp)

bot_spec = importlib.util.spec_from_file_location(
    "guko_bot_bgp_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert bot_spec and bot_spec.loader
bot = importlib.util.module_from_spec(bot_spec)
bot_spec.loader.exec_module(bot)


VALID_SVG = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<rect width="10" height="10"/></svg>'
)


class BGPFetchTest(unittest.TestCase):
    def render_with(self, direct_effect, tmp: str):
        ip = ipaddress.IPv4Address("51.241.130.238")
        prefix = ipaddress.IPv4Network("51.241.130.0/24")
        relay_config = Path(tmp) / "relay.json"
        relay_config.write_text("{}")

        def convert(svg_path: Path, png_path: Path):
            self.assertEqual(svg_path.read_bytes(), VALID_SVG)
            png_path.write_bytes(b"\x89PNG\r\n\x1a\nregression")

        with patch.object(bgp, "prefixes", return_value=[prefix]), patch.object(
            bgp, "fetch", side_effect=direct_effect
        ), patch.object(
            bgp, "fetch_via_managed_server", return_value=(VALID_SVG, "image/svg+xml")
        ) as relayed, patch.object(
            bgp, "svg_to_png", side_effect=convert
        ):
            rc = bgp.fetch_bgp(ip, outdir=Path(tmp), relay_config=relay_config)
            latest = Path(tmp) / "latest-51.241.130.238.png"
            self.assertEqual(rc, 0)
            relayed.assert_called_once()
            self.assertTrue(latest.exists())

    def test_login_html_is_retried_through_the_selected_managed_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.render_with(
                lambda _url: (b"<html><h1>Login to bgp.tools</h1></html>", "text/html"),
                tmp,
            )

    def test_http_403_is_retried_through_the_selected_managed_target(self):
        error = urllib.error.HTTPError(
            "https://bgp.tools/pathimg/rt-51.241.130.0_24",
            403,
            "Forbidden",
            Message(),
            None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.render_with(lambda _url: (_ for _ in ()).throw(error), tmp)

    def test_body_read_timeout_is_retried_through_managed_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.render_with(
                lambda _url: (_ for _ in ()).throw(TimeoutError("body read timed out")),
                tmp,
            )

    def test_direct_standard_svg_bypasses_relay_and_404_does_not_relay(self):
        ip = ipaddress.IPv4Address("51.241.130.238")
        prefix = ipaddress.IPv4Network("51.241.130.0/24")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def convert(_svg_path: Path, png_path: Path):
                png_path.write_bytes(b"\x89PNG\r\n\x1a\nvalid")

            with patch.object(bgp, "prefixes", return_value=[prefix]), patch.object(
                bgp, "fetch", return_value=(VALID_SVG, "image/svg+xml")
            ), patch.object(bgp, "fetch_via_managed_server") as relayed, patch.object(
                bgp, "svg_to_png", side_effect=convert
            ):
                self.assertEqual(bgp.fetch_bgp(ip, outdir=root, relay_config=root / "relay.json"), 0)
                relayed.assert_not_called()

            not_found = urllib.error.HTTPError("https://bgp.tools/pathimg/missing", 404, "Not Found", Message(), None)
            with patch.object(bgp, "prefixes", return_value=[prefix]), patch.object(
                bgp, "fetch", side_effect=not_found
            ), patch.object(bgp, "fetch_via_managed_server") as relayed:
                self.assertNotEqual(bgp.fetch_bgp(ip, outdir=root, relay_config=root / "relay.json"), 0)
                relayed.assert_not_called()

    def test_compressed_response_is_decompressed_with_a_hard_output_bound(self):
        compressed = gzip.compress(b"x" * (bgp.MAX_SVG_BYTES + 1), compresslevel=9)

        class Response:
            def __init__(self):
                self.headers = Message()
                self.headers["Content-Encoding"] = "gzip"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, limit):
                self.limit = limit
                return compressed

        response = Response()
        with patch.object(bgp, "urlopen", return_value=response), patch.object(
            bgp.gzip, "decompress", side_effect=AssertionError("unbounded decompressor used")
        ):
            with self.assertRaises(urllib.error.URLError):
                bgp.fetch("https://bgp.tools/pathimg/test")
        self.assertEqual(response.limit, bgp.MAX_SVG_BYTES + 1)

    def test_only_standard_svg_qnames_are_accepted(self):
        self.assertTrue(bgp.is_svg_document(VALID_SVG))
        self.assertTrue(bgp.is_svg_document(b"<svg/>"))
        self.assertFalse(bgp.is_svg_document(b'<svg xmlns="urn:not-svg"/>'))
        self.assertFalse(bgp.is_svg_document(b"<html/>"))

    def test_relay_uses_accept_new_known_hosts_and_rejects_oversize_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "key"
            known_hosts = root / "known_hosts"
            key.write_text("test-key")
            known_hosts.write_text("")
            config = root / "relay.json"
            config.write_text(json.dumps({
                "host": "relay.example",
                "user": "root",
                "port": 53580,
                "key": str(key),
                "known_hosts": str(known_hosts),
            }))
            def bounded_run(_args, **kwargs):
                self.assertNotIn("capture_output", kwargs)
                self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
                kwargs["stdout"].write(VALID_SVG)
                return SimpleNamespace(returncode=0)

            with patch.object(subprocess, "run", side_effect=bounded_run) as run:
                result = bgp.fetch_via_managed_server("https://bgp.tools/pathimg/test?a&b", config)
            self.assertEqual(result, (VALID_SVG, "image/svg+xml"))
            args = run.call_args.args[0]
            self.assertIn("StrictHostKeyChecking=accept-new", args)
            self.assertIn(f"UserKnownHostsFile={known_hosts}", args)
            self.assertNotIn("StrictHostKeyChecking=no", args)
            remote = args[-1]
            self.assertIn("--max-filesize", remote)
            self.assertIn("'https://bgp.tools/pathimg/test?a&b'", remote)

            def oversized_run(_args, **kwargs):
                kwargs["stdout"].write(b"x" * (bgp.MAX_SVG_BYTES + 1))
                return SimpleNamespace(returncode=0)

            with patch.object(subprocess, "run", side_effect=oversized_run):
                self.assertIsNone(
                    bgp.fetch_via_managed_server("https://bgp.tools/pathimg/test", config)
                )

    def test_bot_resolves_exact_managed_server_with_inventory_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "default_key"
            key.write_text("test-key")
            selected = {
                "name": "BAGE",
                "host": "51.241.130.238",
                "ssh": {"host": "relay.example"},
            }
            inventory = {
                "defaults": {
                    "ssh": {
                        "user": "admin",
                        "port": 53580,
                        "key": str(key),
                    }
                },
                "servers": [selected],
            }
            with patch.object(bot, "load_inventory", return_value=inventory), patch.object(
                bot, "TMP_DIR", root
            ):
                config = bot.build_bgp_relay_config(dict(selected))
            self.assertEqual(config["host"], "relay.example")
            self.assertEqual(config["user"], "admin")
            self.assertEqual(config["port"], 53580)
            self.assertEqual(config["key"], str(key))
            self.assertEqual(Path(config["known_hosts"]).stat().st_mode & 0o777, 0o600)

            stale = dict(selected, host="51.241.130.239")
            with patch.object(bot, "load_inventory", return_value=inventory), patch.object(
                bot, "TMP_DIR", root
            ):
                self.assertIsNone(bot.build_bgp_relay_config(stale))

    def test_concurrent_generation_uses_unique_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            async def run_tool(*args, **_kwargs):
                argv = list(args[0])
                outdir = Path(argv[argv.index("--outdir") + 1])
                await asyncio.sleep(0.01)
                png = outdir / "latest-51.241.130.238.png"
                png.write_bytes(b"\x89PNG\r\n\x1a\nconcurrent")
                return 0, f"PNG={png}\n"

            async def generate_pair():
                return await asyncio.gather(
                    bot.generate_bgp_png("51.241.130.238"),
                    bot.generate_bgp_png("51.241.130.238"),
                )

            with patch.object(bot, "BGP_OUT_ROOT", root), patch.object(
                bot, "ensure_bgp_tool", new=AsyncMock()
            ), patch.object(bot, "run_subprocess", side_effect=run_tool):
                first, second = asyncio.run(generate_pair())
            self.assertNotEqual(first.parent, second.parent)

    def test_generation_cancellation_cleans_temporary_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(bot, "BGP_OUT_ROOT", root), patch.object(
                bot, "ensure_bgp_tool", new=AsyncMock()
            ), patch.object(
                bot, "run_subprocess", new=AsyncMock(side_effect=asyncio.CancelledError())
            ):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(bot.generate_bgp_png("51.241.130.238"))
            self.assertEqual(list(root.iterdir()), [])

    def test_persistence_failure_cleans_relay_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outdir = root / "job"
            outdir.mkdir()
            png = outdir / "latest.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n")
            client = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
            with patch.object(
                bot, "generate_bgp_png", new=AsyncMock(return_value=png)
            ), patch.object(
                bot, "persist_result_file", side_effect=OSError("disk full")
            ), patch.object(bot, "JOBS", {"cleanup-test": {}}), patch.object(bot, "finish_job"):
                asyncio.run(
                    bot.run_bgp_task(
                        client,
                        1,
                        {"name": "BAGE", "host": "51.241.130.238"},
                        "cleanup-test",
                    )
                )
            self.assertFalse(outdir.exists())

    def test_generic_ip_task_explicitly_disables_managed_relay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outdir = root / "job"
            outdir.mkdir()
            png = outdir / "latest.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n")
            saved = root / "saved.png"
            saved.write_bytes(png.read_bytes())
            client = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
            generated = AsyncMock(return_value=png)
            with patch.object(bot, "generate_bgp_png", new=generated), patch.object(
                bot, "persist_result_file", return_value=saved
            ), patch.object(bot, "JOBS", {"generic-test": {}}), patch.object(bot, "finish_job"):
                asyncio.run(
                    bot.run_bgp_task(
                        client,
                        1,
                        {"name": "1.1.1.1", "host": "1.1.1.1", "id": "1.1.1.1"},
                        "generic-test",
                        False,
                    )
                )
            self.assertIsNotNone(generated.await_args)
            self.assertIsNone(generated.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
