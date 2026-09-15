"""Execute production command generation and Bash in an isolated fake host.
No SSH, Telegram, network, or production proxy files are accessed.
"""
import ast
import hashlib
import json
import asyncio
import html
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / 'tests/fixtures/proxy-command-baseline.json').read_text())


def load(path):
    tree = ast.parse(path.read_text())
    names = {'run_proxy_tool_task', 'proxy_tool_config', 'proxy_answers',
             'proxy_extract_config', 'is_proxy_link_line', 'format_proxy_config_html',
             'proxy_menu_text', 'proxy_markup'}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PROXY_TOOLS' for t in n.targets)]
    ns = dict(os=os, shlex=shlex, re=re, safe=lambda v: html.escape(str(v)),
              strip_ansi=lambda s: re.sub(r'\x1b\[[0-9;]*m', '', s), trim_log=lambda s, n=3600: s[:n],
              server_id=lambda s: 'test', ssh_env_for=lambda s: {},
              ssh_args=lambda s, remote, tty=False: remote, ParseMode=types.SimpleNamespace(HTML='HTML'),
              finish_job=lambda *a: None, JOBS={'job': {}},
              InlineKeyboardButton=lambda text, **kw: dict(text=text, **kw), InlineKeyboardMarkup=lambda rows: rows)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)
    return ns


async def invoke(path, action='ensure', kind='anytls', runner=None, mode=None):
    ns = load(path)
    captured = {}
    async def run(cmd, **kw):
        captured.update(command=cmd, **kw)
        return runner(cmd) if runner else (0, '当前配置\nanytls://existing-secret@example.invalid:443')
    async def send(*args, **kw):
        captured['message'] = args[-1]
    ns.update(run_subprocess=run, send_long_text=send)
    bot = types.SimpleNamespace(send_message=send)
    await ns['run_proxy_tool_task'](bot, 1, {'name': 'test'}, 'job', kind, action, mode)
    captured['job'] = ns['JOBS']['job']
    return captured


class ExistingAnyTLSTests(unittest.TestCase):
    def run_host(self, action='ensure', installed=True, unit=True, fail_view=False, download_fail=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for folder in ('root', 'usr/local/bin', 'etc/systemd/system', 'etc/anytls', 'fakebin'):
                (root / folder).mkdir(parents=True)
            binary = root / 'usr/local/bin/anytls-server'
            if installed:
                binary.write_text('#!/bin/bash\necho binary-invoked >> "$AUDIT"\n')
                binary.chmod(0o755)
            if unit:
                (root / 'etc/systemd/system/anytls.service').write_text('existing unit')
            config = root / 'etc/anytls/config'
            original = b'password=existing-secret\nport=443\n'
            config.write_bytes(original)
            manager = root / 'manager.sh'
            manager.write_text('''#!/bin/bash
echo "manager:$1" >> "$AUDIT"
if [[ "$1" == view ]]; then
  echo '当前配置'; echo 'anytls://existing-secret@example.invalid:443'
  exit "${FAIL_VIEW:-0}"
fi
cat > "$ANSWERS"
printf changed > "$CONFIG"
echo '当前配置'; echo 'anytls://new-secret@example.invalid:9999'
''')
            wrappers = {
                'curl': '''#!/bin/bash
echo "curl:$*" >> "$AUDIT"
[[ "${DOWNLOAD_FAIL:-0}" == 1 ]] && exit 22
if [[ "$*" == *api.github.com* ]]; then printf '{"tag_name": "v99.0.0"}\\n'; exit; fi
while [[ $# -gt 0 ]]; do if [[ "$1" == -o ]]; then cp "$MANAGER" "$2"; exit; fi; shift; done
exit 2
''',
                'strings': '#!/bin/bash\necho strings-missing >> "$AUDIT"\nexit 127\n',
                'systemctl': '#!/bin/bash\necho "systemctl:$*" >> "$AUDIT"\nexit 0\n',
            }
            for name, content in wrappers.items():
                f = root / 'fakebin' / name
                f.write_text(content)
                f.chmod(0o755)
            audit = root / 'audit'
            answers = root / 'answers'
            def runner(cmd):
                for prefix in ('/usr/local/bin/', '/etc/systemd/system/', '/usr/local/etc/', '/root'):
                    cmd = cmd.replace(prefix, td + prefix)
                env = dict(os.environ, PATH=str(root / 'fakebin') + ':' + os.environ['PATH'],
                           AUDIT=str(audit), MANAGER=str(manager), CONFIG=str(config), ANSWERS=str(answers),
                           FAIL_VIEW='9' if fail_view else '0', DOWNLOAD_FAIL='1' if download_fail else '0')
                result = subprocess.run(['bash', '-c', cmd], env=env, capture_output=True, text=True, timeout=10)
                return result.returncode, result.stdout + result.stderr
            result = asyncio.run(invoke(ROOT / 'telegram-bot/bot.py', action, runner=runner))
            result.update(audit=audit.read_text() if audit.exists() else '', config=config.read_bytes(),
                          original=original, answers=answers.read_text() if answers.exists() else '',
                          leftovers=list((root / 'root').glob('guko-*')))
            return result

    def test_existing_ensure_preserves_credentials_without_strings(self):
        r = self.run_host()
        self.assertEqual(r['config'], r['original'])
        self.assertIn('manager:view', r['audit'])
        self.assertNotIn('manager:install', r['audit'])
        self.assertEqual(r['job']['status'], 'done')
        self.assertIn('anytls://existing-secret@example.invalid:443', r['message'])

    def test_existing_install_alias_is_read_only(self):
        r = self.run_host('install')
        self.assertEqual(r['config'], r['original'])
        self.assertIn('manager:view', r['audit'])

    def test_existing_never_probes_version_or_restarts_service(self):
        r = self.run_host()
        for forbidden in ('api.github.com', 'strings-missing', 'binary-invoked', 'systemctl:'):
            self.assertNotIn(forbidden, r['audit'])

    def test_existing_message_describes_current_node_not_update(self):
        r = self.run_host()
        self.assertIn('当前配置', r['message'])
        for forbidden in ('程序已更新', '发现程序更新', '安装/更新检查完成', '最新版'):
            self.assertNotIn(forbidden, r['message'])

    def test_existing_binary_without_unit_is_not_overwritten(self):
        r = self.run_host(unit=False)
        self.assertEqual(r['config'], r['original'])
        self.assertIn('manager:view', r['audit'])

    def test_failed_view_does_not_fall_back_to_install(self):
        r = self.run_host(fail_view=True)
        self.assertEqual(r['job']['status'], 'failed')
        self.assertEqual(r['config'], r['original'])
        self.assertNotIn('manager:install', r['audit'])

    def test_missing_binary_installs_with_configured_port(self):
        for action in ('ensure', 'install'):
            with self.subTest(action=action), patch.dict(os.environ, {'GUKO_ANYTLS_DEFAULT_PORT': '15443'}):
                r = self.run_host(action, installed=False, unit=False)
                self.assertIn('manager:install', r['audit'])
                self.assertEqual(r['answers'], '15443\n\n')
                self.assertEqual(r['job']['status'], 'done')
                self.assertIn('安装完成', r['message'])

    def test_missing_binary_uses_existing_default_prompts(self):
        with patch.dict(os.environ, {'GUKO_ANYTLS_DEFAULT_PORT': ''}):
            r = self.run_host(installed=False)
            self.assertEqual(r['answers'], '\n\n')

    def test_view_stays_read_only(self):
        r = self.run_host('view')
        self.assertEqual(r['config'], r['original'])
        self.assertIn('manager:view', r['audit'])
        self.assertNotIn('api.github.com', r['audit'])

    def test_download_failure_fails_closed(self):
        r = self.run_host(download_fail=True)
        self.assertEqual(r['job']['status'], 'failed')
        self.assertEqual(r['config'], r['original'])
        self.assertNotIn('manager:', r['audit'])

    def test_temporary_script_removed(self):
        for kwargs in ({}, {'installed': False}, {'fail_view': True}, {'download_fail': True}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.run_host(**kwargs)['leftovers'], [])

    def test_other_protocol_commands_and_messages_unchanged(self):
        for kind in ('ss', 'snell', 'vless'):
            for action in ('ensure', 'install', 'view'):
                for mode in ((None, 'reality') if kind == 'vless' else (None,)):
                    for port in ('', '15443'):
                        with self.subTest(kind=kind, action=action, mode=mode, port=port), patch.dict(os.environ, {f'GUKO_{kind.upper()}_DEFAULT_PORT': port}):
                            old = BASELINE[json.dumps([kind, action, mode, port])]
                            new = asyncio.run(invoke(ROOT / 'telegram-bot/bot.py', action, kind, mode=mode))
                            self.assertEqual(hashlib.sha256(json.dumps(new, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), old)

    def test_unknown_action_fails_without_remote_execution(self):
        r = asyncio.run(invoke(ROOT / 'telegram-bot/bot.py', 'invalid'))
        self.assertNotIn('command', r)
        self.assertEqual(r['job']['status'], 'failed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
