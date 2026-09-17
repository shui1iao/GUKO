"""IPQuality runs upstream directly, without local Amazon parser patches."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_full_features import bot

class UpstreamOnlyTest(unittest.TestCase):
    def test_obsolete_patch_helpers_are_removed(self):
        self.assertFalse(hasattr(bot, 'ipquality_hotfix_definition'))
        self.assertFalse(hasattr(bot, 'nodequality_ipquality_patch_command'))

    def test_upstream_script_runs_unchanged_and_preserves_protocol_flags(self):
        for mode, expected in [('4', '-y -4'), ('46', '-y')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                fixture=Path(td)/'upstream.sh'
                fixture.write_text('cmp -- "$0" "$FIXTURE" || exit 88\nprintf "UPSTREAM:%s\\n" "$*"\n')
                command='curl() { cp -- "$FIXTURE" "${@: -1}"; }; '+bot.ipquality_remote_command(mode)
                result=subprocess.run(['bash','-c',command],capture_output=True,text=True,env={**os.environ,'FIXTURE':str(fixture)})
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.strip(),'UPSTREAM:'+expected)

    def test_download_failure_does_not_execute_and_cleans_tempfile(self):
        with tempfile.TemporaryDirectory() as td:
            dest=Path(td)/'dest'
            command='curl() { printf "%s" "${@: -1}" > "$DEST"; return 22; }; '+bot.ipquality_remote_command('4')
            result=subprocess.run(['bash','-c',command],capture_output=True,text=True,env={**os.environ,'DEST':str(dest)})
            self.assertEqual(result.returncode,22)
            self.assertFalse(Path(dest.read_text()).exists())
            self.assertEqual(result.stdout,'')

    def test_both_entrypoints_have_no_amazon_interception(self):
        server={'id':'test','name':'Test','host':'192.0.2.10'}
        for mode in bot.NQ_IP_MODES:
            for command in [bot.ipquality_remote_command(mode),bot.nodequality_remote_command(server,2,mode)]:
                for token in ['currentTerritory','guko_ipquality_script','old_download','Amazon parser']:
                    self.assertNotIn(token,command)
                result=subprocess.run(['bash','-n','-c',command],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
