#!/usr/bin/env python3
import asyncio
import stream_unified
import tool_sources
import csv
import hashlib
import html
import ipaddress
import json
import os
import select
import signal
import re
import subprocess
import tempfile
import time
from datetime import datetime
import urllib.request
import shutil
import shlex
import kat_proxy
from proxy_nodes import (
    remote_command, SNAPSHOT_EXIT, SNAPSHOT_HEADER, READ_ERROR, ProxyReadError,
    parse_snapshot, render_snapshot, snell_version_command, snapshot_command,
)
import socket
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
import urllib.error
from PIL import Image, ImageDraw, ImageFont

from auth import inventory_defaults, resolve_ssh, scp_from_args, ssh_args as build_ssh_args

from telegram import BotCommand, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

GUKO_VERSION = os.environ.get('GUKO_VERSION', '0.7.3').strip() or '0.7.3'
DATA_DIR = Path(os.environ.get('DATA_DIR', '/data'))
SERVERS_JSON = Path(os.environ.get('GUKO_INV') or os.environ.get('VPSPILOT_INV') or DATA_DIR / 'servers.json')
KULIN_BASE_URL = os.environ.get('KULIN_BASE_URL') or os.environ.get('KOMARI_BASE_URL') or ''
KULIN_USERNAME = os.environ.get('KULIN_USERNAME') or os.environ.get('KOMARI_USERNAME') or ''
KULIN_PASSWORD = os.environ.get('KULIN_PASSWORD') or os.environ.get('KOMARI_PASSWORD') or ''
KULIN_API_CACHE_TTL = int(os.environ.get('KULIN_API_CACHE_TTL', '300'))
KULIN_GEO_CACHE = {'ts': 0.0, 'by_ip': {}}
MEDIA_DIR = Path(os.environ.get('MEDIA_DIR', DATA_DIR / 'media'))
TMP_DIR = Path(os.environ.get('TMP_DIR', DATA_DIR / 'tmp'))
KEYS_DIR = Path(os.environ.get('KEYS_DIR', DATA_DIR / 'keys'))
RENDER_CHECKPLACE = Path(os.environ.get('RENDER_CHECKPLACE', '/app/render_checkplace.py'))
BGP_FETCH = Path(os.environ.get('BGP_FETCH', DATA_DIR / 'tools/bgp_fetch.py'))
IPPURE_DOWNLOAD = Path(os.environ.get('IPPURE_DOWNLOAD', DATA_DIR / 'tools/download_ippure.js'))
BGP_OUT_ROOT = Path(os.environ.get('BGP_OUT_ROOT', MEDIA_DIR / 'guko-bgp'))
IPPURE_TMP_ROOT = Path(os.environ.get('IPPURE_TMP_ROOT', TMP_DIR / 'guko-ippure'))
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ALLOWED_USERS = {x.strip() for x in os.environ.get('ALLOWED_USERS', '').split(',') if x.strip()}
ADMIN_USERS = {x.strip() for x in os.environ.get('ADMIN_USERS', '').split(',') if x.strip()} or set(ALLOWED_USERS)
ALLOW_INSECURE_STARTUP = os.environ.get('ALLOW_INSECURE_STARTUP', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
SCRIPT_SOURCES = {
    'nexttrace': ('NextTrace', 'https://github.com/nxtrace/NTrace-core'),
    'stream': ('Service Unlock (official latest)', 'https://github.com/shui1iao/service-unlock'),
    'ipq': ('IPQuality / Check.Place', 'https://github.com/xykt/IPQuality'),
    'nq': ('NodeQuality / Check.Place', 'https://github.com/LloydAsp/NodeQuality'),
    'tcpq': ('TcpQuality', 'https://github.com/ibsgss/TcpQuality'),
    'ss': ('Kat-Manager', 'https://github.com/shui1iao/Kat-Manager'),
    'anytls': ('Kat-Manager', 'https://github.com/shui1iao/Kat-Manager'),
    'snell': ('Snell-Manager', 'https://github.com/shui1iao/Snell-Manager'),
}
PROXY_TOOLS = {
    'ss': {
        'name': 'Kat SS',
        'service': 'kat-ss',
        'script_url': 'https://raw.githubusercontent.com/shui1iao/Kat-Manager/main/kat.sh',
        'install_arg': 'install',
        'button': '🔐 SS',
    },
    'anytls': {
        'name': 'Kat AnyTLS',
        'service': 'kat-anytls',
        'script_url': 'https://raw.githubusercontent.com/shui1iao/Kat-Manager/main/kat.sh',
        'install_arg': 'install',
        'button': '🛡 AnyTLS',
    },
    'snell': {
        'name': 'Snell',
        'service': 'snell',
        'script_url': 'https://snell.siaoz.si',
        'install_arg': 'install',
        'button': '🌀 Snell',
    },
}

GB5_OOM_MARKER = '__GUKO_GB5_OOM__'
JOBS = {}
# Short-lived, single-use, user/chat/server/protocol-bound install decisions.
KAT_INSTALL_CONFIRMATIONS = {}
RUNNING = set()
PENDING_NEXTTRACE = {}
ADD_SESSIONS = {}
HISTORY_JSON = Path(os.environ.get('HISTORY_JSON', DATA_DIR / 'history.json'))
RESULTS_DIR = Path(os.environ.get('RESULTS_DIR', DATA_DIR / 'results'))
# Each server/test kind only keeps the latest finished result; this stays intentionally small.
HISTORY_LIMIT = int(os.environ.get('HISTORY_LIMIT', '500'))


def startup_check():
    problems = []
    if not BOT_TOKEN or BOT_TOKEN in {'123456:replace-me', '123:abc', 'CHANGE_ME'}:
        problems.append('BOT_TOKEN is empty or still an example value')
    if not ALLOWED_USERS:
        problems.append('ALLOWED_USERS is empty; GUKO requires whitelist mode')
    if '*' in ALLOWED_USERS or '0' in ALLOWED_USERS:
        problems.append('ALLOWED_USERS contains unsafe wildcard-like value')
    for d in (DATA_DIR, MEDIA_DIR, TMP_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEYS_DIR, 0o700)
        for key_file in KEYS_DIR.iterdir():
            if key_file.is_file():
                os.chmod(key_file, 0o600)
    except Exception as e:
        problems.append(f'failed to tighten key permissions: {e}')
    HISTORY_JSON.parent.mkdir(parents=True, exist_ok=True)
    if SERVERS_JSON.exists():
        try:
            inv = json.loads(SERVERS_JSON.read_text() or '{}')
            leaked = []
            blob = json.dumps(inv, ensure_ascii=False)
            for marker in ('BOT_TOKEN', 'CHANGE_ME', 'PRIVATE KEY'):
                if marker in blob:
                    leaked.append(marker)
            if leaked:
                problems.append('servers.json appears to contain private/example markers: ' + ', '.join(leaked))
        except Exception as e:
            problems.append(f'cannot parse servers inventory: {e}')
    if problems and not ALLOW_INSECURE_STARTUP:
        raise SystemExit('安全启动检查失败：\n- ' + '\n- '.join(problems) + '\n\n请配置 .env；如确实要临时跳过，设置 ALLOW_INSECURE_STARTUP=true')
    if problems:
        print('WARNING: insecure startup allowed:\n- ' + '\n- '.join(problems), flush=True)
    interrupted = reconcile_interrupted_history()
    if interrupted:
        print(f'reconciled {interrupted} interrupted task record(s)', flush=True)


def allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and str(user.id) in ALLOWED_USERS)


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and str(user.id) in ADMIN_USERS)


async def guard(update: Update) -> bool:
    if allowed(update):
        return True
    user = update.effective_user
    uid = user.id if user else 'unknown'
    if update.callback_query:
        await update.callback_query.answer('无权限', show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(f'无权限使用这个GUKO bot。你的 ID：{uid}')
    return False


async def admin_guard(update: Update) -> bool:
    if not await guard(update):
        return False
    if is_admin(update):
        return True
    if update.callback_query:
        await update.callback_query.answer('需要管理员权限', show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text('需要管理员权限。')
    return False


def load_inventory() -> dict:
    if not SERVERS_JSON.exists():
        inv = {
            'updated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'source': 'local',
            'defaults': {
                'ssh': {
                    'user': os.environ.get('GUKO_DEFAULT_USER') or os.environ.get('VPSPILOT_DEFAULT_USER') or os.environ.get('JIAOOPS_DEFAULT_USER', 'root'),
                    'port': int(os.environ.get('GUKO_DEFAULT_PORT') or os.environ.get('VPSPILOT_DEFAULT_PORT') or os.environ.get('JIAOOPS_DEFAULT_PORT', '22')),
                    'key': os.environ.get('GUKO_DEFAULT_KEY') or os.environ.get('VPSPILOT_DEFAULT_KEY') or os.environ.get('JIAOOPS_DEFAULT_KEY', '/data/keys/id_ed25519'),
                }
            },
            'servers': [],
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SERVERS_JSON.write_text(json.dumps(inv, ensure_ascii=False, indent=2) + '\n')
        return inv
    return json.loads(SERVERS_JSON.read_text())


def save_inventory(inv: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SERVERS_JSON.exists():
        backup = SERVERS_JSON.with_name(f'{SERVERS_JSON.name}.bak-{datetime.now().strftime("%Y%m%d-%H%M%S")}')
        shutil.copy2(SERVERS_JSON, backup)
    SERVERS_JSON.write_text(json.dumps(inv, ensure_ascii=False, indent=2) + '\n')


def next_manual_id(servers):
    used = set()
    for s in servers:
        try:
            used.add(int(server_id(s)))
        except Exception:
            pass
    n = -1
    while n in used:
        n -= 1
    return n


def redact_inventory(inv: dict):
    def clean_server(s):
        out = json.loads(json.dumps(s, ensure_ascii=False))
        ssh = out.get('ssh') or {}
        if 'password' in ssh:
            ssh['password'] = '***'
        if out.get('password'):
            out['password'] = '***'
        if 'key' in ssh and ssh.get('key'):
            ssh['key'] = str(ssh['key']).replace(str(DATA_DIR), '/data')
        if out.get('key'):
            out['key'] = str(out['key']).replace(str(DATA_DIR), '/data')
        out['ssh'] = ssh
        return out
    data = {k: v for k, v in inv.items() if k != 'servers'}
    defaults = json.loads(json.dumps(data.get('defaults') or {}, ensure_ascii=False))
    if 'password' in defaults:
        defaults['password'] = '***'
    if defaults.get('key'):
        defaults['key'] = str(defaults['key']).replace(str(DATA_DIR), '/data')
    dssh = defaults.get('ssh') or {}
    if 'password' in dssh:
        dssh['password'] = '***'
    if dssh.get('key'):
        dssh['key'] = str(dssh['key']).replace(str(DATA_DIR), '/data')
    defaults['ssh'] = dssh
    data['defaults'] = defaults
    data['servers'] = [clean_server(s) for s in inv.get('servers', [])]
    return data


def compact_server_identifier(value, max_bytes=36):
    text = str(value or '').strip()
    if len(text.encode()) <= max_bytes:
        return text
    safe_prefix = re.sub(r'[^A-Za-z0-9_.-]+', '_', text).strip('_.-')[:20] or 'server'
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f'{safe_prefix}-{digest}'


def server_id(s):
    for key in ('id', 'legacy_id', 'nezha_id'):
        if s.get(key) is not None:
            return compact_server_identifier(s.get(key))
    host = str(s.get('host') or '').strip()
    if host:
        port = (s.get('ssh') or {}).get('port') or s.get('port')
        safe_host = re.sub(r'[^A-Za-z0-9_.-]+', '_', host).strip('_')
        value = f'{safe_host}-{port}' if port else safe_host
        return compact_server_identifier(value)
    return compact_server_identifier(s.get('name'))


def reorder_servers(servers, sid: str, direction: str):
    offset = {'up': -1, 'down': 1}.get(direction)
    if offset is None:
        return None
    reordered = list(servers)
    index = next(
        (i for i, server in enumerate(reordered) if str(server_id(server)) == str(sid)),
        None,
    )
    if index is None:
        return None
    target = index + offset
    if target < 0 or target >= len(reordered):
        return None
    reordered[index], reordered[target] = reordered[target], reordered[index]
    return reordered


def move_server_by_id(sid: str, direction: str):
    inv = load_inventory()
    reordered = reorder_servers(inv.get('servers') or [], sid, direction)
    if reordered is None:
        return False
    inv['servers'] = reordered
    inv['updated_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
    save_inventory(inv)
    return True


def update_server_by_id(sid: str, patch: dict):
    inv = load_inventory()
    servers = inv.get('servers') or []
    for i, s in enumerate(servers):
        if str(server_id(s)) == str(sid):
            merged = dict(s)
            ssh = dict(merged.get('ssh') or {})
            for k in ('name', 'host', 'aliases', 'role', 'specs', 'ipv6', 'ipv6_status'):
                if k in patch:
                    merged[k] = patch[k]
            if 'ssh' in patch:
                ssh.update(patch['ssh'])
                merged['ssh'] = ssh
            servers[i] = merged
            inv['updated_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
            save_inventory(inv)
            return merged
    return None


def delete_server_by_id(sid: str):
    inv = load_inventory()
    servers = inv.get('servers') or []
    kept = []
    removed = None
    for s in servers:
        if str(server_id(s)) == str(sid):
            removed = s
        else:
            kept.append(s)
    if removed is None:
        return None
    inv['servers'] = kept
    inv['updated_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
    save_inventory(inv)
    return removed


def upsert_server(item: dict):
    inv = load_inventory()
    servers = inv.setdefault('servers', [])
    q = {str(x).lower() for x in [item.get('name'), str(item.get('id') or item.get('legacy_id') or '')] if x}
    q.update(str(x).lower() for x in (item.get('aliases') or []))
    item_host = str(item.get('host') or '').lower()
    item_port = (item.get('ssh') or {}).get('port') or item.get('port')
    replaced = False
    for i, old in enumerate(servers):
        fields = {str(x).lower() for x in [old.get('name'), str(old.get('id') or old.get('legacy_id') or '')] if x}
        fields.update(str(x).lower() for x in (old.get('aliases') or []))
        old_host = str(old.get('host') or '').lower()
        old_port = (old.get('ssh') or {}).get('port') or old.get('port')
        same_endpoint = item_host and old_host == item_host and (not item_port or not old_port or str(item_port) == str(old_port))
        if (q & fields) or same_endpoint:
            item.setdefault('id', old.get('id') or old.get('legacy_id') or next_manual_id(servers))
            item.setdefault('state', old.get('state') or {})
            merged = dict(old)
            merged.update(enrich_server_geo(item))
            servers[i] = merged
            replaced = True
            break
    if not replaced:
        item.setdefault('id', next_manual_id(servers))
        item.setdefault('role', 'manual')
        item.setdefault('source', 'local-manual')
        item.setdefault('state', {})
        servers.append(enrich_server_geo(item))
    inv['updated_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
    save_inventory(inv)
    return item, 'updated' if replaced else 'added'


def ssh_config(s):
    return resolve_ssh(s, load_inventory())


def fmt_bytes(n):
    if n is None:
        return '-'
    n = float(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024:
            return f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}PB'


def pct_num(used, total):
    if used is None or total in (None, 0):
        return None
    return float(used) / float(total) * 100


def pct(used, total):
    p = pct_num(used, total)
    return '-' if p is None else f'{p:.1f}%'


def meter(value, total=100, width=22):
    p = pct_num(value, total)
    if p is None:
        return '▕' + '▱' * width + '▏', '-'
    p = max(0, min(100, p))
    filled = max(0, min(width, round(p / 100 * width)))
    if p >= 85:
        icon = '🔴'
    elif p >= 65:
        icon = '🟠'
    else:
        icon = '🟢'
    # Braille/box chars render cleaner in Telegram than block+shade when wrapped in <code>.
    bar_text = '▕' + '▰' * filled + '▱' * (width - filled) + '▏'
    return bar_text, f'{icon} {p:.1f}%'


def usage_block(label, emoji, used, total):
    b, p = meter(used, total)
    return f'{emoji} <b>{label}</b>  {p}\n<code>{b}</code>\n{fmt_bytes(used)} / {fmt_bytes(total)}'


def cpu_block(cpu, width=22):
    b, p = meter(float(cpu or 0), 100, width)
    return f'🧠 <b>CPU</b>  {p}\n<code>{b}</code>'


def fmt_duration(seconds):
    if seconds is None:
        return '-'
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f'{days}天 {hours}小时'
    if hours:
        return f'{hours}小时 {minutes}分'
    return f'{minutes}分'


def short_cpu_name(name):
    if not name:
        return '-'
    text = str(name).replace('(R)', '').replace('(TM)', '')
    text = ' '.join(text.split())
    return text[:58] + ('…' if len(text) > 58 else '')


IPV4_RE = re.compile(r'(?:^|\D)((?:\d{1,3}\.){3}\d{1,3})(?:\D|$)')
DOMAIN_RE = re.compile(r'^(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?(?:[/?#].*)?$')


def is_ipv4(value):
    m = IPV4_RE.search(str(value or ''))
    if not m:
        return False
    try:
        parts = [int(x) for x in m.group(1).split('.')]
        return len(parts) == 4 and all(0 <= x <= 255 for x in parts)
    except Exception:
        return False


def extract_ipv4(value):
    m = IPV4_RE.search(str(value or ''))
    return m.group(1) if m and is_ipv4(m.group(1)) else ''


def normalize_domain(value):
    text = str(value or '').strip()
    if not text or text.startswith('/'):
        return ''
    first = text.split()[0].strip()
    if extract_ipv4(first):
        return ''
    if not DOMAIN_RE.match(first):
        return ''
    parsed = urlparse(first if '://' in first else '//' + first)
    host = (parsed.hostname or '').strip().rstrip('.')
    return host if re.match(r'^[A-Za-z0-9.-]+$', host) else ''


def safe_target(value):
    text = str(value or '').strip()
    text = re.sub(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', '', text).split('/')[0].split('?')[0].replace(':', '_')
    text = re.sub(r'[^A-Za-z0-9_.-]+', '_', text).strip('_')
    return text or 'target'


def country_flag(code):
    code = (code or '').strip().upper()
    if code == 'TW':
        code = 'CN'
    if len(code) != 2 or not code.isalpha():
        return '🌐'
    return chr(0x1F1E6 + ord(code[0]) - ord('A')) + chr(0x1F1E6 + ord(code[1]) - ord('A'))


def kulin_api_request(path, *, timeout=4):
    if not (KULIN_USERNAME and KULIN_PASSWORD):
        return None
    if not KULIN_BASE_URL:
        return None
    base = KULIN_BASE_URL.rstrip('/')
    cookie = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(cookie)
    try:
        login_body = json.dumps({'username': KULIN_USERNAME, 'password': KULIN_PASSWORD}).encode()
        login_req = urllib.request.Request(
            base + '/api/v1/login',
            data=login_body,
            headers={'Content-Type': 'application/json', 'User-Agent': 'GUKO/1.0'},
        )
        with opener.open(login_req, timeout=timeout) as resp:
            json.loads(resp.read().decode(errors='replace') or '{}')
        req = urllib.request.Request(base + path, headers={'User-Agent': 'GUKO/1.0'})
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode(errors='replace') or '{}')
    except Exception:
        return None


def flatten_kulin_servers(payload):
    data = (payload or {}).get('data')
    if isinstance(data, dict):
        for key in ('servers', 'list', 'items', 'records'):
            if isinstance(data.get(key), list):
                return data.get(key)
    if isinstance(data, list):
        return data
    return []


def ip_from_kulin_host(item):
    if not isinstance(item, dict):
        return ''
    geoip = item.get('geoip')
    if isinstance(geoip, dict):
        geo_ip = geoip.get('ip')
        if isinstance(geo_ip, dict):
            found = extract_ipv4(geo_ip.get('ipv4_addr') or geo_ip.get('IP') or geo_ip.get('ip') or '')
            if found:
                return found
        found = extract_ipv4(geoip.get('ip') or geoip.get('ipv4') or '')
        if found:
            return found
    host = item.get('host')
    if isinstance(host, dict):
        return extract_ipv4(host.get('IP') or host.get('ip') or host.get('ipv4') or '')
    return extract_ipv4(item.get('ip') or item.get('ipv4') or item.get('host') or '')


def country_from_kulin_item(item):
    if not isinstance(item, dict):
        return ''
    geoip = item.get('geoip')
    candidates = []
    if isinstance(geoip, dict):
        candidates.extend([geoip.get('country_code'), geoip.get('country'), geoip.get('region')])
    candidates.extend([item.get('region'), item.get('country'), item.get('country_code')])
    host = item.get('host')
    if isinstance(host, dict):
        candidates.extend([host.get('CountryCode'), host.get('country_code'), host.get('country')])
    for val in candidates:
        text = str(val or '').strip().lower()
        if len(text) == 2 and text.isalpha():
            return text
    return ''


def kulin_geo_map():
    now = time.time()
    if now - float(KULIN_GEO_CACHE.get('ts') or 0) < KULIN_API_CACHE_TTL:
        return KULIN_GEO_CACHE.get('by_ip') or {}
    by_ip = {}
    payload = kulin_api_request('/api/v1/server')
    for item in flatten_kulin_servers(payload):
        ip = ip_from_kulin_host(item)
        code = country_from_kulin_item(item)
        if ip and code:
            by_ip[ip] = code
    KULIN_GEO_CACHE['ts'] = now
    KULIN_GEO_CACHE['by_ip'] = by_ip
    return by_ip


def geolocate_host(host, timeout=4):
    ip = extract_ipv4(host or '')
    if not ip:
        return None
    # Keep GUKO's country flags aligned with Kulin/Komari. Its panel writes
    # server.region from the currently configured GeoIP provider, so prefer
    # that over ad-hoc public web APIs.
    code = kulin_geo_map().get(ip)
    if code:
        return code
    providers = [
        (f'http://ip-api.com/json/{ip}?fields=status,countryCode,query,message', lambda d: d.get('countryCode') if d.get('status') == 'success' else None),
        (f'https://ipinfo.io/{ip}/json', lambda d: d.get('country')),
        (f'https://get.geojs.io/v1/ip/country/{ip}.json', lambda d: d.get('country')),
    ]
    for url, pick in providers:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GUKO/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode(errors='replace'))
            code = pick(data)
            if code:
                return str(code).lower()
        except Exception:
            continue
    return None


def enrich_server_geo(item):
    if item.get('country'):
        item['country'] = str(item.get('country')).lower()
        return item
    code = geolocate_host(item.get('host'))
    if code:
        item['country'] = code
    return item


ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
C0_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def strip_ansi(text):
    return ANSI_RE.sub('', text or '')


def strip_osc(text):
    text = text or ''
    parts = []
    start = 0
    i = 0
    while i < len(text):
        if text[i] != '\x1b' or i + 1 >= len(text) or text[i + 1] != ']':
            i += 1
            continue
        parts.append(text[start:i])
        i += 2
        while i < len(text):
            if text[i] == '\x07':
                i += 1
                break
            if text[i] == '\x1b' and i + 1 < len(text) and text[i + 1] == '\\':
                i += 2
                break
            i += 1
        start = i
    parts.append(text[start:])
    return ''.join(parts)


def tcpquality_text_output(text):
    clean = strip_osc(strip_ansi(text)).replace('\r', '\n')
    lines = []
    previous_blank = False
    for raw_line in clean.splitlines():
        line = C0_RE.sub('', raw_line).rstrip()
        if '探测进度' in line:
            continue
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        lines.append(line)
        previous_blank = is_blank
    return '\n'.join(lines).strip()


def safe(s):
    return html.escape(str(s)) if s is not None else '-'


def running_text(s, task):
    return f'正在运行中：{safe(s.get("name"))} {task}'


async def send_running_notice(bot, chat_id, s, task):
    await bot.send_message(chat_id, running_text(s, task), parse_mode=ParseMode.HTML)


async def bot_task_started_notice(bot, chat_id, s, task, started=True):
    if started:
        await bot.send_message(chat_id, running_text(s, task), parse_mode=ParseMode.HTML)
    else:
        await bot.send_message(chat_id, f'这个任务已经在运行中：{safe(s.get("name"))} {task}', parse_mode=ParseMode.HTML)


def is_valid_hostname(value):
    text = str(value or '').strip()
    if not text or len(text) > 253 or ' ' in text:
        return False
    if is_ipv4(text):
        return True
    return bool(re.match(r'^[A-Za-z0-9.-]+$', text) and '.' in text)


def parse_host_port(text):
    raw = str(text or '').strip()
    if not raw:
        return '', None
    if raw.count(':') == 1 and not raw.startswith('['):
        host, port = raw.rsplit(':', 1)
        if port.isdigit():
            return host.strip(), int(port)
    return raw, None


async def resolve_tool(jid, resolver, *args):
    source = await asyncio.to_thread(resolver, *args)
    JOBS[jid]['tool_source'] = source
    return source


def tool_source_html(item):
    source = item.get('tool_source') or {}
    if not source:
        return ''  # Old history has no proof: never label it with today's latest.
    version = source.get('version') or 'branch content (no release version)'
    commit = source.get('commit')
    label = version + (' · ' + commit if commit else '')
    offer = source.get('source_offer')
    return ('来源：' + safe(label) + (' · <a href="' + safe(offer) + '">对应源码/官方来源</a>' if offer else ''))


def stream_source_offer(job):
    return tool_source_html(job) + '\nGUKO对应源：https://github.com/shui1iao/GUKO/releases/download/v0.7.3/guko-v0.7.3-source.zip'


def source_repo(kind):
    return SCRIPT_SOURCES.get(kind, ('', ''))[1]


def _script_command_text(kind, **kwargs):
    if kind == 'nexttrace':
        target = kwargs.get('target') or '<目标IP或域名>'
        return (
            '脚本命令：\n'
            '任务临时目录程序（实际版本见本任务来源，不改全局安装）\n'
            f'nexttrace {target}'
        )
    if kind == 'stream':
        mode = str(kwargs.get('ip_mode') or 'auto')
        if mode not in {'auto', '4', '6'}:
            raise ValueError('unsupported extra family')
        return ('脚本命令（Service Unlock，每任务官方latest，经SSH校验上传）：\n'
                f'service-unlock --machine --extra-family {mode} --timeout 6 --workers 4')
    if kind == 'ipq':
        suffix = ' -4' if kwargs.get('ip_mode', '4') == '4' else ''
        return '脚本命令：\nbash <(curl -Ls https://IP.Check.Place) -y' + suffix
    if kind in PROXY_TOOLS:
        tool = PROXY_TOOLS[kind]
        action = kwargs.get('action') or 'ensure'
        if action == 'view':
            return 'GUKO 只读配置：直接解析目标服务器现有文件，不调用管理脚本、不写配置。'
        arg = tool['install_arg']
        if kind in kat_proxy.KINDS:
            return 'Kat只读发现全部实例；仅另行明确确认新安装时调用同commit Kat-Manager install ' + kind
        return f"原管理脚本（仅未安装时调用；已有节点只读）：\nbash <(curl -Ls {tool['script_url']}) {arg}"
    if kind == 'nq':
        selected = kwargs.get('selected')
        ip_mode = kwargs.get('ip_mode')
        extra = ''
        if selected or ip_mode:
            extra = f'\n选择：{selected or "-"}；{ip_mode or "-"}'
        return '脚本命令：\nbash <(curl -sL https://run.NodeQuality.com)' + extra
    if kind == 'tcpq':
        mode = tcpquality_mode(kwargs.get('mode') or 'v4')
        args = ' '.join(mode['args'])
        return (
            '脚本命令：\n'
            '任务冻结的同commit wrapper/core（历史版本以原来源记录为准）\n'
            f'bash runTcpQuality.sh --no-rootfs {args}'
        )
    return ''


def script_command_text(kind, **kwargs):
    text = _script_command_text(kind, **kwargs)
    source = kwargs.get('source') or {}
    if source:
        version = source.get('version') or 'branch content (no release version)'
        if source.get('commit'):
            version += ' · ' + source['commit']
        text += '\n本次来源：' + version + '\n' + (source.get('source_offer') or '')
    return text


def script_command_html(kind, **kwargs):
    return safe(script_command_text(kind, **kwargs))


def find_server(name: str, servers: Iterable[dict]):
    q = name.lower()
    for s in servers:
        fields = [s.get('name'), s.get('host'), str(server_id(s))]
        fields += s.get('aliases') or []
        if any((f or '').lower() == q for f in fields):
            return s
    for s in servers:
        fields = [s.get('name'), s.get('host')] + (s.get('aliases') or [])
        if any(q in (f or '').lower() for f in fields):
            return s
    return None


def find_server_by_id(sid: str):
    return find_server(sid, load_inventory().get('servers', []))


def server_button_label(s):
    return f"{country_flag(s.get('country'))} {s.get('name')}"


def main_menu_markup():
    servers = load_inventory().get('servers', [])
    rows = []
    for i in range(0, len(servers), 2):
        rows.append([
            InlineKeyboardButton(server_button_label(s), callback_data=f"srv:{server_id(s)}")
            for s in servers[i:i+2]
        ])
    rows.append([
        InlineKeyboardButton('➕ 添加服务器', callback_data='add:start'),
        InlineKeyboardButton('📥 批量导入', callback_data='add:bulk'),
    ])
    rows.append([InlineKeyboardButton('↕️ 调整顺序', callback_data='sort:list')])
    return InlineKeyboardMarkup(rows)


def server_sort_markup(servers):
    rows = []
    last = len(servers) - 1
    for index, server in enumerate(servers):
        sid = server_id(server)
        rows.append([
            InlineKeyboardButton(f'{index + 1}. {server.get("name") or sid}', callback_data='sort:stay'),
            InlineKeyboardButton('⬆️', callback_data=f'sort:up:{sid}' if index > 0 else 'sort:stay'),
            InlineKeyboardButton('⬇️', callback_data=f'sort:down:{sid}' if index < last else 'sort:stay'),
        ])
    rows.append([InlineKeyboardButton('↩️ 返回服务器列表', callback_data='act:list')])
    return InlineKeyboardMarkup(rows)


def server_has_ipv6(s):
    return bool(s.get('ipv6') and str(s.get('ipv6')).strip() not in ('-', 'None'))


def add_start_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➕ 添加单台', callback_data='add:one')],
        [InlineKeyboardButton('📥 批量导入', callback_data='add:bulk')],
        [InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')],
    ])


def add_auth_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('♻️ 沿用默认密钥/配置', callback_data='addauth:default')],
        [InlineKeyboardButton('📁 使用已有密钥路径', callback_data='addauth:keypath')],
        [InlineKeyboardButton('🔑 上传/粘贴新私钥', callback_data='addauth:key')],
        [InlineKeyboardButton('🔐 使用密码', callback_data='addauth:password')],
        [InlineKeyboardButton('📦 先只保存，不测试登录', callback_data='addauth:skip')],
        [InlineKeyboardButton('❌ 取消', callback_data='add:cancel')],
    ])


def bulk_mode_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ 全部同一个端口', callback_data='bulkport:same')],
        [InlineKeyboardButton('🧩 每台自己写端口', callback_data='bulkport:per')],
        [InlineKeyboardButton('❌ 取消', callback_data='add:cancel')],
    ])


def bulk_auth_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔑 全部同一把密钥', callback_data='bulkauth:key')],
        [InlineKeyboardButton('🔐 全部同一个密码', callback_data='bulkauth:password')],
        [InlineKeyboardButton('🧩 每台自己写认证', callback_data='bulkauth:per')],
        [InlineKeyboardButton('📦 先只导入，不测试登录', callback_data='bulkauth:skip')],
        [InlineKeyboardButton('❌ 取消', callback_data='add:cancel')],
    ])


def add_help_text():
    return (
        '➕ <b>添加服务器</b>\n\n'
        '可以单台添加，也可以批量导入。\n'
        '支持：不同端口、不同用户名、沿用默认密钥、已有密钥路径、上传私钥、密码登录。'
    )


def bulk_help_text():
    return (
        '📥 <b>批量导入服务器</b>\n\n'
        '先选端口策略，再选认证策略。\n\n'
        '每行格式：\n'
        '<code>名称 IP 用户</code>\n'
        '<code>名称 IP:端口 用户</code>\n\n'
        '如果选择“每台自己写认证”，每行可以写：\n'
        '<code>名称 IP 端口 用户 key:/data/keys/a</code>\n'
        '<code>名称 IP 端口 用户 password:你的密码</code>'
    )


def tool_enabled(name):
    val = os.environ.get(f'ENABLE_{name.upper()}', 'true').strip().lower()
    return val in ('1', 'true', 'yes', 'on')



def button_rows(buttons, per_row=2):
    return [buttons[i:i+per_row] for i in range(0, len(buttons), per_row)]


def server_markup(s):
    sid = server_id(s)
    host = s.get('host') or ''
    rows = []
    if host:
        rows.append([InlineKeyboardButton('📋 复制 IPv4', copy_text=CopyTextButton(host))])
    if s.get('ipv6'):
        rows.append([InlineKeyboardButton('📋 复制 IPv6', copy_text=CopyTextButton(s.get('ipv6')))])

    test_buttons = []
    if tool_enabled('ipq'):
        test_buttons.append(InlineKeyboardButton('🧪 IP质量', callback_data=f'ipq:{sid}'))
    if tool_enabled('nq'):
        test_buttons.append(InlineKeyboardButton('📊 NodeQuality', callback_data=f'nqask:{sid}'))
    if tool_enabled('tcpq'):
        test_buttons.append(InlineKeyboardButton('📡 TCPQuality', callback_data=f'tqask:{sid}'))
    if tool_enabled('gb5'):
        test_buttons.append(InlineKeyboardButton('🏁 GB5', callback_data=f'gb5:{sid}'))
    if tool_enabled('stream'):
        test_buttons.append(InlineKeyboardButton('🎬 流媒体', callback_data=f'stream:{sid}'))
    if tool_enabled('bgp'):
        test_buttons.append(InlineKeyboardButton('🧭 BGP图', callback_data=f'bgp:{sid}'))
    if tool_enabled('ippure'):
        test_buttons.append(InlineKeyboardButton('🧼 IPPure', callback_data=f'ippure:{sid}'))
    if tool_enabled('ss'):
        test_buttons.append(InlineKeyboardButton(PROXY_TOOLS['ss']['button'], callback_data=f'proxy:ss:{sid}'))
    if tool_enabled('anytls'):
        test_buttons.append(InlineKeyboardButton(PROXY_TOOLS['anytls']['button'], callback_data=f'proxy:anytls:{sid}'))
    if tool_enabled('snell'):
        test_buttons.append(InlineKeyboardButton(PROXY_TOOLS['snell']['button'], callback_data=f'proxy:snell:{sid}'))
    rows.extend(button_rows(test_buttons, 2))

    ops_buttons = [
        InlineKeyboardButton('📋 当前任务', callback_data=f'jobsrv:{sid}'),
        InlineKeyboardButton('📜 历史记录', callback_data=f'hist:{sid}'),
        InlineKeyboardButton('🧪 测试SSH', callback_data=f'testssh:{sid}'),
    ]
    if tool_enabled('nexttrace'):
        ops_buttons.append(InlineKeyboardButton('🛣 NextTrace', callback_data=f'ntask:{sid}'))
    rows.extend(button_rows(ops_buttons, 2))
    rows.extend([
        [InlineKeyboardButton('✏️ 编辑', callback_data=f'edit:{sid}'), InlineKeyboardButton('🗑 删除', callback_data=f'delask:{sid}')],
        [InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')],
    ])
    return InlineKeyboardMarkup(rows)


NQ_ITEMS = [
    ('hardware', '硬件', 'HardwareQuality', 1),
    ('ip', 'IP质量', 'IPQuality', 2),
    ('net', '网络', 'NetQuality', 4),
    ('backroute', '回程', 'Backroute Trace', 8),
]
NQ_ALL_MASK = sum(x[3] for x in NQ_ITEMS)
NQ_DEFAULT_MASK = 0
NQ_IP_MODES = {'4': '仅 IPv4', '46': 'IPv4 + IPv6'}

TCPQUALITY_MODES = {
    'v4': {
        'label': '三网质量 · IPv4',
        'args': ('-v4',),
        'sections': ('ipv4',),
        'family': 'v4',
        'report_required': True,
    },
    'v6': {
        'label': '三网质量 · IPv6',
        'args': ('-v6',),
        'sections': ('ipv6',),
        'family': 'v6',
        'report_required': True,
    },
    'intl-v4': {
        'label': '国际互联',
        'args': ('--intl',),
        'sections': ('intl',),
        'family': 'v4',
        'report_required': True,
    },
    'route-v4': {
        'label': '回程线路 · IPv4',
        'args': ('--route', '-v4'),
        'sections': (),
        'family': 'v4',
        'report_required': False,
    },
    'route-v6': {
        'label': '回程线路 · IPv6',
        'args': ('--route', '-v6'),
        'sections': (),
        'family': 'v6',
        'report_required': False,
    },
    'speedtest': {
        'label': '三网测速',
        'args': ('--only-speedtest',),
        'sections': ('speedtest',),
        'family': 'v4',
        'report_required': True,
    },
    'all': {
        'label': '完整检测',
        'args': ('-v4', '-v6', '--intl', '--speedtest'),
        'sections': ('ipv4', 'ipv6', 'intl', 'speedtest'),
        'family': 'both',
        'report_required': True,
    },
}

TCPQUALITY_CATEGORIES = {
    'full': {
        'label': '三网质量',
        'description': '检测全国三网节点的 TCP 延迟、重传和回程线路。',
        'modes': ('v4', 'v6'),
    },
    # Keep the old callback valid for TCPQuality menus already sent to Telegram.
    'intl': {
        'label': '国际互联',
        'description': '检测常用网站和 CDN 的国际互联；上游当前使用 IPv4。',
        'modes': ('intl-v4',),
    },
    'route': {
        'label': '回程线路',
        'description': '只识别三网回程，不做 nping 丢包探测，也不会生成公开报告链接。',
        'modes': ('route-v4', 'route-v6'),
    },
    'speedtest': {
        'label': '三网测速',
        'description': '运行国内三网单线程测速，会消耗较多流量。',
        'modes': ('speedtest',),
        'start_label': '🚀 开始三网测速',
    },
    'complete': {
        'label': '完整检测',
        'description': '运行三网 IPv4 / IPv6、国际互联和三网测速，耗时较长并会消耗较多流量。',
        'modes': ('all',),
        'start_label': '🧪 开始完整检测',
    },
}


def tcpquality_mode(mode):
    key = str(mode or '').strip().lower()
    if key not in TCPQUALITY_MODES:
        raise ValueError(f'未知 TCPQuality 模式：{mode}')
    return TCPQUALITY_MODES[key]


def tcpquality_category(category):
    key = str(category or '').strip().lower()
    if key not in TCPQUALITY_CATEGORIES:
        raise ValueError(f'未知 TCPQuality 检测项目：{category}')
    return TCPQUALITY_CATEGORIES[key]


def tcpquality_markup(s):
    sid = server_id(s)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('📡 三网质量', callback_data=f'tqmode:{sid}:full'),
            InlineKeyboardButton('🧭 回程线路', callback_data=f'tqmode:{sid}:route'),
        ],
        [
            InlineKeyboardButton('🌍 国际互联', callback_data=f'tqrun:{sid}:intl-v4'),
            InlineKeyboardButton('🚀 三网测速', callback_data=f'tqmode:{sid}:speedtest'),
        ],
        [InlineKeyboardButton('🧪 完整检测', callback_data=f'tqmode:{sid}:complete')],
        [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
    ])


def tcpquality_family_markup(s, category):
    sid = server_id(s)
    config = tcpquality_category(category)
    rows = []
    for mode in config['modes']:
        mode_config = tcpquality_mode(mode)
        if mode_config['family'] == 'v6' and not server_has_ipv6(s):
            continue
        button_label = config.get('start_label')
        if not button_label:
            button_label = 'IPv6' if mode_config['family'] == 'v6' else 'IPv4'
        rows.append([InlineKeyboardButton(button_label, callback_data=f'tqrun:{sid}:{mode}')])
    rows.append([InlineKeyboardButton('↩️ 返回 TCPQuality', callback_data=f'tqask:{sid}')])
    return InlineKeyboardMarkup(rows)


def tcpquality_menu_text(s):
    ipv6_note = '三网质量和回程线路可选 IPv4 / IPv6。' if server_has_ipv6(s) else '当前未配置 IPv6，协议族选项只显示 IPv4。'
    return (
        f'📡 <b>{safe(s.get("name"))} · TCPQuality</b>\n\n'
        '选择检测项目。完整检测包含三网 IPv4 / IPv6、国际互联和三网测速。\n\n'
        f'{safe(ipv6_note)}\n'
        '除回程线路外，结果会生成 tcpquality.ibsgss.uk 公开报告。'
    )


def tcpquality_family_menu_text(s, category):
    config = tcpquality_category(category)
    family_note = '请选择 IPv4 或 IPv6。'
    if category == 'intl':
        family_note = '国际互联按上游能力使用 IPv4。'
    elif config.get('start_label'):
        family_note = '确认后开始执行。'
    elif not server_has_ipv6(s):
        family_note = '这台服务器未配置 IPv6，只能选择 IPv4。'
    return (
        f'📡 <b>{safe(s.get("name"))} · {safe(config["label"])}</b>\n\n'
        f'{safe(config["description"])}\n{safe(family_note)}'
    )


def tcpquality_remote_command(mode, source):
    config = tcpquality_mode(mode)
    args = ' '.join(shlex.quote(arg) for arg in config['args'])
    downloads = ''.join(tool_sources.shell_download(source['files'][name], '"$bundle/' + name + '"')
                        for name in ('runTcpQuality.sh', 'runTcpQuality-core.sh'))
    return (
        "set -eu; export TERM=xterm-256color; cd /tmp; "
        "bundle=$(mktemp -d /tmp/tcpquality.XXXXXX); "
        'cleanup() { rm -rf "$bundle"; }; '
        "trap cleanup EXIT; trap 'exit 130' HUP INT TERM; "
        + downloads + 'chmod 700 "$bundle/runTcpQuality.sh" "$bundle/runTcpQuality-core.sh"; '
        + 'timeout 20 bash "$bundle/runTcpQuality.sh" --rootfs-help >"$bundle/help" 2>&1 || exit 65; '
        + 'grep -Fq -- --no-rootfs "$bundle/help" || { echo "GUKO: TCP no-rootfs interface unavailable"; exit 65; }; '
        + 'timeout 20 bash "$bundle/runTcpQuality-core.sh" '+args+' --help >"$bundle/help" 2>&1 || { echo "GUKO: TCP arguments unsupported"; exit 65; }; '
        + 'TCPQUALITY_RAW_BASE=' + shlex.quote(source['raw_base']) + ' '
        + 'bash "$bundle/runTcpQuality.sh" --no-rootfs ' + args
    )


IPV6_UNCHECKED = (False, '尚未确认 IPv6 可用，仅可测试 IPv4。')
IPV6_PROBE_COMMAND = r'''if [ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null)" = 1 ]; then
printf 'GUKO_IPV6=disabled\n'; exit 0; fi
if command -v ip >/dev/null 2>&1; then
if ! addresses=$(ip -6 -o addr show scope global 2>/dev/null); then
printf 'GUKO_IPV6=unknown\n'; exit 0; fi
if [ -z "$addresses" ]; then printf 'GUKO_IPV6=no-address\n'; exit 0; fi
fi
if ! command -v curl >/dev/null 2>&1; then printf 'GUKO_IPV6=no-curl\n'; exit 0; fi
for u in https://api64.ipify.org https://ipv6.icanhazip.com; do
v=$(curl --noproxy '*' -6 -fsS --connect-timeout 2 --max-time 4 "$u" 2>/dev/null) || continue
case "$v" in *[!0-9a-fA-F:]*|'') continue;; *:*) printf 'GUKO_IPV6=%s\n' "$v"; exit 0;; esac
done
printf 'GUKO_IPV6=unknown\n'
'''


def stored_ipv6_status(s):
    record = s.get('ipv6_status') or {}
    if record.get('available') in (True, False):
        return bool(record['available']), record.get('reason') or '已记录 IPv6 状态。'
    # Preserve legacy discovered addresses until the next real test refreshes them.
    if server_has_ipv6(s):
        return True, '已记录 IPv6，实际测试时更新状态。'
    return IPV6_UNCHECKED


def ssh_endpoint(s):
    cfg = ssh_config(s)
    return cfg.get('host'), cfg.get('port')


def update_ipv6_from_output(s, output, *, expected_endpoint=None):
    values = re.findall(r'^GUKO_IPV6=([^\r\n]+)', output, re.M)
    if not values:
        return None  # SSH/timeout without evidence must not erase known addresses.
    value = values[-1].strip()
    reasons = {
        'disabled': '系统已禁用 IPv6，仅可测试 IPv4。',
        'no-address': '未检测到全局 IPv6 地址，仅可测试 IPv4。',
    }
    if value in reasons:
        available, address, reason = False, '', reasons[value]
    else:
        try:
            ip = ipaddress.IPv6Address(value)
        except ValueError:
            return None
        if not ip.is_global:
            return None
        available, address, reason = True, str(ip), '已记录 IPv6 可用，实际测试时更新状态。'
    # Reload only the matching endpoint; don't overwrite a retargeted/deleted node.
    current = find_server_by_id(server_id(s))
    if (not current or current.get('host') != s.get('host')
            or ssh_endpoint(current) != (expected_endpoint or ssh_endpoint(s))):
        return None
    patch = {'ipv6': address, 'ipv6_status': {
        'available': available, 'reason': reason, 'checked_at': iso_now(),
    }}
    updated = update_server_by_id(server_id(s), patch)
    if updated is None:
        return None
    s.update(patch)
    return available, reason


async def detect_server_ipv6(s):
    """One initial detection when adding/importing, never from menu callbacks."""
    try:
        endpoint = ssh_endpoint(s)
        code, out = await run_subprocess(ssh_args(s, IPV6_PROBE_COMMAND, tty=False),
                                         timeout=20, env=ssh_env_for(s))
        if code == 0:
            status = update_ipv6_from_output(s, out, expected_endpoint=endpoint)
            if status is not None:
                return status
    except Exception:
        pass
    return False, 'IPv6 状态未确认；实际测试时更新，不影响已保存的服务器。'


def ipquality_markup(s, ip_mode='4', ipv6_status=IPV6_UNCHECKED):
    if not ipv6_status[0]:
        ip_mode = '4'
    sid = server_id(s)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(('✅ ' if mode == ip_mode else '☐ ') + label,
                              callback_data=f'ipqproto:{sid}:{mode}')
         for mode, label in NQ_IP_MODES.items() if mode == '4' or ipv6_status[0]],
        [InlineKeyboardButton('✅ 开始测试', callback_data=f'ipqrun:{sid}:{ip_mode}')],
        [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
    ])


def ipquality_menu_text(s, ip_mode='4', ipv6_status=IPV6_UNCHECKED):
    if not ipv6_status[0]:
        ip_mode = '4'
    return (
        f'🧪 <b>{safe(s.get("name"))} · IP质量</b>\n\n'
        f'IP 协议：<b>{safe(nq_ip_mode_text(ip_mode))}</b>\n\n'
        '选择 IPv4 + IPv6 时，会等待两种协议检测结束并分别返回报告。\n'
        f'{safe(ipv6_status[1])}'
    )


def ipquality_remote_command(ip_mode='4', *, source):
    if ip_mode not in NQ_IP_MODES:
        raise ValueError('未知 IP质量协议选项')
    suffix = ' -4' if ip_mode == '4' else ''
    return (
        'export TERM=xterm-256color; cd /tmp || exit; '
        'script=$(mktemp /tmp/guko-ipquality.XXXXXX.sh) || exit; '
        'trap \'rm -f -- "$script"\' EXIT; '
        + tool_sources.shell_download(source, '"$script"')
        + 'bash "$script" -y' + suffix
    )


def confirm_nq_markup(s, mask=NQ_DEFAULT_MASK, ip_mode='4', ipv6_status=IPV6_UNCHECKED):
    if not ipv6_status[0]:
        ip_mode = '4'
    sid = server_id(s)
    rows = []
    for _key, label, _full, bit in NQ_ITEMS:
        mark = '✅' if mask & bit else '☐'
        new_mask = mask & ~bit if mask & bit else mask | bit
        rows.append([InlineKeyboardButton(f'{mark} {label}', callback_data=f'nqtoggle:{sid}:{new_mask}:{ip_mode}')])
    rows.append([
        InlineKeyboardButton('全选', callback_data=f'nqsel:{sid}:{NQ_ALL_MASK}:{ip_mode}'),
        InlineKeyboardButton('清空', callback_data=f'nqsel:{sid}:0:{ip_mode}'),
    ])
    rows.append([InlineKeyboardButton(('✅ ' if ip_mode == mode else '☐ ') + label,
                                      callback_data=f'nqproto:{sid}:{mask}:{mode}')
                 for mode, label in NQ_IP_MODES.items() if mode == '4' or ipv6_status[0]])
    run_text = '✅ 开始测试' if mask != NQ_ALL_MASK else '✅ 开始全测'
    rows.append([InlineKeyboardButton(run_text, callback_data=f'nqrun:{sid}:{mask}:{ip_mode}')])
    rows.append([InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')])
    return InlineKeyboardMarkup(rows)


def nq_selected(mask):
    return [item for item in NQ_ITEMS if mask & item[3]]


def nq_selected_text(mask):
    items = nq_selected(mask)
    if not items:
        return '未选择'
    return ' / '.join(item[2] for item in items)


def nq_ip_mode_text(ip_mode):
    return NQ_IP_MODES.get(str(ip_mode), NQ_IP_MODES['4'])


def nq_answer_script(mask):
    return ''.join(('y\n' if mask & bit else 'n\n') for _key, _label, _full, bit in NQ_ITEMS)


def nq_remote_ipv_arg(s, ip_mode):
    # Let upstream detect live IPv6; inventory metadata may be absent or stale.
    return '' if ip_mode == '46' else '-4'


def validate_nodequality_work_dir(work_dir):
    if not isinstance(work_dir, str) or not re.fullmatch(r'/root/guko-nodequality-[0-9a-f]{32}', work_dir):
        raise ValueError('不合法的本次 NodeQuality 日志目录')
    return work_dir


def nodequality_remote_command(s, mask=NQ_ALL_MASK, ip_mode='4', *, work_dir=None, source):
    # This path is generated by the task, never parsed from remote stdout.
    # Official -d nests its timestamp directory here; preserve only four logs
    # before upstream removes BenchOs. Never search old .nodequality directories.
    log_setup = log_patch = dir_arg = ''
    if work_dir is not None:
        validate_nodequality_work_dir(work_dir)
        quoted = shlex.quote(work_dir)
        log_setup = f'umask 077; mkdir -m 700 -- {quoted}; '
        dir_arg = ' -d ' + quoted
    answers = nq_answer_script(mask)
    ipv_arg = nq_remote_ipv_arg(s, ip_mode)
    ensure_curl = (
        "if ! command -v curl >/dev/null 2>&1; then "
        "if command -v apt-get >/dev/null 2>&1; then "
        "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq curl ca-certificates; "
        "elif command -v apk >/dev/null 2>&1; then apk add --no-cache curl ca-certificates; "
        "elif command -v dnf >/dev/null 2>&1; then dnf install -y curl ca-certificates; "
        "elif command -v yum >/dev/null 2>&1; then yum install -y curl ca-certificates; "
        "else echo 'GUKO: NodeQuality requires curl and no supported package manager was found' >&2; exit 127; fi; "
        "fi; "
    )
    return (
        "set -e; export TERM=xterm-256color; cd /root; "
        + ensure_curl
        + log_setup
        + "script=$(mktemp /root/nodequality.XXXXXX.sh); "
        + "trap 'rm -f -- \"$script\"' EXIT; "
        + tool_sources.shell_download(source, '"$script"')
        + "printf %b " + shlex.quote(answers) + " | bash \"$script\" " + ipv_arg + dir_arg
    )






def stream_menu_text(s):
    return (
        f'🎬 准备在 <b>{safe(s.get("name"))}</b> 跑流媒体检测：\n\n'
        '按实际出口自动识别地区，检测全球＋对应当地服务；识别失败仅检测全球。\n'
        '一份单框分区报告、一张图；原34项系统选族，新增项自动选择可用地址族。\n'
        'Unknown表示证据不足或安全限制；可达不等于播放、登录或实际注册成功。'
    )


def stream_markup(s):
    sid = server_id(s)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ 开始流媒体检测', callback_data=f'streamrun:{sid}')],
        [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
    ])


def nq_menu_text(s, mask, ip_mode, ipv6_status=IPV6_UNCHECKED):
    if not ipv6_status[0]:
        ip_mode = '4'
    return (
        f'📊 选择要在 <b>{safe(s.get("name"))}</b> 跑的 NodeQuality 项目：\n\n'
        f'当前项目：<b>{safe(nq_selected_text(mask))}</b>\n'
        f'IP 协议：<b>{safe(nq_ip_mode_text(ip_mode))}</b>\n\n'
        '点击项目进行选择/取消；全选就是完整 NodeQuality。\n'
        f'{safe(ipv6_status[1])}'
    )

def menu_text():
    d = load_inventory()
    servers = d.get('servers', [])
    return (
        f'<b>GUKO</b> <code>v{safe(GUKO_VERSION)}</code>\n'
        f'服务器 <b>{len(servers)}</b> 台\n\n'
        '👇 点服务器打开操作面板。'
    )


def server_detail_text(s):
    name = safe(s.get('name'))
    title = f"{country_flag(s.get('country'))} <b>{name}</b>"
    cfg = ssh_config(s)
    lines = [
        title,
        f"<code>{safe(cfg.get('host'))}</code> · SSH <code>{safe(cfg.get('port'))}</code> · <code>{safe(cfg.get('user'))}</code>",
    ]
    ipv6 = s.get('ipv6')
    if ipv6 and str(ipv6).strip() not in ('-', 'None'):
        lines.append(f"IPv6 <code>{safe(ipv6)}</code>")
    return '\n'.join(lines)


def ssh_env_for(s):
    cfg = ssh_config(s)
    if cfg.get('auth') == 'password' and cfg.get('password'):
        env = os.environ.copy()
        env['SSHPASS'] = str(cfg['password'])
        return env
    return None


async def run_cmd(args, timeout=60, env=None):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, '命令超时'
    return proc.returncode, out.decode(errors='replace')


def ssh_args(s, remote, *, tty=False):
    return build_ssh_args(s, remote, tty=tty, inv=load_inventory())


async def test_server_login(s, timeout=15):
    try:
        code, out = await run_cmd(ssh_args(s, 'printf "ok:"; hostname', tty=False), timeout=timeout, env=ssh_env_for(s))
        return code == 0, strip_ansi(out).strip()
    except FileNotFoundError as e:
        return False, f'缺少依赖：{e}'
    except Exception as e:
        return False, str(e)


def server_specs_remote_script():
    return r'''
set -eu
cores=$(nproc 2>/dev/null || true)
mem_bytes=$(awk '/MemTotal:/ {print $2 * 1024; exit}' /proc/meminfo 2>/dev/null || true)
disk_bytes=''
if command -v lsblk >/dev/null 2>&1; then
  disk_bytes=$(lsblk -bdn -o SIZE,TYPE 2>/dev/null | awk '$2 == "disk" {sum += $1} END {if (sum > 0) printf "%.0f", sum}')
fi
[ -n "$disk_bytes" ] || disk_bytes=$(df -B1 / 2>/dev/null | awk 'NR==2 {printf "%.0f", $2}')
printf 'CPU=%s\nMEM_BYTES=%s\nDISK_BYTES=%s\n' "$cores" "$mem_bytes" "$disk_bytes"
'''


def fmt_capacity_2(value):
    try:
        n = float(value)
    except Exception:
        return ''
    if n <= 0:
        return ''
    gb = n / 1000 / 1000 / 1000
    if gb < 1:
        return f'{n / 1000 / 1000:.2f}MB'
    return f'{gb:.2f}GB'


def format_server_specs(specs):
    if not isinstance(specs, dict):
        return ''
    parts = []
    cores = specs.get('cpu_cores')
    if cores not in (None, ''):
        try:
            cores_text = str(int(float(cores)))
        except Exception:
            cores_text = str(cores)
        parts.append(f'🧠 {safe(cores_text)} Cores')
    mem = fmt_capacity_2(specs.get('mem_bytes'))
    if mem:
        parts.append(f'💾 {safe(mem)} 内存')
    disk = fmt_capacity_2(specs.get('disk_bytes'))
    if disk:
        parts.append(f'🗄️ {safe(disk)} 硬盘')
    return ' · '.join(parts)


def cache_server_specs(s, specs):
    if not isinstance(specs, dict) or not specs:
        return None
    payload = dict(specs)
    payload['cached_at'] = iso_now()
    return update_server_by_id(str(server_id(s)), {'specs': payload})


async def read_server_specs(s, timeout=8):
    try:
        code, out = await run_cmd(ssh_args(s, server_specs_remote_script(), tty=False), timeout=timeout, env=ssh_env_for(s))
        if code != 0:
            return None
        vals = {}
        for raw in strip_ansi(out).splitlines():
            if '=' in raw:
                k, v = raw.split('=', 1)
                vals[k.strip()] = v.strip()
        specs = {
            'cpu_cores': vals.get('CPU') or '',
            'mem_bytes': vals.get('MEM_BYTES') or '',
            'disk_bytes': vals.get('DISK_BYTES') or '',
        }
        if not any(specs.values()):
            return None
        cache_server_specs(s, specs)
        return specs
    except Exception:
        return None


async def server_detail_text_with_specs(s):
    text = server_detail_text(s)
    specs_text = format_server_specs(s.get('specs'))
    if not specs_text:
        specs = await read_server_specs(s)
        specs_text = format_server_specs(specs)
    if specs_text:
        text += '\n' + specs_text
    return text


def build_server_item(name, host, user, port, auth_kind=None, password=None, key=None):
    item = {
        'name': name,
        'host': host,
        'role': 'manual',
        'source': 'local-manual',
        'ssh': {
            'user': user or 'root',
            'port': int(port or 22),
        },
    }
    if auth_kind == 'password':
        item['ssh']['auth'] = 'password'
        item['ssh']['password'] = password or ''
    elif auth_kind == 'key':
        item['ssh']['auth'] = 'key'
        item['ssh']['key'] = key or ''
    elif auth_kind == 'default':
        item['ssh']['auth'] = 'key'
    return enrich_server_geo(item)


def parse_bulk_lines(text, *, same_port=None, auth_mode='skip', shared_auth=None):
    items = []
    errors = []
    for lineno, raw in enumerate((text or '').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        try:
            parts = shlex.split(line)
        except Exception as e:
            errors.append(f'第 {lineno} 行解析失败：{e}')
            continue
        if len(parts) < 2:
            errors.append(f'第 {lineno} 行字段太少')
            continue
        name = parts[0]
        host, embedded_port = parse_host_port(parts[1])
        idx = 2
        port = same_port or embedded_port
        if port is None and idx < len(parts) and parts[idx].isdigit():
            port = int(parts[idx]); idx += 1
        user = 'root'
        if idx < len(parts) and not parts[idx].startswith(('key:', 'password:', 'auth:')):
            user = parts[idx]; idx += 1
        if not port:
            port = 22
        if not is_valid_hostname(host):
            errors.append(f'第 {lineno} 行 IP/域名不正确：{host}')
            continue
        auth_kind = None
        password = None
        key = None
        if auth_mode == 'key':
            auth_kind, key = 'key', shared_auth
        elif auth_mode == 'password':
            auth_kind, password = 'password', shared_auth
        elif auth_mode == 'per':
            for token in parts[idx:]:
                if token.startswith('key:'):
                    auth_kind, key = 'key', token[4:]
                elif token.startswith('password:'):
                    auth_kind, password = 'password', token[9:]
            if not auth_kind:
                errors.append(f'第 {lineno} 行缺少 key: 或 password:')
                continue
        item = build_server_item(name, host, user, port, auth_kind, password, key)
        items.append(item)
    return items, errors


def save_private_key(chat_id, content, filename='id_key'):
    text = content.decode(errors='replace') if isinstance(content, bytes) else str(content or '')
    if 'PRIVATE KEY' not in text:
        raise ValueError('没有识别到 PRIVATE KEY 内容')
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = safe_target(filename).replace('.', '_')[:40] or 'id_key'
    path = KEYS_DIR / f'{chat_id}-{int(time.time())}-{safe_name}.pem'
    path.write_text(text.strip() + '\n')
    os.chmod(path, 0o600)
    return str(path)


def edit_markup(s):
    sid = server_id(s)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('改名称', callback_data=f'editfield:{sid}:name'), InlineKeyboardButton('改主机/IP', callback_data=f'editfield:{sid}:host')],
        [InlineKeyboardButton('改端口', callback_data=f'editfield:{sid}:port'), InlineKeyboardButton('改用户', callback_data=f'editfield:{sid}:user')],
        [InlineKeyboardButton('改密钥路径', callback_data=f'editfield:{sid}:key'), InlineKeyboardButton('改密码', callback_data=f'editfield:{sid}:password')],
        [InlineKeyboardButton('改为默认密钥', callback_data=f'editdefault:{sid}')],
        [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
    ])


def add_session(chat_id, **data):
    cur = ADD_SESSIONS.setdefault(chat_id, {})
    cur.update(data)
    return cur


def clear_add_session(chat_id):
    ADD_SESSIONS.pop(chat_id, None)


async def finish_single_add(update: Update, context: ContextTypes.DEFAULT_TYPE, sess: dict):
    item = build_server_item(
        sess.get('name'), sess.get('host'), sess.get('user') or 'root', sess.get('port') or 22,
        sess.get('auth_kind'), sess.get('password'), sess.get('key'),
    )
    saved, action = upsert_server(item)
    ok_text = '未测试登录'
    if sess.get('auth_kind') in ('key', 'password', 'default'):
        ok, out = await test_server_login(saved)
        ok_text = ('✅ 登录成功：' if ok else '⚠️ 已保存，但登录测试失败：') + safe(out[-800:])
    _ipv6_ok, ipv6_reason = await detect_server_ipv6(saved)
    ok_text += '\n' + safe(ipv6_reason)
    clear_add_session(update.effective_chat.id)
    verb = '更新' if action == 'updated' else '添加'
    cfg = ssh_config(saved)
    await update.effective_message.reply_text(
        f'✅ 服务器已{verb}：<b>{safe(saved.get("name"))}</b>\n'
        f'<code>{safe(cfg.get("user"))}@{safe(cfg.get("host"))}:{safe(cfg.get("port"))}</code>\n\n'
        f'{ok_text}',
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_markup(),
    )


async def finish_bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE, sess: dict, text: str):
    items, errors = parse_bulk_lines(
        text,
        same_port=sess.get('same_port'),
        auth_mode=sess.get('auth_mode') or 'skip',
        shared_auth=sess.get('shared_auth'),
    )
    if not items:
        await update.effective_message.reply_text('没有可导入的服务器。\n' + '\n'.join(errors[:8]))
        return
    results = []
    for item in items:
        saved, action = upsert_server(item)
        results.append((saved, action))
    sem = asyncio.Semaphore(3)
    async def initialize_ipv6(saved):
        async with sem:
            return await detect_server_ipv6(saved)
    ipv6_results = await asyncio.gather(*(initialize_ipv6(saved) for saved, _action in results))
    clear_add_session(update.effective_chat.id)
    lines = [f'✅ 已导入 {len(results)} 台服务器。']
    if errors:
        lines.append(f'⚠️ 跳过 {len(errors)} 行：')
        lines.extend(errors[:6])
    lines.append('\n前几台：')
    for (saved, action), (_ipv6_ok, ipv6_reason) in zip(results[:8], ipv6_results[:8]):
        cfg = ssh_config(saved)
        lines.append(f'- {saved.get("name")}  {cfg.get("user")}@{cfg.get("host")}:{cfg.get("port")}  {action}\n  {ipv6_reason}')
    await update.effective_message.reply_text('\n'.join(safe(x) for x in lines), parse_mode=ParseMode.HTML, reply_markup=main_menu_markup())


def job_id(kind, s):
    return f"{kind}-{server_id(s)}-{int(time.time() * 1000)}"

KIND_NAME = {
    'ipq': 'IP质量', 'nq': 'NodeQuality', 'tcpq': 'TCPQuality', 'gb5': 'GB5', 'stream': '流媒体检测',
    'nexttrace': 'NextTrace', 'bgp': 'BGP图', 'ippure': 'IPPure图',
    'ss': 'SS', 'anytls': 'AnyTLS', 'snell': 'Snell',
    'vless': 'VLESS（历史）',  # Passive archive label only, NEVER a runnable tool.
}
STATUS_ICON = {'running': '🟢', 'done': '✅', 'failed': '🔴', 'inconclusive': '🟡'}
INTERRUPTED_MESSAGE = '任务因 GUKO 重启或进程中断，未完成'


def iso_now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def kind_result_dir(s, kind):
    return RESULTS_DIR / str(server_id(s)) / str(kind)


def latest_result_files(s, kind):
    root = kind_result_dir(s, kind)
    if not root.exists():
        return []
    files = [p for p in root.iterdir() if p.is_file() and p.stat().st_size > 0]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def legacy_media_files(s, kind):
    host = str(s.get('host') or '').strip()
    files = []
    if kind == 'bgp' and host:
        for base in ('guko-bgp', 'vpspilot-bgp'):
            files.extend([p for p in (MEDIA_DIR / base).glob(f'*/latest-{host}.png') if p.is_file() and p.stat().st_size > 0])
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def all_result_files(s, kind):
    files = latest_result_files(s, kind)
    return files if files else legacy_media_files(s, kind)


def clear_result_files(s, kind):
    root = kind_result_dir(s, kind)
    if not root.exists():
        return
    for old in root.iterdir():
        if old.is_file():
            try:
                old.unlink()
            except Exception:
                pass


def persist_result_file(s, kind, src, suffix=None, clear=True):
    if not src:
        return None
    src = Path(src)
    if not src.exists() or not src.is_file() or src.stat().st_size <= 0:
        return None
    root = kind_result_dir(s, kind)
    root.mkdir(parents=True, exist_ok=True)
    if clear:
        clear_result_files(s, kind)
    ext = suffix or src.suffix or '.bin'
    dst = root / f'latest{ext}'
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return str(dst)


def latest_media_path(item):
    paths = item.get('media_paths') or []
    for x in paths:
        p = Path(x)
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p
    return None


def load_history():
    if not HISTORY_JSON.exists():
        return []
    try:
        data = json.loads(HISTORY_JSON.read_text() or '[]')
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(items):
    HISTORY_JSON.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_JSON.write_text(json.dumps(items[-HISTORY_LIMIT:], ensure_ascii=False, indent=2) + '\n')


def reconcile_interrupted_history():
    """Turn persisted running records into explicit failures after a restart."""
    items = load_history()
    changed = 0
    now = iso_now()
    for item in items:
        if item.get('status') != 'running':
            continue
        item['status'] = 'failed'
        item.setdefault('completed_at', now)
        item.setdefault('delivery_error', INTERRUPTED_MESSAGE)
        if not (item.get('log_tail') or '').strip():
            item['log_tail'] = INTERRUPTED_MESSAGE
        if item.get('duration_sec') is None:
            try:
                st = datetime.fromisoformat(str(item.get('started_at')))
                en = datetime.fromisoformat(str(item.get('completed_at')))
                item['duration_sec'] = max(0, int((en - st).total_seconds()))
            except Exception:
                pass
        changed += 1
    if changed:
        save_history(items)
    return changed


def history_append(jid, job):
    urls = history_urls(job.get('log') or '')
    if job.get('kind') == 'tcpq':
        report = validated_tcpquality_url(job.get('report_url'))
        urls = [report] if report else []
    item = {
        'job_id': jid,
        'server': job.get('server'),
        'server_id': job.get('server_id'),
        'kind': job.get('kind'),
        'status': job.get('status'),
        'target': job.get('target'),
        'selected': job.get('selected'),
        'ip_mode': job.get('ip_mode'),
        'region': job.get('region'),
        'report_url': job.get('report_url'),
        'delivery_error': job.get('delivery_error'),
        'tool_source': job.get('tool_source'),
        'started_at': job.get('started_at'),
        'completed_at': job.get('completed_at'),
        'duration_sec': job.get('duration_sec'),
        'urls': urls,
        'media_paths': job.get('media_paths') or ([] if not job.get('media_path') else [job.get('media_path')]),
        'log_tail': trim_log(strip_ansi(job.get('log') or ''), 3500),
    }
    for field in ('raw_path', 'artifact_error', 'render_error', 'extraction_error', 'exit_code'):
        if field in job:
            item[field] = job[field]
    if job.get('kind') == 'stream':
        item.update({key: job.get(key) for key in
                     ('exit_code', 'proto', 'render_error', 'artifact_error', 'raw_path', 'json_path', 'report_format', 'unknown_count', 'extra_family', 'selection', 'cleanup_error')})
        if isinstance(job.get('supplement'), dict):
            item['supplement'] = dict(job['supplement'])
            item['rrc_status'] = job.get('rrc_status', job.get('status'))
    if job.get('kind') in kat_proxy.KINDS:
        item['proxy_report_path'] = job.get('proxy_report_path')
        item['proxy_snapshot'] = job.get('proxy_snapshot')
    hist = [
        x for x in load_history()
        if not (
            x.get('job_id') == jid
            or (item.get('kind') != 'stream' and str(x.get('server_id') or '') == str(item.get('server_id') or '') and x.get('kind') == item.get('kind'))
        )
    ]
    hist.append(item)
    save_history(hist)


def create_job(s, kind, status='running', **extra):
    jid = job_id(kind, s)
    now = iso_now()
    JOBS[jid] = {
        'status': status,
        'server': s.get('name'),
        'server_id': str(server_id(s)),
        'kind': kind,
        'created_at': now,
        **extra,
    }
    if status == 'running':
        JOBS[jid]['started_at'] = now
    return jid


def start_job(s, kind, **extra):
    key = (server_id(s), kind)
    if key in RUNNING:
        return None, key
    RUNNING.add(key)
    jid = create_job(s, kind, status='running', **extra)
    return jid, key


def finish_job(jid, key=None):
    job = JOBS.get(jid) or {}
    now = iso_now()
    if not job.get('status'):
        job['status'] = 'done'
    elif job.get('status') == 'running':
        job['status'] = 'failed'
        job.setdefault('delivery_error', INTERRUPTED_MESSAGE)
        if not (job.get('log') or '').strip():
            job['log'] = INTERRUPTED_MESSAGE
    job['completed_at'] = now
    try:
        st = datetime.fromisoformat(str(job.get('started_at') or job.get('created_at')))
        en = datetime.fromisoformat(now)
        job['duration_sec'] = max(0, int((en - st).total_seconds()))
    except Exception:
        pass
    JOBS[jid] = job
    history_append(jid, job)
    if key:
        RUNNING.discard(key)


def launch_job(s, kind, runner, bot, chat_id, server, *runner_tail, **extra):
    jid, _key = start_job(s, kind, **extra)
    if not jid:
        return None
    asyncio.create_task(runner(bot, chat_id, server, jid, *runner_tail))
    return jid


def server_history(s, limit=20):
    sid = str(server_id(s))
    name = str(s.get('name') or '')
    host = str(s.get('host') or '')
    out = []
    seen = set()
    for item in load_history():
        if str(item.get('server_id') or '') == sid or str(item.get('server') or '') in (name, host, sid):
            kind = item.get('kind')
            if kind:
                seen.add(kind)
            out.append(item)
    scan_kinds = []
    root = RESULTS_DIR / sid
    if root.exists():
        scan_kinds.extend([p.name for p in root.iterdir() if p.is_dir()])
    scan_kinds.extend(['bgp'])
    for kind in sorted(set(scan_kinds)):
        if kind in seen:
            continue
        files = all_result_files(s, kind)
        if not files:
            continue
        newest = files[0]
        out.append({
            'job_id': f'file-{sid}-{kind}',
            'server': s.get('name'),
            'server_id': sid,
            'kind': kind,
            'status': 'done',
            'completed_at': datetime.fromtimestamp(newest.stat().st_mtime).astimezone().isoformat(timespec='seconds'),
            'media_paths': [str(p) for p in files],
            'log_tail': str(newest),
        })
    return out[-limit:]


def history_item_for(s, kind):
    for item in reversed(server_history(s, 50)):
        if item.get('kind') == kind:
            return item
    return None


def history_markup(s):
    sid = server_id(s)
    items = list(reversed(server_history(s, 50)))
    buttons = []
    seen = set()
    for item in items:
        kind = item.get('kind')
        if not kind or kind in seen:
            continue
        seen.add(kind)
        icon = STATUS_ICON.get(item.get('status'), '•')
        label = f'{icon} {KIND_NAME.get(kind, kind)}'
        buttons.append(InlineKeyboardButton(label, callback_data=f'histd:{sid}:{kind}'))
    rows = button_rows(buttons, 2)
    rows.append([InlineKeyboardButton('🔄 刷新历史', callback_data=f'hist:{sid}')])
    rows.append([InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')])
    return InlineKeyboardMarkup(rows)


def history_detail_text(s, kind):
    item = history_item_for(s, kind)
    if not item:
        return f'📜 <b>{safe(s.get("name"))}</b> 暂无 {safe(KIND_NAME.get(kind, kind))} 历史。'
    icon = STATUS_ICON.get(item.get('status'), '•')
    lines = [
        f'{icon} <b>{safe(s.get("name"))} · {safe(KIND_NAME.get(kind, kind))}</b>',
        f'状态：<b>{safe(item.get("status") or "-")}</b>',
    ]
    when = item.get('completed_at') or item.get('started_at')
    if when:
        lines.append(f'时间：<code>{safe(when)}</code>')
    if item.get('duration_sec') is not None:
        lines.append(f'耗时：<code>{safe(item.get("duration_sec"))}s</code>')
    params = []
    for label, key in [('目标', 'target'), ('选择', 'selected'), ('IP模式', 'ip_mode'), ('地区', 'region')]:
        if item.get(key):
            params.append(f'{label}：{item.get(key)}')
    if params:
        lines.append('参数：' + safe('；'.join(params)))
    proof = tool_source_html(item)
    if proof:
        lines.append(proof)
    urls = item.get('urls') or []
    if urls:
        lines.append('\n链接：\n' + '\n'.join(safe(u) for u in urls[:8]))
    media = latest_media_path(item)
    if media:
        lines.append('\n图片：点击后会重新发送最近一次结果图。')
    log_tail = (item.get('log_tail') or '').strip()
    if log_tail and not media:
        lines.append('\n详情：\n<pre>' + safe(log_tail[-3200:]) + '</pre>')
    else:
        lines.append('\n详情：暂无可展示内容。')
    if kind == 'stream' and isinstance(item.get('supplement'), dict):
        sub = item['supplement']
        lines.append('\n补充检测：<b>' + safe(sub.get('status') or '-') + '</b> · 17项 · 系统选择地址族')
        if sub.get('unknown_count'):
            lines.append('未知项目：' + safe(sub['unknown_count']))
        if sub.get('error'):
            lines.append('补充错误：' + safe(trim_log(sub['error'], 500)))
        if sub.get('raw_path') or sub.get('json_path'):
            lines.append('补充原始报告/JSON已独立归档。')
    return '\n'.join(lines)


def history_text(s):
    items = server_history(s, 20)
    if not items:
        return f'📜 <b>{safe(s.get("name"))}</b> 暂无测试历史。'
    lines = [f'📜 <b>{safe(s.get("name"))}</b> 最近一次测试结果', '点下面的功能按钮可以查看具体内容。']
    for item in reversed(items):
        icon = STATUS_ICON.get(item.get('status'), '•')
        kind = KIND_NAME.get(item.get('kind'), item.get('kind') or '-')
        extra = []
        for k in ('target', 'selected', 'ip_mode', 'region'):
            if item.get(k):
                extra.append(str(item.get(k)))
        dur = f" · {item.get('duration_sec')}s" if item.get('duration_sec') is not None else ''
        when = item.get('completed_at') or item.get('started_at') or '-'
        suffix = f" — {'；'.join(extra)}" if extra else ''
        lines.append(f'{icon} {safe(kind)} · {safe(item.get("status"))}{safe(dur)}\n   <code>{safe(when)}</code>{safe(suffix)}')
        urls = item.get('urls') or []
        if urls:
            lines.append('   ' + safe(urls[0]))
    return '\n'.join(lines)


def server_jobs(s):
    sid = str(server_id(s))
    name = str(s.get('name') or '')
    host = str(s.get('host') or '')
    found = []
    for jid, j in JOBS.items():
        if (j.get('status') or '') != 'running':
            continue
        j_server = str(j.get('server') or '')
        if f'-{sid}-' in str(jid) or j_server in (name, host, sid):
            found.append((jid, j))
    found.sort(key=lambda kv: kv[1].get('created_at') or kv[1].get('started_at') or kv[0])
    return found


def compact_job_line(s, jid, j):
    status = j.get('status') or '-'
    icon = STATUS_ICON.get(status, '•')
    kind = KIND_NAME.get(j.get('kind'), j.get('kind') or '-')
    parts = [kind]
    if j.get('selected'):
        parts.append(str(j.get('selected')))
    elif j.get('target'):
        parts.append(str(j.get('target')))
    elif j.get('region'):
        parts.append(str(j.get('region')))
    label = '·'.join(parts)
    tail = status
    extras = []
    if j.get('ip_mode'):
        extras.append(str(j.get('ip_mode')))
    if extras:
        tail += f"（{'；'.join(extras)}）"
    return f'{icon} {safe(label)} - {safe(tail)}'


def job_status_text(s):
    jobs = server_jobs(s)
    if not jobs:
        return f'📋 <b>{safe(s.get("name"))}</b> 当前没有任务。'
    lines = [f'📋 <b>{safe(s.get("name"))}</b> 当前任务']
    for jid, j in jobs[-10:]:
        lines.append(compact_job_line(s, jid, j))
    return '\n'.join(lines)



def extract_urls(text):
    text = strip_ansi(text or '')
    urls = re.findall(r'https?://[^\s<>"\'\x00-\x1f\x7f]+', text)
    return [u.rstrip('.,;，。)】]') for u in urls]


def history_urls(text, limit=24):
    urls = []
    seen = set()
    tq = tcpquality_url(text)
    if tq:
        urls.append(tq)
        seen.add(tq)
    nq = nodequality_url(text)
    if nq:
        urls.append(nq)
        seen.add(nq)
    for u in extract_urls(text):
        clean = strip_ansi(u).rstrip('.,;，。)】]')
        m = re.search(r'(https?://nodequality\.com/r/[A-Za-z0-9]{32})', clean)
        if m:
            clean = m.group(1)
        if clean not in seen and (
            'Report.Check.Place/' in clean
            or 'browser.geekbench.com/' in clean
            or 'nodequality.com/r/' in clean
        ):
            urls.append(clean)
            seen.add(clean)
    for u in extract_urls(text):
        clean = strip_ansi(u).rstrip('.,;，。)】]')
        if clean not in seen:
            urls.append(clean)
            seen.add(clean)
        if len(urls) >= limit:
            break
    return urls[:limit]


def first_report_url(text, category=None):
    urls = extract_urls(text)
    reports = [u for u in urls if 'Report.Check.Place' in u]
    if category:
        needle = f'/Report.Check.Place/{category}/'
        needle2 = f'Report.Check.Place/{category}/'
        for u in reports:
            clean = strip_ansi(u).strip()
            if needle in clean or needle2 in clean:
                return clean
        return None
    return strip_ansi(reports[0]).strip() if reports else None



def geekbench_urls(text):
    urls = []
    seen = set()
    for u in extract_urls(text):
        clean = strip_ansi(u).rstrip('.,;，。)】]')
        if re.search(r'browser\.geekbench\.com/v\d+/cpu/\d+', clean) and clean not in seen:
            urls.append(clean)
            seen.add(clean)
    return urls

def validated_tcpquality_url(value):
    clean = strip_ansi(str(value or '')).strip()
    match = re.fullmatch(r'https://tcpquality\.ibsgss\.uk/r/([A-Za-z0-9_-]{10})', clean, re.I)
    if not match:
        return None
    return f'https://tcpquality.ibsgss.uk/r/{match.group(1)}'


def tcpquality_url(text):
    clean = strip_ansi(text or '')
    match = re.search(r'https?://tcpquality\.ibsgss\.uk/r/([A-Za-z0-9_-]{10})', clean, re.I)
    if not match:
        return None
    return f'https://tcpquality.ibsgss.uk/r/{match.group(1)}'


def nodequality_url(text):
    clean = strip_ansi(text or '')
    # NodeQuality output can be immediately followed by curl progress digits
    # (for example the trailing "00" from "100"), so capture only the token.
    m = re.search(r'https?://nodequality\.com/r/([A-Za-z0-9]{32})', clean)
    if m:
        return f'https://nodequality.com/r/{m.group(1)}'
    for u in extract_urls(clean):
        u = strip_ansi(u).rstrip('.,;，。')
        m = re.search(r'(https?://nodequality\.com/r/[A-Za-z0-9]{32})', u)
        if m:
            return m.group(1)
    return None


def all_report_urls(text, category):
    urls = []
    seen = set()
    needle = f'Report.Check.Place/{category}/'
    for u in extract_urls(text):
        clean = strip_ansi(u).strip()
        if needle in clean and clean not in seen:
            urls.append(clean)
            seen.add(clean)
    return urls


def trim_log(text, limit=3200):
    text = (text or '').strip()
    return text[-limit:] if len(text) > limit else text



def run_pty_command_sync(args, timeout=900, send_enter_after=2):
    master, slave = os.openpty()
    try:
        try:
            os.set_blocking(master, False)
        except Exception:
            pass
        proc = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        slave = None
        out = bytearray()
        start = time.monotonic()
        sent_enter = False
        while True:
            now = time.monotonic()
            if not sent_enter and now - start >= send_enter_after:
                try:
                    os.write(master, b'\r')
                except OSError:
                    pass
                sent_enter = True
            if now - start > timeout:
                try:
                    proc.terminate()
                    time.sleep(1)
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                return 124, out.decode(errors='replace') + '\n命令超时'
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(master, 8192)
                    if chunk:
                        out.extend(chunk)
                except OSError:
                    pass
            if proc.poll() is not None:
                # drain remaining output
                for _ in range(10):
                    r, _, _ = select.select([master], [], [], 0.05)
                    if not r:
                        break
                    try:
                        chunk = os.read(master, 8192)
                        if chunk:
                            out.extend(chunk)
                    except OSError:
                        break
                return proc.returncode, out.decode(errors='replace')
    finally:
        if slave is not None:
            try:
                os.close(slave)
            except OSError:
                pass
        try:
            os.close(master)
        except OSError:
            pass


async def run_pty_command(args, timeout=900, send_enter_after=2):
    return await asyncio.to_thread(run_pty_command_sync, args, timeout, send_enter_after)


async def send_long_text(bot, chat_id, text, *, parse_mode=None):
    text = text or '无输出'
    max_len = 3600 if parse_mode == ParseMode.HTML else 3900
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or ['无输出']
    for chunk in chunks[:3]:
        await bot.send_message(chat_id, chunk, parse_mode=parse_mode)



async def run_until_report(args, timeout=900, env=None, *, wait_for_exit=False):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env
    )
    out = bytearray()
    start = time.monotonic()
    report = None
    try:
        while True:
            if time.monotonic() - start > timeout:
                proc.kill()
                await proc.wait()
                return 124, out.decode(errors='replace') + '\n命令超时', report
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=1)
            except asyncio.TimeoutError:
                if proc.returncode is not None:
                    break
                continue
            if chunk:
                out.extend(chunk)
                text = out.decode(errors='replace')
                report = first_report_url(text, 'ip') or report
                if report and not wait_for_exit:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                    return 0, text, report
            elif proc.returncode is not None:
                break
        text = out.decode(errors='replace')
        return proc.returncode, text, first_report_url(text, 'ip')
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()


async def run_subprocess(args, timeout, *, send_enter_after=None, env=None, stdout_only_codes=()):
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE if stdout_only_codes else asyncio.subprocess.STDOUT, env=env
    )
    async def nudge_enter():
        if send_enter_after is None:
            return
        await asyncio.sleep(send_enter_after)
        if proc.returncode is None and proc.stdin:
            try:
                proc.stdin.write(b'\n')
                await proc.stdin.drain()
            except Exception:
                pass
    nudger = asyncio.create_task(nudge_enter())
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        try:
            out, err = await proc.communicate()
        except Exception:
            out, err = b'', b''
        return 124, ((err or b'') + (out or b'')).decode(errors='replace') + '\n命令超时'
    finally:
        nudger.cancel()
    if proc.returncode not in stdout_only_codes:
        # Separated stderr is mostly local SSH notices emitted before any
        # remote output; never let it trail the result.
        out = (err or b'') + out
    return proc.returncode, out.decode(errors='replace')


async def resolve_target_to_ipv4(target):
    ip = extract_ipv4(target)
    if ip:
        return ip, None
    host = normalize_domain(target)
    if not host:
        raise RuntimeError('没有识别到 IPv4 或域名')
    def lookup():
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        seen = []
        for info in infos:
            addr = info[4][0]
            if addr not in seen:
                seen.append(addr)
        if not seen:
            raise RuntimeError('域名没有解析到 IPv4')
        return seen[0]
    return await asyncio.to_thread(lookup), host


def parse_bgp_png(stdout, target, outdir):
    m = re.search(r'^LATEST=(.+)$', stdout or '', re.M)
    if m:
        return Path(m.group(1).strip())
    return Path(outdir) / f'latest-{safe_target(target)}.png'


def is_bgp_temporary_no_path(output):
    text = str(output or '')
    return (
        'PLACEHOLDER' in text
        or 'NONE' in text
        or 'temporarily returned no path image' in text
        or 'prefix not visible in DFZ' in text
        or 'no usable BGP path image found' in text
        or 'no path data' in text
    )


def bgp_retry_message():
    return 'BGP 图暂时没取到，应该是 bgp.tools 偶发抽风，请再试一次。'


async def ensure_bgp_tool():
    if BGP_FETCH.exists():
        return
    bundled = Path('/app/tools/bgp_fetch.py')
    if bundled.exists():
        BGP_FETCH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, BGP_FETCH)
        os.chmod(BGP_FETCH, 0o755)
        return
    raise RuntimeError('BGP 工具不存在。请使用项目 Dockerfile 构建镜像，或设置 BGP_FETCH 指向 bgp_fetch.py。')


async def ensure_ippure_tool():
    if not shutil.which('node'):
        raise RuntimeError('容器里没有 node，无法运行 IPPure。请使用项目 Dockerfile 构建镜像。')
    if not IPPURE_DOWNLOAD.exists():
        bundled = Path('/app/tools/download_ippure.js')
        if bundled.exists():
            IPPURE_DOWNLOAD.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, IPPURE_DOWNLOAD)
            os.chmod(IPPURE_DOWNLOAD, 0o755)
        else:
            raise RuntimeError('IPPure 工具不存在。请使用项目 Dockerfile 构建镜像，或设置 IPPURE_DOWNLOAD 指向 download_ippure.js。')
    try:
        code, _ = await run_subprocess([
            'node', '-e',
            'const fs=require("fs"); const paths=[process.env.CHROMIUM_PATH,"/usr/bin/chromium","/usr/bin/chromium-browser","/usr/bin/google-chrome","/usr/bin/google-chrome-stable"].filter(Boolean); '
            'if(paths.some(p=>fs.existsSync(p))){process.exit(0)}; '
            'const {chromium}=require("playwright"); const p=chromium.executablePath(); console.log(p); process.exit(fs.existsSync(p)?0:2)'
        ], timeout=20)
        if code != 0:
            raise RuntimeError('missing playwright browser')
    except Exception:
        code, out = await run_subprocess(['bash', '-lc', 'npm install -g playwright@1.59.1 && PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright} npx playwright install chromium chromium-headless-shell'], timeout=600)
        if code != 0:
            raise RuntimeError('Playwright 自动安装失败：\n' + trim_log(out, 1000))


def build_bgp_relay_config(server):
    inv = load_inventory()
    sid = str(server_id(server))
    matches = [item for item in (inv.get('servers') or []) if str(server_id(item)) == sid]
    if len(matches) != 1 or str(matches[0].get('host') or '') != str(server.get('host') or ''):
        return None
    cfg = resolve_ssh(matches[0], inv)
    if cfg.get('auth') != 'key' or not cfg.get('key'):
        return None
    known_hosts = TMP_DIR / 'ssh_known_hosts'
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    known_hosts.touch(mode=0o600, exist_ok=True)
    os.chmod(known_hosts, 0o600)
    return {
        'host': cfg.get('host'),
        'user': cfg.get('user'),
        'port': cfg.get('port'),
        'key': cfg.get('key'),
        'known_hosts': str(known_hosts),
    }


async def generate_bgp_png(ip, relay_server=None):
    await ensure_bgp_tool()
    BGP_OUT_ROOT.mkdir(parents=True, exist_ok=True)
    outdir = Path(tempfile.mkdtemp(prefix='bgp-', dir=str(BGP_OUT_ROOT)))
    complete = False
    try:
        args = ['python3', str(BGP_FETCH), '--outdir', str(outdir)]
        if relay_server:
            relay = build_bgp_relay_config(relay_server)
            if relay:
                relay_path = outdir / 'relay.json'
                fd = os.open(relay_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    json.dump(relay, handle)
                args.extend(['--relay-config', str(relay_path)])
        args.append(ip)
        code, out = await run_subprocess(args, timeout=120)
        if code != 0:
            if is_bgp_temporary_no_path(out):
                raise RuntimeError(bgp_retry_message())
            raise RuntimeError(trim_log(out, 1000) or f'BGP 生成失败：{code}')
        png = parse_bgp_png(out, ip, outdir)
        if not png.exists() or png.stat().st_size <= 0:
            raise RuntimeError('BGP 图片生成后未找到文件')
        complete = True
        return png
    finally:
        if not complete:
            shutil.rmtree(outdir, True)


async def generate_ippure_png(ip):
    await ensure_ippure_tool()
    outdir = IPPURE_TMP_ROOT / f'ippure-{int(time.time())}-{os.getpid()}'
    outdir.mkdir(parents=True, exist_ok=True)
    code, out = await run_subprocess(['node', str(IPPURE_DOWNLOAD), '--ip', ip, '--outdir', str(outdir)], timeout=120)
    if code != 0:
        raise RuntimeError(trim_log(out, 1000) or f'IPPure 生成失败：{code}')
    candidates = [Path(line.strip()) for line in (out or '').splitlines() if line.strip().endswith('.png')]
    png = candidates[-1] if candidates else None
    if not png or not png.exists() or png.stat().st_size <= 0:
        raise RuntimeError('IPPure 图片生成后未找到文件')
    return png


async def send_png_and_cleanup(bot, chat_id, png, cleanup_dir=None):
    try:
        with Path(png).open('rb') as f:
            await bot.send_photo(chat_id, photo=f)
    finally:
        if cleanup_dir:
            await asyncio.to_thread(shutil.rmtree, str(cleanup_dir), True)

async def run_bgp_task(bot, chat_id, s, jid, allow_relay=True):
    key = (server_id(s), 'bgp')
    cleanup_dir = None
    try:
        ip = s.get('host')
        png = await generate_bgp_png(ip, s if allow_relay else None)
        cleanup_dir = Path(png).parent
        saved = persist_result_file(s, 'bgp', png, '.png')
        JOBS[jid].update({'status': 'done', 'log': str(png), 'media_path': saved})
        await send_png_and_cleanup(bot, chat_id, png, cleanup_dir)
    except Exception as e:
        JOBS[jid].update({'status': 'failed', 'log': repr(e)})
        await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} BGP 图失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, True)
        finish_job(jid, key)


async def run_ippure_task(bot, chat_id, s, jid):
    key = (server_id(s), 'ippure')
    try:
        ip = s.get('host')
        png = await generate_ippure_png(ip)
        saved = persist_result_file(s, 'ippure', png, '.png')
        JOBS[jid].update({'status': 'done', 'log': str(png), 'media_path': saved})
        await send_png_and_cleanup(bot, chat_id, png, Path(png).parent)
    except Exception as e:
        JOBS[jid].update({'status': 'failed', 'log': repr(e)})
        await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} IPPure 图失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        finish_job(jid, key)


def ip_tools_markup(ip):
    row = []
    if tool_enabled('ippure'):
        row.append(InlineKeyboardButton('🧼 IPPure 图', callback_data=f'ippureip:{ip}'))
    if tool_enabled('bgp'):
        row.append(InlineKeyboardButton('🧭 BGP 图', callback_data=f'bgpip:{ip}'))
    if not row:
        row.append(InlineKeyboardButton('未启用 IP 图像工具', callback_data='noop'))
    return InlineKeyboardMarkup([row])


ANSI_MAX_BYTES = 2 * 1024 * 1024
ANSI_RENDER_SEMAPHORE = asyncio.Semaphore(1)
NQ_ANSI_REPORTS = (
    ('硬件', 'hardware', 1, 'hardware_quality.log'),
    ('IP质量', 'ip', 2, 'ip_quality.log'),
    ('网络', 'net', 4, 'net_quality.log'),
    ('回程', 'backroute', 8, 'backroute_trace.log'),
)


def ipquality_ansi_reports(output):
    """Collect full terminal reports, including upstream Lite without a URL."""
    lines = output.split('\n')
    starts = [i for i, line in enumerate(lines)
              if re.search(r'IP质量体检报告|IP QUALITY CHECK REPORT', strip_ansi(line))]
    reports = []
    for index, start in enumerate(starts):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines)
        section = '\n'.join(lines[max(0, start - 1):end])
        url = next((u for u in extract_urls(strip_ansi(section))
                    if re.fullmatch(r'https://Report\.Check\.Place/ip/[A-Za-z0-9_-]+\.svg', u)), None)
        try:
            reports.append((url, extract_ip_ansi_report(section, url)))
        except ValueError:
            # A title alone is not a report, especially when a dual run times out.
            continue
    return reports


def extract_ip_ansi_report(output, report_url):
    """Slice the final report verbatim; strip ANSI only for boundary detection.

    IP.Check.Place prints its complete colored report before its SVG URL. Keep
    LFCR/SGR intact, excluding download progress and later terminal clear codes.
    Each requested URL selects its own preceding report, including IPv6.
    """
    if report_url:
        end = output.find(report_url)
        if end < 0:
            raise ValueError('IP ANSI 日志缺少报告链接')
    else:
        # Lite reports deliberately do not upload. Require the full footer,
        # never manufacture a public URL or render an unfinished progress log.
        end = 0
        for line in output.splitlines(keepends=True):
            end += len(line)
            if re.search(r'感谢使用xy系列脚本|Thanks for running xy scripts!', strip_ansi(line)):
                break
        else:
            raise ValueError('IP ANSI 日志缺少完整报告结尾')
    prefix = output[:end]
    # Split only at LF: splitlines() treats upstream LFCR as two separate rows.
    lines = prefix.split('\n')
    titles = [i for i, line in enumerate(lines)
              if re.search(r'IP质量体检报告|IP QUALITY CHECK REPORT', strip_ansi(line))]
    if not titles:
        raise ValueError('IP ANSI 日志缺少完整报告标题')
    start_line = titles[-1]
    start = sum(len(line) + 1 for line in lines[:start_line])
    if start_line:
        previous = lines[start_line - 1]
        if re.fullmatch(r'\s*#{20,}\s*', strip_ansi(previous)):
            start -= len(previous) + 1
        else:
            # Standalone upstream finishes its progress spinner with CR, not
            # LF. The opening divider can share that physical line. Preserve
            # its exact SGR bytes while dropping only the preceding progress.
            sgr = r'\x1b\[[0-9;:]*m'
            divider = re.search(
                rf'\r(?:[ \t]|{sgr})*#{{20,}}(?:[ \t\r]|{sgr})*$', previous,
            )
            if divider:
                start -= len(previous) + 1 - divider.start()
    return output[start:end + len(report_url or '')] + '\x1b[0m\n'


async def run_ansi_subprocess(args, timeout=120, *, separate_stderr=False, env=None):
    """Own the renderer process group, including Chromium on timeout/cancel."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE if separate_stderr else asyncio.subprocess.STDOUT,
        start_new_session=True, env=env,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors='replace')
    finally:
        # Even a crashed Node may leave Chromium alive after its own exit.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


async def render_ansi_png(raw_log, out_png, kind='ip'):
    """Render original terminal bytes locally; never fall back to SVG."""
    if kind not in {item[1] for item in NQ_ANSI_REPORTS} | {'stream'}:
        raise ValueError('未知 ANSI 报告类型')
    payload = raw_log.encode('utf-8') if isinstance(raw_log, str) else bytes(raw_log)
    if not payload or len(payload) > ANSI_MAX_BYTES:
        raise ValueError('ANSI 日志为空或超过 2MiB')
    renderer = Path('/app/render_ansi.js')
    if not renderer.is_file():
        renderer = Path(__file__).resolve().parent / 'render_ansi.js'
    async with ANSI_RENDER_SEMAPHORE:
        with tempfile.TemporaryDirectory(prefix='guko-ansi-') as td:
            raw_path = Path(td) / 'report.log'
            fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(payload)
            out_png = Path(out_png)
            out_png.parent.mkdir(parents=True, exist_ok=True)
            # A failed process must not accidentally send a stale output file.
            out_png.unlink(missing_ok=True)
            code, out = await run_ansi_subprocess(
                ['node', str(renderer), str(raw_path), str(out_png), '--kind', kind],
                timeout=120,
            )
            if code != 0:
                out_png.unlink(missing_ok=True)
                raise RuntimeError(f'ANSI 渲染失败 ({code}): {out[-1000:]}')
            if not out_png.is_file() or out_png.stat().st_size <= 8:
                raise RuntimeError('ANSI 渲染器未生成 PNG')
            with out_png.open('rb') as f:
                if f.read(8) != b'\x89PNG\r\n\x1a\n':
                    out_png.unlink(missing_ok=True)
                    raise RuntimeError('ANSI 渲染器输出不是 PNG')


async def ensure_checkplace_renderer():
    if RENDER_CHECKPLACE.exists():
        return
    fallback = Path(__file__).resolve().parent / 'render_checkplace.py'
    if fallback.exists():
        return
    raise RuntimeError('Check.Place PNG 渲染器不存在。请确认镜像包含 /app/render_checkplace.py，或设置 RENDER_CHECKPLACE。')


async def render_checkplace_png(svg_url, out_png):
    await ensure_checkplace_renderer()
    renderer = RENDER_CHECKPLACE if RENDER_CHECKPLACE.exists() else Path(__file__).resolve().parent / 'render_checkplace.py'
    with tempfile.TemporaryDirectory() as td:
        svg_path = Path(td) / 'report.svg'
        def download():
            req = urllib.request.Request(
                svg_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
                    'Accept': 'image/svg+xml,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Referer': 'https://Report.Check.Place/',
                },
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                svg_path.write_bytes(r.read())
        await asyncio.to_thread(download)
        code, out = await run_subprocess(['python', str(renderer), str(svg_path), str(out_png)], timeout=90)
        if code != 0:
            raise RuntimeError(out[-1000:])


TCPQUALITY_MAX_PNG_BYTES = 10 * 1024 * 1024


def urlopen_tcpquality(url, timeout=60):
    """Fetch an official TCPQuality report asset.

    Split out as a module-level function so tests can stub the network.
    """
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'GUKO/0.2 (+https://github.com/shui1iao/GUKO)',
            'Accept': 'image/png,image/*;q=0.8',
            'Referer': 'https://tcpquality.ibsgss.uk/',
        },
    )
    return urllib.request.urlopen(req, timeout=timeout)


async def fetch_tcpquality_png(image_url, out_png):
    """Download the official report PNG verbatim.

    Upstream started serving a real 2x-rendered PNG at `.png?section=...`
    (rv=...-rsvg-2x-20260726), so GUKO no longer fetches the SVG or does any
    local recolouring/cropping — 水饺 asked for the official image as-is.
    """
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    def download():
        with urlopen_tcpquality(image_url, timeout=60) as response:
            payload = response.read(TCPQUALITY_MAX_PNG_BYTES + 1)
        if len(payload) > TCPQUALITY_MAX_PNG_BYTES:
            raise RuntimeError('TCPQuality 报告图超过 10MB 限制')
        if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('TCPQuality 图片接口没有返回 PNG')
        return payload

    payload = await asyncio.to_thread(download)
    out_png.write_bytes(payload)
    if out_png.stat().st_size <= 8:
        raise RuntimeError('TCPQuality PNG 保存后为空')


async def cleanup_nodequality_ansi_logs(s, work_dir):
    """Remove only our four copies, retaining upstream's result.zip policy."""
    validate_nodequality_work_dir(work_dir)
    paths = ' '.join(shlex.quote(work_dir + '/' + item[3]) for item in NQ_ANSI_REPORTS)
    remote = f'rm -f -- {paths}; rmdir -- {shlex.quote(work_dir)} 2>/dev/null || true'
    await run_subprocess(ssh_args(s, remote, tty=False), timeout=30, env=ssh_env_for(s))


async def read_nodequality_ansi_logs(s, work_dir, selected):
    """Read allowlisted original logs from this invocation's private directory."""
    validate_nodequality_work_dir(work_dir)
    logs = {}
    for _label, kind, bit, filename in NQ_ANSI_REPORTS:
        if not selected & bit:
            continue
        path = shlex.quote(work_dir + '/' + filename)
        # Bound transport too, not just renderer input. A symlink is not a log.
        remote = f'[ ! -L {path} ] && [ -f {path} ] && head -c {ANSI_MAX_BYTES + 1} -- {path}'
        # SSH host-key warnings are stderr, never terminal report content.
        code, raw = await run_ansi_subprocess(
            ssh_args(s, remote, tty=False), timeout=60,
            separate_stderr=True, env=ssh_env_for(s),
        )
        if code != 0 or not raw or len(raw.encode('utf-8')) > ANSI_MAX_BYTES:
            raise RuntimeError(f'{kind} 原始 ANSI 日志读取失败（缺失或超过 2MiB）')
        logs[kind] = raw
    return logs


def nodequality_stdout_logs(output, selected):
    """Best-effort original slices; titles/URLs are display aids, not gates.

    Official NodeQuality tees each selected subreport to this invocation's
    stdout. No sed of upstream code or watcher/cross-task log search required.
    If the optional extraction fails, the complete original stdout is relayed.
    """
    logs = {}
    for _label, kind, bit, _filename in NQ_ANSI_REPORTS:
        if not selected & bit:
            continue
        urls = all_report_urls(output, kind)
        if not urls:
            continue
        url = urls[-1]
        end = output.rfind(url)
        lines = output[:end].split('\n')
        headers = [i for i, line in enumerate(lines) if re.search(r'体检报告|QUALITY CHECK REPORT', strip_ansi(line), re.I)]
        if not headers:
            continue
        first = headers[-1]
        if first and re.fullmatch(r'\s*#{20,}\s*', strip_ansi(lines[first-1])):
            first -= 1
        start = sum(len(line)+1 for line in lines[:first])
        logs[kind] = output[start:end+len(url)]
    return logs


async def send_ansi_report_images(bot, chat_id, report_links, prefix, raw_logs):
    """New reports use ANSI only; legacy SVG helper/history stay compatible."""
    out_dir = Path('/tmp/guko-results')
    out_dir.mkdir(parents=True, exist_ok=True)
    sent = []
    kinds = {label: kind for label, kind, _bit, _filename in NQ_ANSI_REPORTS}
    for label, url in report_links:
        kind = kinds[label]
        raw = raw_logs.get(kind)
        if not raw:
            raise RuntimeError(f'{label} 缺少原始 ANSI 日志')
        png = out_dir / f'{prefix}-{kind}-{time.time_ns()}.png'
        await render_ansi_png(raw, png, kind=kind)
        with png.open('rb') as f:
            await bot.send_photo(chat_id, photo=f)
        sent.append((label, url, png))
    return sent


async def send_report_images(bot, chat_id, report_links, prefix):
    if not report_links:
        return []
    out_dir = Path('/tmp/guko-results')
    out_dir.mkdir(parents=True, exist_ok=True)
    sent = []
    for label, url in report_links:
        png = out_dir / f"{prefix}-{label}-{int(time.time())}.png"
        await render_checkplace_png(url, png)
        with png.open('rb') as f:
            await bot.send_photo(chat_id, photo=f)
        sent.append((label, url, png))
    return sent


def proxy_tool_config(kind):
    tool = PROXY_TOOLS.get(kind)
    if not tool:
        raise RuntimeError('未知工具')
    return tool


def proxy_menu_text(s, kind):
    tool = proxy_tool_config(kind)
    if kind in kat_proxy.KINDS:
        return (f"{safe(tool['button'])} <b>{safe(s.get('name'))} · {safe(tool['name'])}</b>\n\n"
                '只读发现本机全部受支持Kat实例，不检查更新、不改凭据、不启停服务。\n'
                '若完整确认所选协议未安装，会另给明确安装确认；缺依赖停止，不安装依赖或升级已有内核。')
    return (
        f"{safe(tool['button'])} <b>{safe(s.get('name'))} · {safe(tool['name'])}</b>\n\n"
        '已安装时只读取当前节点，不检查更新、不重装、不启动/重启，也不改变凭据。\n'
        '仅未安装时调用原管理脚本安装。\n'
        '查看只读取目标服务器当前配置并返回连接信息。'
    )


def proxy_markup(s, kind):
    sid = server_id(s)
    tool = proxy_tool_config(kind)
    if kind in kat_proxy.KINDS:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton('读取全部Kat节点', callback_data=f'proxyrun:{kind}:view:{sid}')],
            [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"安装/读取 {tool['name']} 服务端", callback_data=f'proxyrun:{kind}:ensure:{sid}')],
        [InlineKeyboardButton('查看配置', callback_data=f'proxyrun:{kind}:view:{sid}')],
        [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
    ])


def proxy_answers(kind, port=None, mode=None):
    # Manager scripts are interactive for install: port/SNI/password prompts.
    # Empty password keeps the script default random password.
    port = str(port or '').strip()
    if kind == 'snell':
        return f"{port}\n\n"
    return "\n"


def proxy_extract_config(text, kind):
    clean = strip_ansi(text or '').replace('\r', '')
    markers = ['当前配置', 'Surge:', 'Mihomo:', 'URI:', '地址:', '端口:', '密码:', '加密:', '版本:', 'UUID:', 'PublicKey:', 'ShortId:', 'SNI:', '服务端配置:', '客户端 JSON:']
    lines = []
    keep = False
    for raw in clean.splitlines():
        line = raw.rstrip()
        if any(m in line for m in markers):
            keep = True
        if keep:
            lines.append(line)
    body = '\n'.join(lines).strip() or clean.strip()
    return trim_log(body, 3600)


def is_proxy_link_line(line):
    s = (line or '').strip()
    return s.startswith(('vless://', 'ss://', 'anytls://', 'snell://', 'VPS = ', '- {', '- {"', '{'))


def format_proxy_config_html(body):
    if not body:
        return '<code>无节点配置输出</code>'
    out = []
    block = []

    def flush_block():
        if block:
            out.append('<pre>' + safe('\n'.join(block)) + '</pre>')
            block.clear()

    for raw in str(body).splitlines():
        line = raw.rstrip()
        if is_proxy_link_line(line):
            block.append(line.strip())
        else:
            flush_block()
            out.append(safe(line))
    flush_block()
    return '\n'.join(out).strip()


def valid_kat_confirmation(token, user_id, chat_id):
    now = time.time()
    for key, item in list(KAT_INSTALL_CONFIRMATIONS.items()):
        if item['expires'] < now:
            KAT_INSTALL_CONFIRMATIONS.pop(key, None)
    item = KAT_INSTALL_CONFIRMATIONS.get(token)
    if (not item or item['user_id'] != user_id or item['chat_id'] != chat_id
            or item['kind'] not in kat_proxy.KINDS):
        return None
    return item


async def offer_kat_install(bot, chat_id, s, kind, requester):
    if requester is None:
        return
    if len(KAT_INSTALL_CONFIRMATIONS) >= 128:
        oldest = min(KAT_INSTALL_CONFIRMATIONS, key=lambda key: KAT_INSTALL_CONFIRMATIONS[key]['expires'])
        KAT_INSTALL_CONFIRMATIONS.pop(oldest, None)
    token = os.urandom(16).hex()
    KAT_INSTALL_CONFIRMATIONS[token] = {'server_id':server_id(s), 'kind':kind,
        'user_id':requester, 'chat_id':chat_id, 'expires':time.time()+600,
        'host_hash':hashlib.sha256(str(s.get('host')).encode()).hexdigest()}
    await bot.send_message(chat_id,
        f'{s.get("name")}：完整只读发现未找到Kat {kind}。\n'
        '是否明确安装这个协议？将创建配置/服务并启动；缺前置依赖停止，不安装依赖、不升级已有共享内核，不改变其它协议。\n'
        '确认仅对本服务器/本协议有效，10分钟后失效。',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ 确认新安装 Kat '+kind, callback_data='katinstall:'+token)],
            [InlineKeyboardButton('取消，返回操作面板', callback_data='srv:'+server_id(s))]]))


async def kat_transport(s, command, *, timeout=180, limit=kat_proxy.MAX_WIRE):
    # Reuse the bounded/cancellation-safe existing SSH subprocess transport.
    code, out, _err = await stream_unified.process(
        ssh_args(s, command, tty=False), timeout=timeout, env=ssh_env_for(s), max_output=limit)
    return code, out


async def read_kat_snapshot(s, kind):
    code, raw = await kat_transport(s, kat_proxy.collector_command())
    if code != kat_proxy.SNAPSHOT_EXIT:
        kat_proxy.reject()
    plan = kat_proxy.discovery(raw)
    code, raw = await kat_transport(s, kat_proxy.config_command(plan))
    if code != kat_proxy.SNAPSHOT_EXIT:
        kat_proxy.reject()
    nodes = kat_proxy.parse_nodes(kind, plan, raw)
    paths = sorted({p for n in nodes if n.get('tls_paths') for p in n['tls_paths']})
    if paths:
        code, answer = await kat_transport(s, kat_proxy.tls_metadata_command(paths), limit=4096)
        if code != 0 or answer.strip() != 'GUKO_KAT_TLS_METADATA_OK':
            kat_proxy.reject('Kat证书引用/权限无法可靠确认；未生成猜测客户端项')
    return plan, nodes


async def send_kat_output(bot, chat_id, text):
    # Do not use shared send_long_text's legacy three-chunk cap or split HTML
    # tags. Kat-only chunks preserve every node; reject overlong single lines.
    if not isinstance(text, str) or len(text) > 200000:
        kat_proxy.reject('Kat完整输出超限，未静默截断')
    lines = text.splitlines()
    if any(len(safe(line)) > 3400 for line in lines):
        kat_proxy.reject('Kat单行客户端项超出Telegram安全限额，未静默截断')
    chunks, current = [], ''
    for line in lines:
        escaped = safe(line) + '\n'
        if len(current) + len(escaped) > 3400:
            chunks.append(current);current = ''
        current += escaped
    if current:
        chunks.append(current)
    for chunk in chunks:
        await bot.send_message(chat_id, '<pre>'+chunk+'</pre>', parse_mode=ParseMode.HTML)


async def run_kat_task(bot, chat_id, s, jid, kind, action, requester, ticket):
    key = (server_id(s), kind)
    job = JOBS[jid]
    try:
        if kind not in kat_proxy.KINDS or action not in ('view','ensure','install','kat-confirmed'):
            kat_proxy.reject('不支持的Kat动作，未执行远程命令')
        authorized = None
        if action == 'kat-confirmed':
            authorized = valid_kat_confirmation(ticket, requester, chat_id)
            if (not authorized or authorized['server_id'] != server_id(s) or authorized['kind'] != kind
                    or authorized['host_hash'] != hashlib.sha256(str(s.get('host')).encode()).hexdigest()):
                kat_proxy.reject('Kat安装确认失效，未执行安装')
            KAT_INSTALL_CONFIRMATIONS.pop(ticket, None)  # consume exactly once
        plan, nodes = await read_kat_snapshot(s, kind)
        installed_now = False
        installation_attempted = False
        install_rc = None
        if not nodes and authorized:
            code, answer = await kat_transport(s, kat_proxy.preflight_command(), limit=4096)
            if code != 0 or answer.strip() != 'GUKO_KAT_PREFLIGHT_OK':
                kat_proxy.reject('Kat新装缺前置条件：需要root/Linux amd64/systemd/Python3及已有下载工具；未安装依赖或变更服务')
            source = await resolve_tool(jid, tool_sources.kat_install_source, plan['core'])
            # Re-discover AFTER source resolution; changed authority/JSON stops.
            fresh_plan, fresh_nodes = await read_kat_snapshot(s, kind)
            if fresh_nodes:
                plan, nodes = fresh_plan, fresh_nodes
                job['tool_source']['installation_executed'] = False
            else:
                if fresh_plan['digest'] != plan['digest'] or fresh_plan['config_hashes'] != plan['config_hashes']:
                    kat_proxy.reject('Kat发现信息变化，安装已停止；请重新检查后确认')
                default_port = os.environ.get('GUKO_'+kind.upper()+'_DEFAULT_PORT', '').strip()
                command = kat_proxy.install_command(kind, s.get('host'), default_port, fresh_plan, source)
                installation_attempted = True
                job['tool_source']['installation_attempted'] = True
                code, answer = await kat_transport(s, command, timeout=1600, limit=4096)
                match = re.fullmatch(r'GUKO_KAT_INSTALL_RC:([0-9]+)\s*', answer)
                install_rc = int(match[1]) if match else None
                job['tool_source']['installation_executed'] = True if match is not None else None
                job['tool_source']['installer_exit_code'] = install_rc
                # Never declare success based on manager text. Always reread
                # real units/configs, even when the installer failed or timed out.
                plan, nodes = await read_kat_snapshot(s, kind)
                expected = source['server']
                if (not plan['core'] or plan['core']['sha256'] != expected['sha256']
                        or plan['core']['version'] != expected['version'].lstrip('v')):
                    kat_proxy.reject('安装后Kat内核身份未匹配冻结记录，已停止，不自动重试/升级')
                source['server']['observed_after'] = {'version':plan['core']['version'], 'sha256':plan['core']['sha256']}
                installed_now = code == 0 and install_rc == 0
                if not nodes:
                    kat_proxy.reject('Kat安装未得到所选协议的可靠配置；未宣称成功，请手动检查')
        job['proxy_snapshot'] = {'backend':'kat', 'kernel_record':plan['core'],
            'instances':[{'unit':n['unit'],'config':n['path'],'inbound':n['index'],'state':n['state']} for n in nodes],
            'claim':'configuration files only; connectivity/effective credentials not verified'}
        if not nodes:
            output = '未安装所选Kat协议；本次仅完成只读发现，没有安装或修改。'
            job.update(status='done',log=output,target='view')
            await bot.send_message(chat_id, output)
            await offer_kat_install(bot, chat_id, s, kind, requester)
            return
        output, complete = kat_proxy.render(kind, s.get('host'), nodes)
        if action == 'kat-confirmed' and installation_attempted and not installed_now:
            output = '安装命令未成功完成；以下仅为当前可读取配置，不代表安装成功。\n'+output
            complete = False
        if installed_now:
            # A created but stopped/failed unit must not be called install success.
            if not all(n['state']=='active' for n in nodes):
                complete = False
            output = ('Kat新安装后只读回读（非连通性测试）。\n' if complete else 'Kat安装后存在停止/unsupported状态，未宣称成功。\n')+output
        job.update(status='done' if complete else 'failed', log=output, target=action)
        root = kind_result_dir(s, kind)
        try:
            root.mkdir(parents=True,exist_ok=True,mode=0o700)
            path = root/(jid+'.txt')
            with path.open('x',encoding='utf-8') as handle:
                os.chmod(path,0o600);handle.write(output)
            job['proxy_report_path'] = str(path)
        except Exception:
            job['artifact_error'] = 'Kat完整历史报告未能保存；未重新运行或伪造历史'
        await send_kat_output(bot, chat_id, output)
        if job.get('tool_source'):
            await bot.send_message(chat_id, tool_source_html(job), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except (kat_proxy.KatError, tool_sources.SourceError) as exc:
        job.update(status='failed',log=str(exc),target=action)
        await bot.send_message(chat_id, '❌ '+str(exc))
    except asyncio.CancelledError:
        job.update(status='failed',log='Kat任务已取消；未重试安装，请只读检查当前状态',target=action)
        raise
    except Exception:
        # Do not leak snapshots, installer output, SSH addresses or secrets.
        job.update(status='failed',log='Kat任务未完成；已停止且不回退旧后端/自动重试',target=action)
        await bot.send_message(chat_id, '❌ Kat任务未完成；已停止，请手动检查。')
    finally:
        finish_job(jid,key)


async def run_proxy_tool_task(bot, chat_id, s, jid, kind, action, mode=None, requester=None, install_ticket=None):
    if action not in ('view', 'ensure', 'install', 'kat-confirmed'):
        JOBS[jid].update(status='failed', log='未知代理操作，未执行远程命令')
        finish_job(jid, (server_id(s), kind))
        return
    if kind in kat_proxy.KINDS:
        return await run_kat_task(bot, chat_id, s, jid, kind, action, requester, install_ticket)
    if kind != 'snell':
        JOBS[jid].update(status='failed', log='不支持的代理协议，未执行远程命令')
        finish_job(jid, (server_id(s), kind))
        return
    key = (server_id(s), kind)
    tool = proxy_tool_config(kind)
    try:
        port = os.environ.get(f"GUKO_{kind.upper()}_DEFAULT_PORT", '').strip()
        code, out = await run_subprocess(ssh_args(s, snapshot_command(kind), tty=False),
                                         timeout=300, env=ssh_env_for(s), stdout_only_codes=(SNAPSHOT_EXIT,))
        if code == 10 and action != 'view':
            source = await resolve_tool(jid, tool_sources.script_source, kind)
            # Repeat the existing snapshot guard inside remote_command: a node
            # installed between the two steps is still NEVER overwritten.
            remote = remote_command(kind, action, tool['script_url'],
                                    proxy_answers(kind, port, mode), s.get('host'), mode, port, source=source)
            code, out = await run_subprocess(ssh_args(s, remote, tty=False), timeout=1800,
                                             env=ssh_env_for(s), stdout_only_codes=(SNAPSHOT_EXIT,))
        elif code == 10:
            code, out = 23, 'GUKO_STATUS:未安装，暂无配置'
        if code == SNAPSHOT_EXIT:
            try:
                files = parse_snapshot(kind, out)
                # Validate before invoking even Snell's read-only local -v.
                out = render_snapshot(kind, s.get('host'), files)
                if kind == 'snell':
                    version_code, version_out = await run_subprocess(
                        ssh_args(s, snell_version_command(), tty=False), timeout=15,
                        env=ssh_env_for(s), stdout_only_codes=(0,))
                    out = render_snapshot(kind, s.get('host'), files,
                                          version_out if version_code == 0 else '')
                code = 0
            except ProxyReadError as error:
                code, out = 23, 'GUKO_STATUS:' + str(error)
        elif SNAPSHOT_HEADER in out:
            # Interrupted collection must not expose even encoded credentials.
            code, out = 23, 'GUKO_STATUS:' + READ_ERROR
        sections = proxy_extract_config(out, kind)
        ok = code == 0 and bool(sections)
        JOBS[jid].update({'status': 'done' if ok else 'failed', 'log': out, 'target': action})
        title = '当前配置'
        if action in ('install', 'ensure') and 'GUKO_STATUS:未安装，开始安装' in out:
            title = '安装完成' if ok else '安装失败'
        elif not ok:
            title = '读取失败'
        icon = '✅' if ok else '❌'
        msg = f"{icon} {safe(s.get('name'))} {safe(tool['name'])} {title}"
        if not ok:
            msg += f"（退出码 {safe(code)}）"
        status_lines = [line.split(':', 1)[1] for line in strip_ansi(out or '').splitlines() if line.startswith('GUKO_STATUS:')]
        status_text = '\n'.join(status_lines).strip()
        if status_text:
            msg += f"\n{safe(status_text)}"
        msg += f"\n\n{format_proxy_config_html(sections)}"
        await send_long_text(bot, chat_id, msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        JOBS[jid].update({'status': 'failed', 'log': repr(e), 'target': action})
        await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} {safe(tool['name'])} 任务失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        finish_job(jid, key)


def preserve_tool_output(s, jid, kind, output):
    job = JOBS[jid]
    if not isinstance(output, str):
        raise ValueError('Tool output is not UTF8 text')
    body = output.encode('utf-8', errors='strict')
    if len(body) > ANSI_MAX_BYTES:
        raise ValueError('Tool output exceeds safety limit')
    try:
        root = kind_result_dir(s, kind) / hashlib.sha256(str(jid).encode()).hexdigest()[:24]
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / 'original-output.txt'
        with path.open('x', encoding='utf-8') as handle:
            os.chmod(path, 0o600)
            handle.write(output)
        job['raw_path'] = str(path)
    except Exception:
        job['artifact_error'] = '原始输出存档失败；检测执行状态未被替换'


async def send_original_output(bot, chat_id, output, *, job=None):
    # Untrusted text is HTML escaped. No three-chunk truncation, no guessed
    # business boundaries; used only when optional image/link extraction fails.
    plain = strip_ansi(output)
    for start in range(0, len(plain), 500):
        try:
            await bot.send_message(chat_id, '<pre>'+safe(plain[start:start+500])+'</pre>', parse_mode=ParseMode.HTML)
        except asyncio.CancelledError:
            raise
        except Exception:
            if job is not None:
                job['delivery_error'] = '原始报告发送未完成；执行状态/存档保留'
            return False
    return True


async def run_tcpquality_task(bot, chat_id, s, jid, mode='v4'):
    key = (server_id(s), 'tcpq')

    async def deliver_message(text, **kwargs):
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except Exception as delivery_error:
            JOBS[jid]['delivery_error'] = repr(delivery_error)
            return False

    async def deliver_long_plain(text):
        try:
            await send_long_text(bot, chat_id, text)
            return True
        except Exception as delivery_error:
            JOBS[jid]['delivery_error'] = repr(delivery_error)
            return False

    try:
        config = tcpquality_mode(mode)
        if config['family'] == 'v6' and not server_has_ipv6(s):
            raise RuntimeError('这台服务器没有配置 IPv6')
        label = config['label']
        source = await resolve_tool(jid, tool_sources.tcp_source)
        remote = tcpquality_remote_command(mode, source)
        timeout = 7200 if mode == 'all' else 3600
        code, out = await run_subprocess(
            ssh_args(s, remote, tty=False),
            timeout=timeout,
            env=ssh_env_for(s),
        )
        preserve_tool_output(s, jid, 'tcpq', out)
        report = tcpquality_url(out)
        JOBS[jid].update({
            'log': out,
            'selected': label,
            'target': mode,
            'report_url': report,
        })

        if not config['report_required']:
            clean_output = tcpquality_text_output(out)
            if code != 0:
                JOBS[jid]['status'] = 'failed'
                await deliver_message(
                    f"❌ {safe(s.get('name'))} TCPQuality {safe(label)}失败，"
                    f"退出码 <code>{safe(code)}</code>。\n"
                    f"<pre>{safe(trim_log(clean_output))}</pre>",
                    parse_mode=ParseMode.HTML,
                )
                return
            JOBS[jid].update({'status': 'done', 'media_paths': []})
            await deliver_message(
                f"✅ {safe(s.get('name'))} TCPQuality 完成：{safe(label)}\n\n"
                f"{script_command_html('tcpq', mode=mode, source=JOBS[jid].get('tool_source'))}",
                parse_mode=ParseMode.HTML,
            )
            await send_original_output(bot, chat_id, clean_output or '脚本执行成功，但没有文本输出。', job=JOBS[jid])
            return

        if not report:
            JOBS[jid].update(status='done' if code == 0 and out.strip() else 'failed', exit_code=code,
                              extraction_error='未提取到既有官方报告URL；保留上游原始输出')
            await deliver_message(f"TCPQuality 退出码 {code}；未提取到报告链接，以下为原始输出（不代表提取成功）。")
            await send_original_output(bot, chat_id, out, job=JOBS[jid])
            return

        clear_result_files(s, 'tcpq')
        media_paths = []
        image_errors = []
        safe_sid = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(server_id(s)))
        with tempfile.TemporaryDirectory(prefix='guko-tcpq-') as td:
            out_dir = Path(td)
            for section in config['sections']:
                image_url = f'{report}.png?section={section}'
                png = out_dir / f'tcpq-{safe_sid}-{section}.png'
                try:
                    await fetch_tcpquality_png(image_url, png)
                    saved = persist_result_file(s, 'tcpq', png, f'-{section}.png', clear=False)
                    if saved:
                        media_paths.append(saved)
                    with png.open('rb') as photo:
                        await bot.send_photo(chat_id, photo=photo)
                except Exception as image_error:
                    image_errors.append(f'{section}: {trim_log(str(image_error), 300)}')

        JOBS[jid].update({
            'status': 'done',
            'media_paths': media_paths,
        })
        msg = (
            f"✅ {safe(s.get('name'))} TCPQuality 完成：{safe(label)}\n\n"
            f"{safe(report)}\n\n"
            f"{script_command_html('tcpq', mode=mode, source=JOBS[jid].get('tool_source'))}"
        )
        if code != 0:
            msg += f"\n\n⚠️ 脚本退出码为 <code>{safe(code)}</code>，但报告已经生成。"
        if image_errors:
            msg += f"\n\n部分报告图未生成：<code>{safe('；'.join(image_errors))}</code>"
        await deliver_message(
            msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        job = JOBS[jid]
        if job.get('status') != 'done':
            job.update({'status': 'failed', 'target': mode})
        job.setdefault('log', repr(e))
        await deliver_message(
            f"❌ {safe(s.get('name'))} TCPQuality 任务失败：<code>{safe(e)}</code>",
            parse_mode=ParseMode.HTML,
        )
    finally:
        finish_job(jid, key)


async def run_ip_quality_task(bot, chat_id, s, jid, ip_mode='4'):
    key = (server_id(s), 'ipq')
    try:
        endpoint = ssh_endpoint(s)
        source = await resolve_tool(jid, tool_sources.script_source, 'ipq')
        remote = '(' + IPV6_PROBE_COMMAND + '); ' + ipquality_remote_command(ip_mode, source=source)
        code, out, _first_url = await run_until_report(
            ssh_args(s, remote, tty=False), timeout=1800 if ip_mode == '46' else 900,
            env=ssh_env_for(s), wait_for_exit=ip_mode == '46',
        )
        preserve_tool_output(s, jid, 'ipq', out)
        ipv6_status = update_ipv6_from_output(s, out, expected_endpoint=endpoint)
        reports = ipquality_ansi_reports(out)
        if ip_mode == '4':
            reports = reports[:1]
        # Upstream ends with a conditional IPv6 check; unavailable IPv6 exits 1.
        completed = bool(reports) and code in (0, 1)
        JOBS[jid].update({'status': 'done' if completed else 'failed', 'log': out,
                          'ip_mode': nq_ip_mode_text(ip_mode), 'media_paths': []})
        if not reports:
            JOBS[jid].update(status='done' if code == 0 and out.strip() else 'failed', exit_code=code,
                              extraction_error='报告边界/图片提取未识别；保留原输出')
            await send_original_output(bot, chat_id, out, job=JOBS[jid])
            links = all_report_urls(out, 'ip')
            message = f"IP质量脚本退出码 {code}；未识别既有展示边界，已转发原始输出（非检测结论重建）。\n" + '\n'.join(safe(u) for u in links)
        else:
            errors = []
            media_paths = JOBS[jid]['media_paths']
            with tempfile.TemporaryDirectory(prefix='guko-ipq-') as td:
                for index, (url, raw_report) in enumerate(reports, 1):
                    png = Path(td) / f'report-{index}.png'
                    try:
                        await render_ansi_png(raw_report, png, kind='ip')
                        saved = persist_result_file(s, 'ipq', png, f'-{index}.png', clear=not media_paths)
                        if saved:
                            media_paths.append(saved)
                    except Exception as e:
                        errors.append(f'第 {index} 份转 PNG 失败：{e}')
                        continue
                    try:
                        with png.open('rb') as photo:
                            await bot.send_photo(chat_id, photo=photo)
                    except Exception as e:
                        errors.append(f'第 {index} 份图片发送失败：{e}')
            state = '✅' if completed else '⚠️'
            result = '完成' if completed else f'未完成（退出码 {code}，保留已生成报告）'
            message = f"{state} {safe(s.get('name'))} IP质量{result}（{safe(nq_ip_mode_text(ip_mode))}）\n"
            message += '\n'.join(safe(url) if url else f'第 {index} 份报告：上游未提供公开链接，已保留终端报告。'
                                 for index, (url, _raw) in enumerate(reports, 1))
            if ip_mode == '46' and len(reports) == 1 and not (ipv6_status is not None and not ipv6_status[0]):
                message += '\n\n双栈模式仅收到一份报告，另一协议可能不可用或未生成。'
            message += f"\n\n{script_command_html('ipq', ip_mode=ip_mode)}"
            if errors:
                message += '\n\n' + safe(trim_log('；'.join(errors), 800))
                JOBS[jid]['render_error'] = '；'.join(errors)
                await send_original_output(bot, chat_id, out, job=JOBS[jid])
        if ipv6_status is not None and not ipv6_status[0]:
            message += '\n\n⚠️ 没有可用 IPv6，已更新服务器 IP 状态；本次仅测试 IPv4。'
        try:
            await bot.send_message(chat_id, message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            JOBS[jid]['delivery_error'] = str(e)
    except Exception as e:
        if JOBS[jid].get('status') == 'done':
            JOBS[jid]['delivery_error'] = repr(e)
        else:
            JOBS[jid].update(status='failed')
            JOBS[jid].setdefault('log', repr(e))
        try:
            await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} IP质量任务失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
        except Exception as delivery_error:
            JOBS[jid]['delivery_error'] = str(delivery_error)
    finally:
        finish_job(jid, key)


async def fetch_checkplace_svg_from_json(category, json_path):
    # Check.Place rejects replayed/masked JSON from nodequality.com exports, so this
    # is only a best-effort fallback for future unmasked JSON cases. Normal path
    # should parse the SVG printed by the live sub-script stdout.
    if not json_path.exists() or json_path.stat().st_size <= 0:
        return None
    script = (
        "json_file=$1; category=$2; "
        "curl -s -X POST https://upload.check.place "
        "-d type=$category --data-urlencode json@$json_file --data-urlencode content="
    )
    code, text = await run_subprocess(['bash', '-lc', script, 'bash', str(json_path), category], timeout=60)
    if code != 0:
        return None
    m = re.search(r'https://Report\.Check\.Place/[^\s<>"]+\.svg', text)
    return m.group(0) if m else None


def report_log_from_nodequality_url(text):
    token = None
    nq = nodequality_url(text)
    if nq:
        token = nq.rstrip('/').split('/')[-1]
    return f"https://api.nodequality.com/api/v1/record/{token}" if token else None


def nodequality_token(text):
    nq = nodequality_url(text)
    return nq.rstrip('/').split('/')[-1] if nq else None


async def upload_nodequality_result_from_remote(s):
    """Re-upload exactly like official NodeQuality.sh: base64(result.zip) as raw POST body."""
    remote = r'''set -e
z=""
for d in $(ls -td /root/.nodequality* /tmp/.nodequality* 2>/dev/null); do
  if [ -s "$d/result.zip" ]; then z="$d/result.zip"; break; fi
done
[ -n "$z" ] || exit 2
# Official NodeQuality.sh does: base64 result.zip | curl --data-binary @-
base64 "$z" | curl -fsS -X POST --data-binary @- https://api.nodequality.com/api/v1/record
'''
    code, out = await run_subprocess(ssh_args(s, remote, tty=False), timeout=120, env=ssh_env_for(s))
    if code != 0:
        return None
    return nodequality_url(out)


async def recover_report_links_from_remote(s, selected):
    cats = []
    for label, cat, bit in [('硬件', 'hardware', 1), ('IP质量', 'ip', 2), ('网络', 'net', 4), ('回程', 'backroute', 8)]:
        if selected & bit:
            cats.append((label, cat))
    if not cats:
        return []
    remote = """td=$(mktemp -d /tmp/nqrecover.XXXXXX)
for d in $(ls -td /root/.nodequality* /tmp/.nodequality* 2>/dev/null); do
  r=\"$d/BenchOs/result\"
  [ -d \"$r\" ] || { [ -s \"$d/result.zip\" ] && unzip -oq \"$d/result.zip\" -d \"$td\" && r=\"$td\" || continue; }
  for pair in hardware:hardware_quality.json ip:ip_quality.json net:net_quality.json backroute:backroute_trace.json; do
    cat=${pair%%:*}; fn=${pair#*:}; p=\"$r/$fn\"
    [ -s \"$p\" ] && printf '%s\t%s\n' \"$cat\" \"$p\"
  done
done || true"""
    code, out = await run_subprocess(ssh_args(s, remote, tty=False), timeout=30, env=ssh_env_for(s))
    if code != 0:
        return []
    mapping = {}
    for line in out.splitlines():
        if '\t' not in line:
            continue
        cat, path = line.split('\t', 1)
        mapping.setdefault(cat, path)
    recovered = []
    with tempfile.TemporaryDirectory() as td:
        for label, cat in cats:
            rp = mapping.get(cat)
            if not rp:
                continue
            local = Path(td) / f'{cat}.json'
            scp_args = scp_from_args(s, rp, str(local), inv=load_inventory())
            c, scp_out = await run_subprocess(scp_args, timeout=60, env=ssh_env_for(s))
            if c != 0:
                c, data = await run_subprocess(ssh_args(s, f"cat {shlex.quote(rp)}", tty=False), timeout=60, env=ssh_env_for(s))
                if c != 0:
                    continue
                local.write_text(data)
            try:
                u = await fetch_checkplace_svg_from_json(cat, local)
            except Exception:
                u = None
            if u:
                recovered.append((label, u))
    return recovered


def canonical_geekbench5_url(text):
    match = re.search(r'https://browser\.geekbench\.com/v5/cpu/(\d+)', str(text or ''), re.I)
    return f'https://browser.geekbench.com/v5/cpu/{match.group(1)}' if match else None


def sanitize_geekbench5_output(text):
    return re.sub(
        r'(https://browser\.geekbench\.com/v5/cpu/\d+)/claim\?key=[^\s<>"\']+',
        r'\1',
        str(text or ''),
        flags=re.I,
    )


def parse_geekbench5_scores(text):
    clean = strip_ansi(sanitize_geekbench5_output(text))
    scores = {}
    patterns = {
        'single': r'Single-Core Score\s+(\d+)',
        'multi': r'Multi-Core Score\s+(\d+)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, clean, re.I)
        if m:
            scores[key] = m.group(1)
    url = canonical_geekbench5_url(clean)
    if url:
        scores['url'] = url
    return scores


def fetch_geekbench5_csv_scores(result_url):
    url = canonical_geekbench5_url(result_url)
    if not url:
        raise ValueError('invalid Geekbench 5 result URL')
    request = urllib.request.Request(
        url + '.csv',
        headers={'User-Agent': 'GUKO/Geekbench5'},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(65536).decode('utf-8', errors='replace')
    rows = {}
    for row in csv.reader(raw.splitlines()):
        if len(row) >= 2 and row[0] not in rows:
            rows[row[0]] = row[1]
    single = str(rows.get('Single-Core') or '').strip()
    multi = str(rows.get('Multi-Core') or '').strip()
    if not single.isdigit() or not multi.isdigit():
        raise ValueError('Geekbench 5 CSV does not contain valid scores')
    return {
        'url': url,
        'single': single,
        'multi': multi,
        'model': str(rows.get('Model') or '').strip(),
        'processor': str(rows.get('Processor') or '').strip(),
        'platform': str(rows.get('Platform') or '').strip(),
    }

def gb5_result_image(s, scores, out_png):
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    width, height = 940, 520
    background = (245, 247, 250)
    white = (255, 255, 255)
    dark = (30, 41, 59)
    muted = (100, 116, 139)
    line = (226, 232, 240)
    blue = (47, 111, 191)
    blue_track = (219, 234, 254)
    green = (22, 163, 74)
    green_track = (220, 252, 231)
    try:
        font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
        font_summary = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
        font_score = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 82)
        font_label = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
    except Exception:
        font_title = font_summary = font_score = font_label = ImageFont.load_default()

    single = str(scores.get('single') or '-')
    multi = str(scores.get('multi') or '-')
    image = Image.new('RGB', (width, height), background)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle([24, 20, width - 24, 275], radius=18, fill=white, outline=line, width=2)
    draw.text((55, 42), 'Geekbench 5 Score', fill=muted, font=font_title)
    draw.line([width // 2, 82, width // 2, 245], fill=line, width=2)
    draw.text((235, 115), single, fill=dark, font=font_score, anchor="ma")
    draw.text((705, 115), multi, fill=dark, font=font_score, anchor="ma")
    draw.text((235, 238), 'Single-Core Score', fill=muted, font=font_label, anchor="ma")
    draw.text((705, 238), 'Multi-Core Score', fill=muted, font=font_label, anchor="ma")

    try:
        single_value = max(0, int(single))
        multi_value = max(0, int(multi))
    except ValueError:
        single_value = multi_value = 0
    score_max = max(single_value, multi_value, 1)
    bar_left = 245
    bar_width = 520
    bar_height = 18
    single_fill = max(bar_height, round(bar_width * single_value / score_max))
    multi_fill = max(bar_height, round(bar_width * multi_value / score_max))

    draw.rounded_rectangle([24, 300, width - 24, 495], radius=18, fill=white, outline=line, width=2)
    draw.text((55, 322), 'Benchmark Summary', fill=dark, font=font_summary)
    for label, value, top, fill_width, track, fill in (
        ('Single-Core', single, 390, single_fill, blue_track, blue),
        ('Multi-Core', multi, 455, multi_fill, green_track, green),
    ):
        draw.text((55, top - 9), label, fill=muted, font=font_label)
        draw.rounded_rectangle(
            [bar_left, top, bar_left + bar_width, top + bar_height],
            radius=bar_height // 2,
            fill=track,
        )
        draw.rounded_rectangle(
            [bar_left, top, bar_left + min(bar_width, fill_width), top + bar_height],
            radius=bar_height // 2,
            fill=fill,
        )
        draw.text((875, top - 10), value, fill=dark, font=font_label, anchor='ra')

    image.save(out_png, quality=95)
    return out_png

def gb5_remote_command(source):
    version = source['version']
    if not re.fullmatch(r'5\.[0-9]+\.[0-9]+', version):
        raise tool_sources.SourceError('不是可确认的Geekbench 5正式包，已停止。')
    return (
        "set -e; export TERM=xterm-256color; cd /root; "
        'case "$(uname -m)" in x86_64|amd64) :;; *) echo "GUKO: GB5 unsupported architecture"; exit 65;; esac; '
        'bundle=$(mktemp -d /root/guko-gb5.XXXXXXXX); swapfile=; '
        'cleanup(){ if [ -n "$swapfile" ]; then swapoff "$swapfile" 2>/dev/null || true; rm -f "$swapfile"; fi; rm -rf "$bundle"; }; '
        "trap cleanup EXIT; trap 'exit 130' HUP INT TERM; "
        + tool_sources.shell_download(source, '"$bundle/package.tar.gz"')
        + 'tar -xzf "$bundle/package.tar.gz" -C "$bundle"; '
        + 'd="$bundle/Geekbench-' + version + '-Linux"; '
        + '[ -x "$d/geekbench5" ] || exit 65; '
        + "mem_available_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo); "
        "swap_free_kb=$(awk '/SwapFree:/ {print $2}' /proc/meminfo); "
        "memory_headroom_kb=$((${mem_available_kb:-0} + ${swap_free_kb:-0})); "
        'if [ $memory_headroom_kb -lt 1500000 ]; then swapfile="$bundle/geekbench5.swap"; '
        '(fallocate -l 2G "$swapfile" 2>/dev/null || dd if=/dev/zero of="$swapfile" bs=1M count=2048 status=none); '
        'chmod 600 "$swapfile"; mkswap "$swapfile" >/dev/null; swapon "$swapfile"; fi; '
        + "oom_before=$(awk '$1 == \"oom_kill\" {print $2}' /proc/vmstat); "
        + 'set +e; "$d/geekbench5" --upload 2>&1; rc=$?; set -e; '
        + "oom_after=$(awk '$1 == \"oom_kill\" {print $2}' /proc/vmstat); "
        + 'if [ ${oom_after:-0} -gt ${oom_before:-0} ]; then echo ' + shlex.quote(GB5_OOM_MARKER) + '; fi; exit $rc'
    )


async def run_gb5_task(bot, chat_id, s, jid):
    key = (server_id(s), 'gb5')
    try:
        source = await resolve_tool(jid, tool_sources.gb5_source)
        remote = gb5_remote_command(source)
        code, out = await run_subprocess(ssh_args(s, remote, tty=False), timeout=3600, env=ssh_env_for(s))
        preserve_tool_output(s, jid, 'gb5', out)
        oom_killed = GB5_OOM_MARKER in out
        out = sanitize_geekbench5_output(
            out.replace(GB5_OOM_MARKER, 'GUKO：系统内存不足，Geekbench 被 OOM Killer 终止。')
        )
        scores = parse_geekbench5_scores(out)
        gb_urls = [canonical_geekbench5_url(u) for u in extract_urls(out)]
        gb_urls = [u for u in gb_urls if u]
        if gb_urls:
            scores['url'] = gb_urls[-1]
        if scores.get('url') and not (scores.get('single') and scores.get('multi')):
            try:
                scores.update(await asyncio.to_thread(fetch_geekbench5_csv_scores, scores['url']))
            except Exception:
                pass
        JOBS[jid].update({'status': 'done' if code == 0 and scores.get('url') else 'failed', 'log': out})
        if code != 0 or not scores.get('url'):
            reason = '内存不足，Geekbench 被系统 OOM Killer 终止。' if oom_killed else '没拿到结果链接。'
            await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} GB5 {reason}\n<pre>{safe(trim_log(out))}</pre>", parse_mode=ParseMode.HTML)
            return
        if scores.get('single') and scores.get('multi'):
            try:
                img = gb5_result_image(s, scores, RESULTS_DIR / str(server_id(s)) / 'gb5' / 'latest.jpg')
                JOBS[jid].update({'media_path': str(img)})
                with img.open('rb') as f:
                    await bot.send_photo(chat_id, photo=f)
            except Exception:
                JOBS[jid]['render_error'] = '可选评分图未交付；原报告URL/输出保留'
                await send_original_output(bot, chat_id, out, job=JOBS[jid])
        await bot.send_message(chat_id, f"✅ {safe(s.get('name'))} GB5 完成\n{safe(scores['url'])}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        if JOBS[jid].get('status') == 'done':
            JOBS[jid]['delivery_error'] = repr(e)
        else:
            JOBS[jid].update(status='failed')
            JOBS[jid].setdefault('log', repr(e))
        await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} GB5任务失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        finish_job(jid, key)







def load_font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()






def ansi_to_spans(text):
    palette = {
        30: (51, 65, 85), 90: (100, 116, 139),
        31: (220, 38, 38), 91: (220, 38, 38),
        32: (22, 163, 74), 92: (22, 163, 74),
        33: (202, 138, 4), 93: (202, 138, 4),
        34: (37, 99, 235), 94: (37, 99, 235),
        35: (192, 38, 211), 95: (192, 38, 211),
        36: (8, 145, 178), 96: (8, 145, 178),
        37: (30, 41, 59), 97: (15, 23, 42),
    }
    default = (30, 41, 59)
    spans = []
    color = default
    bold = False
    i = 0
    buf = ''
    while i < len(text):
        if text[i] == '\x1b' and i + 1 < len(text) and text[i + 1] == '[':
            m = re.match(r'\x1b\[([0-9;]*)m', text[i:])
            if m:
                if buf:
                    spans.append((buf, color, bold))
                    buf = ''
                codes = [int(x) if x else 0 for x in m.group(1).split(';')]
                if not codes:
                    codes = [0]
                for code in codes:
                    if code == 0:
                        color = default
                        bold = False
                    elif code == 1:
                        bold = True
                    elif code == 22:
                        bold = False
                    elif code in palette:
                        color = palette[code]
                i += len(m.group(0))
                continue
        buf += text[i]
        i += 1
    if buf:
        spans.append((buf, color, bold))
    return spans



def terminal_char_width(ch):
    o = ord(ch)
    if o == 0:
        return 0
    if o < 32 or 0x7f <= o < 0xa0:
        return 0
    # CJK / fullwidth ranges; enough for NextTrace Chinese geo/ISP labels.
    if (
        0x1100 <= o <= 0x115f or 0x2e80 <= o <= 0xa4cf or
        0xac00 <= o <= 0xd7a3 or 0xf900 <= o <= 0xfaff or
        0xfe10 <= o <= 0xfe19 or 0xfe30 <= o <= 0xfe6f or
        0xff00 <= o <= 0xff60 or 0xffe0 <= o <= 0xffe6
    ):
        return 2
    return 1


def terminal_text_width(text):
    return sum(terminal_char_width(ch) for ch in strip_ansi(text or ''))


def draw_terminal_spans(draw, x0, y, spans, *, cell_w, ascii_font, ascii_bold, cjk_font, cjk_bold):
    col = 0
    for text, color, bold in spans:
        for ch in text:
            w = terminal_char_width(ch)
            if w <= 0:
                continue
            is_cjk = w == 2
            font = (cjk_bold if bold else cjk_font) if is_cjk else (ascii_bold if bold else ascii_font)
            # Draw every glyph onto a fixed terminal grid. This keeps NextTrace's original column layout
            # while still letting CJK render with a CJK font.
            draw.text((x0 + col * cell_w, y), ch, fill=color, font=font)
            col += w

def render_nexttrace_image(s, target, out, code, out_png):
    raw = (out or '').replace('\r\n', '\n').replace('\r', '\n')
    raw = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', lambda m: m.group(0) if m.group(0).endswith('m') else '', raw)
    lines = []
    for line in raw.split('\n'):
        if 'Generated by' in strip_ansi(line) or 'MapTrace URL:' in strip_ansi(line):
            continue
        lines.append(line.rstrip())
    while lines and not strip_ansi(lines[0]).strip():
        lines.pop(0)
    while lines and not strip_ansi(lines[-1]).strip():
        lines.pop()
    if not lines:
        lines = ['无输出']

    title_font = load_font([
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ], 42)
    mono_font = load_font([
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    ], 24)
    mono_bold = load_font([
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
    ], 24)
    cjk_font = load_font([
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ], 24)
    cjk_bold = load_font([
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    ], 24)

    dummy = Image.new('RGB', (1, 1))
    d0 = ImageDraw.Draw(dummy)
    char_w = max(13, int(d0.textlength('M', font=mono_font)))
    line_h = 34
    max_cols = min(150, max(78, max((terminal_text_width(x) for x in lines), default=78)))
    W = max(1180, min(2100, 112 + max_cols * char_w))
    H = 150 + max(1, len(lines)) * line_h + 42

    bg = (248, 250, 252)
    panel = (255, 255, 255)
    border = (203, 213, 225)
    fg = (15, 23, 42)
    muted = (100, 116, 139)
    accent = (2, 132, 199)
    warn = (202, 138, 4)
    err = (220, 38, 38)

    im = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((28, 24, W - 28, H - 28), radius=24, fill=panel, outline=border, width=2)
    d.rounded_rectangle((48, 44, W - 48, 118), radius=18, fill=(241, 245, 249), outline=(203, 213, 225), width=1)
    title = 'NextTrace'
    title_box = d.textbbox((0, 0), title, font=title_font)
    title_h = title_box[3] - title_box[1]
    title_y = 44 + (118 - 44 - title_h) / 2 - title_box[1]
    d.text((72, title_y), title, fill=accent, font=title_font)
    source_name = source_repo('nexttrace')
    source_w = d.textlength(source_name, font=mono_font)
    d.text((W - 72 - source_w, 72), source_name, fill=muted, font=mono_font)
    if code != 0:
        d.text((W - 260, 96), f'退出码 {code}', fill=warn, font=mono_font)
    d.line((54, 126, W - 54, 126), fill=border, width=1)

    y = 148
    x0 = 68
    for line in lines:
        x = x0
        plain = strip_ansi(line)
        if plain.startswith('traceroute to') or 'hops max' in plain:
            d.rounded_rectangle((54, y - 4, W - 54, y + line_h - 2), radius=8, fill=(248, 250, 252), outline=(226, 232, 240), width=1)
        draw_terminal_spans(
            d, x0, y, ansi_to_spans(line),
            cell_w=char_w,
            ascii_font=mono_font,
            ascii_bold=mono_bold,
            cjk_font=cjk_font,
            cjk_bold=cjk_bold,
        )
        y += line_h

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_png, quality=95)
    return out_png

def nexttrace_prompt_text(s):
    return (
        f'🛣 <b>{safe(s.get("name"))} NextTrace</b>\n\n'
        '请直接发送要追踪的 <b>IP 或域名</b>。\n'
        '例如：<code>1.1.1.1</code> 或 <code>cloudflare.com</code>\n\n'
        '也可以用命令：<code>/nexttrace 服务器 目标IP或域名</code>'
    )


def format_nexttrace_output(s, target, out, code):
    clean = strip_ansi(out or '').replace('\r', '')
    lines = []
    for raw in clean.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        skip = [
            'NextTrace', 'nali', 'MapTrace', 'IP Geo Data Provider',
            'traceroute to', 'Generated by', '请勿用于商业用途',
        ]
        if any(x.lower() in line.lower() for x in skip):
            continue
        lines.append(line)
    body = '\n'.join(lines).strip() or clean.strip() or '无输出'
    body = trim_log(body, 3200)
    title = f'🛣 <b>{safe(s.get("name"))} NextTrace</b> → <code>{safe(target)}</code>'
    if code != 0:
        title = '⚠️ ' + title + f'\n退出码：<code>{safe(code)}</code>'
    return title + '\n\n<pre>' + safe(body) + '</pre>'


async def run_nexttrace_task(bot, chat_id, s, jid, target='1.1.1.1'):
    key = (server_id(s), 'nexttrace')
    try:
        arch_code, arch = await run_subprocess(ssh_args(s, 'LC_ALL=C uname -m', tty=False), timeout=20, env=ssh_env_for(s))
        if arch_code != 0:
            raise tool_sources.SourceError('NextTrace架构读取失败，已停止。')
        source = await resolve_tool(jid, tool_sources.nexttrace_source, arch.strip())
        # The quoted command is interpreted only after an owned directory exists.
        trace_cmd = '"$bundle/nexttrace" ' + shlex.quote(str(target))
        remote = (
            "set -eu; umask 077; export TERM=xterm-256color COLORTERM=truecolor CLICOLOR_FORCE=1 FORCE_COLOR=1; "
            'command -v script >/dev/null 2>&1 || exit 127; '
            'bundle=$(mktemp -d /tmp/guko-nexttrace.XXXXXXXX); export bundle; child=; '
            'cleanup(){ if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi; rm -rf "$bundle"; }; '
            "trap cleanup EXIT; trap 'exit 130' HUP INT TERM; "
            + tool_sources.shell_download(source['binary'], '"$bundle/nexttrace"')
            + 'chmod 700 "$bundle/nexttrace"; script -qfec ' + shlex.quote(trace_cmd) + ' /dev/null 2>&1 & child=$!; '
            + 'set +e; wait "$child"; rc=$?; child=; exit "$rc"'
        )
        code, out = await run_subprocess(ssh_args(s, remote, tty=False), timeout=300, env=ssh_env_for(s))
        preserve_tool_output(s, jid, 'nexttrace', out)
        JOBS[jid].update({'status': 'done' if code == 0 else 'failed', 'log': out, 'target': target})
        out_dir = Path('/tmp/guko-results')
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / f"nexttrace-{server_id(s)}-{safe_target(target)}-{int(time.time())}.jpg"
        try:
            img = render_nexttrace_image(s, target, out, code, png)
        except Exception:
            img = None
        if img:
            saved = persist_result_file(s, 'nexttrace', img, '.jpg')
            JOBS[jid].update({'media_path': saved})
            with img.open('rb') as f:
                await bot.send_photo(chat_id, photo=f)
            await bot.send_message(chat_id, script_command_text('nexttrace', target=target, source=JOBS[jid].get('tool_source')))
            if code != 0:
                await bot.send_message(chat_id, '提示：NextTrace 退出码不为 0，图片是已抓到的部分结果。')
        else:
            await bot.send_message(chat_id, format_nexttrace_output(s, target, out, code), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        if JOBS[jid].get('status') == 'done':
            JOBS[jid]['delivery_error'] = repr(e)
        else:
            JOBS[jid].update(status='failed')
            JOBS[jid].setdefault('log', repr(e))
        await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} NextTrace 失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        finish_job(jid, key)


async def run_stream_task(bot, chat_id, s, jid):
    """One native CLI measurement, one JSON/ANSI report and one image."""
    key = (server_id(s), 'stream')
    label = '实际出口自动地区'
    mode = str(JOBS[jid].get('ip_mode') or 'auto')
    if mode not in ('4', '6', 'auto'):
        mode = 'auto'
    token = hashlib.sha256(str(jid).encode()).hexdigest()[:24]
    root = kind_result_dir(s, 'stream-unified') / token
    job = JOBS[jid]
    job.update(region=label, selected='upstream original report', proto='CLI default core policy; extra-family requested: ' + mode,
               report_format='guko-unified-v1', json_path=None)
    terminal = None
    try:
        job['tool_source'] = {}
        code, raw, stderr, cleanup_error = await stream_unified.remote_run(
            s, ssh_args, ssh_env_for, family=mode, identity_out=job['tool_source'])
        job.update(exit_code=code, stderr=stderr, log_tail=trim_log(strip_ansi(raw), 3500))
        if cleanup_error:
            job['cleanup_error'] = cleanup_error
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            (root / 'transport-output.txt').write_text(raw, encoding='utf-8')
            (root / 'stderr.txt').write_text(stderr, encoding='utf-8')
        except Exception as exc:
            job['artifact_error'] = repr(exc)
        report, terminal, inconclusive = stream_unified.validate_output(raw, code, family=mode)
        # Selection is untrusted raw upstream metadata, never reconstructed or
        # used as proof of counts, countries, verdicts or rendering semantics.
        if 'selection' in report:
            job['selection'] = report['selection']
        job.update(status='inconclusive' if inconclusive else 'done',
                   log=terminal, log_tail=trim_log(strip_ansi(terminal), 3500))
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            raw_path, json_path = root / 'report.txt', root / 'report.json'
            raw_path.write_text(terminal, encoding='utf-8')
            json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            job.update(raw_path=str(raw_path), json_path=str(json_path))
        except Exception as exc:
            job['artifact_error'] = repr(exc)
        delivered = False
        try:
            with tempfile.TemporaryDirectory(prefix='guko-stream-unified-') as tmp:
                rendered = Path(tmp) / 'report.png'
                await render_ansi_png(terminal, rendered, kind='stream')
                image = rendered
                try:
                    root.mkdir(parents=True, exist_ok=True, mode=0o700)
                    saved = root / 'report.png'
                    shutil.copy2(rendered, saved)
                    job.update(media_path=str(saved), media_paths=[str(saved)])
                    image = saved
                except Exception as exc:
                    job['artifact_error'] = repr(exc)
                try:
                    with image.open('rb') as photo:
                        await bot.send_photo(chat_id, photo=photo,
                            caption=f'🎬 <b>{safe(s.get("name"))} 流媒体完整报告</b>\n'
                                    f'{safe(label)}；内容/布局/地区与结论均为本次CLI原报告。\n'
                                    + stream_source_offer(job),
                            parse_mode=ParseMode.HTML)
                    delivered = True
                except Exception as exc:
                    job['delivery_error'] = repr(exc)
        except Exception as exc:
            job['render_error'] = repr(exc)
        if not delivered:
            # Send useful chunks rather than silently truncating a large unified report.
            plain = strip_ansi(terminal)
            for start in range(0, len(plain), 2800):
                try:
                    await bot.send_message(chat_id,
                        f'🎬 <b>{safe(s.get("name"))} 流媒体完整报告（文本）</b>\n' +
                        (stream_source_offer(job) + '\n' if start == 0 else '') +
                        '<pre>' + safe(plain[start:start+2800]) + '</pre>',
                        parse_mode=ParseMode.HTML)
                except Exception as exc:
                    job['delivery_error'] = (job.get('delivery_error', '') + '; ' + repr(exc)).strip('; ')
                    break
    except asyncio.CancelledError:
        job['status'] = 'cancelled'
        raise
    except Exception as exc:
        job.update(status='failed', error=repr(exc))
        if getattr(exc, 'supplement_cleanup_error', None):
            job['cleanup_error'] = exc.supplement_cleanup_error
        try:
            await bot.send_message(chat_id, f'⚠️ <b>{safe(s.get("name"))} 新版完整检测未完成</b>：<code>{safe(trim_log(str(exc), 700))}</code>', parse_mode=ParseMode.HTML)
        except Exception as delivery:
            job['delivery_error'] = repr(delivery)
    finally:
        try:
            finish_job(jid, key)
        except Exception as exc:
            # History storage failure is separate from the completed probe result.
            job['artifact_error'] = repr(exc)
            RUNNING.discard(key)


async def run_nq_task(bot, chat_id, s, jid, mask=NQ_ALL_MASK, ip_mode='4'):
    key = (server_id(s), 'nq')
    work_dir = None
    try:
        selected_text = nq_selected_text(mask)
        ip_text = nq_ip_mode_text(ip_mode)
        endpoint = ssh_endpoint(s)
        source = await resolve_tool(jid, tool_sources.script_source, 'nq')
        work_dir = '/root/guko-nodequality-' + os.urandom(16).hex()
        remote = '(' + IPV6_PROBE_COMMAND + '); ' + nodequality_remote_command(s, mask, ip_mode, work_dir=work_dir, source=source)
        code, out = await run_subprocess(ssh_args(s, remote, tty=False), timeout=7200, env=ssh_env_for(s))
        preserve_tool_output(s, jid, 'nq', out)
        ipv6_status = update_ipv6_from_output(s, out, expected_endpoint=endpoint)
        JOBS[jid].update({'log': out, 'selected': selected_text, 'ip_mode': ip_text})
        nq = nodequality_url(out)
        gb_urls = geekbench_urls(out)
        # Keep the URL generated by the official NodeQuality script. Re-uploading
        # result.zip can create a record that opens with `bad token` / JSON parse
        # errors on nodequality.com, so do not replace the original link here.
        report_links = []
        for label, cat, bit in [('硬件', 'hardware', 1), ('IP质量', 'ip', 2), ('网络', 'net', 4), ('回程', 'backroute', 8)]:
            if not (mask & bit):
                continue
            urls = all_report_urls(out, cat)
            if urls:
                report_links.append((label, urls[-1]))
        image_ok = False
        image_error = ''
        # Full selections keep their combined link only. For partial selections,
        # use this invocation's official raw logs, never old directories or SVG.
        if mask != NQ_ALL_MASK:
            try:
                try:
                    raw_logs = await read_nodequality_ansi_logs(s, work_dir, mask)
                except Exception:
                    raw_logs = nodequality_stdout_logs(out, mask)
                image_entries = []
                for label, kind, bit, _filename in NQ_ANSI_REPORTS:
                    if not mask & bit:
                        continue
                    urls = all_report_urls(raw_logs.get(kind, ''), kind)
                    url = next((u for name, u in report_links if name == label), '')
                    if not url and urls:
                        url = urls[-1]
                        report_links.append((label, url))
                    image_entries.append((label, url))
                sent = await send_ansi_report_images(bot, chat_id, image_entries, f"nq-{server_id(s)}", raw_logs)
                media_paths = []
                clear_result_files(s, 'nq')
                for label, url, png in sent:
                    saved = persist_result_file(s, 'nq', png, f'-{label}.png', clear=False)
                    if saved:
                        media_paths.append(saved)
                if media_paths:
                    JOBS[jid].update({'media_paths': media_paths})
                image_ok = True
            except Exception as e:
                image_error = str(e) or type(e).__name__
        final_ok = code == 0 and bool(out.strip())
        if not nq and not report_links or image_error:
            JOBS[jid]['extraction_error'] = image_error or '未提取既有展示链接；原输出保留'
            await send_original_output(bot, chat_id, out, job=JOBS[jid])
        JOBS[jid]['exit_code'] = code
        JOBS[jid].update({'status': 'done' if final_ok else 'failed'})
        msg = f"✅ {safe(s.get('name'))} NodeQuality 完成：{safe(selected_text)}；{safe(ip_text)}" if final_ok else f"❌ {safe(s.get('name'))} NodeQuality 失败：{safe(selected_text)}；{safe(ip_text)}"
        if ipv6_status is not None and not ipv6_status[0]:
            msg += '\n\n⚠️ 没有可用 IPv6，已更新服务器 IP 状态；本次仅测试 IPv4。'
        if nq:
            msg += f"\n\nNodeQuality:\n{safe(nq)}"
        if gb_urls:
            msg += "\n\nGeekbench:\n" + "\n".join(safe(u) for u in gb_urls)
        if mask != NQ_ALL_MASK and not image_ok:
            if report_links:
                msg += "\n\n分项报告：\n" + "\n".join(f"- {safe(label)}: {safe(url)}" for label, url in report_links)
            if image_error:
                msg += f"\n\n转 PNG 失败：<code>{safe(image_error)}</code>"
        if not nq and not report_links:
            msg += f"\n\n未解析到既有展示链接，完整原输出已转发；摘要：\n<pre>{safe(trim_log(out))}</pre>"
        msg += f"\n\n{script_command_html('nq', selected=selected_text, ip_mode=ip_text)}"
        await bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        if JOBS[jid].get('status') == 'done':
            JOBS[jid]['delivery_error'] = repr(e)
        else:
            JOBS[jid].update(status='failed')
            JOBS[jid].setdefault('log', repr(e))
        await bot.send_message(chat_id, f"❌ {safe(s.get('name'))} NQ任务失败：<code>{safe(e)}</code>", parse_mode=ParseMode.HTML)
    finally:
        try:
            if work_dir is not None:
                await cleanup_nodequality_ansi_logs(s, work_dir)
        except Exception:
            # A failed cleanup must not hide an already delivered result.
            pass
        finally:
            finish_job(jid, key)


async def send_history_result(bot, chat_id, s, kind):
    item = history_item_for(s, kind)
    if not item:
        await bot.send_message(chat_id, f'暂无 {safe(KIND_NAME.get(kind, kind))} 历史。', parse_mode=ParseMode.HTML)
        return False
    if kind in kat_proxy.KINDS and item.get('proxy_report_path'):
        path = Path(item['proxy_report_path'])
        root = kind_result_dir(s, kind)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 800000:
            await bot.send_message(chat_id, 'Kat历史完整报告不可读取；未重新检测或补造结果。')
            return False
        await send_kat_output(bot, chat_id, path.read_text(encoding='utf-8'))
        return True
    if item.get('raw_path') and (item.get('extraction_error') or not item.get('media_paths') and not item.get('urls')):
        raw = Path(item['raw_path'])
        root = kind_result_dir(s, 'stream-unified' if kind == 'stream' else kind)
        if raw.is_symlink() or not raw.is_file() or not raw.resolve().is_relative_to(root.resolve()) or raw.stat().st_size > ANSI_MAX_BYTES:
            await bot.send_message(chat_id, '原始历史输出不可安全读取；未重新执行或补造报告。')
            return False
        return await send_original_output(bot, chat_id, raw.read_text(encoding='utf-8', errors='strict'))
    media_paths = []
    for x in item.get('media_paths') or []:
        p = Path(x)
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            media_paths.append(p)
    if kind == 'ipq':
        errors = []
        for media in media_paths:
            try:
                with media.open('rb') as photo:
                    await bot.send_photo(chat_id, photo=photo)
            except Exception as e:
                errors.append(str(e))
        text = history_detail_text(s, kind)
        if errors:
            text += '\n\n图片重发失败：' + safe(trim_log('；'.join(errors), 500))
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return bool(media_paths or item.get('urls'))
    if kind == 'tcpq':
        if item.get('status') != 'done':
            await bot.send_message(
                chat_id,
                f"❌ {safe(s.get('name'))} 最近一次 TCPQuality 状态为 "
                f"<code>{safe(item.get('status') or '-')}</code>，暂无可重发的完整报告。",
                parse_mode=ParseMode.HTML,
            )
            return False
        mode = item.get('target') or 'v4'
        mode_config = TCPQUALITY_MODES.get(mode)
        selected = item.get('selected') or (mode_config or {}).get('label') or '-'
        if mode_config and not mode_config['report_required']:
            log_tail = tcpquality_text_output(item.get('log_tail') or '')
            if not log_tail:
                await bot.send_message(
                    chat_id,
                    f"⚠️ {safe(s.get('name'))} 最近一次回程识别没有可重发的文本结果。",
                    parse_mode=ParseMode.HTML,
                )
                return False
            await bot.send_message(
                chat_id,
                f"✅ {safe(s.get('name'))} TCPQuality 完成：{safe(selected)}\n\n"
                f"{script_command_html('tcpq', mode=mode, source=item.get('tool_source'))}",
                parse_mode=ParseMode.HTML,
            )
            await send_long_text(bot, chat_id, log_tail)
            return True
        report = validated_tcpquality_url(item.get('report_url'))
        if not report:
            report = next(
                (validated for url in (item.get('urls') or []) if (validated := validated_tcpquality_url(url))),
                None,
            )
        if not report:
            await bot.send_message(
                chat_id,
                f"⚠️ {safe(s.get('name'))} 最近一次 TCPQuality 没有有效的官方报告链接。",
                parse_mode=ParseMode.HTML,
            )
            return False
        photo_errors = []
        for media in media_paths:
            try:
                with media.open('rb') as photo:
                    await bot.send_photo(chat_id, photo=photo)
            except Exception as photo_error:
                photo_errors.append(trim_log(str(photo_error), 200))
        msg = f"✅ {safe(s.get('name'))} TCPQuality 完成：{safe(selected)}\n\n{safe(report)}"
        safe_mode = mode if mode in TCPQUALITY_MODES else 'v4'
        msg += f"\n\n{script_command_html('tcpq', mode=safe_mode, source=item.get('tool_source'))}"
        if photo_errors:
            msg += f"\n\n报告图重发失败：<code>{safe('；'.join(photo_errors))}</code>"
        await bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    if kind == 'nq':
        urls = item.get('urls') or []
        nq = next((u for u in urls if 'nodequality.com/r/' in u), None)
        gb_urls = [u for u in urls if 'browser.geekbench.com/' in u]
        report_urls = [u for u in urls if 'Report.Check.Place/' in u]
        selected = item.get('selected') or '-'
        ip_mode = item.get('ip_mode') or '-'
        is_full_nq = selected == nq_selected_text(NQ_ALL_MASK)
        if not is_full_nq:
            for media in media_paths:
                with media.open('rb') as f:
                    await bot.send_photo(chat_id, photo=f)
        msg = f"✅ {safe(s.get('name'))} NodeQuality 完成：{safe(selected)}；{safe(ip_mode)}"
        if nq:
            msg += f"\n\nNodeQuality:\n{safe(nq)}"
        if gb_urls:
            msg += "\n\nGeekbench:\n" + "\n".join(safe(u) for u in gb_urls)
        if not media_paths and report_urls:
            msg += "\n\n分项报告：\n" + "\n".join(f"- {safe(u)}" for u in report_urls)
        msg += f"\n\n{script_command_html('nq', selected=selected, ip_mode=ip_mode, source=item.get('tool_source'))}"
        await bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    if media_paths:
        for media in media_paths:
            with media.open('rb') as f:
                await bot.send_photo(chat_id, photo=f)
        return True
    await bot.send_message(chat_id, history_detail_text(s, kind), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    return True


async def send_or_edit(update: Update, text, markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await send_or_edit(update, menu_text(), main_menu_markup())


async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await update.message.reply_text(f'GUKO v{GUKO_VERSION}')


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await send_or_edit(update, menu_text(), main_menu_markup())


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await send_or_edit(update, menu_text(), main_menu_markup())


async def addserver_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_guard(update): return
    clear_add_session(update.effective_chat.id)
    await update.message.reply_text(add_help_text(), parse_mode=ParseMode.HTML, reply_markup=add_start_markup())


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    if not context.args:
        await update.message.reply_text('用法：/info <名字/IP/ID/别名>')
        return
    s = find_server(' '.join(context.args), load_inventory().get('servers', []))
    if not s:
        await update.message.reply_text('没找到这台。')
        return
    await update.message.reply_text(await server_detail_text_with_specs(s), parse_mode=ParseMode.HTML, reply_markup=server_markup(s))


async def export_config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_guard(update): return
    data = redact_inventory(load_inventory())
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    path = TMP_DIR / f'guko-export-redacted-{int(time.time())}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    with path.open('rb') as f:
        await update.message.reply_document(document=f, filename='guko-servers-redacted.json', caption='已导出脱敏配置（密码已隐藏）。')


async def testall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_guard(update): return
    servers = [s for s in load_inventory().get('servers', []) if s.get('host')]
    if not servers:
        await update.message.reply_text('当前没有服务器。')
        return
    msg = await update.message.reply_text(f'🧪 开始批量测试 SSH：{len(servers)} 台，并发 3。')
    sem = asyncio.Semaphore(3)
    results = []
    async def one(s):
        async with sem:
            ok, out = await test_server_login(s, timeout=12)
            results.append((s, ok, out))
    await asyncio.gather(*(one(s) for s in servers))
    lines = []
    for s, ok, out in results:
        mark = '✅' if ok else '❌'
        cfg = ssh_config(s)
        lines.append(f'{mark} {s.get("name")}  {cfg.get("user")}@{cfg.get("host")}:{cfg.get("port")}')
        if not ok:
            lines.append('   ' + strip_ansi(out).splitlines()[-1][:120] if out else '   无输出')
    await msg.edit_text('<pre>' + safe('\n'.join(lines)[-3500:]) + '</pre>', parse_mode=ParseMode.HTML)


async def testssh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_guard(update): return
    if not context.args:
        await update.message.reply_text('用法：/testssh <名字/IP/ID/别名>')
        return
    s = find_server(' '.join(context.args), load_inventory().get('servers', []))
    if not s:
        await update.message.reply_text('没找到这台服务器。')
        return
    msg = await update.message.reply_text(f'🧪 正在测试 {safe(s.get("name"))} SSH…', parse_mode=ParseMode.HTML)
    ok, out = await test_server_login(s)
    await msg.edit_text(('✅ SSH 登录成功：' if ok else '⚠️ SSH 登录失败：') + '<pre>' + safe(out[-1200:]) + '</pre>', parse_mode=ParseMode.HTML)


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    if not context.args:
        await update.message.reply_text('用法：/history <名字/IP/ID/别名>')
        return
    s = find_server(' '.join(context.args), load_inventory().get('servers', []))
    if not s:
        await update.message.reply_text('没找到这台服务器。')
        return
    await update.message.reply_text(history_text(s), parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=history_markup(s))


async def jobs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    if not JOBS:
        await update.message.reply_text('暂无后台任务。')
        return
    lines = []
    for jid, j in list(JOBS.items())[-10:]:
        lines.append(f"{jid}: {j.get('server')} {j.get('kind')} {j.get('status')}")
    await update.message.reply_text('<pre>' + safe('\n'.join(lines)) + '</pre>', parse_mode=ParseMode.HTML)


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    chat_id = update.effective_chat.id if update.effective_chat else None
    sess = ADD_SESSIONS.get(chat_id) if chat_id is not None else None
    if not sess or sess.get('step') not in ('single_key_text', 'bulk_shared_key_text'):
        await update.message.reply_text('收到文件了，但当前没有等待密钥上传。请先点“添加服务器”。')
        return
    doc = update.message.document
    if not doc:
        return
    if doc.file_size and doc.file_size > 128 * 1024:
        await update.message.reply_text('密钥文件太大了，不像 SSH 私钥。')
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    try:
        key_path = save_private_key(chat_id, bytes(data), doc.file_name or 'telegram-key')
    except Exception as e:
        await update.message.reply_text(f'密钥识别失败：{safe(e)}', parse_mode=ParseMode.HTML)
        return
    if sess.get('step') == 'single_key_text':
        add_session(chat_id, key=key_path, auth_kind='key')
        await finish_single_add(update, context, ADD_SESSIONS[chat_id])
    else:
        add_session(chat_id, auth_mode='key', shared_auth=key_path, step='bulk_lines')
        await update.message.reply_text('密钥已保存。现在发送服务器列表，每行一台。\n\n格式：<code>名称 IP 用户</code>', parse_mode=ParseMode.HTML)


async def fallback_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    text = update.message.text or ''
    chat_id = update.effective_chat.id if update.effective_chat else None
    sess = ADD_SESSIONS.get(chat_id) if chat_id is not None else None
    if sess:
        step = sess.get('step')
        if step == 'single_basic':
            parts = shlex.split(text)
            if len(parts) < 2:
                await update.message.reply_text('格式：<code>名称 IP [端口] [用户]</code>\n例：<code>hk-01 1.2.3.4 22 root</code>', parse_mode=ParseMode.HTML)
                return
            host, embedded_port = parse_host_port(parts[1])
            if not is_valid_hostname(host):
                await update.message.reply_text('IP/域名看起来不对，重新发一次。')
                return
            port = embedded_port
            user = 'root'
            if len(parts) >= 3 and parts[2].isdigit():
                port = int(parts[2])
                if len(parts) >= 4:
                    user = parts[3]
            elif len(parts) >= 3:
                user = parts[2]
            add_session(chat_id, step='single_auth', name=parts[0], host=host, port=port or 22, user=user)
            await update.message.reply_text('选择这台服务器的登录方式：', reply_markup=add_auth_markup())
            return
        if step == 'single_password':
            add_session(chat_id, password=text.strip(), auth_kind='password')
            await finish_single_add(update, context, ADD_SESSIONS[chat_id])
            return
        if step == 'single_key_path':
            key_path = os.path.expanduser(text.strip())
            if not key_path:
                await update.message.reply_text('密钥路径不能为空。')
                return
            add_session(chat_id, key=key_path, auth_kind='key')
            await finish_single_add(update, context, ADD_SESSIONS[chat_id])
            return
        if step == 'single_key_text':
            try:
                key_path = save_private_key(chat_id, text, 'telegram-key')
            except Exception as e:
                await update.message.reply_text(f'密钥识别失败：{safe(e)}', parse_mode=ParseMode.HTML)
                return
            add_session(chat_id, key=key_path, auth_kind='key')
            await finish_single_add(update, context, ADD_SESSIONS[chat_id])
            return
        if step == 'bulk_port':
            if not text.strip().isdigit():
                await update.message.reply_text('端口需要是数字，比如 22 或 53580。')
                return
            add_session(chat_id, same_port=int(text.strip()), step='bulk_auth')
            await update.message.reply_text('端口已设置。现在选择认证方式：', reply_markup=bulk_auth_markup())
            return
        if step == 'bulk_shared_password':
            add_session(chat_id, auth_mode='password', shared_auth=text.strip(), step='bulk_lines')
            await update.message.reply_text('密码已记录。现在发送服务器列表，每行一台。\n\n格式：<code>名称 IP 用户</code>', parse_mode=ParseMode.HTML)
            return
        if step == 'bulk_shared_key_text':
            try:
                key_path = save_private_key(chat_id, text, 'bulk-key')
            except Exception as e:
                await update.message.reply_text(f'密钥识别失败：{safe(e)}', parse_mode=ParseMode.HTML)
                return
            add_session(chat_id, auth_mode='key', shared_auth=key_path, step='bulk_lines')
            await update.message.reply_text('密钥已保存。现在发送服务器列表，每行一台。\n\n格式：<code>名称 IP 用户</code>', parse_mode=ParseMode.HTML)
            return
        if step == 'bulk_lines':
            await finish_bulk_add(update, context, sess, text)
            return
        if step == 'edit_value':
            sid = sess.get('sid')
            field = sess.get('field')
            s = find_server_by_id(sid)
            if not s:
                clear_add_session(chat_id)
                await update.message.reply_text('这台服务器不在当前清单里。')
                return
            val = text.strip()
            patch = {}
            if field == 'name':
                patch['name'] = val
            elif field == 'host':
                host, embedded_port = parse_host_port(val)
                if not is_valid_hostname(host):
                    await update.message.reply_text('IP/域名看起来不对，重新发一次。')
                    return
                patch['host'] = host
                if embedded_port:
                    patch['ssh'] = {'port': embedded_port}
            elif field == 'port':
                if not val.isdigit():
                    await update.message.reply_text('端口需要是数字。')
                    return
                patch['ssh'] = {'port': int(val)}
            elif field == 'user':
                patch['ssh'] = {'user': val}
            elif field == 'key':
                patch['ssh'] = {'auth': 'key', 'key': os.path.expanduser(val)}
            elif field == 'password':
                patch['ssh'] = {'auth': 'password', 'password': val}
            updated = update_server_by_id(sid, patch)
            clear_add_session(chat_id)
            await update.message.reply_text(f'已更新：<b>{safe(updated.get("name"))}</b>', parse_mode=ParseMode.HTML, reply_markup=server_markup(updated))
            return
    pending_sid = PENDING_NEXTTRACE.pop(chat_id, None) if chat_id is not None else None
    if pending_sid:
        s = find_server_by_id(pending_sid)
        if not s:
            await update.message.reply_text('刚才选择的服务器不在当前清单里。')
            return
        target = extract_ipv4(text) or normalize_domain(text)
        if not target:
            await update.message.reply_text('没识别到 IP 或域名，已取消这次 NextTrace。')
            return
        jid = launch_job(s, 'nexttrace', run_nexttrace_task, context.bot, chat_id, s, target, target=target)
        await bot_task_started_notice(context.bot, chat_id, s, f'NextTrace {safe(target)}', jid is not None)
        return
    # 普通文本不再触发任何功能；只有点击 NextTrace 后的下一条 IP/域名才会被消费。
    return


async def post_init(app: Application):
    commands = [
        BotCommand('start', '打开 GUKO 面板'),
        BotCommand('list', '服务器列表'),
        BotCommand('status', '总览状态'),
        BotCommand('addserver', '添加/批量导入服务器'),
        BotCommand('testssh', '测试服务器 SSH'),
        BotCommand('testall', '批量测试 SSH'),
        BotCommand('exportconfig', '导出脱敏配置'),
        BotCommand('info', '查看单台操作面板：/info 名字/IP/ID'),
        BotCommand('jobs', '查看后台任务'),
        BotCommand('history', '查看测试历史：/history 服务器'),
        BotCommand('ip', 'IP/域名工具：/ip 1.1.1.1'),
        BotCommand('nexttrace', '路由追踪：/nexttrace 服务器 目标'),
        BotCommand('version', '查看 GUKO 版本'),
    ]
    await app.bot.set_my_commands(commands)


async def ip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    if not context.args:
        await update.message.reply_text('用法：/ip <IPv4 或域名>')
        return
    target = ' '.join(context.args)
    try:
        ip, host = await resolve_target_to_ipv4(target)
        suffix = f'{safe(host)} → <code>{safe(ip)}</code>' if host else f'<code>{safe(ip)}</code>'
        await update.message.reply_text(f'识别到 {suffix}，选一个生成：', parse_mode=ParseMode.HTML, reply_markup=ip_tools_markup(ip))
    except Exception as e:
        await update.message.reply_text(f'解析失败：{safe(e)}', parse_mode=ParseMode.HTML)


async def nexttrace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    if not context.args:
        await update.message.reply_text('用法：/nexttrace <服务器名/IP/ID/别名> [目标IP或域名]\n例：/nexttrace 海创 1.1.1.1')
        return
    s = find_server(context.args[0], load_inventory().get('servers', []))
    if not s:
        await update.message.reply_text('没找到这台服务器。')
        return
    target = context.args[1] if len(context.args) > 1 else '1.1.1.1'
    if not (extract_ipv4(target) or normalize_domain(target)):
        await update.message.reply_text('目标需要是 IPv4 或域名。')
        return
    jid = launch_job(s, 'nexttrace', run_nexttrace_task, context.bot, update.effective_chat.id, s, target, target=target)
    if jid:
        await update.message.reply_text(f'🛣 已启动 {safe(s.get("name"))} NextTrace：{safe(target)}', parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f'这个任务已经在运行中：{safe(s.get("name"))} NextTrace：{safe(target)}', parse_mode=ParseMode.HTML)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    q = update.callback_query
    await q.answer()
    data = q.data or ''
    chat_id = q.message.chat_id if q.message else update.effective_chat.id
    if data == 'add:start':
        if not await admin_guard(update): return
        clear_add_session(chat_id)
        await q.edit_message_text(add_help_text(), parse_mode=ParseMode.HTML, reply_markup=add_start_markup())
    elif data == 'add:one':
        if not await admin_guard(update): return
        add_session(chat_id, step='single_basic')
        await q.edit_message_text(
            '➕ 发送服务器信息：\n\n'
            '<code>名称 IP [端口] [用户]</code>\n\n'
            '例：<code>hk-01 1.2.3.4 22 root</code>\n'
            '也支持：<code>hk-01 1.2.3.4:53580 root</code>',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]])
        )
    elif data == 'add:bulk':
        if not await admin_guard(update): return
        add_session(chat_id, step='bulk_choose_port')
        await q.edit_message_text(bulk_help_text() + '\n\n先选择端口策略：', parse_mode=ParseMode.HTML, reply_markup=bulk_mode_markup())
    elif data == 'add:cancel':
        clear_add_session(chat_id)
        await q.edit_message_text('已取消添加服务器。', reply_markup=main_menu_markup())
    elif data == 'addauth:default':
        defaults = inventory_defaults(load_inventory())
        add_session(chat_id, auth_kind='default')
        await q.edit_message_text(
            f'将沿用默认 SSH 配置测试登录：\n<code>{safe(defaults.get("user"))}@服务器:{safe(defaults.get("port"))}</code>\n密钥：<code>{safe(defaults.get("key"))}</code>',
            parse_mode=ParseMode.HTML,
        )
        await finish_single_add(update, context, ADD_SESSIONS[chat_id])
    elif data == 'addauth:keypath':
        add_session(chat_id, step='single_key_path')
        await q.edit_message_text('请发送已有 SSH 私钥路径，例如：\n<code>/data/keys/id_ed25519</code>\n\n适合新服务器继续使用以前同一把密钥。', parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'addauth:key':
        add_session(chat_id, step='single_key_text')
        await q.edit_message_text('请直接发送 SSH 私钥文本，或以文件形式上传私钥。\n\n需要包含 SSH 私钥的 BEGIN/END 头尾标记。', parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'addauth:password':
        add_session(chat_id, step='single_password')
        await q.edit_message_text('请发送这台服务器的 SSH 密码。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'addauth:skip':
        add_session(chat_id, auth_kind=None)
        await finish_single_add(update, context, ADD_SESSIONS[chat_id])
    elif data == 'bulkport:same':
        add_session(chat_id, step='bulk_port')
        await q.edit_message_text('请输入所有服务器共用的 SSH 端口，例如 <code>22</code> 或 <code>53580</code>。', parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'bulkport:per':
        add_session(chat_id, same_port=None, step='bulk_auth')
        await q.edit_message_text('好，每台服务器自己写端口。现在选择认证方式：', reply_markup=bulk_auth_markup())
    elif data == 'bulkauth:key':
        add_session(chat_id, step='bulk_shared_key_text')
        await q.edit_message_text('请发送所有服务器共用的 SSH 私钥文本，或上传私钥文件。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'bulkauth:password':
        add_session(chat_id, step='bulk_shared_password')
        await q.edit_message_text('请发送所有服务器共用的 SSH 密码。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'bulkauth:per':
        add_session(chat_id, auth_mode='per', step='bulk_lines')
        await q.edit_message_text(
            '请发送服务器列表，每行一台：\n\n'
            '<code>名称 IP 端口 用户 key:/data/keys/a</code>\n'
            '<code>名称 IP 端口 用户 password:你的密码</code>',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]])
        )
    elif data == 'bulkauth:skip':
        add_session(chat_id, auth_mode='skip', step='bulk_lines')
        await q.edit_message_text('请发送服务器列表，每行一台：\n\n<code>名称 IP [端口] [用户]</code>', parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data == 'noop':
        await q.answer('该功能未启用', show_alert=True)
    elif data == 'act:list':
        await send_or_edit(update, menu_text(), main_menu_markup())
    elif data.startswith('sort:'):
        if not await admin_guard(update): return
        if data == 'sort:stay':
            return
        if data != 'sort:list':
            parts = data.split(':', 2)
            if len(parts) != 3 or parts[1] not in ('up', 'down') or not parts[2]:
                return
            if not move_server_by_id(parts[2], parts[1]):
                return
        servers = load_inventory().get('servers', [])
        await q.edit_message_text(
            '↕️ <b>调整服务器顺序</b>\n\n点击箭头后立即保存。',
            parse_mode=ParseMode.HTML,
            reply_markup=server_sort_markup(servers),
        )
    elif data.startswith('edit:'):
        if not await admin_guard(update): return
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        cfg = ssh_config(s)
        await q.edit_message_text(
            f'✏️ 编辑 <b>{safe(s.get("name"))}</b>\n<code>{safe(cfg.get("user"))}@{safe(cfg.get("host"))}:{safe(cfg.get("port"))}</code>',
            parse_mode=ParseMode.HTML,
            reply_markup=edit_markup(s),
        )
    elif data.startswith('editfield:'):
        if not await admin_guard(update): return
        _p, sid, field = data.split(':', 2)
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=main_menu_markup())
            return
        add_session(chat_id, step='edit_value', sid=sid, field=field)
        labels = {'name': '新名称', 'host': '新 IP/域名（可带 :端口）', 'port': '新端口', 'user': '新 SSH 用户名', 'key': '新密钥路径', 'password': '新密码'}
        await q.edit_message_text(f'请发送{labels.get(field, "新值")}：', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ 取消', callback_data='add:cancel')]]))
    elif data.startswith('editdefault:'):
        if not await admin_guard(update): return
        sid = data.split(':', 1)[1]
        updated = update_server_by_id(sid, {'ssh': {'auth': 'key', 'key': None}})
        if not updated:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=main_menu_markup())
            return
        await q.edit_message_text(f'已改为沿用默认密钥：<b>{safe(updated.get("name"))}</b>', parse_mode=ParseMode.HTML, reply_markup=server_markup(updated))
    elif data.startswith('jobsrv:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        await q.edit_message_text(
            job_status_text(s),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🔄 刷新任务', callback_data=f'jobsrv:{sid}')],
                [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
            ]),
        )
    elif data.startswith('hist:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        await q.edit_message_text(
            history_text(s),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=history_markup(s),
        )
    elif data.startswith('histd:'):
        parts = data.split(':', 2)
        sid = parts[1] if len(parts) > 1 else ''
        kind = parts[2] if len(parts) > 2 else ''
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        item = history_item_for(s, kind)
        can_resend = bool(
            item
            and ((item.get('status') == 'done' or kind == 'stream' and item.get('status') == 'inconclusive')
                 and (latest_media_path(item) or kind in ('nq', 'tcpq'))
                 or kind in kat_proxy.KINDS and item.get('proxy_report_path'))
        )
        if can_resend:
            sent = await send_history_result(context.bot, q.message.chat_id, s, kind)
            summary = (
                f'已重新发送 <b>{safe(KIND_NAME.get(kind, kind))}</b> 最近一次完整结果。'
                if sent
                else f'最近一次 <b>{safe(KIND_NAME.get(kind, kind))}</b> 没有可重发的完整结果。'
            )
            await q.edit_message_text(
                summary,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('↩️ 返回历史记录', callback_data=f'hist:{sid}')],
                    [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
                ]),
            )
        else:
            if item and kind == 'tcpq':
                detail = (
                    f"📜 <b>{safe(s.get('name'))} · TCPQuality</b>\n"
                    f"状态：<b>{safe(item.get('status') or '-')}</b>\n\n"
                    '最近一次没有可重发的完整官方报告。'
                )
            else:
                detail = history_detail_text(s, kind)
            await q.edit_message_text(
                detail,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('↩️ 返回历史记录', callback_data=f'hist:{sid}')],
                    [InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')],
                ]),
            )
    elif data.startswith('testssh:'):
        if not await admin_guard(update): return
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        await q.edit_message_text(f'🧪 正在测试 {safe(s.get("name"))} SSH…', parse_mode=ParseMode.HTML)
        ok, out = await test_server_login(s)
        await q.edit_message_text(
            (f'✅ <b>{safe(s.get("name"))}</b> SSH 登录成功：' if ok else f'⚠️ <b>{safe(s.get("name"))}</b> SSH 登录失败：') + '<pre>' + safe(out[-1200:]) + '</pre>',
            parse_mode=ParseMode.HTML,
            reply_markup=server_markup(s),
        )
    elif data.startswith('delask:'):
        if not await admin_guard(update): return
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        cfg = ssh_config(s)
        await q.edit_message_text(
            '⚠️ 确认删除这台服务器？\n\n'
            f'<b>{safe(s.get("name"))}</b>\n'
            f'<code>{safe(cfg.get("user"))}@{safe(cfg.get("host"))}:{safe(cfg.get("port"))}</code>\n\n'
            '只会从 GUKO 配置删除，不会动远端机器。',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('✅ 确认删除', callback_data=f'delconfirm:{sid}')],
                [InlineKeyboardButton('❌ 取消删除', callback_data=f'srv:{sid}')],
            ]),
        )
    elif data.startswith('delconfirm:'):
        if not await admin_guard(update): return
        sid = data.split(':', 1)[1]
        removed = delete_server_by_id(sid)
        if not removed:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=main_menu_markup())
            return
        await q.edit_message_text(f'已从配置删除：<b>{safe(removed.get("name"))}</b>', parse_mode=ParseMode.HTML, reply_markup=main_menu_markup())
    elif data.startswith(('proxy:vless:', 'proxyrun:vless:', 'vlessmode:')) or data in ('proxy:vless', 'proxyrun:vless'):
        await q.edit_message_text('VLESS入口已移除；远端既有服务和历史记录未改变。')
        return
    elif data.startswith('katinstall:'):
        token = data.split(':', 1)[1]
        decision = valid_kat_confirmation(token, update.effective_user.id, q.message.chat_id)
        if not decision:
            await q.edit_message_text('Kat安装确认已失效，请重新只读检查后确认。')
            return
        s = find_server_by_id(decision['server_id'])
        if not s or decision['host_hash'] != hashlib.sha256(str(s.get('host')).encode()).hexdigest():
            KAT_INSTALL_CONFIRMATIONS.pop(token, None)
            await q.edit_message_text('服务器信息已变化，原Kat安装确认失效。')
            return
        kind = decision['kind']
        jid = launch_job(s, kind, run_proxy_tool_task, context.bot, q.message.chat_id,
                         s, kind, 'kat-confirmed', None, update.effective_user.id, token, target='confirmed install')
        await bot_task_started_notice(context.bot, q.message.chat_id, s, 'Kat明确确认新安装', jid is not None)
    elif data.startswith('proxy:'):
        parts = data.split(':', 2)
        kind = parts[1]
        sid = parts[2] if len(parts) > 2 else ''
        s = find_server_by_id(sid)
        if kind not in PROXY_TOOLS or not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        await q.edit_message_text(proxy_menu_text(s, kind), parse_mode=ParseMode.HTML, reply_markup=proxy_markup(s, kind))
    elif data.startswith('proxyrun:'):
        parts = data.split(':', 3)
        kind = parts[1] if len(parts) > 1 else ''
        action = parts[2] if len(parts) > 2 else ''
        sid = parts[3] if len(parts) > 3 else ''
        s = find_server_by_id(sid)
        if kind not in PROXY_TOOLS or action not in ('install', 'ensure', 'view') or not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        tool = proxy_tool_config(kind)
        task = f"{safe(tool['name'])} {'安装/读取检查' if action in ('install', 'ensure') else '查看配置'}"
        # Old ensure/install callbacks for Kat ONLY read. They never authorize installation.
        if kind in kat_proxy.KINDS:
            action = 'view'
        jid = launch_job(s, kind, run_proxy_tool_task, context.bot, q.message.chat_id, s, kind, action, None, update.effective_user.id, target=action)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, task, jid is not None)

    elif data.startswith('tqask:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        await q.edit_message_text(
            tcpquality_menu_text(s),
            parse_mode=ParseMode.HTML,
            reply_markup=tcpquality_markup(s),
        )
    elif data.startswith('tqmode:'):
        parts = data.split(':', 2)
        sid = parts[1] if len(parts) > 1 else ''
        category = parts[2] if len(parts) > 2 else ''
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        try:
            markup = tcpquality_family_markup(s, category)
            text = tcpquality_family_menu_text(s, category)
        except ValueError:
            await q.answer('未知 TCPQuality 检测项目', show_alert=True)
            return
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith('tqrun:'):
        parts = data.split(':', 2)
        sid = parts[1] if len(parts) > 1 else ''
        mode = parts[2] if len(parts) > 2 else 'v4'
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        try:
            config = tcpquality_mode(mode)
        except ValueError:
            await q.answer('未知 TCPQuality 模式', show_alert=True)
            return
        if config['family'] == 'v6' and not server_has_ipv6(s):
            await q.answer('这台服务器没有配置 IPv6', show_alert=True)
            return
        jid = launch_job(
            s,
            'tcpq',
            run_tcpquality_task,
            context.bot,
            q.message.chat_id,
            s,
            mode,
            selected=config['label'],
            target=mode,
        )
        await bot_task_started_notice(
            context.bot,
            q.message.chat_id,
            s,
            f"TCPQuality（{safe(config['label'])}）",
            jid is not None,
        )
    elif data.startswith(('ipq:', 'ipqproto:', 'ipqrun:')):
        parts = data.split(':')
        action, sid = parts[:2]
        ip_mode = parts[2] if len(parts) > 2 else '4'
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        if ip_mode not in NQ_IP_MODES:
            await q.answer('未知 IP质量协议选项', show_alert=True)
            return
        ipv6_status = stored_ipv6_status(s)
        blocked = ip_mode == '46' and not ipv6_status[0]
        if action != 'ipqrun' or blocked:
            await q.edit_message_text(ipquality_menu_text(s, ip_mode, ipv6_status), parse_mode=ParseMode.HTML,
                                      reply_markup=ipquality_markup(s, ip_mode, ipv6_status))
            return
        ip_text = nq_ip_mode_text(ip_mode)
        jid = launch_job(s, 'ipq', run_ip_quality_task, context.bot, q.message.chat_id, s, ip_mode, ip_mode=ip_text)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, f'IP质量任务（{safe(ip_text)}）', jid is not None)
    elif data.startswith('gb5:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        jid = launch_job(s, 'gb5', run_gb5_task, context.bot, q.message.chat_id, s)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, 'GB5', jid is not None)
    elif data.startswith('stream:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        await q.edit_message_text(
            stream_menu_text(s),
            parse_mode=ParseMode.HTML,
            reply_markup=stream_markup(s),
        )
    elif data.startswith('streamrun:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        region_label = '实际出口自动地区'
        jid = launch_job(s, 'stream', run_stream_task, context.bot, q.message.chat_id, s, region=region_label)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, f'流媒体检测（{safe(region_label)}）', jid is not None)
    elif data.startswith('ntask:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        PENDING_NEXTTRACE[q.message.chat_id] = sid
        await q.edit_message_text(
            nexttrace_prompt_text(s),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回操作面板', callback_data=f'srv:{sid}')]])
        )
    elif data.startswith('ntrun:'):
        parts = data.split(':', 2)
        sid = parts[1]
        target = parts[2] if len(parts) > 2 else '1.1.1.1'
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        jid = launch_job(s, 'nexttrace', run_nexttrace_task, context.bot, q.message.chat_id, s, target, target=target)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, f'NextTrace {safe(target)}', jid is not None)
    elif data.startswith('bgp:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        jid = launch_job(s, 'bgp', run_bgp_task, context.bot, q.message.chat_id, s)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, 'BGP 图任务', jid is not None)
    elif data.startswith('ippure:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        jid = launch_job(s, 'ippure', run_ippure_task, context.bot, q.message.chat_id, s)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, 'IPPure 图任务', jid is not None)
    elif data.startswith('bgpip:'):
        ip = data.split(':', 1)[1]
        if not is_ipv4(ip):
            await q.answer('无效 IPv4', show_alert=True)
            return
        pseudo = {'id': ip, 'name': ip, 'host': ip}
        jid, key = start_job(pseudo, 'bgp')
        if not jid:
            await q.answer('这个 IP 的 BGP 图已经在生成了', show_alert=True)
            return
        await send_running_notice(context.bot, q.message.chat_id, pseudo, 'BGP 图任务')
        asyncio.create_task(run_bgp_task(context.bot, q.message.chat_id, pseudo, jid, False))
    elif data.startswith('ippureip:'):
        ip = data.split(':', 1)[1]
        if not is_ipv4(ip):
            await q.answer('无效 IPv4', show_alert=True)
            return
        pseudo = {'id': ip, 'name': ip, 'host': ip}
        jid, key = start_job(pseudo, 'ippure')
        if not jid:
            await q.answer('这个 IP 的 IPPure 图已经在生成了', show_alert=True)
            return
        await send_running_notice(context.bot, q.message.chat_id, pseudo, 'IPPure 图任务')
        asyncio.create_task(run_ippure_task(context.bot, q.message.chat_id, pseudo, jid))
    elif data.startswith('nqask:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        mask = NQ_DEFAULT_MASK
        ipv6_status = stored_ipv6_status(s)
        await q.edit_message_text(
            nq_menu_text(s, mask, '4', ipv6_status),
            parse_mode=ParseMode.HTML, reply_markup=confirm_nq_markup(s, mask, '4', ipv6_status)
        )
    elif data.startswith('nqtoggle:') or data.startswith('nqsel:') or data.startswith('nqproto:'):
        parts = data.split(':')
        _kind, sid = parts[0], parts[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        try:
            mask = int(parts[2]) & NQ_ALL_MASK
        except Exception:
            mask = NQ_DEFAULT_MASK
        ip_mode = parts[3] if len(parts) > 3 else '4'
        ipv6_status = stored_ipv6_status(s)
        await q.edit_message_text(
            nq_menu_text(s, mask, ip_mode, ipv6_status),
            parse_mode=ParseMode.HTML, reply_markup=confirm_nq_markup(s, mask, ip_mode, ipv6_status)
        )
    elif data.startswith('nqrun:'):
        parts = data.split(':')
        sid = parts[1]
        try:
            mask = int(parts[2]) & NQ_ALL_MASK if len(parts) > 2 else NQ_DEFAULT_MASK
        except Exception:
            mask = NQ_DEFAULT_MASK
        ip_mode = parts[3] if len(parts) > 3 else '4'
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        ipv6_status = stored_ipv6_status(s)
        if ip_mode == '46':
            if not ipv6_status[0]:
                await q.edit_message_text(nq_menu_text(s, mask, ip_mode, ipv6_status), parse_mode=ParseMode.HTML,
                                          reply_markup=confirm_nq_markup(s, mask, ip_mode, ipv6_status))
                return
        if mask == 0:
            await q.answer('至少选一项', show_alert=True)
            await q.edit_message_text(
                nq_menu_text(s, mask, ip_mode, ipv6_status) + '\n\n至少选一项才能开始。',
                parse_mode=ParseMode.HTML, reply_markup=confirm_nq_markup(s, mask, ip_mode, ipv6_status)
            )
            return
        selected_text = nq_selected_text(mask)
        ip_text = nq_ip_mode_text(ip_mode)
        jid = launch_job(s, 'nq', run_nq_task, context.bot, q.message.chat_id, s, mask, ip_mode, selected=selected_text, ip_mode=ip_text)
        await bot_task_started_notice(context.bot, q.message.chat_id, s, f'NodeQuality（{safe(selected_text)}；{safe(ip_text)}）', jid is not None)
    elif data.startswith('srv:'):
        sid = data.split(':', 1)[1]
        s = find_server_by_id(sid)
        if not s:
            await q.edit_message_text('这台服务器不在当前清单里。', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ 返回列表', callback_data='act:list')]]))
            return
        if not format_server_specs(s.get('specs')):
            await q.edit_message_text(server_detail_text(s) + '\n正在读取配置…', parse_mode=ParseMode.HTML)
        await q.edit_message_text(await server_detail_text_with_specs(s), parse_mode=ParseMode.HTML, reply_markup=server_markup(s))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f'bot error: {context.error!r}', flush=True)


def main():
    startup_check()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(['start', 'help'], start))
    app.add_handler(CommandHandler('version', version_cmd))
    app.add_handler(CommandHandler('list', list_cmd))
    app.add_handler(CommandHandler('status', status_cmd))
    app.add_handler(CommandHandler('addserver', addserver_cmd))
    app.add_handler(CommandHandler('testssh', testssh_cmd))
    app.add_handler(CommandHandler('testall', testall_cmd))
    app.add_handler(CommandHandler('exportconfig', export_config_cmd))
    app.add_handler(CommandHandler('info', info_cmd))
    app.add_handler(CommandHandler('jobs', jobs_cmd))
    app.add_handler(CommandHandler('history', history_cmd))
    app.add_handler(CommandHandler('ip', ip_cmd))
    app.add_handler(CommandHandler('nexttrace', nexttrace_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_panel))
    app.add_error_handler(error_handler)
    print(f'guko telegram bot started v{GUKO_VERSION}', flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
