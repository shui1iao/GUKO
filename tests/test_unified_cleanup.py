"""Native child + local shell stub; NEVER connects to managed-server SSH."""
import asyncio
import os
from pathlib import Path
import signal
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import stream_unified as s

class NativeCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def local_run(self, *, cancel=False, timeout=False):
        native=Path(os.environ.get('UNIFIED_CLEANUP_FIXTURE',str(ROOT/'tests/native-fixture')))
        self.assertTrue(native.is_file(),'native fixture must be built before the offline suite')
        token=os.urandom(16).hex();parent=Path(s.owned_parent(token))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'service-unlock_linux_amd64';binary.write_bytes(native.read_bytes())
            pidfile=root/'child.pid';env=dict(os.environ,FIXTURE_CHILD_PID=str(pidfile))
            called=[]
            async def runner(args,**kwargs):
                called.append(args[-1])
                if args[-1]=='LC_ALL=C uname -m':return 0,'x86_64\n',''
                if timeout and 'cat > "$work/probe"' in args[-1]:kwargs['timeout']=.08
                return await s.process(['sh','-c',args[-1]],**kwargs)
            with patch.object(s.uuid,'uuid4',return_value=type('Token',(),{'hex':token})()), patch.dict(s.CATALOGUE['binary_sha256'], {'amd64':hashlib.sha256(native.read_bytes()).hexdigest()}):
                task=asyncio.create_task(s.remote_run({},lambda server,cmd,**kw:['local-stub',cmd],lambda server:env,binary_dir=root,runner=runner))
                deadline=asyncio.get_running_loop().time()+2
                while not pidfile.exists() and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.005)
                self.assertTrue(pidfile.exists(),'native child did not start')
                pid=int(pidfile.read_text())
                try:
                    if cancel:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):await task
                    else:
                        with self.assertRaises(asyncio.TimeoutError):await task
                    self.assertFalse(parent.exists(),'owned temporary directory leaked')
                    for _ in range(100):
                        try:
                            state=Path('/proc')/str(pid)/'stat'
                            if not state.exists() or state.read_text().split()[2]=='Z':break
                        except FileNotFoundError:break
                        await asyncio.sleep(.01)
                    else:self.fail('native probe left running')
                    self.assertTrue(any('/proc/$pid/exe' in cmd for cmd in called),'scoped cleanup did not run')
                    self.assertNotIn('pkill',''.join(called))
                finally:
                    if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                    # Fixture-only guard: PID points to our unique uploaded native
                    # executable; never signal arbitrary reused PIDs.
                    try:
                        exe=os.readlink(f'/proc/{pid}/exe')
                        if str(parent) in exe:os.kill(pid,signal.SIGKILL)
                    except FileNotFoundError:pass

    async def test_cancel_stops_only_owned_native_child_and_removes_temp(self):
        await self.local_run(cancel=True)

    async def test_timeout_stops_only_owned_native_child_and_removes_temp(self):
        await self.local_run(timeout=True)

    async def test_cleanup_error_does_not_discard_complete_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'service-unlock_linux_amd64').write_bytes(b'fixture')
            async def runner(args,**kwargs):
                cmd=args[-1]
                if cmd=='LC_ALL=C uname -m':return 0,'amd64',''
                if 'cat > "$work/probe"' in cmd:return 1,'complete-report','separate stderr'
                return 255,'','SSH cleanup unreachable'
            with patch.dict(s.CATALOGUE['binary_sha256'], {'amd64':hashlib.sha256(b'fixture').hexdigest()}):
                out=await s.remote_run({},lambda server,cmd,**kw:['stub',cmd],lambda server:None,binary_dir=root,runner=runner)
            self.assertEqual(out[:3],(1,'complete-report','separate stderr'))
            self.assertIn('cleanup failed',out[3])

if __name__=='__main__':unittest.main()
