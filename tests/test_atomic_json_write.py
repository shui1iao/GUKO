from __future__ import annotations

import errno
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location(
    "guko_bot_atomic_write_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


class AtomicJsonWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.orig_data_dir = bot.DATA_DIR
        self.orig_servers = bot.SERVERS_JSON
        self.orig_history = bot.HISTORY_JSON
        bot.DATA_DIR = self.root
        bot.SERVERS_JSON = self.root / "servers.json"
        bot.HISTORY_JSON = self.root / "history.json"

    def tearDown(self):
        bot.DATA_DIR = self.orig_data_dir
        bot.SERVERS_JSON = self.orig_servers
        bot.HISTORY_JSON = self.orig_history
        self.tmp.cleanup()

    def test_normal_atomic_replace_writes_json_with_0600_and_no_tmp_left(self):
        target = self.root / "servers.json"
        payload = {"servers": [{"id": "1", "name": "node-a"}]}

        bot._atomic_write_json(target, payload, 0o600)

        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.root.glob("*.tmp")], [])

    def test_ebusy_and_exdev_fallback_overwrite_in_place_truncates_and_cleans_tmp(self):
        for err_no in (errno.EBUSY, errno.EXDEV):
            with self.subTest(errno=err_no):
                target = self.root / f"bind-{err_no}.json"
                initial = {"servers": [{"id": "1", "name": "long-" + ("x" * 200)}]}
                target.write_text(json.dumps(initial), encoding="utf-8")
                os.chmod(target, 0o644)
                orig_inode = target.stat().st_ino

                shorter = {"servers": [{"id": "1", "name": "ok"}]}
                with patch.object(
                    bot.os,
                    "replace",
                    side_effect=OSError(err_no, os.strerror(err_no)),
                ):
                    bot._atomic_write_json(target, shorter, 0o600)

                self.assertEqual(target.stat().st_ino, orig_inode)
                self.assertEqual(json.loads(target.read_text(encoding="utf-8")), shorter)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual([p.name for p in self.root.glob("*.tmp")], [])

    def test_unexpected_replace_error_reraises_and_cleans_tmp(self):
        target = self.root / "readonly.json"
        target.write_text("{}", encoding="utf-8")

        with patch.object(
            bot.os,
            "replace",
            side_effect=OSError(errno.EACCES, os.strerror(errno.EACCES)),
        ):
            with self.assertRaises(OSError) as ctx:
                bot._atomic_write_json(target, {"a": 1}, 0o600)

        self.assertEqual(ctx.exception.errno, errno.EACCES)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")
        self.assertEqual([p.name for p in self.root.glob("*.tmp")], [])

    def test_save_inventory_and_save_history_succeed_under_ebusy(self):
        bot.SERVERS_JSON.write_text(json.dumps({"servers": [{"id": "s1", "name": "FXTRANSIT"}]}), encoding="utf-8")
        bot.HISTORY_JSON.write_text("[]", encoding="utf-8")
        srv_inode = bot.SERVERS_JSON.stat().st_ino
        hist_inode = bot.HISTORY_JSON.stat().st_ino

        with patch.object(
            bot.os,
            "replace",
            side_effect=OSError(errno.EBUSY, os.strerror(errno.EBUSY)),
        ):
            updated = bot.update_server_by_id("s1", {"ipv6": False, "ipv6_status": "none"})
            bot.save_history([{"job_id": "ipq-s1-1", "status": "done"}])

        self.assertIsNotNone(updated)
        self.assertEqual(bot.SERVERS_JSON.stat().st_ino, srv_inode)
        self.assertEqual(bot.HISTORY_JSON.stat().st_ino, hist_inode)
        self.assertEqual(bot.load_inventory()["servers"][0]["ipv6_status"], "none")
        self.assertEqual(bot.load_history(), [{"job_id": "ipq-s1-1", "status": "done"}])
        self.assertEqual([p.name for p in self.root.glob("*.tmp")], [])


if __name__ == "__main__":
    unittest.main()
