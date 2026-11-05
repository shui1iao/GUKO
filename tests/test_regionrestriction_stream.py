"""No retired detector/semantic mirrors in production; passive history remains.
Actual historical 0.5.4/0.5.6/0.5.7 and dual-image replay is exercised in
 test_stream_unified.TaskTest, never by running a retired backend.
"""
import unittest
from test_stream_unified import bot
class NoRetiredBusinessMirror(unittest.TestCase):
    def test_new_executor_has_no_retired_business_mirrors(self):
        for name in ('STREAM_REGION_BY_COUNTRY','REGIONRESTRICTION_REGIONS','parse_stream_results',
                     'stream_terminal_report','regionrestriction_remote_command','stream_status_label'):
            self.assertFalse(hasattr(bot,name),name)
