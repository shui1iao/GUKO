"""RRC output fixtures transcribed from upstream check.sh output statements.
These are branch/format fixtures, not claims about a live server's unlock state.
"""
import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('BOT_TOKEN', '123456:test-token')
os.environ.setdefault('ALLOWED_USERS', '1')
spec = importlib.util.spec_from_file_location('guko_rrc_test', ROOT / 'telegram-bot/bot.py')
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

HEADER = '[Stream Platform & Game Region Restriction Test]\n ** Checking Results Under IPv4\n============[ Multination ]============\n'
FIXTURE = HEADER + ''' Netflix:                 \x1b[32mYes (Region: US)\x1b[0m
 Disney+:                 No
 Dazn:                    Failed (Network Connection)
 Amazon Prime Video:      Originals Only
 TVBAnywhere+:            IPv6 Is Not Currently Supported
 OneTrust Region:         US [California]
 iQyi Oversea Region:     US
 Apple Region:            US
 Bing Region:             US (Risky)
 YouTube CDN:             Frankfurt
 Geo Region:              US
=======================================
===============[ Japan ]===============
 Abema.TV:                Oversea Only (Region: JP)
 DMM TV:                  Unsupported IPv6
 WOWOW:                   Yes
=======================================
Testing Done! Thanks for Using This Script!
'''

class RegionRestrictionStreamTest(unittest.TestCase):
    def test_display_command_is_short_and_matches_execution_options(self):
        for mode in ('4', '6'):
            text = bot.script_command_text('stream', ip_mode=mode, region_id='sea')
            self.assertEqual(text, '脚本命令：\nbash <(curl -' + mode + ' -fsSL ' + bot.REGIONRESTRICTION_URL + ') -M ' + mode + ' -R 9 -E en')
            self.assertNotIn('mktemp', text)
            self.assertIn('mktemp', bot.regionrestriction_remote_command(mode, 'sea'))

    def test_southeast_asia_selects_official_region_nine(self):
        for country in ('sg', 'my', 'th', 'id', 'ph', 'vn', 'kh', 'la', 'mm', 'bn', 'tl'):
            with self.subTest(country=country):
                region, label = bot.stream_region_for_server({'country': country})
                self.assertEqual(region, 'sea')
                self.assertEqual(label, '全球 + 东南亚')
                self.assertIn('-R 9 -E en', bot.regionrestriction_remote_command('4', region))

    def test_real_jp_output_and_no_advertisement(self):
        text = (ROOT / 'tests/fixtures/rrc-live-jp.txt').read_text()
        rows = bot.parse_stream_results(text)
        self.assertEqual(len(rows), 49)
        names = {r['service']: r for r in rows}
        self.assertIn('J:com On Demand', names)
        self.assertIn('Project Sekai: Colorful Stage', names)
        self.assertEqual(names['Radiko']['detail'], 'Yes (City: TOKYO)')
        self.assertEqual(names['Google Gemini']['region'], 'JPN')
        self.assertEqual(names['Netflix']['state'], 'originals_only')
        self.assertEqual(names['Steam Currency']['state'], 'info')
        self.assertEqual(names['Princess Connect Re:Dive Japan']['category'], 'Japan / Game')
        self.assertEqual(bot.parse_stream_results(text + HEADER + ' Ad Service: Yes\n'), rows)
        self.assertEqual(bot.parse_stream_results(text + '<html>advertisement</html>'), rows)

    def test_parse_upstream_states_without_losing_details(self):
        rows = bot.parse_stream_results(FIXTURE)
        self.assertEqual(len(rows), 14)
        by_name = {r['service']: r for r in rows}
        for name, state in [('Netflix', 'available'), ('Disney+', 'unavailable'), ('Dazn', 'failed'), ('Amazon Prime Video', 'originals_only'), ('TVBAnywhere+', 'unsupported'), ('DMM TV', 'unsupported'), ('Abema.TV', 'restricted')]:
            self.assertEqual(by_name[name]['state'], state)
        self.assertEqual(by_name['Netflix']['detail'], 'Yes (Region: US)')
        self.assertEqual(by_name['Netflix']['region'], 'US')
        self.assertEqual(by_name['Bing Region']['detail'], 'US (Risky)')
        self.assertEqual(by_name['Geo Region']['state'], 'info')
        self.assertEqual(by_name['WOWOW']['category'], 'Japan')

    def test_output_context_and_actual_service_evidence_required(self):
        for text in ['Netflix: Yes', '{}', '[]', 'curl: (22) HTTP 503', HEADER, HEADER + 'Geo Region: US', '<html>' + FIXTURE + '</html>', HEADER + 'error: failed to download', HEADER + 'Version: Yes']:
            with self.subTest(text=text):
                self.assertEqual(bot.parse_stream_results(text), [])
        self.assertTrue(bot.parse_stream_results(HEADER + ' Netflix: No\n'))
        self.assertTrue(bot.parse_stream_results(HEADER + ' Netflix: Failed (Network Connection)\n'))

    def test_new_service_not_hidden_by_old_allowlist(self):
        rows = bot.parse_stream_results(HEADER + ' Future Streaming Service: Yes (Region: CA)\n')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['service'], 'Future Streaming Service')

    def test_remote_command_modes_regions_and_shell_syntax(self):
        self.assertTrue(hasattr(bot, 'regionrestriction_remote_command'))
        for mode in ['4', '6']:
            for group, number in {'':0, 'unknown':0, 'tw':1, 'hk':2, 'jp':3, 'na':4, 'sa':5, 'eu':6, 'oc':7, 'kr':8, 'af':11}.items():
                cmd = bot.regionrestriction_remote_command(mode, group)
                self.assertIn('https://raw.githubusercontent.com/lmc999/RegionRestrictionCheck/main/check.sh', cmd)
                self.assertIn(f'bash "$script" -M {mode} -R {number} -E en', cmd)
                for flag in ['--proto', '--proto-redir', '--connect-timeout', '--max-time', '--max-filesize', 'mktemp', 'trap', 'test -s', 'wc -c']:
                    self.assertIn(flag, cmd)
                self.assertNotIn('| bash', cmd)
                self.assertNotIn('<(', cmd)
                checked = subprocess.run(['sh', '-n', '-c', cmd], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)
        with self.assertRaises(ValueError):
            bot.regionrestriction_remote_command('46', 'jp')

    def test_generated_runner_executes_unchanged_script_and_cleans(self):
        self.assertTrue(hasattr(bot, 'regionrestriction_remote_command'))
        for payload, download_code, expected in [
            ('#!/bin/bash\nprintf "%s\\n" "$*"; exit 7\n', 0, 7),
            ('', 0, 1), ('<html>bad gateway</html>', 0, 2), ('partial', 22, 22),
        ]:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tools = root / 'bin'
                tools.mkdir()
                (root / 'payload').write_text(payload)
                downloader = tools / 'curl'
                downloader.write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; cp "$PAYLOAD" "$1"; fi; shift; done\nexit "$DOWNLOAD_CODE"\n')
                downloader.chmod(0o755)
                env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'], TMPDIR=tmp,
                           PAYLOAD=str(root / 'payload'), DOWNLOAD_CODE=str(download_code))
                completed = subprocess.run(['sh', '-c', bot.regionrestriction_remote_command('6', 'jp')], env=env, capture_output=True, text=True)
                self.assertEqual(completed.returncode, expected, completed.stderr)
                self.assertFalse(list(root.glob('guko-rrc.*')))
                if expected == 7:
                    self.assertEqual(completed.stdout.strip(), '-M 6 -R 3 -E en')

    def test_history_preserves_execution_and_artifact_diagnostics(self):
        job = {'kind': 'stream', 'status': 'done', 'exit_code': 0,
               'proto': 'IPv4', 'render_error': 'Pillow failed',
               'artifact_error': 'disk full', 'raw_path': '/tmp/current-stream.txt'}
        with patch.object(bot, 'load_history', return_value=[]), patch.object(bot, 'save_history') as save:
            bot.history_append('stream-history', job)
        item = save.call_args.args[0][0]
        for key in ['exit_code', 'proto', 'render_error', 'artifact_error', 'raw_path']:
            self.assertEqual(item.get(key), job[key])

    def test_user_recipe_matches_safe_runner(self):
        self.assertTrue(hasattr(bot, 'regionrestriction_remote_command'))
        recipe = bot.script_command_text('stream', ip_mode='6', region_id='eu')
        self.assertIn('-M 6 -R 6 -E en', recipe)
        self.assertIn(bot.REGIONRESTRICTION_URL, recipe)
        self.assertNotIn('mktemp', recipe)
        self.assertEqual(subprocess.run(['bash', '-n'], input=recipe.split('\n', 1)[1], text=True, capture_output=True).returncode, 0)

    def test_region_country_collision_preserved(self):
        self.assertEqual(bot.stream_region_for_server({'country':'na'})[0], 'af')
        self.assertEqual(bot.stream_region_for_server({'country':'us'})[0], 'na')
        self.assertEqual(bot.stream_region_for_server({'country':'jp'})[0], 'jp')

    def test_summary_preserves_details_and_escapes_html(self):
        text = bot.format_stream_summary({'name':'<Tokyo>'}, FIXTURE, 'IPv4', '全球 + 日本', 'jp')
        self.assertIn('RegionRestrictionCheck', text)
        self.assertIn('Originals Only', text)
        self.assertIn('Failed (Network Connection)', text)
        self.assertIn('Yes (Region: US)', text)
        self.assertIn('&lt;Tokyo&gt;', text)
        self.assertNotIn('可用（JP）', text)

    def test_terminal_slice_preserves_real_ansi_tabs_cr_and_all_results(self):
        self.assertTrue(hasattr(bot, 'stream_terminal_report'))
        raw = (ROOT / 'tests/fixtures/rrc-live-jp.txt').read_bytes().decode('utf-8')
        start = raw.rfind('\n', 0, raw.index('** Checking Results Under')) + 1
        end = raw.index('\n', raw.index('Testing Done!')) + 1
        report = bot.stream_terminal_report(raw)
        self.assertEqual(report, raw[start:end])
        self.assertEqual(report.count('\r'), 49)
        self.assertEqual(bot.parse_stream_results(report), bot.parse_stream_results(raw))
        for text in ['Your Network Provider:', '[ Multination ]', '[ Japan ]', 'Testing Done!']:
            self.assertIn(text, report)
        for noise in ['Github Repository', 'Supporting OS', 'Advertisement', 'Number of Script Runs']:
            self.assertNotIn(noise, report)

    def test_partial_terminal_slice_keeps_original_control_bytes_and_eof(self):
        self.assertTrue(hasattr(bot, 'stream_terminal_report'))
        body = ' ** Checking Results Under IPv6\n\n============[ Multination ]============\n\r Netflix:\t\x1b[33mOriginals Only\x1b[0m\n\nprogress 0%\rprogress 100%\n last row'
        self.assertEqual(bot.stream_terminal_report('SSH warning\ninstall menu\n' + body), body)
        for footer in ['Number of Script Runs for Today: 1', '【Advertisement】', 'Connection to host closed.']:
            self.assertEqual(bot.stream_terminal_report(body + '\n' + footer + '\nnoise'), body + '\n')
        with self.assertRaises(ValueError):
            bot.stream_terminal_report('no upstream header')

    def test_white_card_and_status_rewriters_are_retired(self):
        for name in ['stream_result_image', 'stream_status_color', 'stream_status_label', 'stream_status_icon']:
            self.assertFalse(hasattr(bot, name), name)
        self.assertTrue(callable(bot.load_font))

    def test_retired_backend_absent_from_active_code_and_docs(self):
        retired = 'Unlock' + 'Scope'
        for p in [ROOT / 'telegram-bot/bot.py', ROOT / 'README.md', ROOT / 'README.en.md']:
            self.assertFalse(retired.lower() in p.read_text().lower(), str(p))
        for symbol in ['stream_json_results', 'STREAM_COMMON_DISPLAY_IDS', 'stream_runtime_evidence']:
            self.assertFalse(hasattr(bot, symbol))

class StreamTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_ipv4_probe_distinguishes_no_route_from_probe_failure(self):
        server = {'host': '192.0.2.1'}
        for output, expected in [('GUKO_IPV4=present\n', True), ('GUKO_IPV4=absent\n', False), ("Warning: Permanently added host to known hosts.\r\nGUKO_IPV4=present\n", True)]:
            with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(0, output))) as run:
                self.assertEqual(await bot.remote_has_ipv4(server), expected)
                self.assertIn('ip -4 route get', str(run.call_args))
                self.assertNotIn('api.ipify.org', str(run.call_args))
        for code, output in [(127, 'ip missing'), (255, 'SSH failed'), (0, 'garbage')]:
            with patch.object(bot, 'run_subprocess', AsyncMock(return_value=(code, output))):
                with self.assertRaises(RuntimeError):
                    await bot.remote_has_ipv4(server)

    async def run_task(self, output=FIXTURE, code=0, photo_error=False, render_error=False, v4=True, message_error=False):
        jid = 'rrc-fixture-job'
        bot.JOBS[jid] = {'status':'running'}
        sender = type('Sender', (), {})()
        sender.send_photo = AsyncMock(side_effect=RuntimeError('photo unavailable') if photo_error else None)
        sender.send_message = AsyncMock(side_effect=RuntimeError('message unavailable') if message_error else None)
        async def render_report(raw, output_path, *, kind):
            self.assertEqual(kind, 'stream')
            self.assertEqual(raw, bot.stream_terminal_report(output))
            Image.new('RGB', (100, 100)).save(output_path, format='PNG')
        with tempfile.TemporaryDirectory() as tmp, patch.object(bot, 'remote_has_ipv4', AsyncMock(return_value=v4)), patch.object(bot, 'run_subprocess', AsyncMock(return_value=(code, output))) as run, patch.object(bot, 'RESULTS_DIR', Path(tmp)), patch.object(bot, 'finish_job'), patch.object(bot, 'render_ansi_png', AsyncMock(side_effect=RuntimeError('render failed') if render_error else render_report)) as render:
            await bot.run_stream_task(sender, 1, {'id':'rrc-server', 'host':'192.0.2.1', 'name':'fixture', 'country':'jp'}, jid)
            job = dict(bot.JOBS[jid])
            if job.get('media_path'):
                self.assertTrue(Path(job['media_path']).is_file())
            if bot.parse_stream_results(output):
                self.assertEqual(render.await_count, 1)
            else:
                render.assert_not_awaited()
            if job.get('media_path'):
                self.assertEqual(Path(job['media_path']).suffix, '.png')
                with Image.open(job['media_path']) as image:
                    self.assertEqual(image.format, 'PNG')
            self.assertIn('raw_path', job)
            self.assertEqual(Path(job['raw_path']).read_text(), output)
            return job, sender, run

    async def test_exit_zero_without_results_fails(self):
        for output in ['hello', '<html>502 Bad Gateway</html>', HEADER + 'Geo Region: US']:
            job, sender, _ = await self.run_task(output)
            self.assertEqual(job['status'], 'failed')
            self.assertNotIn('完成', ''.join(str(c) for c in sender.send_message.call_args_list))

    async def test_success_persists_image_and_ipv4_first(self):
        job, sender, run = await self.run_task()
        self.assertEqual(job['status'], 'done')
        self.assertIn('media_path', job)
        self.assertEqual(sender.send_photo.await_count, 1)
        self.assertIn('fixture', sender.send_photo.call_args.kwargs.get('caption', ''))
        self.assertIn('-M 4 -R 3 -E en', str(run.call_args))

    async def test_ipv6_fallback_and_partial_failure(self):
        job, sender, run = await self.run_task(code=7, v4=False)
        self.assertEqual(job['status'], 'failed')
        self.assertIn('-M 6 -R 3 -E en', str(run.call_args))
        self.assertIn('未完成', ''.join(str(c) for c in sender.send_message.call_args_list))

    async def test_photo_failure_does_not_rewrite_remote_success(self):
        job, _, _ = await self.run_task(photo_error=True)
        self.assertEqual(job['status'], 'done')
        self.assertIn('photo unavailable', job['delivery_error'])
        self.assertEqual(job['log'], FIXTURE)

    async def test_message_failure_preserves_both_success_and_failure(self):
        for code in [0, 7]:
            job, _, _ = await self.run_task(code=code, message_error=True)
            self.assertEqual(job['status'], 'done' if code == 0 else 'failed')
            self.assertIn('message unavailable', job['delivery_error'])
            self.assertEqual(job['log'], FIXTURE)

    async def test_render_failure_is_not_delivery_or_remote_failure(self):
        job, _, _ = await self.run_task(render_error=True)
        self.assertEqual(job['status'], 'done')
        self.assertIn('render failed', job['render_error'])
        self.assertNotIn('delivery_error', job)

if __name__ == '__main__':
    unittest.main()
