"""Current single-primary probe and regional-source-name contract, offline."""
import copy
import json
from pathlib import Path
import unittest
import stream_unified as u
import stream_terminal as t
ROOT=Path(__file__).resolve().parents[1]
def envelope(name='jp'):return json.loads((ROOT/'tests/fixtures/unified'/(name+'.json')).read_text())

class PlatformPresentationTest(unittest.TestCase):
    def test_single_primary_status_and_no_other_country_source(self):
        d=envelope();groups=t._groups(d['report'],u._country)
        names=[t._plain(r[0]) for _,rs in groups for r in rs]
        for name in ('ChatGPT','Claude','Gemini','Netflix'):
            self.assertEqual(names.count(name),1)
        rows=[r for _,rs in groups for r in rs]
        for row in rows:
            self.assertRegex(t._plain(row[1]),r'^[●○] (Yes|No|Limited|Unknown)$')
            self.assertNotIn(' · ',t._plain(row[1]))
        netflix=next(r for r in rows if t._plain(r[0])=='Netflix')
        source=next(r for r in d['report']['results'] if r['id']=='netflix_access')
        self.assertEqual(t._plain(netflix[2]),u._country(source['region']))
        self.assertFalse({'openai','anthropic','gemini','qwen_cn'} & {r['id'] for r in d['report']['ai_endpoints']})
        # Mutate only the retained Web result: old terminal Yes cannot validate.
        next(r for r in d['report']['results'] if r['id']=='chatgpt_web')['status']='blocked'
        with self.assertRaises(ValueError):t.validate_terminal(d['terminal'],d['report'],u.selection_label(d['report']['selection']),u._country)
    def test_all_selected_regions_original_media_names_order_and_counts(self):
        counts={'global-failed':28,'tw':39,'hk':36,'jp':54,'na':65,'sa':31,'eu':58,'oc':47,'kr':36,'sea':39,'af':31}
        for name,count in counts.items():
            d=envelope(name);report,_,_=u.validate_output(json.dumps(d),1);groups=t._groups(report,u._country)
            self.assertEqual(sum(len(rs) for _,rs in groups),count,name)
            region=report['selection']['region'];ids=set(u.CATALOGUE['groups'].get(region,()))-set(u.CATALOGUE['groups']['global'])
            expected=[t.CONTRACT['mapping']['extra:'+r['id']]['name'] for r in report['extra_checks'] if r['id'] in ids and t.CONTRACT['mapping']['extra:'+r['id']]['purpose'] in ('video','music')]
            actual=[t._plain(r[0]) for title,rs in groups if title.startswith('Regional media — ') for r in rs]
            self.assertEqual(actual,expected,name)
            if expected:self.assertEqual(groups[-1][0],'Regional media — '+t.CONTRACT['region_titles'][region])
            else:self.assertFalse(any(title.startswith('Regional media') for title,_ in groups))
        names=[t._plain(r[0]) for title,rs in t._groups(envelope('sea')['report'],u._country) if title.startswith('Regional media') for r in rs]
        samples=[r['display_name'] for r in u.CATALOGUE['extra'] if r['function'].startswith('MediaUnlockTest_BGlobal')]
        for sample in samples:self.assertEqual(names.count(sample),1)
        self.assertNotIn('Bilibili',names)
    def test_real_official_narrow_renderer_wraps_losslessly_and_refuses_deleted_continuation(self):
        d=envelope('jp-narrow');report,term,_=u.validate_output(json.dumps(d),1)
        self.assertLessEqual(len(term.splitlines()[1]),40)
        rows=[r for _,rs in t._groups(report,u._country) for r in rs]
        self.assertGreater(len(term.splitlines()),len(rows)+15)
        lines=term.splitlines();index=next(i for i,line in enumerate(lines) if line.startswith('│ ') and i>10 and 'Unknown' in line)
        del lines[index];d['terminal']='\n'.join(lines)+'\n'
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
    def test_semantically_wrong_fragment_color_or_oversize_rejected(self):
        d=envelope();d['terminal']=d['terminal'].replace('\x1b[1;38;5;2m● Yes','\x1b[1;38;5;1m● Yes',1)
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
        d=envelope();d['terminal']+='x'*(2<<20)
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
