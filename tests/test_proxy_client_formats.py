"""New Kat client contract; replaces obsolete ss-rust/AnyTLS-go file shapes.
Test source updated but not executed in this ordinary change.
"""
import json
import unittest
from test_kat_proxy import fixture,frame,encode,k


class ClientFormatTests(unittest.TestCase):
    def test_anytls_uri_quotes_slash_and_mihomo_enables_udp(self):
        plan,packet,_=fixture();nodes=k.parse_nodes('anytls',plan,frame(packet))
        output,complete=k.render('anytls','example.invalid',nodes)
        self.assertTrue(complete)
        self.assertIn('anytls://test%2F%40secret@',output)
        self.assertIn('"udp":true',output)
        self.assertIn('skip-cert-verify=true',output)

    def test_ss_2017_preserves_exact_secret_and_surge_quotes_fields(self):
        plan,packet,configs=fixture('ss');path=next(iter(configs))
        configs[path]['inbounds'][0]['ss']={'method':'aes-128-gcm','password':'a,b"\\/='}
        packet['config',path]=encode(configs[path])
        nodes=k.parse_nodes('ss',plan,frame(packet));out,complete=k.render('ss','2001:db8::1',nodes)
        self.assertTrue(complete)
        self.assertIn('VPS = ss, [2001:db8::1],',out)
        self.assertIn('password="a,b\\"\\\\/=", udp-relay=true',out)
        self.assertEqual(nodes[0]['password'],'a,b"\\/=')

    def test_multi_nodes_are_not_condensed_by_identical_password(self):
        plan,packet,_=fixture(extra=True);nodes=k.parse_nodes('anytls',plan,frame(packet))
        self.assertEqual(nodes[0]['password'],nodes[1]['password'])
        output,_=k.render('anytls','example.invalid',nodes)
        self.assertEqual(output.count('Surge:'),2)
        self.assertEqual(output.count('Mihomo:'),2)
