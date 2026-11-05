"""Current platform/six-purpose/fragment-style/wrapping regression, offline."""
import copy
import json
from pathlib import Path
import unittest
import stream_unified as u
import stream_terminal as t
ROOT=Path(__file__).resolve().parents[1]
def envelope(name='jp'):return json.loads((ROOT/'tests/fixtures/unified'/(name+'.json')).read_text())

class PlatformPresentationTest(unittest.TestCase):
    def test_one_platform_row_six_categories_independent_api_colors_and_source_regions(self):
        d=envelope();groups=t._groups(d['report'],u._country)
        self.assertEqual([name for name,rows in groups],t.CONTRACT['titles'])
        rows=[row for name,rows in groups for row in rows];names=[t._plain(r[0]) for r in rows]
        self.assertEqual(names.count('ChatGPT'),1);self.assertEqual(names.count('Netflix'),1)
        netflix=next(r for r in rows if t._plain(r[0])=='Netflix')
        self.assertIn('Catalogue US',t._plain(netflix[2]));self.assertIn('Fast US',t._plain(netflix[2]))
        # Synthetic unit mutation of the already-mocked measurement, not field
        # evidence: Web Yes stays green while API independently becomes Unknown.
        next(r for r in d['report']['ai_endpoints'] if r['id']=='openai')['status']='error'
        rows=[r for _,rs in t._groups(d['report'],u._country) for r in rs]
        cell=next(r[1] for r in rows if t._plain(r[0])=='ChatGPT');plain=t._plain(cell)
        self.assertEqual(plain,'Web ● Yes · API ○ Unknown')
        yes=plain.index('Yes');unknown=plain.index('Unknown')
        self.assertEqual(cell[yes][1:],(True,2));self.assertEqual(cell[unknown][1:],(True,None))
        # A terminal still claiming both Yes cannot pass against this raw report.
        with self.assertRaises(ValueError):t.validate_terminal(d['terminal'],d['report'],u.selection_label(d['report']['selection']),u._country)
    def test_real_official_narrow_renderer_wraps_losslessly_and_refuses_deleted_continuation(self):
        d=envelope('jp-narrow');raw=json.dumps(d)
        report,term,_=u.validate_output(raw,1)
        width=len(term.splitlines()[1]);self.assertLessEqual(width,40)
        rows=[r for _,rs in t._groups(report,u._country) for r in rs]
        self.assertGreater(len(term.splitlines()),len(rows)+15)
        # Delete an actual wrapped physical row; strict raw/ANSI matching fails.
        lines=term.splitlines();index=next(i for i,line in enumerate(lines) if line.startswith('│ ') and i>10 and 'Unknown' in line)
        del lines[index];d['terminal']='\n'.join(lines)+'\n'
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
    def test_semantically_wrong_fragment_color_or_oversize_rejected(self):
        d=envelope();d['terminal']=d['terminal'].replace('\x1b[1;38;5;2m● Yes','\x1b[1;38;5;1m● Yes',1)
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
        d=envelope();d['terminal']+='x'*(2<<20)
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
