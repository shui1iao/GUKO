from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location(
    "guko_bot_history_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


class HistoryRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_history = bot.HISTORY_JSON
        self.original_jobs = bot.JOBS
        self.original_running = bot.RUNNING
        bot.HISTORY_JSON = Path(self.tmp.name) / "history.json"
        bot.JOBS = {}
        bot.RUNNING = set()

    def tearDown(self):
        bot.HISTORY_JSON = self.original_history
        bot.JOBS = self.original_jobs
        bot.RUNNING = self.original_running
        self.tmp.cleanup()

    def test_finish_job_marks_unfinished_running_job_failed(self):
        jid = "nq-test-node-1"
        key = ("test-node", "nq")
        bot.RUNNING.add(key)
        bot.JOBS[jid] = {
            "status": "running",
            "server": "Test Node",
            "server_id": "test-node",
            "kind": "nq",
            "started_at": "2026-07-27T10:00:00+08:00",
        }

        bot.finish_job(jid, key)

        item = bot.load_history()[0]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["delivery_error"], bot.INTERRUPTED_MESSAGE)
        self.assertIn(bot.INTERRUPTED_MESSAGE, item["log_tail"])
        self.assertNotIn(key, bot.RUNNING)

    def test_reconcile_interrupted_history_only_changes_running_records(self):
        records = [
            {
                "job_id": "old-running",
                "status": "running",
                "started_at": "2026-07-27T10:00:00+08:00",
                "completed_at": "2026-07-27T10:05:00+08:00",
                "log_tail": "",
            },
            {"job_id": "done", "status": "done", "log_tail": "kept"},
        ]
        bot.HISTORY_JSON.write_text(json.dumps(records))

        self.assertEqual(bot.reconcile_interrupted_history(), 1)

        updated = bot.load_history()
        self.assertEqual(updated[0]["status"], "failed")
        self.assertEqual(updated[0]["duration_sec"], 300)
        self.assertEqual(updated[0]["log_tail"], bot.INTERRUPTED_MESSAGE)
        self.assertEqual(updated[1], records[1])


if __name__ == "__main__":
    unittest.main()
