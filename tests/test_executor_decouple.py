"""Ordinary upstream changes; ALL I/O mocked/local. No actual installs/TG/SSH."""
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import tool_sources as t
import stream_unified as u
from test_tool_sources import OfficialHTTP, source_zip, SHA
from test_stream_unified import bot
from test_kat_proxy import fixture, frame, encode, k

class FutureSourceTest(unittest.TestCase):
    def test_future_release_not_in_any_version_list(self):
        tag='v99.12.34'
        h=OfficialHTTP(tag=tag,payloads={'service-unlock_linux_amd64':b'OFFLINE future native','service-unlock-'+tag+'-source.zip':source_zip()})
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,TMP_DIR=td),patch.object(t,'fetch',side_effect=h.fetch):
            body,meta=t.stream_source('amd64')
            self.assertEqual(meta['version'],tag);self.assertEqual(meta['commit'],SHA)
            self.assertEqual(meta['binary']['sha256'],hashlib.sha256(body).hexdigest());self.assertIn('/'+tag+'/',meta['source_offer'])
    def test_script_ordinary_refactors_without_implementation_tokens(self):
        for kind in ('ipq','nq','snell'):
            entry,repo,name=t.ENTRIES[kind];data=b'#!/bin/sh\n# completely refactored official implementation\n'
            fixed=f'https://raw.githubusercontent.com/{repo}/{SHA}/{name}'
            def fetch(url,**kw):return data,('https://raw.githubusercontent.com/'+repo+'/main/'+name if url==entry else fixed)
            with self.subTest(kind=kind),patch.object(t,'commit_for',return_value=SHA),patch.object(t,'fetch',side_effect=fetch):
                meta=t.script_source(kind);self.assertEqual(meta['sha256'],hashlib.sha256(data).hexdigest());self.assertIsNone(meta['version'])
    def test_tcp_same_commit_refactor_does_not_require_old_source_symbols(self):
        with patch.object(t,'latest_release',return_value={'version':'future','repository':'ibsgss/TcpQuality','commit':SHA,'assets':[]}),patch.object(t,'fetch',side_effect=lambda url,*a,**kw:(b'#!/bin/sh\n# refactored\n',url)):
            self.assertEqual(len(t.tcp_source()['files']),2)

class FutureStreamTask(unittest.IsolatedAsyncioTestCase):
    async def test_future_changed_layout_new_removed_items_and_extra_fields_deliver_verbatim(self):
        doc={'format':'guko-unified-v1','extra_envelope_field':123,'report':{'schema_version':27,'future_country':'NEW','unknown_new_item':[{'name':'<Future>','arbitrary':'raw'}]},'terminal':'New order / future country\n\x1b[33mFuture unclassified outcome\x1b[0m\n'}
        text=json.dumps(doc);seen=[]
        async def remote(*args,**kw):kw['identity_out'].update(version='v99.12.34',commit=SHA,source_offer='https://github.com/shui1iao/service-unlock/releases/download/v99.12.34/service-unlock-v99.12.34-source.zip');return 0,text,'',None
        async def render(terminal,path,kind):seen.append(terminal);Path(path).write_bytes(b'OFFLINE MOCK PNG')
        api=SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
        with tempfile.TemporaryDirectory() as td,patch.dict(bot.JOBS,{'future':{'kind':'stream','started_at':bot.iso_now()}},clear=True),patch.object(bot,'kind_result_dir',return_value=Path(td)),patch.object(bot,'finish_job'),patch.object(u,'remote_run',side_effect=remote),patch.object(bot,'render_ansi_png',side_effect=render):
            await bot.run_stream_task(api,1,{'id':'future','name':'MOCK'},'future')
            job=bot.JOBS['future'];self.assertEqual(job['status'],'done');self.assertNotIn('unknown_count',job)
            self.assertEqual(seen,[doc['terminal']]);self.assertEqual(Path(job['raw_path']).read_text(),doc['terminal'])
            self.assertEqual(json.loads(Path(job['json_path']).read_text()),doc['report']);api.send_photo.assert_awaited_once()

class FutureKatShapeTest(unittest.TestCase):
    def test_future_core_same_shape_still_reads_and_unknown_shape_still_refuses(self):
        for kind in k.KINDS:
            old,packet,configs=fixture(kind);packet['kernel','kat']=encode({'version':'99.12.34','sha256':'a'*64,'source':'release'})
            plan=k.discovery(frame({key:value for key,value in packet.items() if key[0]!='config'}))
            self.assertEqual(len(k.parse_nodes(kind,plan,frame(packet))),1);self.assertEqual(plan['core']['version'],'99.12.34')
            path=next(iter(configs));configs[path]['inbounds'][0]['new_unknown_security_meaning']=True;packet['config',path]=encode(configs[path])
            with self.assertRaises(k.KatError):k.parse_nodes(kind,plan,frame(packet))

class RuntimeCapabilityTest(unittest.TestCase):
    def fakecurl(self,root):
        curl=root/'curl';curl.write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do case "$1" in https:*) url=$1;; -o) shift; dest=$1;; esac; shift; done\ncp "$MOCK_FILES/${url##*/}" "$dest"\n');curl.chmod(0o700)
    def environment(self,root,marker):return dict(os.environ,PATH=str(root)+':'+os.environ['PATH'],MOCK_FILES=str(root),MOCK_RUN_MARKER=str(marker))
    def test_tcp_real_help_missing_no_rootfs_or_unsupported_args_never_runs(self):
        for bad in ('none','rootfs','args'):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as td:
                root=Path(td);mark=root/'ran'
                wrapper=('#!/bin/sh\ncase "$1" in --rootfs-help) echo '+('unavailable' if bad=='rootfs' else '--no-rootfs')+'; exit 0;; esac\nprintf run > "$MOCK_RUN_MARKER"\n').encode()
                core=('#!/bin/sh\nexit '+('2' if bad=='args' else '0')+'\n').encode()
                for n,b in [('runTcpQuality.sh',wrapper),('runTcpQuality-core.sh',core)]:(root/n).write_bytes(b)
                self.fakecurl(root)
                source={'raw_base':f'https://raw.githubusercontent.com/ibsgss/TcpQuality/{SHA}','files':{n:{'url':f'https://raw.githubusercontent.com/ibsgss/TcpQuality/{SHA}/{n}','sha256':hashlib.sha256((root/n).read_bytes()).hexdigest()} for n in ('runTcpQuality.sh','runTcpQuality-core.sh')}}
                result=subprocess.run(['sh','-c',bot.tcpquality_remote_command('v4',source)],capture_output=True,env=self.environment(root,mark),timeout=10)
                self.assertEqual(result.returncode,0 if bad=='none' else 65,result.stderr);self.assertEqual(mark.exists(),bad=='none')
    def test_kat_required_cli_parser_failure_stops_before_sentinel_mutation(self):
        for compatible in (True,False):
            with self.subTest(compatible=compatible),tempfile.TemporaryDirectory() as td:
                root=Path(td);marker=root/'would-mutate';flags="['--host','--port','--binary','--sha256','--version']" if compatible else "['--host']"
                manager=("import argparse,os\nfrom pathlib import Path\np=argparse.ArgumentParser(add_help=False)\np.add_argument('--help',action='store_true')\np.add_argument('action');p.add_argument('kind')\nfor flag in "+flags+":p.add_argument(flag)\na=p.parse_args()\nif a.help:raise SystemExit(0)\nPath(os.environ['MOCK_RUN_MARKER']).write_text('LOCAL SENTINEL ONLY')\n").encode()
                bodies={'kat.sh':b'#!/bin/sh\n# refactored wrapper not capability proof','kat_manager.py':manager,'kat_config.py':b'# refactored helper','core':b'OFFLINE mock core'}
                for n,b in bodies.items():(root/n).write_bytes(b)
                self.fakecurl(root)
                meta=lambda n:{'url':f'https://raw.githubusercontent.com/shui1iao/Kat-Manager/{SHA}/{n}','sha256':hashlib.sha256(bodies[n]).hexdigest()}
                source={'files':{n:meta(n) for n in ('kat.sh','kat_manager.py','kat_config.py')},'server':{'mode':'new','version':'v99.12.34','sha256':meta('core')['sha256'],'binary':meta('core')}}
                command=k.install_command('ss','example.invalid','',{'paths':[],'config_hashes':{},'digest':'a'*64},source)
                tail='umask 077; work='+command.split('umask 077; work=',1)[1]
                result=subprocess.run(['sh','-c',tail],capture_output=True,env=self.environment(root,marker),timeout=10)
                self.assertEqual(result.returncode,0 if compatible else 65,result.stderr);self.assertEqual(marker.exists(),compatible);self.assertNotIn(b'usage:',result.stdout)

class RawReportFallback(unittest.IsolatedAsyncioTestCase):
    async def test_new_title_and_layout_output_not_lost_for_ipq_tcp_nq(self):
        output='Future title; new geography / new layout\n'+('<Future>& payload\n'*800)
        for kind in ('ipq','tcpq','nq'):
            api=SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td,patch.dict(bot.JOBS,{'j':{'kind':kind}},clear=True),patch.object(bot,'kind_result_dir',return_value=Path(td)),patch.object(bot,'finish_job'),patch.object(bot,'resolve_tool',new=AsyncMock(return_value={})),patch.object(bot,'run_subprocess',new=AsyncMock(return_value=(0,output))),patch.object(bot,'run_until_report',new=AsyncMock(return_value=(0,output,None))),patch.object(bot,'tcpquality_remote_command',return_value='MOCK'),patch.object(bot,'ipquality_remote_command',return_value='MOCK'),patch.object(bot,'nodequality_remote_command',return_value='MOCK'):
                if kind=='ipq':await bot.run_ip_quality_task(api,1,{'id':'s','name':'MOCK','host':'example.invalid'},'j')
                elif kind=='tcpq':await bot.run_tcpquality_task(api,1,{'id':'s','name':'MOCK','host':'example.invalid'},'j')
                else:await bot.run_nq_task(api,1,{'id':'s','name':'MOCK','host':'example.invalid'},'j',15)
                job=bot.JOBS['j'];self.assertEqual(job['status'],'done');self.assertIn('extraction_error',job);self.assertEqual(Path(job['raw_path']).read_text(),output)
                recovered=''.join(html.unescape(m.args[1][5:-6]) for m in api.send_message.await_args_list if m.args[1].startswith('<pre>'))
                self.assertEqual(recovered,output);self.assertGreater(api.send_message.await_count,3)
    async def test_true_execution_failure_not_success_while_original_is_preserved(self):
        api=SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
        with tempfile.TemporaryDirectory() as td,patch.dict(bot.JOBS,{'j':{'kind':'nq'}},clear=True),patch.object(bot,'kind_result_dir',return_value=Path(td)),patch.object(bot,'finish_job'),patch.object(bot,'resolve_tool',new=AsyncMock(return_value={})),patch.object(bot,'run_subprocess',new=AsyncMock(return_value=(2,'invalid option --needed-flag'))),patch.object(bot,'nodequality_remote_command',return_value='MOCK'):
            await bot.run_nq_task(api,1,{'id':'s','name':'MOCK','host':'example.invalid'},'j',15)
            self.assertEqual(bot.JOBS['j']['status'],'failed');self.assertEqual(Path(bot.JOBS['j']['raw_path']).read_text(),'invalid option --needed-flag')
    def test_current_nq_stdout_preserves_each_original_selected_report_without_patch(self):
        first='\r'+'#'*40+'\n\x1b[32mIP质量体检报告\x1b[0m\nnew region field\nhttps://Report.Check.Place/ip/AAA.svg'
        second='\r'+'#'*40+'\n\x1b[33m网络质量体检报告\x1b[0m\nnew rows\nhttps://Report.Check.Place/net/BBB.svg'
        self.assertEqual(bot.nodequality_stdout_logs('preamble\n'+second+'\n'+first,6),{'ip':first,'net':second})
