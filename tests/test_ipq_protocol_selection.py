"""IPQuality protocol UI and complete dual-stack report transport."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from test_full_features import bot, callbacks

SERVER = {"id": "test-node", "name": "Test", "host": "192.0.2.10", "ipv6_status": {"available": True, "reason": "已记录 IPv6 可用"}}
URL4 = "https://Report.Check.Place/ip/TEST4.svg"
URL6 = "https://Report.Check.Place/ip/TEST6.svg"

def report(ip, url):
    return '\r' + '#' * 72 + '\n\rIP质量体检报告：' + ip + '\n\r风险 \x1b[42m低\x1b[0m\n\r报告链接：' + url + '\n'

RAW4 = report('192.0.2.*', URL4)
RAW6 = report('2001:db8::*', URL6)

class IpqProtocolMenuTest(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, data):
        q = SimpleNamespace(data=data, message=SimpleNamespace(chat_id=1), answer=AsyncMock(), edit_message_text=AsyncMock())
        with patch.object(bot, 'guard', AsyncMock(return_value=True)), patch.object(bot, 'find_server_by_id', return_value=SERVER), patch.object(bot, 'launch_job', return_value='test') as launch, patch.object(bot, 'bot_task_started_notice', AsyncMock()):
            await bot.on_button(SimpleNamespace(callback_query=q), SimpleNamespace(bot=object()))
        return q, launch

    async def test_old_ipq_button_opens_choices_without_starting(self):
        q, launch = await self.invoke('ipq:test-node')
        self.assertTrue(q.edit_message_text.called, 'IPQuality must open protocol choices')
        launch.assert_not_called()
        found = callbacks(q.edit_message_text.call_args.kwargs['reply_markup'])
        self.assertIn('ipqproto:test-node:4', found)
        self.assertIn('ipqproto:test-node:46', found)
        self.assertIn('ipqrun:test-node:4', found)

    async def test_dual_selection_without_ipv6_metadata_sticks(self):
        q, launch = await self.invoke('ipqproto:test-node:46')
        self.assertTrue(q.edit_message_text.called, 'Missing protocol callback')
        self.assertIn('ipqrun:test-node:46', callbacks(q.edit_message_text.call_args.kwargs['reply_markup']))
        launch.assert_not_called()

    async def test_start_passes_mode_and_history_label(self):
        for mode in ('4', '46'):
            q, launch = await self.invoke('ipqrun:test-node:' + mode)
            self.assertTrue(launch.called, 'Missing start callback')
            self.assertEqual(launch.call_args.args[-1], mode)
            self.assertEqual(launch.call_args.kwargs['ip_mode'], bot.nq_ip_mode_text(mode))

    async def test_invalid_mode_cannot_launch(self):
        q, launch = await self.invoke('ipqrun:test-node:invalid')
        launch.assert_not_called()

    def test_remote_and_display_commands_honor_family(self):
        self.assertTrue(hasattr(bot, 'ipquality_remote_command'), 'Missing testable IP command builder')
        for mode, ending in [('4', '-y -4'), ('46', '-y')]:
            cmd = bot.ipquality_remote_command(mode)
            self.assertTrue(cmd.endswith('bash "$script" ' + ending))
            self.assertIn('https://IP.Check.Place -o "$script"', cmd)
            self.assertEqual(subprocess.run(['bash','-n','-c',cmd], capture_output=True).returncode, 0)
            self.assertTrue(bot.script_command_text('ipq', ip_mode=mode).endswith(ending))
        with self.assertRaises(ValueError):
            bot.ipquality_remote_command('invalid')

class IpqCollectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_dual_waits_for_second_delayed_report(self):
        self.assertIn('wait_for_exit', __import__('inspect').signature(bot.run_until_report).parameters)
        script = f'import time; print({RAW4!r}, flush=True); time.sleep(.15); print({RAW6!r}, flush=True)'
        code, output, url = await bot.run_until_report([sys.executable, '-c', script], timeout=5, wait_for_exit=True)
        self.assertEqual(code, 0)
        self.assertIn(URL6, output)
        self.assertEqual(url, URL4)

    async def test_timeout_retains_first_report_but_is_not_success(self):
        self.assertIn('wait_for_exit', __import__('inspect').signature(bot.run_until_report).parameters)
        script = f'import time; print({RAW4!r}, flush=True); time.sleep(10)'
        code, output, url = await bot.run_until_report([sys.executable, '-c', script], timeout=.15, wait_for_exit=True)
        self.assertEqual(code, 124)
        self.assertIn(URL4, output)
        self.assertEqual(url, URL4)

class IpqTaskTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(bot, 'RESULTS_DIR', self.root))
        self.stack.enter_context(patch.object(bot, 'HISTORY_JSON', self.root / 'history.json'))
        self.stack.enter_context(patch.object(bot, 'ssh_args', side_effect=lambda s,c,**kw: ['ssh',c]))
        self.stack.enter_context(patch.object(bot, 'ssh_env_for', return_value=None))
        self.render = self.stack.enter_context(patch.object(bot,'render_ansi_png', AsyncMock(side_effect=self.render_report)))
        self.tg = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
        bot.JOBS['ipq-test'] = {'kind':'ipq', 'server_id':'test-node', 'server':'Test'}

    async def asyncTearDown(self):
        self.stack.close()
        self.tmp.cleanup()
        bot.JOBS.pop('ipq-test',None)

    async def render_report(self, raw, path, **kw):
        Path(path).write_text(raw)

    async def run_task(self, code=0, output=RAW4+RAW6, mode='46'):
        self.assertIn('ip_mode', __import__('inspect').signature(bot.run_ip_quality_task).parameters)
        with patch.object(bot, 'run_until_report', AsyncMock(return_value=(code,output,URL4 if URL4 in output else None))) as runner:
            await bot.run_ip_quality_task(self.tg, 1, SERVER, 'ipq-test', mode)
        self.assertEqual(runner.await_args.kwargs.get('wait_for_exit',False), mode=='46')
        return bot.JOBS['ipq-test']

    async def test_both_reports_render_persist_and_replay_without_overwrite(self):
        job = await self.run_task()
        self.assertEqual(self.render.await_count, 2)
        self.assertEqual(self.tg.send_photo.await_count, 2)
        self.assertNotIn(URL6,self.render.await_args_list[0].args[0])
        self.assertNotIn(URL4,self.render.await_args_list[1].args[0])
        paths = job['media_paths']
        self.assertEqual(len(set(paths)),2)
        self.assertTrue(all(Path(x).exists() for x in paths))
        self.assertIn(URL4,Path(paths[0]).read_text())
        self.assertIn(URL6,Path(paths[1]).read_text())
        self.assertTrue(all(not Path(c.args[1]).exists() for c in self.render.await_args_list))
        self.assertEqual(job['status'],'done')
        item = bot.load_history()[-1]
        self.assertEqual(item['ip_mode'],'IPv4 + IPv6')
        self.assertIn(URL4,item['urls']); self.assertIn(URL6,item['urls'])
        self.tg.send_photo.reset_mock(); self.tg.send_message.reset_mock()
        await bot.send_history_result(self.tg,1,SERVER,'ipq')
        self.assertEqual(self.tg.send_photo.await_count,2)
        text='\n'.join(c.args[1] for c in self.tg.send_message.await_args_list)
        self.assertIn(URL4,text); self.assertIn(URL6,text)
        self.assertIn('IPv4 + IPv6',text)

    async def test_v4_explicit_command_keeps_single_report(self):
        job = await self.run_task(output=RAW4,mode='4')
        self.assertEqual(self.render.await_count,1)
        self.assertEqual(job['status'],'done')

    async def test_one_report_in_dual_mode_is_explicit(self):
        job = await self.run_task(code=1,output=RAW4)
        self.assertEqual(job['status'],'done')
        self.assertIn('仅收到一份',self.tg.send_message.await_args.args[1])

    async def test_timeout_keeps_partial_report_and_failed_status(self):
        job = await self.run_task(code=124,output=RAW4+'命令超时')
        self.assertEqual(job['status'],'failed')
        self.assertIn('未完成',self.tg.send_message.await_args.args[1])
        self.assertIn(URL4,self.tg.send_message.await_args.args[1])

    async def test_one_render_failure_keeps_second_image_and_both_links(self):
        async def render(raw,path,**kw):
            if URL4 in raw: raise RuntimeError('render failed')
            await self.render_report(raw,path,**kw)
        self.render.side_effect=render
        job = await self.run_task()
        self.assertEqual(self.tg.send_photo.await_count,1)
        text=self.tg.send_message.await_args.args[1]
        self.assertIn(URL4,text); self.assertIn(URL6,text); self.assertIn('失败',text)
        self.assertEqual(job['status'],'done')

    async def test_photo_failure_does_not_stop_second_report(self):
        self.tg.send_photo.side_effect=[RuntimeError('photo failed'),None]
        job = await self.run_task()
        self.assertEqual(self.tg.send_photo.await_count,2)
        self.assertEqual(len(job['media_paths']),2)
        self.assertEqual(job['status'],'done')

    async def test_final_delivery_failure_does_not_erase_detection(self):
        self.tg.send_message.side_effect=RuntimeError('telegram unavailable')
        job = await self.run_task()
        self.assertEqual(job['status'],'done')
        self.assertIn('telegram unavailable',job['delivery_error'])

    async def test_missing_report_fails(self):
        job = await self.run_task(code=2,output='failed')
        self.assertEqual(job['status'],'failed')
        self.tg.send_photo.assert_not_awaited()

    async def test_ipv6_lite_without_public_url_is_still_rendered(self):
        lite = RAW6.replace('报告链接：'+URL6, '今日IP检测量：1；总检测量：2。感谢使用xy系列脚本！')
        job = await self.run_task(output=RAW4+lite)
        self.assertEqual(self.render.await_count,2)
        self.assertEqual(len(job['media_paths']),2)
        self.assertEqual(job['status'],'done')
        self.assertIn('未提供公开链接',self.tg.send_message.await_args.args[1])
        self.assertNotIn('仅收到一份',self.tg.send_message.await_args.args[1])

    async def test_unlinked_incomplete_report_is_not_rendered(self):
        incomplete=RAW6.replace('报告链接：'+URL6,'still testing')
        job=await self.run_task(code=124,output=RAW4+incomplete)
        self.assertEqual(self.render.await_count,1)
        self.assertEqual(job['status'],'failed')

if __name__=='__main__': unittest.main()
