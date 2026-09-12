"""Persistent capability: add once, read menus locally, refresh inside tests."""
import asyncio
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from test_full_features import bot, callbacks

ADDRESS='2606:4700::1111'
SERVER={'id':'test-node','name':'Test','host':'192.0.2.10','ipv6':ADDRESS,'ipv6_status':{'available':True,'reason':'已记录 IPv6 可用'}}

class PersistedMenuTest(unittest.IsolatedAsyncioTestCase):
    async def test_menus_and_starts_use_saved_status_without_any_ssh(self):
        for available in (True,False):
            server={**SERVER,'ipv6':ADDRESS if available else '', 'ipv6_status':{'available':available,'reason':'已记录 IPv6 可用' if available else '没有可用 IPv6'}}
            for data in ('ipq:test-node','nqask:test-node','ipqproto:test-node:46','nqproto:test-node:15:46','nqtoggle:test-node:2:46','nqsel:test-node:15:46','ipqrun:test-node:46','nqrun:test-node:15:46'):
                with self.subTest(available=available,data=data):
                    q=SimpleNamespace(data=data,message=SimpleNamespace(chat_id=1),answer=AsyncMock(),edit_message_text=AsyncMock())
                    with patch.object(bot,'guard',AsyncMock(return_value=True)),patch.object(bot,'find_server_by_id',return_value=server),patch.object(bot,'run_subprocess',AsyncMock()) as ssh,patch.object(bot,'launch_job',return_value='test') as launch,patch.object(bot,'bot_task_started_notice',AsyncMock()):
                        await bot.on_button(SimpleNamespace(callback_query=q),SimpleNamespace(bot=None))
                    ssh.assert_not_awaited()
                    if 'run:' in data and available:
                        launch.assert_called_once()
                        self.assertEqual(launch.call_args.args[-1],'46')
                    else:
                        launch.assert_not_called()
                        found=callbacks(q.edit_message_text.call_args.kwargs['reply_markup'])
                        self.assertEqual(any(x.endswith(':46') for x in found),available)
                        if not available:self.assertIn('没有可用 IPv6',q.edit_message_text.call_args.args[0])

class PersistedIpv6Test(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'servers.json'
        self.path.write_text(json.dumps({'defaults':{},'servers':[SERVER,{'id':'other','name':'Other','host':'192.0.2.20','note':'keep'}]}))
        self.patches=[patch.object(bot,'SERVERS_JSON',self.path),patch.object(bot,'DATA_DIR',self.path.parent)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def saved(self):return bot.find_server_by_id('test-node')

    async def test_initial_probe_persists_actual_address_once(self):
        self.assertTrue(hasattr(bot,'detect_server_ipv6'),'Missing add-time detection')
        with patch.object(bot,'run_subprocess',AsyncMock(return_value=(0,'GUKO_IPV6='+ADDRESS))) as run,patch.object(bot,'ssh_args',return_value=['ssh']),patch.object(bot,'ssh_env_for',return_value=None):
            await bot.detect_server_ipv6(SERVER.copy())
        run.assert_awaited_once()
        self.assertEqual(self.saved()['ipv6'],ADDRESS)
        self.assertTrue(self.saved()['ipv6_status']['available'])
        self.assertIn('checked_at',self.saved()['ipv6_status'])
        self.assertEqual(bot.find_server_by_id('other')['note'],'keep')

    async def test_both_add_paths_initialize(self):
        self.assertTrue(hasattr(bot,'detect_server_ipv6'),'Missing add-time detection')
        message=SimpleNamespace(reply_text=AsyncMock())
        update=SimpleNamespace(effective_chat=SimpleNamespace(id=1),effective_message=message)
        with patch.object(bot,'build_server_item',return_value=SERVER.copy()),patch.object(bot,'upsert_server',return_value=(SERVER.copy(),'added')),patch.object(bot,'detect_server_ipv6',AsyncMock(return_value=(True,'已记录 IPv6 可用'))) as detect,patch.object(bot,'main_menu_markup',return_value=None):
            await bot.finish_single_add(update,None,{'name':'Test','host':'192.0.2.10'})
            detect.assert_awaited_once()
        with patch.object(bot,'parse_bulk_lines',return_value=([SERVER.copy()],[])),patch.object(bot,'upsert_server',return_value=(SERVER.copy(),'added')),patch.object(bot,'detect_server_ipv6',AsyncMock(return_value=(True,'已记录 IPv6 可用'))) as detect,patch.object(bot,'main_menu_markup',return_value=None):
            await bot.finish_bulk_add(update,None,{},'fixture')
            detect.assert_awaited_once()

    def test_observation_clears_disabled_address_and_updates_only_target(self):
        self.assertTrue(hasattr(bot,'update_ipv6_from_output'),'Missing test observation sync')
        status=bot.update_ipv6_from_output(SERVER.copy(),'GUKO_IPV6=disabled\nIPv4 report')
        self.assertFalse(status[0]);self.assertFalse(self.saved()['ipv6_status']['available']);self.assertFalse(self.saved().get('ipv6'))
        self.assertEqual(bot.find_server_by_id('other')['note'],'keep')

    def test_ssh_failure_missing_or_invalid_marker_does_not_erase_known_state(self):
        self.assertTrue(hasattr(bot,'update_ipv6_from_output'),'Missing test observation sync')
        for out in ('SSH timeout','GUKO_IPV6=<html>blocked</html>','GUKO_IPV6=::1','GUKO_IPV6=192.0.2.1','GUKO_IPV6=no-curl'):
            bot.update_ipv6_from_output(SERVER.copy(),out)
            self.assertTrue(self.saved()['ipv6_status']['available'])
            self.assertEqual(self.saved()['ipv6'],ADDRESS)

    def test_result_cannot_overwrite_retargeted_or_deleted_server(self):
        self.assertTrue(hasattr(bot,'update_ipv6_from_output'),'Missing test observation sync')
        bot.update_server_by_id('test-node',{'host':'192.0.2.11'})
        bot.update_ipv6_from_output(SERVER.copy(),'GUKO_IPV6=disabled')
        self.assertEqual(self.saved()['host'],'192.0.2.11')
        self.assertNotEqual(self.saved().get('ipv6_status',{}).get('reason'),'系统已禁用 IPv6，仅可测试 IPv4。')
        bot.delete_server_by_id('test-node')
        bot.update_ipv6_from_output(SERVER.copy(),'GUKO_IPV6='+ADDRESS)
        self.assertIsNone(self.saved())

    def test_real_probe_failures_and_invalid_responses_preserve_known_address(self):
        tools=Path(self.temp.name)/'bin';tools.mkdir()
        (tools/'cat').write_text('#!/bin/sh\nprintf "0\\n"\n');(tools/'cat').chmod(0o700)
        for ip_script,curl_script in [
            ('printf "inet6 address\\n"','printf "<html>blocked</html>\\n"'),
            ('exit 2','printf "<html>blocked</html>\\n"'),
            ('printf "inet6 address\\n"','exit 28'),
        ]:
            with self.subTest(ip=ip_script,curl=curl_script):
                for name,text in [('ip',ip_script),('curl',curl_script)]:
                    p=tools/name;p.write_text('#!/bin/sh\n'+text+'\n');p.chmod(0o700)
                result=subprocess.run(['bash','-c',bot.IPV6_PROBE_COMMAND],env={**os.environ,'PATH':str(tools)+':/usr/bin:/bin'},capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                bot.update_ipv6_from_output(SERVER.copy(),result.stdout)
                self.assertEqual(self.saved()['ipv6'],ADDRESS,result.stdout)
        (tools/'ip').write_text('#!/bin/sh\nexit 0\n')
        result=subprocess.run(['bash','-c',bot.IPV6_PROBE_COMMAND],env={**os.environ,'PATH':str(tools)+':/usr/bin:/bin'},capture_output=True,text=True)
        self.assertIn('GUKO_IPV6=no-address',result.stdout)
        bot.update_ipv6_from_output(SERVER.copy(),result.stdout)
        self.assertEqual(self.saved()['ipv6'],'')

    def test_late_result_rejects_effective_ssh_host_and_port_changes(self):
        for ssh in ({'host':'192.0.2.11'},{'port':2222}):
            with self.subTest(ssh=ssh):
                inv=json.loads(self.path.read_text());inv['servers'][0]=SERVER.copy();self.path.write_text(json.dumps(inv))
                bot.update_server_by_id('test-node',{'ssh':ssh})
                result=bot.update_ipv6_from_output(SERVER.copy(),'GUKO_IPV6=disabled')
                self.assertIsNone(result)
                self.assertEqual(self.saved()['ipv6'],ADDRESS)

    async def test_initial_probe_snapshots_inherited_ssh_port(self):
        async def remote(*args,**kw):
            inv=json.loads(self.path.read_text());inv['defaults']={'port':2222};self.path.write_text(json.dumps(inv))
            return 0,'GUKO_IPV6=disabled'
        with patch.object(bot,'run_subprocess',AsyncMock(side_effect=remote)),patch.object(bot,'ssh_args',return_value=['ssh']),patch.object(bot,'ssh_env_for',return_value=None):
            await bot.detect_server_ipv6(SERVER.copy())
        self.assertEqual(self.saved()['ipv6'],ADDRESS)

    async def test_missing_ipv6_notice_is_not_limited_to_dual_or_report_success(self):
        from test_ipq_protocol_selection import RAW4,URL4
        for mode,body in [('4',RAW4),('4',''),('46','')]:
            for kind,runner in [('ipq',bot.run_ip_quality_task),('nq',bot.run_nq_task)]:
                with self.subTest(mode=mode,body=bool(body),kind=kind):
                    bot.JOBS['notice-test']={};tg=SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
                    output='GUKO_IPV6=disabled\n'+body
                    with patch.object(bot,'run_until_report',AsyncMock(return_value=(1,output,URL4 if body else None))),patch.object(bot,'run_subprocess',AsyncMock(return_value=(0,output))),patch.object(bot,'ssh_args',return_value=['ssh']),patch.object(bot,'ssh_env_for',return_value=None),patch.object(bot,'finish_job'),patch.object(bot,'render_ansi_png',AsyncMock(side_effect=RuntimeError('offline renderer'))),patch.object(bot,'cleanup_nodequality_ansi_logs',AsyncMock()):
                        if kind=='ipq':await runner(tg,1,SERVER.copy(),'notice-test',mode)
                        else:await runner(tg,1,SERVER.copy(),'notice-test',15,mode)
                    self.assertIn('没有可用 IPv6',tg.send_message.await_args.args[1])
                    self.assertIn('已更新',tg.send_message.await_args.args[1])
                    bot.JOBS.pop('notice-test',None)

    async def test_real_test_results_refresh_and_explain_missing_ipv6(self):
        from test_ipq_protocol_selection import RAW4,URL4
        for kind,runner in [('ipq',bot.run_ip_quality_task),('nq',bot.run_nq_task)]:
            with self.subTest(kind=kind):
                bot.JOBS['state-test']={}
                tg=SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
                output='GUKO_IPV6=disabled\n'+RAW4
                with patch.object(bot,'run_until_report',AsyncMock(return_value=(1,output,URL4))) as iprun,patch.object(bot,'run_subprocess',AsyncMock(return_value=(0,output))) as nqrun,patch.object(bot,'ssh_args',side_effect=lambda s,c,**kw:['ssh',c]),patch.object(bot,'ssh_env_for',return_value=None),patch.object(bot,'finish_job'),patch.object(bot,'render_ansi_png',AsyncMock(side_effect=RuntimeError('offline renderer'))),patch.object(bot,'cleanup_nodequality_ansi_logs',AsyncMock()):
                    if kind=='ipq':await runner(tg,1,SERVER.copy(),'state-test','46'); remote=iprun.await_args.args[0][-1]
                    else:await runner(tg,1,SERVER.copy(),'state-test',15,'46');remote=nqrun.await_args.args[0][-1]
                self.assertIn('GUKO_IPV6=',remote,'Probe must share the real test SSH invocation')
                self.assertFalse(self.saved()['ipv6_status']['available'])
                self.assertIn('没有可用 IPv6',tg.send_message.await_args.args[1])
                self.assertIn('已更新',tg.send_message.await_args.args[1])
                bot.JOBS.pop('state-test',None)

if __name__=='__main__':unittest.main()
