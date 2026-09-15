"""Execute production command generation and Bash in an isolated fake host.
No SSH, Telegram, network, or production proxy files are accessed.
"""
import ast
import asyncio
import html
import os
from pathlib import Path
import re
import shlex
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    tree = ast.parse(path.read_text())
    names = {'run_proxy_tool_task', 'proxy_tool_config', 'proxy_answers',
             'proxy_extract_config', 'is_proxy_link_line', 'format_proxy_config_html',
             'proxy_menu_text', 'proxy_markup', 'script_command_text'}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PROXY_TOOLS' for t in n.targets)]
    import sys
    sys.path.insert(0, str(ROOT))
    from proxy_nodes import remote_command
    ns = dict(remote_command=remote_command, os=os, shlex=shlex, re=re, safe=lambda v: html.escape(str(v)),
              strip_ansi=lambda s: re.sub(r'\x1b\[[0-9;]*m', '', s), trim_log=lambda s, n=3600: s[:n],
              server_id=lambda s: 'test', ssh_env_for=lambda s: {},
              ssh_args=lambda s, remote, tty=False: remote, ParseMode=types.SimpleNamespace(HTML='HTML'),
              finish_job=lambda *a: None, JOBS={'job': {}},
              InlineKeyboardButton=lambda text, **kw: dict(text=text, **kw), InlineKeyboardMarkup=lambda rows: rows)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)
    return ns


async def invoke(path, action='ensure', kind='anytls', runner=None, mode=None):
    ns = load(path)
    captured = {}
    async def run(cmd, **kw):
        captured.update(command=cmd, **kw)
        return runner(cmd) if runner else (0, '当前配置\nanytls://existing-secret@example.invalid:443')
    async def send(*args, **kw):
        captured['message'] = args[-1]
    ns.update(run_subprocess=run, send_long_text=send)
    bot = types.SimpleNamespace(send_message=send)
    await ns['run_proxy_tool_task'](bot, 1, {'name': 'test'}, 'job', kind, action, mode)
    captured['job'] = ns['JOBS']['job']
    return captured


class ProxyCommandTests(unittest.TestCase):
    def test_unknown_action_fails_without_remote_execution(self):
        r = asyncio.run(invoke(ROOT / 'telegram-bot/bot.py', 'invalid'))
        self.assertNotIn('command', r)
        self.assertEqual(r['job']['status'], 'failed')

    def test_displayed_view_never_suggests_mutating_manager_view(self):
        ns = load(ROOT / 'telegram-bot/bot.py')
        for kind in ns['PROXY_TOOLS']:
            text = ns['script_command_text'](kind, action='view')
            self.assertNotIn('curl', text)
            self.assertNotIn('bash', text)
            self.assertIn('只读', text)

    def test_all_menus_explain_readonly_existing_nodes(self):
        ns = load(ROOT / 'telegram-bot/bot.py')
        for kind in ns['PROXY_TOOLS']:
            text = ns['proxy_menu_text']({'name': 'fixture'}, kind)
            self.assertIn('不重装', text)
            self.assertIn('不启动/重启', text)
            self.assertNotIn('安装/更新', str(ns['proxy_markup']({}, kind)))
