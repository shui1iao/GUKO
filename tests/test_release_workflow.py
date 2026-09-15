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
        self.assertEqual(len(tag_blocks), 1)
        self.assertTrue(all("$IMAGE:latest" in block for block in tag_blocks))
        outside_tag_blocks = re.sub(tag_if_pattern, "", text, flags=re.DOTALL)
        self.assertNotIn("$IMAGE:latest", outside_tag_blocks)

    def test_release_publication_requires_successful_exact_main_ci(self):
        text = WORKFLOW.read_text()
        self.assertIn("if: github.ref_type == 'tag'", text)
        self.assertIn('test "$SHA" = "$MAIN"', text)
        self.assertIn('head_sha=$SHA&branch=main&event=push', text)
        self.assertIn('.status == "completed" and .conclusion == "success"', text)
        self.assertLess(text.index('Verify exact main CI'), text.index('Build and push image'))

    def test_multiarch_image_has_revision_and_attestations(self):
        text = WORKFLOW.read_text()
        for required in ('platforms: linux/amd64,linux/arm64', 'provenance: mode=max',
                         'sbom: true', 'build-args: GUKO_REVISION=${{ github.sha }}'):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
