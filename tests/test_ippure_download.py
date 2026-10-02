from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "telegram-bot" / "tools" / "download_ippure.js"


class IPPureDownloadTest(unittest.TestCase):
    def test_visitor_ipv6_probe_is_aborted_before_card_wait(self):
        # IPPure probes the visitor's own IPv6 before rendering the queried card.
        # Hosts with an IPv6 route but no IPv6 egress hang on this request and the
        # card never appears, so the probe must be aborted, not left to time out.
        text = SCRIPT.read_text()
        route = re.search(r"await page\.route\('\*\*/\*', route => \{(.*?)\n  \}\);", text, re.DOTALL)
        self.assertIsNotNone(route)
        body = route.group(1)
        abort_condition = body[: body.index("return route.abort()")]
        self.assertIn("url.startsWith('https://ipv6.icanhazip.com/')", abort_condition)
        self.assertLess(text.index("await page.route("), text.index("await page.goto("))
        self.assertLess(text.index("await page.goto("), text.index("waitForSelector('.iptable-container'"))

    def test_queried_ip_lookups_are_not_blocked(self):
        text = SCRIPT.read_text()
        route = re.search(r"await page\.route\('\*\*/\*', route => \{(.*?)\n  \}\);", text, re.DOTALL)
        abort_condition = route.group(1).split("return route.abort()")[0]
        prefixes = re.findall(r"url\.startsWith\('([^']+)'\)", abort_condition)
        substrings = re.findall(r"url\.includes\('([^']+)'\)", abort_condition)

        def blocked(url):
            return any(url.startswith(p) for p in prefixes) or any(s in url for s in substrings)

        self.assertTrue(blocked("https://ipv6.icanhazip.com/"))
        for url in (
            "https://ippure.com/?ip=203.0.113.7",
            "https://icanhazip.com/",
            "https://ipv4.icanhazip.com/",
            "https://api.123169.xyz/api/info/ip-basic/203.0.113.7",
            "https://api.123169.xyz/api/info/ip-risk/203.0.113.7",
            "https://ipinfo.io/widget/demo/203.0.113.7",
        ):
            self.assertFalse(blocked(url), url)


if __name__ == "__main__":
    unittest.main()
