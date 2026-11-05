"""Exercise the real source packager in task-owned tiny Git repositories."""
import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('git'), 'Source packager runs separately in mandatory CI checkout step with Git; runtime image intentionally has no Git')
class ExactSourceTest(unittest.TestCase):
    def test_deterministic_tracked_allowlist_no_untracked_or_recursive_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'scripts').mkdir()
            required=('version.txt','LICENSE','LICENSES/AGPL-3.0.txt','NOTICE-STREAM.md','kat_proxy.py',
                      'tool_sources.py','stream_platforms.json','stream_terminal.py','telegram-bot/bot.py',
                      'telegram-bot/Dockerfile','scripts/build-source.py')
            for name in required:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes((ROOT/name).read_bytes())
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            # Not tracked: cannot accidentally leak into the source archive.
            (root/'local-source.tar.gz').write_bytes(b'private generated recursion sentinel')
            (root/'.env').write_text('PRIVATE_RUNTIME=must-not-appear\n')
            def build():
                return subprocess.run([sys.executable,str(root/'scripts/build-source.py')],capture_output=True,text=True)
            a=build();self.assertEqual(a.returncode,0,a.stderr)
            target=root/('dist/guko-v'+(root/'version.txt').read_text().strip()+'-source.zip');first=target.read_bytes()
            b=build();self.assertEqual(b.returncode,0,b.stderr);self.assertEqual(first,target.read_bytes())
            with zipfile.ZipFile(target) as z:
                self.assertEqual({n.split('/',1)[1] for n in z.namelist()},set(required))
                for n in z.namelist():self.assertEqual(z.read(n),(root/n.split('/',1)[1]).read_bytes())
            self.assertIn(hashlib.sha256(first).hexdigest(),(root/'dist/SHA256SUMS').read_text())
            subprocess.run(['git','-C',str(root),'add','--force','.env'],check=True)
            c=build();self.assertNotEqual(c.returncode,0);self.assertIn('private/generated',c.stderr)
