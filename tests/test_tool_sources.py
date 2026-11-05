"""Official source protocol regressions, all HTTP is injected in memory.
No live endpoints, platform probes, account actions or real installers.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import tool_sources as t
SHA='a'*40

def digest(data):return hashlib.sha256(data).hexdigest()
def source_zip():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for f in ('go.mod','go.sum','LICENSE','LICENSES/AGPL-3.0.txt','vendor/modules.txt'):z.writestr('source/'+f,'OFFLINE MOCK licensed source')
    return b.getvalue()

class OfficialHTTP:
    """Frozen official-shaped metadata and bytes, not evidence of a live version."""
    def __init__(self,repo='shui1iao/service-unlock',tag='v0.5.7',payloads=None):
        self.repo=repo;self.tag=tag;self.calls=[];self.fail_latest=False
        self.payloads=payloads or {'service-unlock_linux_amd64':b'OFFLINE native', 'service-unlock-v0.5.7-source.zip':source_zip()}
        self.payloads['SHA256SUMS']=''.join(digest(b)+'  '+n+'\n' for n,b in self.payloads.items()).encode()
        self.release={'id':123,'tag_name':tag,'draft':False,'prerelease':False,'assets':[
            {'name':n,'size':len(b),'digest':'sha256:'+digest(b),'browser_download_url':self.url(n)} for n,b in self.payloads.items()]}
    def url(self,name):return f'https://github.com/{self.repo}/releases/download/{self.tag}/{name}'
    def fetch(self,url,limit=4<<20,**kw):
        self.calls.append(url)
        prefix='https://api.github.com/repos/'+self.repo
        if url==prefix+'/releases/latest':
            if self.fail_latest:raise t.SourceError('offline latest unavailable')
            return json.dumps(self.release).encode(),url
        if url.startswith(prefix+'/commits/'):return json.dumps({'sha':SHA}).encode(),url
        for name,body in self.payloads.items():
            if url==self.url(name):return body,url
        raise AssertionError('Unexpected outbound URL in offline test')

class FrozenSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,TMP_DIR=self.temp.name);self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_each_task_rechecks_latest_cache_only_saves_bytes_and_failure_never_reuses(self):
        h=OfficialHTTP()
        with patch.object(t,'fetch',side_effect=h.fetch):
            a,m=t.stream_source('amd64');b,n=t.stream_source('amd64')
            self.assertEqual(a,b);self.assertFalse(m['binary']['download_cache']);self.assertTrue(n['binary']['download_cache'])
            self.assertEqual(h.calls.count('https://api.github.com/repos/shui1iao/service-unlock/releases/latest'),2)
            self.assertEqual(sum(x==h.url('service-unlock_linux_amd64') for x in h.calls),1)
            self.assertEqual(m['commit'],SHA);self.assertIn('/v0.5.7/',m['source_offer'])
            h.fail_latest=True
            with self.assertRaises(t.SourceError):t.stream_source('amd64')
    def test_missing_source_wrong_asset_url_bad_digest_and_sums_fail_closed(self):
        for mode in ('missing','url','digest','sums','future'):
            h=OfficialHTTP()
            if mode=='missing':h.release['assets']=[a for a in h.release['assets'] if 'source.zip' not in a['name']]
            elif mode=='url':h.release['assets'][0]['browser_download_url']='https://evil.invalid/binary'
            elif mode=='digest':h.release['assets'][0]['digest']='sha256:'+'f'*64
            elif mode=='future':h.release['tag_name']='v0.5.8'
            else:
                h.payloads['SHA256SUMS']=b'0'*64+b'  service-unlock_linux_amd64\n'
                a=next(a for a in h.release['assets'] if a['name']=='SHA256SUMS');a.update(size=len(h.payloads['SHA256SUMS']),digest='sha256:'+digest(h.payloads['SHA256SUMS']))
            with self.subTest(mode=mode),patch.object(t,'fetch',side_effect=h.fetch):
                with self.assertRaises(t.SourceError):t.stream_source('amd64')
    def test_cache_tamper_and_symlink_are_not_fallbacks(self):
        h=OfficialHTTP()
        with patch.object(t,'fetch',side_effect=h.fetch):
            _,m=t.stream_source('amd64');p=Path(m['binary']['path']);p.write_bytes(b'broken')
            with self.assertRaises(t.SourceError):t.stream_source('amd64')
            p.unlink();p.symlink_to(Path(self.temp.name)/'absent')
            with self.assertRaises(t.SourceError):t.stream_source('amd64')
    def test_api_rejects_duplicate_keys_nonfinite_and_private_redirect(self):
        for raw in (b'{"sha":1,"sha":2}',b'{"sha":NaN}'):
            with patch.object(t,'fetch',return_value=(raw,'https://api.github.com')):
                with self.assertRaises(t.SourceError):t.api('repo/commits/main')
        for url in ('http://github.com/a','https://github.com@evil.invalid/a','https://token@github.com/a','https://github.com:444/a'):
            with self.assertRaises(t.SourceError):t._url(url,t.OFFICIAL_HOSTS)
    def test_tcp_wrapper_core_use_same_commit_and_incompatible_stops(self):
        calls=[]
        def fetch(url,*a,**kw):
            calls.append(url)
            return ((b'#!/bin/sh\n--no-rootfs runTcpQuality-core.sh TCPQUALITY_RAW_BASE' if url.endswith('/runTcpQuality.sh') else b'#!/bin/sh\nTCPQUALITY'),url)
        release={'repository':'ibsgss/TcpQuality','version':'v-test','commit':SHA,'assets':[]}
        with patch.object(t,'latest_release',return_value=release),patch.object(t,'fetch',side_effect=fetch):m=t.tcp_source()
        self.assertEqual(len(calls),2);self.assertTrue(all('/'+SHA+'/' in u for u in calls))
        self.assertEqual(m['raw_base'],'https://raw.githubusercontent.com/ibsgss/TcpQuality/'+SHA)
        with patch.object(t,'latest_release',return_value=release),patch.object(t,'fetch',return_value=(b'#!/bin/sh\nwrong','https://raw.githubusercontent.com')):
            with self.assertRaises(t.SourceError):t.tcp_source()
    def test_script_current_entry_must_equal_same_commit_and_correct_repository(self):
        body=b'#!/bin/sh\nReport.Check.Place\n';entry,repo,file=t.ENTRIES['ipq'];fixed=f'https://raw.githubusercontent.com/{repo}/{SHA}/{file}'
        def fetch(url,**kw):return (body,'https://raw.githubusercontent.com/'+repo+'/main/'+file) if url==entry else (body,fixed)
        with patch.object(t,'commit_for',return_value=SHA),patch.object(t,'fetch',side_effect=fetch):m=t.script_source('ipq')
        self.assertEqual(m['url'],fixed);self.assertEqual(m['repository'],'xykt/IPQuality')
        for bad in ('repo','changed'):
            def broken(url,**kw):
                if url==entry:return body,'https://raw.githubusercontent.com/'+('evil/repo' if bad=='repo' else repo)+'/main/'+file
                return b'#!/bin/sh\nchanged',fixed
            with self.subTest(bad=bad),patch.object(t,'commit_for',return_value=SHA),patch.object(t,'fetch',side_effect=broken):
                with self.assertRaises(t.SourceError):t.script_source('ipq')
    def test_gb5_official_failure_or_only_gb6_never_probes_guessed_packages(self):
        with patch.object(t,'fetch',side_effect=t.SourceError('offline')) as fetch:
            with self.assertRaises(t.SourceError):t.gb5_source()
            self.assertEqual(fetch.call_count,1)
        with patch.object(t,'fetch',return_value=(b'Geekbench 6 https://cdn.geekbench.com/Geekbench-6.6.6-Linux.tar.gz','https://www.geekbench.com/download/legacy/')) as fetch:
            with self.assertRaises(t.SourceError):t.gb5_source()
            self.assertEqual(fetch.call_count,1)
    def test_nexttrace_asset_is_task_local_and_unknown_arch_stops(self):
        r={'repository':'nxtrace/NTrace-core','version':'v-test','commit':SHA,'assets':[]}
        with patch.object(t,'latest_release',return_value=r),patch.object(t,'release_asset',return_value=(b'bin',{'path':'/task/cache/hash','sha256':'a'*64})) as asset:
            m=t.nexttrace_source('aarch64');self.assertEqual(m['arch'],'arm64');self.assertEqual(asset.call_args.args[1],'nexttrace_linux_arm64')
            with self.assertRaises(t.SourceError):t.nexttrace_source('unsupported')
            self.assertEqual(asset.call_count,1)
    def manager(self,broken=False):
        manager=b"VERSION = '0.1.1'\n"+b'\n'.join(x.encode() for x in ('def do_install(self):','def acquire(self):',"'--credential-file'","'--host'","'https://github.com/shui1iao/Kat-Server/releases/download'","'https://api.github.com/repos/shui1iao/Kat-Server/releases/latest'","'复用已安装的 Kat 内核 '"))
        config=b'# offline config helper\n'
        wrapper=('KAT_HELPER_MANAGER_SHA256="'+('f'*64 if broken else digest(manager))+'"\nKAT_HELPER_CONFIG_SHA256="'+digest(config)+'"\nexec python3 "$kat_dir/kat_manager.py" "$@"\n').encode()
        return {'kat.sh':wrapper,'kat_manager.py':manager,'kat_config.py':config}
    def test_kat_same_commit_full_helpers_pins_and_reuse_never_queries_server_latest(self):
        for broken in (False,True):
            bodies=self.manager(broken);calls=[]
            def fetch(url,*a,**kw):calls.append(url);return bodies[url.rsplit('/',1)[1]],url
            with patch.object(t,'commit_for',return_value=SHA),patch.object(t,'fetch',side_effect=fetch),patch.object(t,'latest_release',side_effect=AssertionError('Existing core may not query/upgrade latest')):
                if broken:
                    with self.assertRaises(t.SourceError):t.kat_install_source({'version':'0.7.1','sha256':'a'*64})
                else:
                    m=t.kat_install_source({'version':'0.7.1','sha256':'a'*64});self.assertEqual(m['server']['mode'],'reuse');self.assertEqual(set(m['files']),set(bodies))
            self.assertEqual(len(calls),3);self.assertTrue(all('/'+SHA+'/' in u for u in calls))
    def test_kat_new_core_freezes_same_release_binary_checksum_and_rejects_unknown_version(self):
        bodies=self.manager();binary=b'OFFLINE core';asset='kat-0.7.2-linux-amd64'
        release={'version':'v0.7.2','commit':SHA,'repository':'shui1iao/Kat-Server','assets':[]}
        def fetch(url,*a,**kw):return bodies[url.rsplit('/',1)[1]],url
        def download(r,name,limit):return ((digest(binary)+'  '+asset).encode(),{'sha256':'b'*64}) if name.endswith('.sha256') else (binary,{'sha256':digest(binary),'url':'https://github.com/shui1iao/Kat-Server/releases/download/v0.7.2/'+asset})
        with patch.object(t,'commit_for',return_value=SHA),patch.object(t,'fetch',side_effect=fetch),patch.object(t,'latest_release',return_value=release),patch.object(t,'release_asset',side_effect=download):m=t.kat_install_source()
        self.assertEqual(m['server']['sha256'],digest(binary));self.assertEqual(m['server']['version'],'v0.7.2')
        release['version']='v0.7.3'
        with patch.object(t,'commit_for',return_value=SHA),patch.object(t,'fetch',side_effect=fetch),patch.object(t,'latest_release',return_value=release):
            with self.assertRaises(t.SourceError):t.kat_install_source()
