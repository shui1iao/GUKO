from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docker-publish.yml"


class DockerPublishWorkflowTest(unittest.TestCase):
    def test_only_release_tags_publish_latest(self):
        text = WORKFLOW.read_text()
        tag_if_pattern = (
            r'\s*if \[ "\$\{\{ github\.ref_type \}\}" = "tag" \]; then\n'
            r'.*?\n\s*fi'
        )
        tag_blocks = re.findall(tag_if_pattern, text, re.DOTALL)
        self.assertEqual(len(tag_blocks), 2)
        self.assertTrue(all("$IMAGE:latest" in block for block in tag_blocks))
        outside_tag_blocks = re.sub(tag_if_pattern, "", text, flags=re.DOTALL)
        self.assertNotIn("$IMAGE:latest", outside_tag_blocks)


if __name__ == "__main__":
    unittest.main()
