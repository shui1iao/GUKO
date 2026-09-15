"""Real generated Bash, fake host paths, audited tools; never SSH or network."""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_anytls_existing import invoke, ROOT

KINDS = ('ss', 'anytls', 'snell', 'vless')
BINS = dict(zip(KINDS, ('ss-rust', 'anytls-server', 'snell-server', 'xray')))
CONFIGS = {'ss': '/etc/ss-rust/config.json', 'anytls': '/etc/systemd/system/anytls.service',
           'snell': '/etc/snell/snell-server.conf', 'vless': '/usr/local/etc/xray/config.json'}
UUID = '12345678-1234-4234-8234-123456789abc'


def host(kind, state='installed', action='ensure', mode=None, download_fail=False, existing_mode='none', default_port='15443'):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        def path(p):
            f = root / p.lstrip('/')
            f.parent.mkdir(parents=True, exist_ok=True)
            return f
        binary = path('/usr/local/bin/' + BINS[kind])
        config = path(CONFIGS[kind])
        unit = path('/etc/systemd/system/' + ('xray' if kind == 'vless' else 'ss-rust' if kind == 'ss' else kind) + '.service')
        path('/root/placeholder').touch()
        if state == 'absent':
            for folder in ('/etc/ss-rust', '/etc/snell', '/usr/local/etc/xray'):
                candidate = root / folder.lstrip('/')
                if candidate.is_dir(): candidate.rmdir()
        if state != 'absent':
            if state != 'no_binary':
                binary.write_text('#!/bin/bash\necho binary >> "$AUDIT"\necho snell-server v6.0.0\n')
                binary.chmod(0o755)
            unit.write_text('[Service]\n')
            data = {'ss': json.dumps({'server_port': 443, 'password': 'fixture-secret', 'method': 'aes-128-gcm'}),
                    'anytls': '[Service]\nExecStart=/usr/local/bin/anytls-server -l 0.0.0.0:443 -p fixture-secret\n',
                    'snell': '[snell-server]\nlisten = 0.0.0.0:443\npsk = fixture-secret\n',
                    'vless': json.dumps({'inbounds': [{'protocol': 'vless', 'port': 443, 'settings': {'clients': [{'id': UUID}]}, 'streamSettings': {'network': 'tcp', 'security': existing_mode}}]})}[kind]
            config.write_text(data)
            if kind == 'vless':
                path('/usr/local/etc/xray/client.txt').write_text(f'VLESS {existing_mode}\nvless://{UUID}@example.invalid:443?security={existing_mode}&type=tcp#fixture\n')
            if state == 'no_unit':
                unit.unlink()
            elif state == 'corrupt':
                config.write_text('broken config')
            elif state == 'unreadable':
                config.chmod(0)
            elif state == 'stale_client':
                path('/usr/local/etc/xray/client.txt').write_text('VLESS stale\nvless://wrong@example.invalid:123?security=reality')
            elif state == 'binary_only':
                config.unlink()
                if unit.exists(): unit.unlink()
            elif state == 'nonexec_binary':
                binary.chmod(0o644)
            elif state == 'no_config':
                config.unlink()
            elif state == 'other_xray':
                config.write_text('{"inbounds":[{"protocol":"trojan","port":443}]}')
            elif state == 'legacy':
                path('/etc/xray/vless-basic.json').write_bytes(config.read_bytes()); config.unlink()
                path('/usr/local/etc/xray/client.txt').unlink()
            elif state == 'symlink':
                config.unlink(); config.symlink_to('/nonexistent-fixture')
        watched = [p for p in root.rglob('*') if p.is_file() and 'placeholder' not in p.name]
        before = {str(p): p.read_bytes() for p in watched}
        audit = root / 'audit'
        manager = path('/manager.sh')
        manager.write_text('''#!/bin/bash
if [[ "$1" == view ]]; then echo forbidden-view >> "$AUDIT"; echo 当前配置; exit 0; fi
echo "install:$*" >> "$AUDIT"
cat > "$ANSWERS"
echo 当前配置
echo fixture-installed
''')
        wrappers = {
            'curl': '''#!/bin/bash
echo "curl:$*" >> "$AUDIT"
[[ "$DOWNLOAD_FAIL" == 1 ]] && exit 22
[[ "$*" == *api.github.com* ]] && { echo '{"tag_name":"v99.0.0"}'; exit; }
while [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && { cp "$MANAGER" "$2"; exit; }; shift; done
exit 99
''',
            'systemctl': '#!/bin/bash\necho "systemctl:$*" >> "$AUDIT"\nexit 0\n',
            'ss': '#!/bin/bash\nexit 0\n',
            'strings': '#!/bin/bash\necho strings >> "$AUDIT"\n',
        }
        for name, content in wrappers.items():
            f = path('/fakebin/' + name); f.write_text(content); f.chmod(0o755)
        def runner(command):
            command = re.sub(r'/usr/local/(?:bin|etc)(?=/|[\"\'])|/(?:usr/)?lib/systemd/system|/etc(?=/|[\"\'])|/root(?=[/;\s])', lambda m: td + m[0], command)
            result = subprocess.run(['bash', '-c', command], capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, PATH=str(root/'fakebin')+':'+os.environ['PATH'],
                                             AUDIT=str(audit), MANAGER=str(manager), ANSWERS=str(root/'answers'),
                                             DOWNLOAD_FAIL=str(int(download_fail))))
            return result.returncode, result.stdout + result.stderr
        with patch.dict(os.environ, {f'GUKO_{kind.upper()}_DEFAULT_PORT': default_port}):
            result = asyncio.run(invoke(ROOT/'telegram-bot/bot.py', action, kind, runner, mode))
        result.update(audit=audit.read_text() if audit.exists() else '',
                      before=before, after={str(p): p.read_bytes() for p in watched if p.exists()},
                      answers=(root/'answers').read_text() if (root/'answers').exists() else '',
                      leftovers=list((root/'root').glob('guko-*')))
        return result


class ProxyReadonlyTests(unittest.TestCase):
    def test_vless_modes_share_one_install_job_lock(self):
        source = (ROOT/'telegram-bot/bot.py').read_text()
        self.assertNotIn("launch_job(s, f'vless-{mode}'", source)

    def test_deployment_includes_shared_module(self):
        self.assertIn('proxy_nodes.py', (ROOT/'telegram-bot/Dockerfile').read_text())

    def test_snell_reports_actual_local_major_without_update_http(self):
        r = host('snell')
        self.assertIn('version=6', r['message'])
        self.assertNotIn('curl:', r['audit'])

    def test_stale_vless_summary_fails_closed(self):
        r = host('vless', 'stale_client', existing_mode='reality')
        self.assertEqual(r['job']['status'], 'failed')
        self.assertEqual(r['audit'], '')
        self.assertEqual(r['before'], r['after'])

    def test_all_existing_actions_are_readonly(self):
        for kind in KINDS:
            for action in ('install', 'ensure', 'view'):
                for state in ('installed', 'no_binary', 'no_unit', 'nonexec_binary'):
                    with self.subTest(kind=kind, action=action, state=state):
                        r = host(kind, state, action)
                        self.assertEqual(r['before'], r['after'])
                        expected_audit = 'binary\n' if kind == 'snell' and state in ('installed', 'no_unit') else ''
                        self.assertEqual(r['audit'], expected_audit)
                        expected = 'failed' if kind == 'anytls' and state == 'no_unit' else 'done'
                        self.assertEqual(r['job']['status'], expected, r['job'])
                        if expected == 'done': self.assertIn('当前配置', r['message'])
                        self.assertNotIn('更新', r['message'])

    def test_partial_or_corrupt_state_fails_closed(self):
        for kind in KINDS:
            for state in ('corrupt', 'no_config', 'symlink', 'unreadable', 'binary_only'):
                for action in ('ensure', 'view'):
                    with self.subTest(kind=kind, state=state, action=action):
                        r = host(kind, state, action)
                        self.assertEqual(r['before'], r['after'])
                        self.assertEqual(r['audit'], '')
                        self.assertEqual(r['job']['status'], 'failed', r['job'])

    def test_fresh_xray_keeps_existing_installer_compatibility_guards(self):
        r = host('vless', 'absent')
        self.assertIn('geoip:private', r['command'])
        self.assertIn('run -test', r['command'])

    def test_original_default_prompts_are_preserved(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                r = host(kind, 'absent', default_port='')
                self.assertEqual(r['job']['status'], 'done', r['job'])
                expected = {'ss':'\n\n\n', 'anytls':'\n\n', 'snell':'\n\n', 'vless':'2\n8443\n\n0\n'}[kind]
                self.assertEqual(r['answers'], expected)

    def test_fresh_install_calls_original_manager(self):
        for kind in KINDS:
            for action in ('ensure', 'install'):
                for mode in (('plain', 'reality') if kind == 'vless' else (None,)):
                    with self.subTest(kind=kind, action=action, mode=mode):
                        r = host(kind, 'absent', action, mode)
                        self.assertEqual(r['job']['status'], 'done', r['job'])
                        self.assertEqual(r['audit'].count('curl:'), 1)
                        self.assertEqual(r['audit'].count('install:'), 1)
                        self.assertNotIn('api.github.com', r['audit'])
                        self.assertIn('15443\n', r['answers'])
                        if kind == 'vless': self.assertTrue(r['answers'].startswith('3\n' if mode == 'reality' else '2\n'))
                        self.assertEqual(r['leftovers'], [])

    def test_download_failures_do_not_execute_manager(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                r = host(kind, 'absent', download_fail=True)
                self.assertEqual(r['job']['status'], 'failed')
                self.assertNotIn('install:', r['audit'])
                self.assertEqual(r['leftovers'], [])
                r = host(kind, download_fail=True)
                self.assertEqual(r['job']['status'], 'done', r['job'])
                self.assertEqual(r['audit'], 'binary\n' if kind == 'snell' else '')

    def test_view_absent_never_downloads_or_installs(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                r = host(kind, 'absent', 'view')
                self.assertEqual(r['audit'], '')
                self.assertEqual(r['job']['status'], 'failed')

    def test_vless_retains_original_mode_and_protects_other_protocols(self):
        for existing in ('none', 'reality', 'tls'):
            for requested in ('plain', 'reality'):
                r = host('vless', mode=requested, existing_mode=existing)
                self.assertEqual(r['audit'], '')
                self.assertEqual(r['job']['status'], 'done', r['job'])
                self.assertIn('security='+existing, r['message'])
        r = host('vless', 'other_xray')
        self.assertEqual(r['audit'], '')
        self.assertEqual(r['job']['status'], 'failed')
        self.assertIn('不是 VLESS', r['message'])
        r = host('vless', 'legacy')
        self.assertEqual(r['audit'], '')
        self.assertEqual(r['job']['status'], 'done', r['job'])
        self.assertEqual(r['before'], r['after'])
