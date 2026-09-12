"""Capability gate safety; cadence is covered by persistence tests."""
import subprocess
import unittest
from test_full_features import bot,callbacks

class QualityIpv6GateTest(unittest.TestCase):
    def test_unverified_renderers_fail_closed(self):
        server={'id':'test','host':'192.0.2.10','ipv6':'2606:4700::1111'}
        for markup in (bot.ipquality_markup(server),bot.confirm_nq_markup(server,15)):
            self.assertFalse(any(x.endswith(':46') for x in callbacks(markup)))

    def test_probe_is_bounded_direct_ipv6_read_only(self):
        command=bot.IPV6_PROBE_COMMAND
        self.assertIn('--noproxy',command)
        self.assertIn('-6',command)
        self.assertIn('--max-time 4',command)
        self.assertIn('disable_ipv6',command)
        self.assertNotIn('sysctl -w',command)
        result=subprocess.run(['bash','-n','-c',command],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_saved_unavailable_wins_over_old_address(self):
        s={'ipv6':'2606:4700::1111','ipv6_status':{'available':False,'reason':'没有可用 IPv6'}}
        self.assertEqual(bot.stored_ipv6_status(s),(False,'没有可用 IPv6'))

    def test_legacy_address_is_kept_until_real_test(self):
        self.assertTrue(bot.stored_ipv6_status({'ipv6':'2606:4700::1111'})[0])
        self.assertFalse(bot.stored_ipv6_status({})[0])

if __name__=='__main__':unittest.main()
