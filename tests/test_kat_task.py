"""Kat task/confirmation regressions. Isolated mocks/sentinels, no SSH or nodes."""
import asyncio
import copy
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from test_kat_proxy import fixture,frame,k,ROOT
os.environ.setdefault('BOT_TOKEN','123456:test-token');os.environ.setdefault('ALLOWED_USERS','1')
spec=importlib.util.spec_from_file_location('kat_task_actual_bot',ROOT/'telegram-bot/bot.py')
bot=importlib.util.module_from_spec(spec);spec.loader.exec_module(bot)
SERVER={'id':'offline-kat','name':'OFFLINE','host':'example.invalid'}

def state(kind='anytls'):
    plan,packet,_=fixture(kind);nodes=k.parse_nodes(kind,plan,frame(packet));return plan,nodes

def absent(kind='ss'):
    other='anytls' if kind=='ss' else 'ss';plan,packet,_=fixture(other)
    return plan,k.parse_nodes(kind,plan,frame(packet))

def source():
    return {'repository':'shui1iao/Kat-Manager','commit':'b'*40,'version':'0.1.1',
            'files':{n:{'url':'https://raw.githubusercontent.com/shui1iao/Kat-Manager/'+'b'*40+'/'+n,'sha256':'c'*64} for n in ('kat.sh','kat_manager.py','kat_config.py')},
            'server':{'mode':'reuse','version':'0.7.1','sha256':'a'*64}}

class KatTaskTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.api=SimpleNamespace(send_message=AsyncMock())
        self.stack=__import__('contextlib').ExitStack()
        self.stack.enter_context(patch.dict(bot.JOBS,{'job':{}},clear=True))
        self.stack.enter_context(patch.dict(bot.KAT_INSTALL_CONFIRMATIONS,{},clear=True))
        self.stack.enter_context(patch.object(bot,'finish_job'))
        self.stack.enter_context(patch.object(bot,'kind_result_dir',return_value=Path(self.temp.name)))
    async def asyncTearDown(self):self.stack.close();self.temp.cleanup()
    async def ticket(self,kind='ss'):
        await bot.offer_kat_install(self.api,7,SERVER,kind,11)
        return next(iter(bot.KAT_INSTALL_CONFIRMATIONS))
    async def test_existing_read_never_resolves_or_executes_installer(self):
        with patch.object(bot,'read_kat_snapshot',AsyncMock(return_value=state())),patch.object(bot,'resolve_tool',AsyncMock()) as resolve,patch.object(bot,'kat_transport',AsyncMock()) as remote:
            await bot.run_kat_task(self.api,7,SERVER,'job','anytls','view',11,None)
        resolve.assert_not_awaited();remote.assert_not_awaited();self.assertEqual(bot.JOBS['job']['status'],'done')
        p=Path(bot.JOBS['job']['proxy_report_path']);self.assertEqual(p.stat().st_mode&0o777,0o600)
    async def test_old_ensure_is_only_read_and_offer_not_install(self):
        with patch.object(bot,'read_kat_snapshot',AsyncMock(return_value=absent())),patch.object(bot,'resolve_tool',AsyncMock()) as resolve,patch.object(bot,'kat_transport',AsyncMock()) as remote:
            await bot.run_kat_task(self.api,7,SERVER,'job','ss','ensure',11,None)
        resolve.assert_not_awaited();remote.assert_not_awaited();self.assertEqual(len(bot.KAT_INSTALL_CONFIRMATIONS),1)
        self.assertIn('确认新安装',str(self.api.send_message.call_args.kwargs['reply_markup']))
    async def test_user_chat_expiry_host_kind_and_replay_rejected_before_ssh(self):
        for mode in ('user','chat','expiry','host','kind','replay'):
            bot.KAT_INSTALL_CONFIRMATIONS.clear();token=await self.ticket();uid,chat=11,7
            if mode=='user':uid=12
            if mode=='chat':chat=8
            if mode=='expiry':bot.KAT_INSTALL_CONFIRMATIONS[token]['expires']=time.time()-1
            if mode=='host':bot.KAT_INSTALL_CONFIRMATIONS[token]['host_hash']='wrong'
            if mode=='kind':bot.KAT_INSTALL_CONFIRMATIONS[token]['kind']='vless'
            if mode=='replay':bot.KAT_INSTALL_CONFIRMATIONS.pop(token)
            with self.subTest(mode=mode),patch.object(bot,'read_kat_snapshot',AsyncMock()) as read,patch.object(bot,'kat_transport',AsyncMock()) as remote:
                await bot.run_kat_task(self.api,chat,SERVER,'job','ss','kat-confirmed',uid,token)
                read.assert_not_awaited();remote.assert_not_awaited();self.assertEqual(bot.JOBS['job']['status'],'failed')
    async def test_missing_preflight_stops_before_source_resolution_or_download(self):
        token=await self.ticket()
        with patch.object(bot,'read_kat_snapshot',AsyncMock(return_value=absent())),patch.object(bot,'kat_transport',AsyncMock(return_value=(23,'private-upstream-data'))) as remote,patch.object(bot,'resolve_tool',AsyncMock()) as resolve:
            await bot.run_kat_task(self.api,7,SERVER,'job','ss','kat-confirmed',11,token)
        resolve.assert_not_awaited();self.assertEqual(remote.await_count,1);self.assertNotIn('private-upstream-data',bot.JOBS['job']['log']);self.assertNotIn(token,bot.KAT_INSTALL_CONFIRMATIONS)
    async def test_race_to_existing_after_resolution_only_reads_never_installs(self):
        token=await self.ticket()
        async def resolve(jid,*args):bot.JOBS[jid]['tool_source']=source();return bot.JOBS[jid]['tool_source']
        with patch.object(bot,'read_kat_snapshot',AsyncMock(side_effect=[absent(),state('ss')])),patch.object(bot,'kat_transport',AsyncMock(return_value=(0,'GUKO_KAT_PREFLIGHT_OK'))) as remote,patch.object(bot,'resolve_tool',side_effect=resolve),patch.object(k,'install_command',side_effect=AssertionError('No installation after race')):
            await bot.run_kat_task(self.api,7,SERVER,'job','ss','kat-confirmed',11,token)
        self.assertEqual(remote.await_count,1);self.assertFalse(bot.JOBS['job']['tool_source']['installation_executed'])
    async def test_changed_snapshot_hash_stops_before_install_command(self):
        token=await self.ticket();a=absent();b=copy.deepcopy(a);b[0]['digest']='f'*64
        async def resolve(jid,*args):bot.JOBS[jid]['tool_source']=source();return bot.JOBS[jid]['tool_source']
        with patch.object(bot,'read_kat_snapshot',AsyncMock(side_effect=[a,b])),patch.object(bot,'kat_transport',AsyncMock(return_value=(0,'GUKO_KAT_PREFLIGHT_OK'))),patch.object(bot,'resolve_tool',side_effect=resolve),patch.object(k,'install_command',side_effect=AssertionError('No installation after identity conflict')):
            await bot.run_kat_task(self.api,7,SERVER,'job','ss','kat-confirmed',11,token)
        self.assertEqual(bot.JOBS['job']['status'],'failed')
    async def test_installer_text_or_nonzero_never_claims_success_always_readback(self):
        for answer,rc in [('success private-password',0),('GUKO_KAT_INSTALL_RC:1\n',1),('GUKO_KAT_INSTALL_RC:0\n',0)]:
            bot.KAT_INSTALL_CONFIRMATIONS.clear();token=await self.ticket();bot.JOBS['job']={}
            async def resolve(jid,*args):bot.JOBS[jid]['tool_source']=source();return bot.JOBS[jid]['tool_source']
            with patch.object(bot,'read_kat_snapshot',AsyncMock(side_effect=[absent(),absent(),state('ss')])) as read,patch.object(bot,'kat_transport',AsyncMock(side_effect=[(0,'GUKO_KAT_PREFLIGHT_OK'),(rc,answer)])) as remote,patch.object(bot,'resolve_tool',side_effect=resolve):
                await bot.run_kat_task(self.api,7,SERVER,'job','ss','kat-confirmed',11,token)
            self.assertEqual(read.await_count,3);self.assertEqual(remote.await_count,2)
            self.assertEqual(bot.JOBS['job']['status'],'done' if answer=='GUKO_KAT_INSTALL_RC:0\n' else 'failed')
            self.assertNotIn('private-password',bot.JOBS['job']['log'])
    async def test_vless_stale_callbacks_do_not_find_server_launch_or_ssh(self):
        for data in ('proxy:vless:gone','proxyrun:vless:ensure:gone','vlessmode:gone:reality'):
            q=SimpleNamespace(data=data,answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace(chat_id=7))
            with patch.object(bot,'guard',AsyncMock(return_value=True)),patch.object(bot,'find_server_by_id',side_effect=AssertionError('No lookup')),patch.object(bot,'launch_job') as launch,patch.object(bot,'kat_transport',AsyncMock()) as remote:
                await bot.on_button(SimpleNamespace(callback_query=q),SimpleNamespace(bot=self.api))
            launch.assert_not_called();remote.assert_not_awaited();self.assertIn('VLESS入口已移除',q.edit_message_text.call_args.args[0])
    async def test_kat_long_text_all_nodes_and_no_three_message_truncation(self):
        value='\n'.join('unit-'+str(i)+'\n'+('x'*3000) for i in range(8))
        await bot.send_kat_output(self.api,7,value)
        self.assertGreater(self.api.send_message.await_count,3)
        recovered=''.join(html.unescape(c.args[1][5:-6]) for c in self.api.send_message.call_args_list)
        self.assertEqual(recovered,value+'\n')

class KatSentinelShellTest(unittest.TestCase):
    def test_final_snapshot_guard_runs_before_any_download(self):
        p,_=absent();p['digest']='0'*64
        # Only replace the discovery source with a bounded sentinel; execute the
        # real generated final compare before real shell_download instructions.
        shell="bad(){ exit 23; }; discover(){ printf 'changed\\n'; }; curl(){ echo DOWNLOAD-MUST-NOT-RUN; exit 90; };"
        with patch.object(k,'SHELL',shell),patch.object(k,'PREFLIGHT',''):
            cmd=k.install_command('ss','example.invalid','443',p,source())
        result=subprocess.run(['sh','-c',cmd],capture_output=True,text=True)
        self.assertEqual(result.returncode,23);self.assertNotIn('DOWNLOAD',result.stdout)
    def test_missing_python_preflight_never_bootstraps(self):
        shell='bad(){ exit 23; }; command(){ [ "$2" != python3 ]; };'
        with patch.object(k,'SHELL',shell):cmd=k.preflight_command()
        result=subprocess.run(['sh','-c',cmd],capture_output=True,text=True)
        self.assertEqual(result.returncode,23);self.assertNotIn('PREFLIGHT_OK',result.stdout)
        for forbidden in ('apt-get','apk add','pip install'):self.assertNotIn(forbidden,cmd)
    def test_kernel_threads_only_are_skipped_unreadable_userspace_is_error(self):
        start=k.SHELL.index('  exe=$(readlink');end=k.SHELL.index('  case "$exe"',start)
        snippet=k.SHELL[start:end]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for flags,expected in ((2097152,0),(0,23)):
                (p/'stat').write_text('9 (offline kernel name) S 1 1 1 0 0 '+str(flags)+' 0\n')
                script='bad(){ exit 23; }; readlink(){ return 1; }; for proc in "$1"; do\n'+snippet+'\nexit 99; done'
                result=subprocess.run(['sh','-c',script,'test',td],capture_output=True,text=True)
                self.assertEqual(result.returncode,expected)
