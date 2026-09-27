"""Exercise actual subprocess transport with SSH-style stderr warnings."""
import ast
import asyncio
import json
import sys
import types
import unittest

from test_anytls_existing import ROOT, load


def run_with_ssh_warning():
    path = ROOT / 'telegram-bot/bot.py'
    ns = load(path)
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'run_subprocess')
    ns['asyncio'] = asyncio
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
    config = json.dumps({'server_port': 443, 'method': 'aes-128-gcm', 'password': 'fixture-secret'})
    frame = 'GUKO_SNAPSHOT_V1:ss\nconfig:ok\n' + config.encode().hex() + '\nGUKO_END_FILE\nGUKO_END_SNAPSHOT\n'
    script = ('import sys; '
              'sys.stderr.write("Warning: Permanently added host to known hosts.\\n"); '
              f'sys.stdout.write({frame!r}); sys.exit(20)')
    ns['ssh_args'] = lambda *args, **kwargs: [sys.executable, '-c', script]
    captured = {}

    async def send(*args, **kwargs):
        captured['message'] = args[-1]

    ns['send_long_text'] = send
    asyncio.run(ns['run_proxy_tool_task'](types.SimpleNamespace(send_message=send), 1,
                                       {'name': 'test', 'host': 'example.invalid'}, 'job', 'ss', 'view'))
    return ns['JOBS']['job'], captured


class SSHStderrTests(unittest.TestCase):
    def test_first_connection_warning_does_not_corrupt_snapshot(self):
        job, captured = run_with_ssh_warning()
        self.assertEqual(job['status'], 'done', captured)
        self.assertIn('ss://', captured['message'])
        self.assertNotIn('Warning:', job['log'])
