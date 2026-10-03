"""Fresh-install output keeps its real order; stderr never trails the config.

Runs the generated remote command in a fake host through the real
run_subprocess transport. No SSH, Telegram, network or real proxy files.
"""
import ast
import asyncio
import os
from pathlib import Path
import re
import tempfile
import types
import unittest

from test_anytls_existing import ROOT, load

KINDS = ('ss', 'anytls', 'snell', 'vless')
PATHS = r'/usr/local/(?:bin|etc)(?=/|[\"\'])|/(?:usr/)?lib/systemd/system|/etc(?=/|[\"\'])|/root(?=[/;\s])'
SUCCESS = '''#!/bin/bash
cat >/dev/null
echo "▶ 下载 fixture"
echo "progress-noise 100 12.7M" >&2
echo "请选择加密方式 progress-noise" >&2
echo "Created symlink progress-noise" >&2
echo "✓ 已安装并启动"
echo "VLESS 当前配置"
echo "fixture-config-line"
'''
FAILURE = '''#!/bin/bash
cat >/dev/null
echo "▶ 下载 fixture"
echo "curl: (22) The requested URL returned error: 503" >&2
exit 22
'''


def run_install(kind, manager_text):
    path = ROOT / 'telegram-bot/bot.py'
    ns = load(path)
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'run_subprocess')
    ns['asyncio'] = asyncio
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'root').mkdir()
        fakebin = root / 'fakebin'
        fakebin.mkdir()
        manager = root / 'manager.sh'
        manager.write_text(manager_text)
        wrappers = {
            'curl': '#!/bin/bash\nwhile [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && { cp "$MANAGER" "$2"; exit; }; shift; done\nexit 99\n',
            'ss': '#!/bin/bash\nexit 0\n',
        }
        for name, content in wrappers.items():
            (fakebin / name).write_text(content)
            (fakebin / name).chmod(0o755)
        env = dict(os.environ, PATH=str(fakebin) + ':' + os.environ['PATH'], MANAGER=str(manager))

        def ssh(s, remote, tty=False):
            remote = re.sub(PATHS, lambda m: td + m[0], remote)
            # Local SSH client warnings arrive on stderr before any remote output.
            return ['sh', '-c', 'echo "Warning: Permanently added fixture host." >&2; ' + remote]

        captured = {}

        async def send(*args, **kwargs):
            captured['message'] = args[-1]

        ns.update(ssh_args=ssh, ssh_env_for=lambda s: env, send_long_text=send)
        asyncio.run(ns['run_proxy_tool_task'](types.SimpleNamespace(send_message=send), 1,
                                           {'name': 'test', 'host': '192.0.2.1'}, 'job', kind, 'ensure'))
        return ns['JOBS']['job'], captured.get('message', '')


class InstallOutputOrderTests(unittest.TestCase):
    def test_install_progress_and_ssh_warning_do_not_trail_config(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                job, message = run_install(kind, SUCCESS)
                self.assertEqual(job['status'], 'done', job)
                self.assertIn('fixture-config-line', message)
                self.assertNotIn('progress-noise', message)
                self.assertNotIn('Warning:', message)
                log = job['log']
                self.assertLess(log.index('Warning:'), log.index('▶ 下载'))
                self.assertLess(log.index('▶ 下载'), log.index('progress-noise'))
                self.assertLess(log.rindex('progress-noise'), log.index('✓ 已安装并启动'))

    def test_failed_install_still_reports_error_in_order(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                job, message = run_install(kind, FAILURE)
                self.assertEqual(job['status'], 'failed', job)
                self.assertIn('退出码 22', message)
                self.assertIn('curl: (22)', message)
                self.assertLess(message.index('▶ 下载'), message.index('curl: (22)'))


if __name__ == '__main__':
    unittest.main()
