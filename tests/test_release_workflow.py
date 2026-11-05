from __future__ import annotations

import re
import subprocess
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

class ExactReleaseAssetsTest(unittest.TestCase):
    def test_dynamic_assets_exact_main_ci_and_no_old_release_overwrite(self):
        text=(ROOT/'.github/workflows/release.yml').read_text()
        for required in ('test "$tag" = "v$(cat version.txt)"','head_sha=$SHA&branch=main&event=push',
                         'dist/default.env.example','dist/docker-compose.example.yml',
                         'dist/guko-${RELEASE_TAG}-source.zip','dist/SHA256SUMS',
                         '--verify-tag','--latest','Release already exists; refusing'):
            self.assertIn(required,text)
        self.assertNotIn('--clobber',text)
        self.assertNotIn('guko-v0.6.9-source.zip',text)
        self.assertLess(text.index('same') if 'same' in text else text.index('main CI'),text.index('Publish complete'))
    def test_public_docker_is_independent_and_offers_matching_source(self):
        text=(ROOT/'telegram-bot/Dockerfile').read_text()
        self.assertNotIn('FROM guko-local:',text)
        self.assertNotIn('COPY local-source.tar.gz',text)
        self.assertIn('guko-v${GUKO_VERSION}-source.zip',text)
        for module in ('kat_proxy.py','tool_sources.py','stream_terminal.py','stream_platforms.json'):
            self.assertIn(module,text)
        compile_step=(ROOT/'.github/workflows/ci.yml').read_text()
        for module in ('kat_proxy.py','tool_sources.py','stream_terminal.py','proxy_nodes.py'):self.assertIn(module,compile_step)

class ActualCurrentReleaseNotesTest(unittest.TestCase):
    def test_existing_workflow_awk_extracts_this_exact_version_only(self):
        version=(ROOT/'version.txt').read_text().strip()
        program='''index($0, "## [" version "]") == 1 { capture=1; next }
        capture && index($0, "## [") == 1 { exit }
        capture { print }'''
        notes=subprocess.check_output(['awk','-v','version='+version,program,str(ROOT/'CHANGELOG.md')],text=True)
        self.assertIn('CLI v0.5.8',notes)
        self.assertIn('辅助',notes)
        self.assertNotIn('## [0.7.1]',notes)
        self.assertNotIn('### 真正单主探针与区域媒体恢复',notes)
