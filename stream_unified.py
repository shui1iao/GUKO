"""GUKO unified integration, AGPL-3.0-only; original MIT portions preserved. No imports perform network I/O.

Transport is injected from bot.py's existing SSH builder/auth environment.
No public downloader, new SSH policy, provider framework, or remote runtime.
"""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import uuid

CATALOGUE = json.loads((Path(__file__).resolve().parent / 'unified_catalogue.json').read_text())
ACCESS = tuple((r['id'], r['name']) for r in CATALOGUE['native'] if r['array'] == 'results')
SERVICES = tuple((r['id'], r['name'], r['kind']) for r in CATALOGUE['native'] if r['array'] == 'services')
AI = tuple((r['id'], r['name']) for r in CATALOGUE['native'] if r['array'] == 'ai_endpoints')
EXTRA = {r['function']: r for r in CATALOGUE['extra']}
BINARY_DIR = Path('/app/stream-unified')
MAX_OUTPUT = 2 * 1024 * 1024
SOURCE_COMMIT = '50e084bb3ed34b55fc6839fe0dc4bafd9fe275fc'
EXTRA_COMMIT = 'b6d4a6f9a87fc6eae6d3e62d0092ececcec8e844'


def normalize_terminal(text):
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_OUTPUT:
        raise ValueError('Unified ANSI report is empty or oversized')
    return text.replace('\r\n', '\n').rstrip('\r\n') + '\n'


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('Duplicate JSON key')
        out[key] = value
    return out


def selected_ids(region):
    if region not in CATALOGUE['groups']:
        raise ValueError('Unsupported inventory region')
    return list(dict.fromkeys(CATALOGUE['groups']['global'] + ([] if region == 'global' else CATALOGUE['groups'][region])))


def _country(value):
    return CATALOGUE['region_codes'].get(value or '', '')


def _selection(selection, family):
    if not isinstance(selection, dict) or selection.get('requested_region') != 'auto':
        raise ValueError('GUKO requires actual exit-country auto selection')
    if set(selection) - {'region', 'requested_region', 'extra_family_requested', 'extra_family', 'extra_expected_ids', 'extra_source_commit', 'detected_country', 'detection_source', 'detection_error', 'resolution_reason'}:
        raise ValueError('Unexpected selection/identity metadata')
    country, source, error = (selection.get(k, '') for k in ('detected_country', 'detection_source', 'detection_error'))
    reason, region = selection.get('resolution_reason'), selection.get('region')
    if reason in ('country_mapped', 'unsupported_region_country'):
        if not isinstance(country, str) or len(country) != 2 or _country(country) != country or country == 'UK' or error:
            raise ValueError('Invalid detected country')
        if source not in ('https://www.cloudflare.com/cdn-cgi/trace', 'https://api.ip.sb/geoip'):
            raise ValueError('Invalid detection source')
        mapped = CATALOGUE['country_groups'].get(country)
        if reason == 'country_mapped' and (not mapped or region != mapped):
            raise ValueError('Country/group mismatch')
        if reason == 'unsupported_region_country' and (mapped or region != 'global'):
            raise ValueError('Unexpected unsupported-country resolution')
    elif reason == 'detection_failed':
        if country or source or region != 'global' or not isinstance(error, str):
            raise ValueError('Invalid detection failure')
        codes = r'(request_failed|http_[0-9]{3}|unexpected_final_endpoint|challenge|response_too_large|invalid_country_response)'
        if error not in ('no_extra_family_route', 'detection_budget_exhausted') and not re.fullmatch(r'cloudflare_trace:' + codes + r'; ip_sb_country:' + codes, error):
            raise ValueError('Unrecognized/unsafe detection error')
    else:
        raise ValueError('Invalid auto resolution reason')
    ids = selected_ids(region)
    if selection.get('extra_source_commit') != EXTRA_COMMIT or selection.get('extra_expected_ids') != ids or selection.get('extra_family_requested') != family:
        raise ValueError('Unexpected unified selection')
    actual = selection.get('extra_family')
    if type(actual) is not int or actual not in (0, 4, 6) or family in ('4', '6') and actual != int(family):
        raise ValueError('Invalid extra family')
    if actual == 0 and (reason != 'detection_failed' or error != 'no_extra_family_route'):
        raise ValueError('No-route family must explain failed detection')
    return region, ids, actual


def selection_label(selection):
    region = selection['region']
    names = {'global': 'Global', 'tw': 'Taiwan', 'hk': 'Hong Kong', 'jp': 'Japan', 'na': 'North America', 'sa': 'South America', 'eu': 'Europe', 'oc': 'Oceania', 'kr': 'Korea', 'sea': 'Southeast Asia', 'af': 'Africa'}
    reason = selection['resolution_reason']
    if reason == 'country_mapped':
        return 'Automatic region: %s -> %s (%s)' % (selection['detected_country'], names[region], region)
    if reason == 'unsupported_region_country':
        return 'Automatic region: %s -> Global (unsupported_region_country)' % selection['detected_country']
    return 'Automatic region: unavailable -> Global (detection_failed)'


def validate_output(raw, code, *, family='auto'):
    if family not in ('auto', '4', '6') or type(code) is not int or code not in (0, 1) or not isinstance(raw, str) or len(raw.encode()) > MAX_OUTPUT:
        raise ValueError('Unified execution/output failed')
    doc = json.loads(raw, object_pairs_hook=_unique_object,
                     parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(doc, dict) or set(doc) != {'format', 'report', 'terminal'} or doc.get('format') != 'guko-unified-v1':
        raise ValueError('Invalid unified envelope')
    report = doc.get('report')
    if not isinstance(report, dict) or type(report.get('schema_version')) is not int or report.get('schema_version') != 1:
        raise ValueError('Invalid unified schema')
    if set(report) != {'schema_version', 'source', 'generated_at', 'network', 'results', 'services', 'ai_endpoints', 'extra_checks', 'selection'}:
        raise ValueError('Unexpected or missing report fields')
    source, network, selection = report.get('source'), report.get('network'), report.get('selection')
    if source != {'repository': 'https://github.com/remnawave/geocheck', 'tag': 'v0.3.0', 'commit': SOURCE_COMMIT, 'port': 'Go v0.4.0 standalone three-group extraction with conservative error handling'}:
        raise ValueError('Unexpected historical native source (not the CLI release version)')
    if network != {'mode': 'direct', 'address_family': 'system-selected', 'timeout_seconds': 6, 'timeout_scope': 'request including redirects and body', 'workers': 4}:
        raise ValueError('Unexpected native35 network/resources')
    region, ids, actual_family = _selection(selection, family)
    timestamp = lambda value: isinstance(value, str) and bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value))
    if not timestamp(report.get('generated_at')):
        raise ValueError('Invalid report timestamp')
    identities = [('results', ACCESS), ('services', SERVICES), ('ai_endpoints', AI),
                  ('extra_checks', tuple((i, 'Amazon Prime Video (access)' if i == 'MediaUnlockTest_PrimeVideo' else EXTRA[i]['display_name']) for i in ids))]
    errors, displayed = 0, {}
    for field, expected in identities:
        rows = report.get(field)
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise ValueError('Incomplete unified ' + field)
        displayed[field] = []
        for row, identity in zip(rows, expected):
            if not isinstance(row, dict) or row.get('id') != identity[0] or row.get('name') != identity[1]:
                raise ValueError('Wrong/duplicated/reordered unified ID or name')
            common = {'id', 'name', 'status', 'detail', 'error', 'checked_at', 'elapsed_ms'}
            fields = {'results': {'platform', 'region'}, 'services': {'type', 'value'}, 'ai_endpoints': {'vendor', 'http_status'}, 'extra_checks': {'source_function', 'source_line', 'scope', 'family', 'region'}}
            if set(row) != common | fields[field]:
                raise ValueError('Unexpected or missing row fields')
            status = row.get('status')
            allowed = {'available', 'restricted', 'blocked', 'error'} if field in ('results', 'extra_checks') else {'observed', 'error'} if field == 'services' else {'reachable', 'blocked', 'error'}
            if status not in allowed or not isinstance(row.get('detail'), str) or len(row['detail']) > 8192:
                raise ValueError('Invalid unified status/detail')
            elapsed = row.get('elapsed_ms')
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0 or not timestamp(row.get('checked_at')):
                raise ValueError('Invalid unified timing')
            if status == 'error':
                errors += 1
                if not isinstance(row.get('error'), str) or not row['error'] or len(row['error']) > 8192:
                    raise ValueError('Unknown without evidence')
            elif row.get('error') is not None:
                raise ValueError('Contradictory error')
            region_value = row.get('region')
            if region_value is not None and (not isinstance(region_value, str) or not re.fullmatch('[A-Z]{2,3}', region_value) or not _country(region_value)):
                raise ValueError('Invalid result region')
            if field == 'services':
                if row.get('type') != identity[2]:
                    raise ValueError('Wrong native observation type')
                value = row.get('value')
                if status == 'error' and value is not None or status != 'error' and ((identity[2] == 'country' and (not isinstance(value, str) or len(value) != 2 or not _country(value))) or identity[2] != 'country' and value not in ('yes', 'no')):
                    raise ValueError('Invalid service value')
                if identity[0] == 'spotify_signup' and status != 'error' and (value != 'no' or row['detail'] != 'legacy anonymous signup endpoint explicitly rejected this request as a proxy (status320); actual registration/login not tested'):
                    raise ValueError('Unsupported Spotify signup eligibility claim')
                label = 'Unknown' if status == 'error' else ('Yes' if identity[2] == 'country' or (value == 'no' if identity[2] == 'blocked' else value == 'yes') else 'No')
                display_region = _country(value) if identity[2] == 'country' else ''
            else:
                label = {'available': 'Yes', 'reachable': 'Yes', 'blocked': 'No', 'restricted': 'Limited', 'error': 'Unknown'}[status]
                display_region = '' if field == 'ai_endpoints' else _country(region_value)
            if field == 'results' and row.get('platform') != ('ChatGPT' if identity[0] == 'chatgpt_web' else identity[1]):
                raise ValueError('Invalid legacy platform')
            if field == 'ai_endpoints' and row.get('vendor') != CATALOGUE['ai_vendors'][identity[0]]:
                raise ValueError('Invalid AI vendor')
            if field == 'ai_endpoints' and (type(row.get('http_status')) is not int or row['http_status'] not in range(600)):
                raise ValueError('Invalid AI status')
            if field == 'extra_checks':
                c = EXTRA[identity[0]]
                if row.get('source_function') != identity[0] or row.get('source_line') != c['source_line'] or type(row.get('family')) is not int or row.get('family') != actual_family or row.get('scope') != ('global' if 'global' in c['groups'] else region):
                    raise ValueError('Extra source/family/scope mismatch')
                if (c['safety_exception'] or c['ipv6_unsupported_guard'] and actual_family == 6 or actual_family == 0) and status != 'error':
                    raise ValueError('Unsupported check claims a verdict')
                if region_value is not None and len(region_value) != 2:
                    raise ValueError('Extra region not ISO2')
            displayed[field].append((identity[1], label, display_region))
    if (errors > 0) != (code == 1):
        raise ValueError('Exit code contradicts complete results')
    terminal = normalize_terminal(doc.get('terminal'))
    clean = re.sub(r'\x1b\[[0-9;:]*m', '', terminal)
    if '\x1b' in clean or any(ord(c) < 32 and c != '\n' for c in clean):
        raise ValueError('Invalid terminal controls')
    lines, ansi_lines = clean.splitlines(), terminal.splitlines()
    if not lines or lines.pop(0) != selection_label(selection):
        raise ValueError('Missing/incorrect automatic selection notice')
    ansi_lines.pop(0)
    if not lines or not re.fullmatch('╭─+╮', lines[0]) or not re.fullmatch('╰─+╯', lines[-1]):
        raise ValueError('Not a complete single rounded frame')
    width = len(lines[0])
    if width > 100 or width < 14 or any(len(line) != width for line in lines):
        raise ValueError('Broken unified frame width')
    separator = '├' + '─' * (width-2) + '┤'
    expected = [('services', 'Service regions & access'), ('results', 'Service availability'), ('ai_endpoints', 'AI endpoints'), ('global', 'Global services')]
    if region != 'global': expected.append(('regional', 'Regional services'))
    if not re.fullmatch(r'│ Service +Result +Region │', lines[1]) or lines[2] != separator:
        raise ValueError('Wrong/duplicate table header')
    at = 3
    colors = {'Yes': '\x1b[1;38;5;2m● Yes\x1b[m', 'No': '\x1b[1;38;5;1m● No\x1b[m', 'Limited': '\x1b[1;38;5;3m● Limited\x1b[m', 'Unknown': '\x1b[1m○ Unknown\x1b[m'}
    for field, title in expected:
        if at+1 >= len(lines) or lines[at] != '│ ' + title + ' ' * (width-3-len(title)) + '│' or lines[at+1] != separator:
            raise ValueError('Missing/reordered internal section')
        at += 2
        if field in ('global', 'regional'):
            rows = [v for v, row in zip(displayed['extra_checks'], report['extra_checks']) if (row['scope'] == 'global') == (field == 'global')]
        else: rows = displayed[field]
        for name, label, display_region in rows:
            if at >= len(lines)-1:
                raise ValueError('Missing terminal rows')
            line, ansi_line = lines[at], ansi_lines[at]
            match = re.fullmatch(r'│ (.*?) +([●○]) (Yes|No|Limited|Unknown) +([A-Z]{2})? *│', line)
            if not match or (match[1], match[2], match[3], match[4] or '') != (name, '○' if label == 'Unknown' else '●', label, display_region) or colors[label] not in ansi_line:
                raise ValueError('Terminal row/region/color differs from JSON')
            at += 1
        if at < len(lines)-1:
            if lines[at] != separator: raise ValueError('Unexpected group footer')
            at += 1
    if at != len(lines)-1 or any(clean.count(c) != 1 for c in '╭╮╰╯'):
        raise ValueError('Extra rows/footers/frames in unified report')
    return report, terminal, errors


async def process(args, *, timeout, env=None, payload=None, max_output=MAX_OUTPUT):
    """One owned SSH process group, bounded streams, cleanup on timeout/cancel."""
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True)
    async def read(stream, limit):
        chunks, size = [], 0
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                return b''.join(chunks)
            size += len(chunk)
            if size > limit:
                raise ValueError('Unified transport output exceeds limit')
            chunks.append(chunk)
    async def write():
        if payload:
            proc.stdin.write(payload)
            await proc.stdin.drain()
        proc.stdin.close()
        try:
            await proc.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass
    tasks = [asyncio.create_task(read(proc.stdout, max_output)), asyncio.create_task(read(proc.stderr, 65536)),
             asyncio.create_task(write()), asyncio.create_task(proc.wait())]
    try:
        out, err, _, code = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        return code, out.decode('utf-8', errors='strict'), err.decode('utf-8', errors='replace')
    finally:
        # A finished SSH parent can still leave pipe-holding children; own and
        # reap its group even when the parent has already exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await proc.wait()


def owned_parent(token):
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise ValueError('Invalid unified task token')
    return '/tmp/guko-unified.' + token


def execution_command(token, digest, region="auto", family="auto"):
    if region != 'auto':
        raise ValueError('GUKO new tasks must use exit-country auto')
    if family not in ("auto", "4", "6"):
        raise ValueError("Invalid extra family")
    parent = owned_parent(token)
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid binary checksum')
    return r'''set -eu
umask 077
parent=__PARENT__
owned=0
child=
cleanup() {
 if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
 if [ "$owned" = 1 ]; then rm -rf -- "$parent"; fi
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
for cmd in mktemp rm cat chmod readlink; do command -v "$cmd" >/dev/null 2>&1 || { echo "Unified missing dependency: $cmd" >&2; exit 127; }; done
mkdir -m 700 -- "$parent"
owned=1
printf '%s' __TOKEN__ > "$parent/owner"
work=$(mktemp -d "$parent/work.XXXXXXXX")
cat > "$work/probe"
if command -v sha256sum >/dev/null 2>&1; then sum=$(sha256sum "$work/probe")
elif command -v shasum >/dev/null 2>&1; then sum=$(shasum -a 256 "$work/probe")
elif command -v openssl >/dev/null 2>&1; then sum=$(openssl dgst -sha256 -r "$work/probe")
else echo 'Unified requires an existing SHA256 tool' >&2; exit 127; fi
[ "${sum%% *}" = __DIGEST__ ] || { echo 'Unified SHA256 mismatch; refusing execution' >&2; exit 65; }
chmod 700 "$work/probe"
printf '%s' "$work/probe" > "$parent/executable"
(unset NO_COLOR; export CLICOLOR_FORCE=1 TERM=xterm-256color COLORTERM=truecolor; exec "$work/probe" --machine --extra-family __FAMILY__ --timeout 6 --workers 4) &
child=$!
printf '%s' "$child" > "$parent/pid"
set +e
wait "$child"
result=$?
child=
exit "$result"
'''.replace('__PARENT__', shlex.quote(parent)).replace('__TOKEN__', shlex.quote(token)).replace('__DIGEST__', shlex.quote(digest)).replace('__REGION__', shlex.quote(region)).replace('__FAMILY__', shlex.quote(family))


def cleanup_command(token):
    parent = owned_parent(token)
    return r'''set -eu
parent=__PARENT__
[ -d "$parent" ] || exit 0
[ ! -L "$parent" ] && [ "$(cat "$parent/owner" 2>/dev/null)" = __TOKEN__ ] || exit 66
pid=$(cat "$parent/pid" 2>/dev/null || :)
exe=$(cat "$parent/executable" 2>/dev/null || :)
case "$pid" in ''|*[!0-9]*) pid=;; esac
case "$exe" in "$parent"/work.????????/probe) :;; *) exe=;; esac
matches() { [ -n "$pid" ] && [ -n "$exe" ] && [ "$(readlink "/proc/$pid/exe" 2>/dev/null || :)" = "$exe" ]; }
if matches; then
 kill -TERM "$pid" 2>/dev/null || :
 for n in 1 2 3 4 5; do matches || break; sleep 1; done
 if matches; then kill -KILL "$pid" 2>/dev/null || :; fi
fi
# Only the exact per-task parent with its ownership marker is removed.
rm -rf -- "$parent"
'''.replace('__PARENT__', shlex.quote(parent)).replace('__TOKEN__', shlex.quote(token))


async def remote_run(server, ssh_args, ssh_env, *, region="auto", family="auto", binary_dir=BINARY_DIR, runner=process):
    if region != 'auto':
        raise ValueError('GUKO new tasks must use exit-country auto')
    if family not in ("auto", "4", "6"):
        raise ValueError("Invalid extra family")
    token = uuid.uuid4().hex
    env = ssh_env(server)
    result, failure, cleanup_error = None, None, None
    try:
        code, arch, err = await runner(ssh_args(server, 'LC_ALL=C uname -m', tty=False), timeout=20, env=env, max_output=128)
        if code != 0:
            raise RuntimeError('Unified architecture probe failed: ' + err[-500:])
        architectures = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}
        target = architectures.get(arch.strip())
        if not target:
            raise RuntimeError('Unified unsupported architecture: ' + arch.strip()[:80])
        data = (Path(binary_dir) / ('service-unlock_linux_' + target)).read_bytes()
        if not 0 < len(data) <= 16 * 1024 * 1024:
            raise ValueError('Invalid unified binary size')
        digest = hashlib.sha256(data).hexdigest()
        if digest != CATALOGUE['binary_sha256'][target]:
            raise ValueError('Packaged Service Unlock v0.5.4 checksum mismatch')
        code, raw, err = await runner(ssh_args(server, execution_command(token, digest, region, family), tty=False), timeout=1200, env=env, payload=data)
        result = (code, raw, err)
    except BaseException as exc:
        failure = exc
    finally:
        # Even a dropped SSH channel must have a separate bounded opportunity
        # to stop only this task's verified executable and remove its temp files.
        task = asyncio.create_task(runner(ssh_args(server, cleanup_command(token), tty=False), timeout=20, env=env, max_output=1024))
        try:
            code, _, err = await asyncio.shield(task)
            if code != 0:
                cleanup_error = 'Unified cleanup failed: ' + err[-500:]
        except asyncio.CancelledError as exc:
            failure = failure or exc
            try:
                await asyncio.shield(task)
            except Exception as cleanup:
                cleanup_error = str(cleanup)
        except Exception as cleanup:
            cleanup_error = str(cleanup)
    if failure is not None:
        if cleanup_error:
            setattr(failure, 'supplement_cleanup_error', cleanup_error)
        raise failure
    return (*result, cleanup_error)
