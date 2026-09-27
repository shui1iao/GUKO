"""Read real fake-host files without a usable remote interpreter."""
import asyncio
import base64
import unittest

from test_anytls_existing import ROOT, invoke
from test_proxy_readonly import KINDS, host


class NoPythonProxyTests(unittest.TestCase):
    def test_existing_view_and_ensure_work_without_python(self):
        for kind in KINDS:
            for action in ('view', 'ensure'):
                with self.subTest(kind=kind, action=action):
                    result = host(kind, action=action, no_python=True)
                    self.assertEqual(result['job']['status'], 'done', result['message'])
                    self.assertIn('当前配置', result['message'])
                    self.assertIn({'ss': 'ss://', 'anytls': 'anytls://fixture-secret@',
                                   'snell': 'version=6', 'vless': 'vless://'}[kind], result['message'])
                    self.assertEqual(result['before'], result['after'])
                    self.assertEqual(result['audit'], 'binary\n' if kind == 'snell' else '')
                    self.assertNotIn('GUKO_SNAPSHOT', result['job']['log'])

    def test_absent_ensure_installs_once_without_reader_python(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                result = host(kind, 'absent', no_python=True)
                self.assertEqual(result['job']['status'], 'done', result['message'])
                self.assertNotIn('python3', result['audit'])
                self.assertEqual(result['audit'].count('curl:'), 1)
                self.assertEqual(result['audit'].count('install:'), 1)

    def test_absent_view_never_installs_without_python(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                result = host(kind, 'absent', 'view', no_python=True)
                self.assertEqual(result['job']['status'], 'failed')
                self.assertIn('未安装', result['message'])
                self.assertEqual(result['audit'], '')

    def test_broken_state_fails_closed_without_python(self):
        for kind in KINDS:
            for state in ('corrupt', 'unreadable', 'empty', 'no_config', 'binary_only',
                          'directory_only', 'symlink', 'oversized', 'fifo'):
                for action in ('ensure', 'view'):
                    with self.subTest(kind=kind, state=state, action=action):
                        result = host(kind, state, action, no_python=True)
                        self.assertEqual(result['job']['status'], 'failed')
                        self.assertEqual(result['audit'], '')
                        self.assertEqual(result['before'], result['after'])
                        self.assertNotIn('fixture-secret', result['message'])
                        self.assertNotIn('fixture-secret', result['job']['log'])

    def test_vless_legacy_and_summary_checks_without_python(self):
        for action in ('ensure', 'view'):
            for state, mode, expected in (
                ('legacy', 'none', 'done'), ('installed', 'tls', 'done'),
                ('installed', 'reality', 'done'), ('stale_client', 'reality', 'failed'),
                ('client_unreadable', 'tls', 'failed'), ('other_xray', 'none', 'failed'),
                ('client_unreadable', 'none', 'done'),
            ):
                with self.subTest(action=action, state=state, mode=mode):
                    result = host('vless', state, action, no_python=True, existing_mode=mode)
                    self.assertEqual(result['job']['status'], expected, result['message'])
                    self.assertEqual(result['audit'], '')
                    self.assertEqual(result['before'], result['after'])

    def test_plain_vless_ignores_invalid_optional_summary(self):
        for state in ('client_invalid_utf8', 'client_oversized'):
            for mode in ('none', 'tls', 'reality'):
                for action in ('view', 'ensure'):
                    with self.subTest(state=state, mode=mode, action=action):
                        result = host('vless', state, action, no_python=True, existing_mode=mode)
                        self.assertEqual(result['job']['status'], 'done' if mode == 'none' else 'failed')
                        self.assertEqual(result['audit'], '')
                        self.assertEqual(result['before'], result['after'])

    def test_file_at_bound_still_renders_without_python(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                result = host(kind, 'at_limit', no_python=True)
                self.assertEqual(result['job']['status'], 'done', result['message'])
                self.assertEqual(result['audit'], 'binary\n' if kind == 'snell' else '')
                self.assertEqual(result['before'], result['after'])

    def test_snell_version_failures_never_guess_or_leak(self):
        from proxy_nodes import render_snapshot, snell_major
        files = {'config': '[snell-server]\nlisten=0.0.0.0:443\npsk=fixture-secret\n'}
        for raw in ('', 'v99.0.0\nGUKO_VERSION_RC:1\n', 'v99.0.0',
                    'v99.0.0' + 'x' * 4097 + '\nGUKO_VERSION_RC:0\n'):
            with self.subTest(size=len(raw)):
                self.assertIsNone(snell_major(raw))
                output = render_snapshot('snell', 'example.invalid', files, raw)
                self.assertIn('核心版本不可读取', output)
                self.assertNotIn('version=99', output)
                self.assertNotIn('GUKO_VERSION_RC', output)

    def test_hex_transport_rejects_wrong_kind_invalid_utf8_and_odd_hex(self):
        from proxy_nodes import ProxyReadError, parse_snapshot
        for kind, value in (('anytls', '7b7d'), ('ss', 'ff'), ('ss', '123')):
            with self.subTest(kind=kind, value=value):
                raw = f'GUKO_SNAPSHOT_V1:{kind}\nconfig:ok\n{value}\nGUKO_END_FILE\nGUKO_END_SNAPSHOT\n'
                with self.assertRaises(ProxyReadError):
                    parse_snapshot('ss', raw)

    def test_interrupted_collection_does_not_leak_even_encoded_secrets(self):
        secret = 'INTERRUPTED-DO-NOT-LEAK'
        frame = 'GUKO_SNAPSHOT_V1:ss\nconfig:ok\n' + secret.encode().hex()
        for code in (0, 23, 124, 255):
            with self.subTest(code=code):
                result = asyncio.run(invoke(ROOT/'telegram-bot/bot.py', 'view', 'ss', lambda command: (code, frame)))
                self.assertEqual(result['job']['status'], 'failed')
                for output in (result['message'], result['job']['log']):
                    self.assertNotIn(secret, output)
                    self.assertNotIn(secret.encode().hex(), output)
                    self.assertNotIn('GUKO_SNAPSHOT', output)

    def test_malformed_snapshot_is_bounded_and_never_leaks_raw_secrets(self):
        secret = 'DO-NOT-LEAK-snapshot-password'
        encoded = secret.encode().hex()
        # 20 identifies an existing-node snapshot, never installer output.
        frames = [
            secret,
            f'GUKO_SNAPSHOT_V1:ss\nconfig:ok\n{encoded}\n',
            f'GUKO_SNAPSHOT_V1:ss\nconfig:ok\n{encoded}\nGUKO_END_FILE\nGUKO_END_SNAPSHOT\n',
            f'GUKO_SNAPSHOT_V1:ss\nconfig:ok\n{secret}\nGUKO_END_FILE\nGUKO_END_SNAPSHOT\n',
            'GUKO_SNAPSHOT_V1:ss\n' + encoded * 40000,
            f'GUKO_SNAPSHOT_V1:ss\nconfig:ok\n{encoded}\nGUKO_END_FILE\nconfig:ok\n{encoded}\nGUKO_END_FILE\nGUKO_END_SNAPSHOT\n',
            f'GUKO_SNAPSHOT_V1:ss\n/etc/shadow:ok\n{encoded}\nGUKO_END_FILE\nGUKO_END_SNAPSHOT\n',
        ]
        for frame in frames:
            with self.subTest(size=len(frame), prefix=frame[:32]):
                result = asyncio.run(invoke(ROOT/'telegram-bot/bot.py', 'ensure', 'ss', lambda command: (20, frame)))
                self.assertEqual(result['job']['status'], 'failed')
                for output in (result['message'], result['job']['log']):
                    self.assertNotIn(secret, output)
                    self.assertNotIn(encoded, output)
                    self.assertNotIn(base64.b64encode(secret.encode()).decode(), output)
                    self.assertLess(len(output), 1000)
