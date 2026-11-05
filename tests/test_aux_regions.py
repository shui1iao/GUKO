"""CLI0.5.8 original pipeline/renderer + HTTPmock, NOT real measurement."""
import copy
import json
from pathlib import Path
import unittest
import stream_unified as u
import stream_terminal as t
ROOT=Path(__file__).parent/'fixtures/unified'
def envelope(name='sea'):return json.loads((ROOT/(name+'.json')).read_text())
class AuxiliaryRegionTest(unittest.TestCase):
    def test_six_countries_are_auxiliary_not_exit_or_primary_votes(self):
        d=envelope();r,term,_=u.validate_output(json.dumps(d),1)
        self.assertEqual(r['selection']['detected_country'],'SG')
        for field,ids in [('results',u.AUX_ACCESS_REGIONS),('services',u.AUX_SERVICE_REGIONS)]:
            for row in r[field]:
                if row['id'] in ids:self.assertEqual(row['region'],'JP')
        spotify=next(x for x in r['services'] if x['id']=='spotify_signup')
        self.assertEqual((spotify['status'],spotify['value'],spotify['region']),('error',None,'JP'))
        groups=t._groups(r,u._country);rows=[row for _,rs in groups for row in rs]
        for name in ('ChatGPT','TikTok','YouTube'):
            row=next(x for x in rows if t._plain(x[0])==name)
            self.assertEqual((t._plain(row[1]),t._plain(row[2])),('● Yes','JP'))
        d=envelope('sea-primary-denied');r,_,_=u.validate_output(json.dumps(d),1)
        for x in r['results']:
            if x['id'] in u.AUX_ACCESS_REGIONS:self.assertEqual((x['status'],x['region']),('blocked','JP'))
        d=envelope('sea-aux-unknown');r,_,_=u.validate_output(json.dumps(d),1)
        for x in r['results']:
            if x['id'] in u.AUX_ACCESS_REGIONS:self.assertEqual((x['status'],x['region']),('available',None))
        for x in r['services']:
            if x['id'] in u.AUX_SERVICE_REGIONS:self.assertNotIn('region',x)
    def test_auxiliary_metadata_contract_is_strict_and_same_terminal(self):
        for value in (None,'','WW','EU','UK','USA','ZZ','jp',42,{},['JP']):
            d=envelope();next(x for x in d['report']['services'] if x['id']=='spotify_signup')['region']=value
            with self.subTest(value=value),self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
        for field,id in [('services','youtube_music'),('services','twitch'),('ai_endpoints','deepseek')]:
            d=envelope();next(x for x in d['report'][field] if x['id']==id)['region']='JP'
            with self.subTest(id=id),self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
        for field,id in [('results','chatgpt_web'),('services','reddit_guest')]:
            d=envelope();next(x for x in d['report'][field] if x['id']==id)['region']='SG'
            with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
        d=envelope();next(x for x in d['report']['services'] if x['id']=='spotify_signup')['region_error']='secret response'
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
    def test_country_never_promotes_strict_spotify(self):
        d=envelope('jp-denied');r,_,_=u.validate_output(json.dumps(d),1)
        spotify=next(x for x in r['services'] if x['id']=='spotify_signup');self.assertEqual((spotify['value'],spotify['region']),('no','JP'))
        for name in ('sea','sea-primary-denied','sea-aux-unknown'):
            d=envelope(name);r,_,_=u.validate_output(json.dumps(d),1)
            spotify=next(x for x in r['services'] if x['id']=='spotify_signup');self.assertEqual((spotify['status'],spotify['value']),('error',None))
        d=envelope('jp-denied');next(x for x in d['report']['services'] if x['id']=='spotify_signup')['value']='yes'
        with self.assertRaises(ValueError):u.validate_output(json.dumps(d),1)
