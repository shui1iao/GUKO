"""Offline behavior tests: no SSH, Telegram, benchmarks or browser required."""
import asyncio
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('BOT_TOKEN', '123456:test-token')
os.environ.setdefault('ALLOWED_USERS', '1')
spec = importlib.util.spec_from_file_location('ansi_bot_under_test', ROOT / 'telegram-bot/bot.py')
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)
URL = 'https://Report.Check.Place/ip/ABC123.svg'
REPORT = '\r' + '#' * 72 + '\n\r\x1b[1mIP质量体检报告：\x1b[36m192.0.2.*\x1b[0m\n\r风险 \x1b[42m低\x1b[0m\n\r' + '#' * 72 + '\n\r报告链接：\x1b[4m' + URL + '\x1b[0m\n'
RAW = 'Downloading 10%\r99%\x1b[2J\x1b[H\n' + REPORT + '\x1b[2Jgoodbye'
SERVER = {'name': 'Test', 'host': '192.0.2.10'}
WORKDIR = '/root/guko-nodequality-' + 'a' * 32
CATS = [('硬件', 'hardware', 1, 'hardware_quality.log'), ('IP质量', 'ip', 2, 'ip_quality.log'), ('网络', 'net', 4, 'net_quality.log'), ('回程', 'backroute', 8, 'backroute_trace.log')]

class AnsiExtractionTest(unittest.TestCase):
    def test_final_ip_report_keeps_color_not_download_or_clear(self):
        result = bot.extract_ip_ansi_report(RAW, URL)
        self.assertIn('\x1b[42m低', result)
        self.assertTrue(result.startswith('\r' + '#' * 72))
        self.assertIn(URL, result)
        self.assertNotIn('Downloading', result)
        self.assertNotIn('\x1b[2J', result)

    def test_progress_and_report_divider_sharing_lf_line_preserves_header(self):
        for reset in ['', '\x1b[0m', '\x1b[0m\x1b[1;37m']:
            with self.subTest(reset=reset):
                expected = '\r' + reset + REPORT.lstrip('\r')
                raw = '正在检测黑名单数据库 95%\r\r' + expected + '\x1b[2Jgoodbye'
                result = bot.extract_ip_ansi_report(raw, URL)
                self.assertRegex(bot.strip_ansi(result.split('\n')[0]).strip(), r'^#{72}$')
                self.assertNotIn('95%', result)
                self.assertNotIn('正在检测', result)
                self.assertIn('\x1b[42m低', result)
                self.assertEqual(result[result.index('#'):], bot.extract_ip_ansi_report(REPORT, URL)[bot.extract_ip_ansi_report(REPORT, URL).index('#'):])

    def test_divider_in_progress_without_carriage_return_is_not_header(self):
        raw = 'Downloading ' + '#'*72 + '\n' + REPORT.split('\n',1)[1]
        result = bot.extract_ip_ansi_report(raw, URL)
        self.assertNotIn('Downloading', result)
        self.assertIn('IP质量体检报告', result.split('\n')[0])

    def test_ipv6_followup_is_not_combined_with_first_report(self):
        second = REPORT.replace(URL, URL.replace('ABC123', 'SECOND')).replace('192.0.2.*', '2001:db8::*')
        result = bot.extract_ip_ansi_report(RAW + second, URL)
        self.assertNotIn('2001:db8', result)
        self.assertEqual(result.count('IP质量体检报告'), 1)

    def test_missing_report_fails_instead_of_rendering_progress(self):
        with self.assertRaises(ValueError):
            bot.extract_ip_ansi_report('Downloading\n' + URL, URL)

class AnsiIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tg = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
        self.stack = __import__('contextlib').ExitStack()
        for name in ['finish_job', 'clear_result_files']:
            self.stack.enter_context(patch.object(bot, name))
        self.stack.enter_context(patch.object(bot, 'persist_result_file', return_value='saved.png'))
        self.stack.enter_context(patch.object(bot, 'ssh_args', side_effect=lambda s, cmd, **kw: ['ssh', cmd]))
        self.stack.enter_context(patch.object(bot, 'ssh_env_for', return_value=None))
        self.old = self.stack.enter_context(patch.object(bot, 'render_checkplace_png', new_callable=AsyncMock))
        bot.JOBS['ansi-test'] = {}

    async def asyncTearDown(self):
        self.stack.close()
        bot.JOBS.pop('ansi-test', None)

    async def render_ok(self, raw, png, kind='ip'):
        Path(png).write_bytes(b'PNG test transport fixture')

    async def test_ip_task_sends_true_ansi_using_new_renderer(self):
        with patch.object(bot, 'run_until_report', AsyncMock(return_value=(0, RAW, URL))), patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=self.render_ok), create=True) as render:
            await bot.run_ip_quality_task(self.tg, 1, SERVER, 'ansi-test')
        render.assert_awaited_once()
        self.assertIn('\x1b[42m低', render.await_args.args[0])
        self.assertNotIn('Downloading', render.await_args.args[0])
        self.tg.send_photo.assert_awaited_once()
        self.old.assert_not_awaited()

    async def test_ip_renderer_failure_keeps_link_without_svg_fallback(self):
        with patch.object(bot, 'run_until_report', AsyncMock(return_value=(0, RAW, URL))), patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=RuntimeError('renderer failed')), create=True):
            await bot.run_ip_quality_task(self.tg, 1, SERVER, 'ansi-test')
        self.assertIn(URL, self.tg.send_message.await_args.args[1])
        self.assertIn('失败', self.tg.send_message.await_args.args[1])
        self.tg.send_photo.assert_not_awaited()
        self.old.assert_not_awaited()

    async def test_nonzero_ip_exit_with_complete_report_still_succeeds(self):
        with patch.object(bot, 'run_until_report', AsyncMock(return_value=(1, RAW, URL))), patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=self.render_ok)):
            await bot.run_ip_quality_task(self.tg, 1, SERVER, 'ansi-test')
        self.tg.send_photo.assert_awaited_once()
        self.assertEqual(bot.JOBS['ansi-test']['status'], 'done')

    async def test_partial_nq_renderer_failure_keeps_all_links(self):
        net_url = URL.replace('/ip/', '/net/')
        with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, URL + '\n' + net_url))), patch.object(bot, 'read_nodequality_ansi_logs', AsyncMock(return_value={'ip': REPORT, 'net': '\x1b[32mnetwork'})), patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=RuntimeError('browser failure'))):
            await bot.run_nq_task(self.tg, 1, SERVER, 'ansi-test', 6)
        message = self.tg.send_message.await_args.args[1]
        self.assertIn(URL, message)
        self.assertIn(net_url, message)
        self.assertIn('失败', message)
        self.old.assert_not_awaited()

    async def test_partial_nq_timeout_still_explicitly_reports_image_failure(self):
        with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, URL))), patch.object(bot, 'read_nodequality_ansi_logs', AsyncMock(return_value={'ip': REPORT})), patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=asyncio.TimeoutError)):
            await bot.run_nq_task(self.tg, 1, SERVER, 'ansi-test', 2)
        self.assertIn('转 PNG 失败', self.tg.send_message.await_args.args[1])
        self.assertIn(URL, self.tg.send_message.await_args.args[1])

    async def test_nq_each_single_kind_uses_matching_original_log(self):
        for label, kind, bit, filename in CATS:
            with self.subTest(kind=kind):
                url = URL.replace('/ip/', '/' + kind + '/')
                raw = '\x1b[32m' + filename + '\x1b[0m'
                with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, url))), patch.object(bot, 'read_nodequality_ansi_logs', AsyncMock(return_value={kind: raw}), create=True) as read, patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=self.render_ok), create=True) as render:
                    await bot.run_nq_task(self.tg, 1, SERVER, 'ansi-test', bit)
                read.assert_awaited_once()
                self.assertRegex(read.await_args.args[1], r'^/root/guko-nodequality-[0-9a-f]{32}$')
                self.assertEqual(render.await_args.args[0], raw)
                self.assertEqual(render.await_args.kwargs['kind'], kind)
        self.old.assert_not_awaited()

    async def test_full_nq_sends_only_combined_link(self):
        nq = 'https://nodequality.com/r/abcdefgh12345678abcdefgh12345678'
        with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, nq + '\n' + URL))), patch.object(bot, 'read_nodequality_ansi_logs', AsyncMock(), create=True) as read, patch.object(bot, 'render_ansi_png', AsyncMock(), create=True) as render:
            await bot.run_nq_task(self.tg, 1, SERVER, 'ansi-test', bot.NQ_ALL_MASK)
        render.assert_not_awaited()
        read.assert_not_awaited()
        self.tg.send_photo.assert_not_awaited()
        self.assertIn(nq, self.tg.send_message.await_args.args[1])

    async def test_nq_log_read_failure_keeps_link_never_svg(self):
        with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, URL))), patch.object(bot, 'read_nodequality_ansi_logs', AsyncMock(side_effect=RuntimeError('log missing')), create=True), patch.object(bot, 'render_ansi_png', AsyncMock(), create=True) as render:
            await bot.run_nq_task(self.tg, 1, SERVER, 'ansi-test', 2)
        self.assertIn(URL, self.tg.send_message.await_args.args[1])
        self.assertIn('失败', self.tg.send_message.await_args.args[1])
        self.old.assert_not_awaited()
        render.assert_not_awaited()

    async def test_remote_reader_matches_allowlisted_logs_no_old_directory(self):
        with patch.object(bot, 'run_ansi_subprocess', AsyncMock(return_value=(0, '\x1b[32moriginal\x1b[0m'))) as run:
            logs = await bot.read_nodequality_ansi_logs(SERVER, WORKDIR, 15)
        self.assertEqual(set(logs), {x[1] for x in CATS})
        self.assertEqual(run.await_count, 4)
        for call, (_, kind, bit, filename) in zip(run.await_args_list, CATS):
            cmd = call.args[0][-1]
            self.assertTrue(call.kwargs['separate_stderr'])
            self.assertIn(WORKDIR, cmd)
            self.assertIn(filename, cmd)
            self.assertNotIn('/root/.nodequality*', cmd)
            self.assertIn('\x1b[32m', logs[kind])

    async def test_cleanup_only_removes_current_allowlisted_copies(self):
        with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, ''))) as run:
            await bot.cleanup_nodequality_ansi_logs(SERVER, WORKDIR)
            for bad in [WORKDIR + ';id', '/root/.nodequalityOLD']:
                with self.assertRaises(ValueError):
                    await bot.cleanup_nodequality_ansi_logs(SERVER, bad)
        run.assert_awaited_once()
        command = run.await_args.args[0][-1]
        self.assertIn('rm -f --', command)
        self.assertNotIn('rm -rf', command)
        for _, _, _, filename in CATS:
            self.assertIn(WORKDIR + '/' + filename, command)
        self.assertNotIn('result.zip', command)

    async def test_external_workdir_rejected_before_any_ssh(self):
        with patch.object(bot, 'run_subprocess', AsyncMock()) as run:
            for path in ['/tmp/nq_OLD', WORKDIR + ';touch /tmp/pwn', WORKDIR + '/../old', '/root/guko-nodequality-$(id)']:
                with self.assertRaises(ValueError):
                    await bot.read_nodequality_ansi_logs(SERVER, path, 2)
                with self.assertRaises(ValueError):
                    bot.nodequality_remote_command(SERVER, 2, work_dir=path)
        run.assert_not_awaited()

class NodeQualityShellTest(unittest.TestCase):
    def test_official_cleanup_preserves_only_this_invocations_logs(self):
        # Exercise the generated shell with a tiny upstream-shaped script. No
        # benchmark/network/SSH: fake curl serves this fixture from local disk.
        work_dir = '/root/guko-nodequality-' + os.urandom(16).hex()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            upstream = td / 'upstream.sh'
            upstream.write_text('''#!/bin/bash
function run_ip_quality(){
    chroot_run bash <(curl -Ls https://IP.Check.Place) $opt_ipv $opt_lang -y -o /result/$ip_quality_json_filename
}
while getopts '4d:' opt; do [ "$opt" != d ] || base=$OPTARG; done
work_dir="$base/.nodequalityCURRENT"
mkdir -p "$work_dir/BenchOs/result"
printf '\\033[32mthis run\\033[0m\\n' > "$work_dir/BenchOs/result/ip_quality.log"
rm -rf $work_dir/BenchOs
rm -rf "${work_dir}"/
''')
            curl = td / 'curl'
            curl.write_text('#!/bin/bash\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then cp "$NQ_FIXTURE" "$2"; exit; fi; shift; done\nexit 9\n')
            curl.chmod(0o700)
            env = dict(os.environ, PATH=str(td) + ':' + os.environ['PATH'], NQ_FIXTURE=str(upstream))
            cmd = bot.nodequality_remote_command(SERVER, 2, work_dir=work_dir)
            checked = subprocess.run(['bash', '-n'], input=cmd, text=True, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            try:
                result = subprocess.run(['bash', '-c', cmd], env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = Path(work_dir, 'ip_quality.log').read_bytes()
                self.assertEqual(raw, b'\x1b[32mthis run\x1b[0m\n')
                self.assertEqual(stat.S_IMODE(Path(work_dir).stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(Path(work_dir, 'ip_quality.log').stat().st_mode), 0o600)
                self.assertFalse(Path(work_dir, '.nodequalityCURRENT/BenchOs').exists())
            finally:
                __import__('shutil').rmtree(work_dir, ignore_errors=True)


class AnsiProcessCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_kills_entire_process_group(self):
        proc = SimpleNamespace(pid=87654321, communicate=AsyncMock(side_effect=asyncio.TimeoutError), wait=AsyncMock(), returncode=None)
        with patch.object(bot.asyncio, 'create_subprocess_exec', AsyncMock(return_value=proc)) as create, patch.object(bot.os, 'killpg') as kill:
            with self.assertRaises(asyncio.TimeoutError):
                await bot.run_ansi_subprocess(['node', 'test.js'], timeout=0.1)
        self.assertTrue(create.await_args.kwargs['start_new_session'])
        kill.assert_called_once_with(proc.pid, bot.signal.SIGKILL)
        proc.wait.assert_awaited()

    async def test_cancellation_kills_entire_process_group(self):
        proc = SimpleNamespace(pid=87654321, communicate=AsyncMock(side_effect=asyncio.CancelledError), wait=AsyncMock(), returncode=None)
        with patch.object(bot.asyncio, 'create_subprocess_exec', AsyncMock(return_value=proc)), patch.object(bot.os, 'killpg') as kill:
            with self.assertRaises(asyncio.CancelledError):
                await bot.run_ansi_subprocess(['node', 'test.js'], timeout=120)
        kill.assert_called_once_with(proc.pid, bot.signal.SIGKILL)
        proc.wait.assert_awaited()

    async def test_ssh_log_stdout_excludes_stderr_warning(self):
        result = await bot.run_ansi_subprocess(
            [sys.executable, '-c', 'import sys; sys.stdout.write("\\x1b[32mraw\\x1b[0m"); sys.stderr.write("Warning: Permanently added host\\n")'],
            timeout=5, separate_stderr=True, env=dict(os.environ),
        )
        self.assertEqual(result, (0, '\x1b[32mraw\x1b[0m'))

    async def test_normal_exit_reaps_descendants_and_preserves_output(self):
        result = await bot.run_ansi_subprocess([sys.executable, '-c', 'print("real process")'], timeout=5)
        self.assertEqual(result, (0, 'real process\n'))


class RendererProcessTest(unittest.IsolatedAsyncioTestCase):
    async def test_node_cli_private_temp_and_cleanup(self):
        seen = []
        async def runner(args, timeout):
            self.assertEqual(args[0], 'node')
            self.assertTrue(args[1].endswith('/render_ansi.js'))
            self.assertEqual(args[-2:], ['--kind', 'net'])
            self.assertEqual(timeout, 120)
            p = Path(args[2]); seen.append(p)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(p.read_bytes(), b'\x1b[31mraw\x1b[0m')
            Path(args[3]).write_bytes(b'\x89PNG\r\n\x1a\nDATA')
            return 0, ''
        with tempfile.TemporaryDirectory() as td, patch.object(bot, 'run_ansi_subprocess', side_effect=runner):
            await bot.render_ansi_png('\x1b[31mraw\x1b[0m', Path(td) / 'out.png', kind='net')
        self.assertTrue(seen)
        self.assertFalse(seen[0].exists())

    async def test_stream_renderer_passes_original_control_bytes(self):
        raw = ' ** Checking Results Under IPv4\n\r Netflix:\t\x1b[33mOriginals Only\x1b[0m\n'
        async def runner(args, timeout):
            self.assertEqual(args[-2:], ['--kind', 'stream'])
            self.assertEqual(Path(args[2]).read_bytes(), raw.encode())
            Path(args[3]).write_bytes(b'\x89PNG\r\n\x1a\nDATA')
            return 0, ''
        with tempfile.TemporaryDirectory() as td, patch.object(bot, 'run_ansi_subprocess', side_effect=runner) as run:
            await bot.render_ansi_png(raw, Path(td) / 'out.png', kind='stream')
            run.assert_awaited_once()

    async def test_renderer_rejects_empty_oversize_and_unknown_kind(self):
        with patch.object(bot, 'run_subprocess', AsyncMock()) as run:
            for raw, kind in [('', 'ip'), ('x' * (2 * 1024 * 1024 + 1), 'ip'), ('raw', '../bad')]:
                with self.assertRaises(ValueError):
                    await bot.render_ansi_png(raw, '/tmp/never.png', kind=kind)
        run.assert_not_awaited()

    async def test_renderer_nonzero_cleans_temp_and_raises(self):
        seen = []
        async def fail(args, timeout):
            seen.append(Path(args[2]))
            return 124, 'timed out'
        with patch.object(bot, 'run_ansi_subprocess', side_effect=fail):
            with self.assertRaises(RuntimeError):
                await bot.render_ansi_png('raw', '/tmp/never.png')
        self.assertFalse(seen[0].exists())
