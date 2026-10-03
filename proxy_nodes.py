"""Fail-closed node discovery; collect on SSH, parse/render in GUKO.

The target needs only a POSIX shell and coreutils, not Python. Existing nodes
never enter a manager (even its view may install dependencies or migrate files).
"""
import base64
import configparser
import json
import re
import shlex
from typing import NoReturn
from urllib.parse import quote, urlencode

XRAY_COMPAT = 'perl -0pi -e \'s/\\$XRAY_BIN test -config "\\$CONFIG"/if \\$XRAY_BIN help 2>\\/dev\\/null | grep -qE "^[[:space:]]*test[[:space:]]"; then \\$XRAY_BIN test -config "\\$CONFIG"; else \\$XRAY_BIN run -test -config "\\$CONFIG"; fi/\' "$tmp"; perl -0pi -e \'s/\\"geoip:private\\"/\\"127.0.0.0\\\\\\/8\\",\\"10.0.0.0\\\\\\/8\\",\\"172.16.0.0\\\\\\/12\\",\\"192.168.0.0\\\\\\/16\\",\\"fc00::\\\\\\/7\\"/g\' "$tmp"; '

CONFIGS = {'ss': '/etc/ss-rust/config.json', 'anytls': '/etc/systemd/system/anytls.service',
           'snell': '/etc/snell/snell-server.conf', 'vless': '/usr/local/etc/xray/config.json'}
BINS = {'ss': 'ss-rust', 'anytls': 'anytls-server', 'snell': 'snell-server', 'vless': 'xray'}
# Exit 10 remains exclusively 'no installation traces'. 20 is a snapshot,
# never installer output; the caller must validate/render it before success.
SNAPSHOT_EXIT = 20
SNAPSHOT_HEADER = 'GUKO_SNAPSHOT_V1:'
MAX_FILE_BYTES = 262144
# od adds spaces and a newline to each row, not just two hex digits per byte.
MAX_SNAPSHOT_BYTES = 2 * (MAX_FILE_BYTES * 4 + 256)
READ_ERROR = '配置缺失、损坏或不可读取；已拒绝安装/修改，请手动检查'
RULE = '-' * 42


class ProxyReadError(ValueError):
    """Only fixed, secret-free diagnostics may cross the bot boundary."""


def fail(message=READ_ERROR) -> NoReturn:
    raise ProxyReadError(message)


# od is both an encoder and a bounded reader, so its exit status cannot be
# lost in a pipeline. No temp files, eval, sourced configs or network calls.
# The optional VLESS summary can be unreadable without affecting plain TCP.
COLLECTOR = r'''has_trace() { [ -e "$1" ] || [ -L "$1" ]; }
collect_file() {
    file=$1
    key=$2
    if ! [ -f "$file" ] || ! [ -r "$file" ]; then
        printf '%s:unavailable\nGUKO_END_FILE\n' "$key"
        return
    fi
    permissions=$(stat -L -c %a -- "$file" 2>/dev/null) || return 23
    case "$permissions" in ''|*[!0-7]*) return 23 ;; esac
    # Root can read mode 000; deliberately reject it as the old reader did.
    if [ "$((0$permissions & 0444))" -eq 0 ]; then
        printf '%s:unavailable\nGUKO_END_FILE\n' "$key"
        return
    fi
    value=$(od -An -v -tx1 -N __READ_LIMIT__ -- "$file" 2>/dev/null) || return 23
    printf '%s:ok\n%s\nGUKO_END_FILE\n' "$key" "$value"
}
'''.replace('__READ_LIMIT__', str(MAX_FILE_BYTES + 1))


def snapshot_command(kind: str):
    config = CONFIGS[kind]
    service = {'ss': 'ss-rust', 'vless': 'xray'}.get(kind, kind)
    traces = ['/usr/local/bin/' + BINS[kind], config]
    traces += [directory + '/' + service + '.service' for directory in
               ('/etc/systemd/system', '/usr/lib/systemd/system', '/lib/systemd/system')]
    traces += (['/etc/xray', '/usr/local/etc/xray', '/etc/systemd/system/xray-vless.service']
               if kind == 'vless' else ['/etc/' + {'ss': 'ss-rust'}.get(kind, kind)])
    command = COLLECTOR + 'present=0\n'
    for trace in traces:
        command += 'if has_trace ' + shlex.quote(trace) + '; then present=1; fi\n'
    command += '[ "$present" -eq 1 ] || exit 10\n'
    command += 'printf "%s\\n" ' + shlex.quote(SNAPSHOT_HEADER + kind) + '\n'
    command += 'config=' + shlex.quote(config) + '\n'
    if kind == 'vless':
        command += 'if ! has_trace "$config" && has_trace /etc/xray/vless-basic.json; then config=/etc/xray/vless-basic.json; fi\n'
    command += 'collect_file "$config" config || exit 23\n'
    if kind == 'vless':
        command += 'collect_file /usr/local/etc/xray/client.txt client || exit 23\n'
    return command + 'printf "GUKO_END_SNAPSHOT\\n"\nexit ' + str(SNAPSHOT_EXIT) + '\n'


def parse_snapshot(kind, raw):
    """Reject truncated/oversized/extra records, with no raw data in errors."""
    if kind not in CONFIGS or not isinstance(raw, str) or len(raw) > MAX_SNAPSHOT_BYTES:
        fail()
    if not raw.startswith(SNAPSHOT_HEADER + kind + '\n') or not raw.endswith('GUKO_END_SNAPSHOT\n'):
        fail()
    body = raw[len(SNAPSHOT_HEADER + kind + '\n'):-len('GUKO_END_SNAPSHOT\n')]
    records = body.split('GUKO_END_FILE\n')
    keys = ('config', 'client') if kind == 'vless' else ('config',)
    if len(records) != len(keys) + 1 or records[-1] != '':
        fail()
    files = {}
    for key, record in zip(keys, records):
        if record == key + ':unavailable\n':
            files[key] = None
            continue
        if not record.startswith(key + ':ok\n'):
            fail()
        encoded = record[len(key + ':ok\n'):]
        if len(encoded) > 4 * (MAX_FILE_BYTES + 1) or not re.fullmatch(r'[0-9a-f \n]+', encoded):
            fail()
        try:
            data = bytes.fromhex(encoded)
        except ValueError:
            fail()
        # Plain VLESS does not use client.txt. Preserve strict framing while
        # treating unusable optional content exactly like an unavailable file;
        # TLS/Reality still fail when render_snapshot actually requires it.
        if len(data) > MAX_FILE_BYTES:
            if key != 'client':
                fail()
            files[key] = None
            continue
        try:
            files[key] = data.decode('utf-8')
        except UnicodeError:
            if key != 'client':
                fail()
            files[key] = None
    return files


def snell_version_command():
    # The final status marker is inside timeout and the bounded pipe. Missing
    # tools, truncation, a hang or a failed -v can never produce a guessed major.
    return r'''binary=/usr/local/bin/snell-server
if [ -f "$binary" ] && [ -x "$binary" ]; then
    timeout 5 sh -c '"$1" -v 2>&1; printf "\nGUKO_VERSION_RC:%s\n" "$?"' guko "$binary" 2>/dev/null | head -c 4097
fi
'''


def snell_major(raw):
    if not isinstance(raw, str) or len(raw) > 4096 or not raw.endswith('\nGUKO_VERSION_RC:0\n'):
        return None
    match = re.search(r'(?i)\bv?([1-9][0-9]*)\.[0-9]+\.[0-9]+', raw)
    return match[1] if match else None


def port(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 65535:
        fail()
    return int(value)


def secret(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        fail()
    return value


def render_snapshot(kind, host, files, version_output=''):
    def read(key):
        value = files.get(key)
        if not isinstance(value, str) or not value.strip():
            fail()
        return value

    host = host or '<服务器IP>'
    try:
        address = '[' + host + ']' if ':' in host and not host.startswith('[') else host
        if kind == 'ss':
            data = json.loads(read('config'))
            p, password, method = port(data['server_port']), secret(data['password']), secret(data['method'])
            auth = method + ':' + quote(password, safe='') if method.startswith('2022-') else base64.urlsafe_b64encode((method + ':' + password).encode()).decode().rstrip('=')
            # Same layout as SS-Rust-Manager's view, built from the file only.
            output = '\n'.join((
                RULE, 'ss-rust 当前配置', '地址: ' + host, '端口: ' + str(p), '密码: ' + password,
                '加密: ' + method, RULE, 'Surge:',
                'VPS = ss, ' + address + ', ' + str(p) + ', encrypt-method=' + method + ', password=' + password + ', udp-relay=true',
                'URI:', 'ss://' + auth + '@' + address + ':' + str(p) + '#VPS', RULE))
        elif kind == 'anytls':
            lines = [line.split('=',1)[1] for line in read('config').splitlines() if line.startswith('ExecStart=')]
            if len(lines) != 1:
                fail()
            args = shlex.split(lines[0])
            if args.count('-l') != 1 or args.count('-p') != 1:
                fail()
            p = port(args[args.index('-l')+1].rsplit(':',1)[1])
            password = secret(args[args.index('-p')+1])
            mihomo = json.dumps({'name': 'VPS', 'server': host, 'port': p, 'password': password,
                                 'skip-cert-verify': True, 'type': 'anytls'}, ensure_ascii=False, separators=(',', ':'))
            # Same layout as AnyTLS-Manager's view, built from the unit only.
            output = '\n'.join((
                RULE, 'anytls 当前配置', '地址: ' + host, '端口: ' + str(p), '密码: ' + password, RULE, 'Surge:',
                'VPS = anytls, ' + address + ', ' + str(p) + ', password=' + json.dumps(password, ensure_ascii=False) + ', skip-cert-verify=true, udp-relay=true',
                'Mihomo:', '  - ' + mihomo,
                'URI:', 'anytls://' + quote(password, safe='/') + '@' + address + ':' + str(p) + '?security=tls&type=tcp&allowInsecure=1&insecure=1#VPS',
                RULE))
        elif kind == 'snell':
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.read_string(read('config'))
            data = parser['snell-server']
            p, password = port(data['listen'].split(',')[0].rsplit(':',1)[1].strip()), secret(data['psk'])
            # The bot fetches only local -v, after the configuration validates.
            major = snell_major(version_output)
            output = 'Snell 当前配置\n地址: ' + host + '\n端口: ' + str(p) + '\n密码: ' + password + '\n模式: ' + data.get('mode', 'default') + '\nVPS = snell, ' + address + ', ' + str(p) + ', psk=' + json.dumps(password, ensure_ascii=False)
            if major:
                output += ', version=' + major
            else:
                output = output.split('\nVPS = ', 1)[0] + '\n核心版本不可读取；请沿用现有客户端 version 参数，未生成猜测节点'
            for option in ('obfs', 'obfs-host'):
                if data.get(option): output += ', ' + option + '=' + json.dumps(data[option], ensure_ascii=False)
        else:
            data = json.loads(read('config'))
            inbounds = data['inbounds']
            if not isinstance(inbounds, list) or not inbounds:
                fail()
            nodes = [node for node in inbounds if node.get('protocol') == 'vless']
            if not nodes:
                fail('检测到现有 Xray 配置不是 VLESS，为避免覆盖已拒绝安装')
            output = []
            for node in nodes:
                p = port(node['port'])
                stream = node.get('streamSettings', {})
                network, security = stream.get('network', 'tcp'), stream.get('security', 'none')
                clients = node['settings']['clients']
                if not clients: fail()
                for client in clients:
                    uid = secret(client['id'])
                    if network in ('tcp', 'raw') and security in ('none', ''):
                        query = {'encryption':'none', 'security':'none', 'type':network}
                        if client.get('flow'): query['flow'] = client['flow']
                        output.append('VLESS 当前配置\nvless://' + quote(uid, safe='') + '@' + address + ':' + str(p) + '?' + urlencode(query) + '#VPS')
                    else:
                        # Preserve the original manager's mode-specific summary, never
                        # re-run its migration/render functions (they write files).
                        summary = read('client')
                        if uid not in summary or ':' + str(p) not in summary or 'security=' + security not in summary:
                            fail('现有 VLESS 客户端摘要与服务端配置不匹配或缺失；已拒绝修改')
                        output.append('VLESS 当前配置\n' + summary)
            output = '\n'.join(dict.fromkeys(output))
        return 'GUKO_STATUS:已安装，直接读取当前配置\n' + output
    except ProxyReadError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, configparser.Error, RecursionError):
        fail()


def remote_command(kind, action, script, answers, host, mode=None, port=''):
    if kind not in CONFIGS or action not in ('install', 'ensure', 'view'):
        raise ValueError('未知操作')
    command = 'export TERM=xterm-256color;\n(\n' + snapshot_command(kind) + ')\nrc=$?;\n'
    command += 'if [ "$rc" -ne 10 ]; then exit "$rc"; fi;\n'
    if action == 'view':
        return command + 'echo "GUKO_STATUS:未安装，暂无配置"; exit 23\n'
    install = 'printf %b ' + shlex.quote(answers) + ' | bash "$tmp" install'
    if kind == 'vless':
        choice = '3' if mode == 'reality' else '2'
        if port:
            install = 'printf %b ' + shlex.quote(choice + '\n' + answers + '\n0\n') + ' | bash "$tmp"'
        else:
            install = 'guko_port=8443; if ss -lnt | awk \'NR>1 {print $4}\' | grep -Eq \'(^|:)8443$\'; then while :; do guko_port=$(shuf -i 20000-65000 -n 1); ss -lnt | awk \'NR>1 {print $4}\' | grep -Eq "(^|:)${guko_port}$" || break; done; echo "GUKO_STATUS:默认端口 8443 已占用，改用 $guko_port"; fi; printf %b "' + choice + '\\n${guko_port}\\n\\n0\\n" | bash "$tmp"'
    if kind == 'vless':
        install = XRAY_COMPAT + install
    # Only a confirmed-absent node reaches here. Merge installer stderr (curl
    # progress, prompts, systemd notices) remotely so it keeps its real order
    # instead of trailing the rendered config; snapshots stay stdout-only.
    return (command + 'exec 2>&1;\n'
            'cd /root || exit $?;\n'
            'tmp=$(mktemp /root/guko-' + kind + '.XXXXXX.sh) || exit $?;\n'
            'trap \'rm -f "$tmp"\' EXIT;\n'
            'curl -LfsS ' + shlex.quote(script) + ' -o "$tmp" || exit $?;\n'
            'bash -n "$tmp" || exit $?;\n'
            'echo "GUKO_STATUS:未安装，开始安装";\n' + install + '\n')
