"""Existing SS/AnyTLS nodes render the same client formats as their managers.

The read-only path must not run the manager's view, yet users still need the
Surge (and AnyTLS Mihomo) lines the manager prints after a fresh install.
"""
import json
import sys
import unittest

from test_anytls_existing import ROOT
from test_proxy_readonly import host

sys.path.insert(0, str(ROOT))
from proxy_nodes import render_snapshot  # noqa: E402

RULE = '-' * 42


class ClientFormatTests(unittest.TestCase):
    def test_ss_matches_manager_layout_with_surge(self):
        config = json.dumps({'server_port': 15459, 'password': 'gK/+=', 'method': '2022-blake3-aes-128-gcm'})
        output = render_snapshot('ss', '192.0.2.10', {'config': config})
        self.assertEqual(output.splitlines(), [
            'GUKO_STATUS:已安装，直接读取当前配置',
            RULE,
            'ss-rust 当前配置',
            '地址: 192.0.2.10',
            '端口: 15459',
            '密码: gK/+=',
            '加密: 2022-blake3-aes-128-gcm',
            RULE,
            'Surge:',
            'VPS = ss, 192.0.2.10, 15459, encrypt-method=2022-blake3-aes-128-gcm, password=gK/+=, udp-relay=true',
            'URI:',
            'ss://2022-blake3-aes-128-gcm:gK%2F%2B%3D@192.0.2.10:15459#VPS',
            RULE,
        ])

    def test_ss_legacy_cipher_keeps_existing_uri(self):
        config = json.dumps({'server_port': 443, 'password': 'fixture-secret', 'method': 'aes-128-gcm'})
        output = render_snapshot('ss', '192.0.2.10', {'config': config})
        self.assertIn('VPS = ss, 192.0.2.10, 443, encrypt-method=aes-128-gcm, password=fixture-secret, udp-relay=true', output)
        self.assertIn('ss://YWVzLTEyOC1nY206Zml4dHVyZS1zZWNyZXQ@192.0.2.10:443#VPS', output)

    def test_anytls_matches_manager_layout_with_surge_and_mihomo(self):
        unit = "[Service]\nExecStart=/usr/local/bin/anytls-server -l 0.0.0.0:53588 -p 'Dx-Vp@m2/7'\n"
        output = render_snapshot('anytls', '192.0.2.10', {'config': unit})
        self.assertEqual(output.splitlines(), [
            'GUKO_STATUS:已安装，直接读取当前配置',
            RULE,
            'anytls 当前配置',
            '地址: 192.0.2.10',
            '端口: 53588',
            '密码: Dx-Vp@m2/7',
            RULE,
            'Surge:',
            'VPS = anytls, 192.0.2.10, 53588, password="Dx-Vp@m2/7", skip-cert-verify=true, udp-relay=true',
            'Mihomo:',
            '  - {"name":"VPS","server":"192.0.2.10","port":53588,"password":"Dx-Vp@m2/7","skip-cert-verify":true,"type":"anytls"}',
            'URI:',
            'anytls://Dx-Vp%40m2/7@192.0.2.10:53588?security=tls&type=tcp&allowInsecure=1&insecure=1#VPS',
            RULE,
        ])

    def test_bot_message_shows_copyable_surge_lines(self):
        expected = {
            'ss': ('Surge:', '<pre>VPS = ss, ', 'encrypt-method=aes-128-gcm, password=fixture-secret, udp-relay=true'),
            'anytls': ('Surge:', 'Mihomo:', '<pre>VPS = anytls, ', 'password=&quot;fixture-secret&quot;, skip-cert-verify=true'),
        }
        for kind, needles in expected.items():
            for action in ('view', 'ensure'):
                with self.subTest(kind=kind, action=action):
                    result = host(kind, action=action)
                    self.assertEqual(result['job']['status'], 'done', result['message'])
                    self.assertEqual(result['before'], result['after'])
                    self.assertEqual(result['audit'], '')
                    for needle in needles:
                        self.assertIn(needle, result['message'])


if __name__ == '__main__':
    unittest.main()
