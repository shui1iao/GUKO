from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.versioning import normalize_version

ROOT = Path(__file__).resolve().parents[1]


def must_match(pattern: str, text: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    assert match is not None
    return match.group(1)


class VersionCarryTest(unittest.TestCase):
    def test_patch_ten_carries_into_minor(self):
        self.assertEqual(normalize_version("0.1.10"), "0.2.0")

    def test_minor_ten_carries_into_major(self):
        self.assertEqual(normalize_version("0.10.0"), "1.0.0")

    def test_legacy_patch_above_ten_carries_once_and_resets(self):
        self.assertEqual(normalize_version("0.1.24"), "0.2.0")

    def test_already_normal_version_is_unchanged(self):
        self.assertEqual(normalize_version("0.2.5"), "0.2.5")

    def test_invalid_version_is_rejected(self):
        for value in ("", "1.2", "v1.2.3", "1.-1.0", "1.2.x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_version(value)
    def test_project_version_files_are_consistent_and_already_carried(self):
        bot_text = (ROOT / "telegram-bot" / "bot.py").read_text()
        docker_text = (ROOT / "telegram-bot" / "Dockerfile").read_text()
        env_text = (ROOT / ".env.example").read_text()
        bot_version = must_match(r"GUKO_VERSION = os\.environ\.get\('GUKO_VERSION', '([^']+)'", bot_text)
        docker_version = must_match(r"^ARG GUKO_VERSION=(\S+)$", docker_text, re.MULTILINE)
        env_version = must_match(r"^GUKO_VERSION=(\S+)$", env_text, re.MULTILINE)
        self.assertEqual({bot_version, docker_version, env_version}, {bot_version})
        self.assertEqual(normalize_version(bot_version), bot_version)

    def test_cli_prints_the_carried_version(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "versioning.py"), "0.2.10"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "0.3.0")


if __name__ == "__main__":
    unittest.main()
