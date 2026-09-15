"""Fail-closed node discovery and read-only configuration rendering.

No manager view is used: SS view installs dependencies; Xray's menu migrates
legacy services. Only an entirely absent node may run the user's installer.
The embedded stdlib-only reader runs on the SSH target, without network access.
"""
import shlex

# Keep the established fresh-Xray compatibility fixes; never run on existing nodes.
XRAY_COMPAT = 'perl -0pi -e \'s/\\$XRAY_BIN test -config "\\$CONFIG"/if \\$XRAY_BIN help 2>\\/dev\\/null | grep -qE "^[[:space:]]*test[[:space:]]"; then \\$XRAY_BIN test -config "\\$CONFIG"; else \\$XRAY_BIN run -test -config "\\$CONFIG"; fi/\' "$tmp"; perl -0pi -e \'s/\\"geoip:private\\"/\\"127.0.0.0\\\\\\/8\\",\\"10.0.0.0\\\\\\/8\\",\\"172.16.0.0\\\\\\/12\\",\\"192.168.0.0\\\\\\/16\\",\\"fc00::\\\\\\/7\\"/g\' "$tmp"; '

# Exit 10 is exclusively 'no installation traces'; every other error is fatal.
READER = r'''
import base64, configparser, json, os, re, shlex, subprocess, sys
from pathlib import Path
from urllib.parse import quote, urlencode
kind, host = sys.argv[1:]
bins = {'ss':'ss-rust', 'anytls':'anytls-server', 'snell':'snell-server', 'vless':'xray'}
configs = {'ss':'/etc/ss-rust/config.json', 'anytls':'/etc/systemd/system/anytls.service',
           'snell':'/etc/snell/snell-server.conf', 'vless':'/usr/local/etc/xray/config.json'}
service = {'ss':'ss-rust', 'vless':'xray'}.get(kind, kind)
config = Path(configs[kind])
traces = [Path('/usr/local/bin') / bins[kind], config,
          Path('/etc/systemd/system') / (service + '.service'),
          Path('/usr/lib/systemd/system') / (service + '.service'),
          Path('/lib/systemd/system') / (service + '.service')]
if kind == 'vless':
    traces += [Path('/etc/xray'), Path('/usr/local/etc/xray'), Path('/etc/systemd/system/xray-vless.service')]
else:
    traces += [Path('/etc') / {'ss':'ss-rust'}.get(kind, kind)]
if not any(os.path.lexists(p) for p in traces):
    sys.exit(10)

def fail(message='配置缺失、损坏或不可读取；已拒绝安装/修改，请手动检查'):
    print('GUKO_STATUS:' + message)
    sys.exit(23)

def read(path):
    # Reject dangling symlinks, empty files and files without any read bits,
    # including when SSH runs as root. Never print parser exceptions/secrets.
    if not path.is_file() or not path.stat().st_mode & 0o444:
        fail()
    value = path.read_text()
    if not value.strip():
        fail()
    return value

def port(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 65535:
        fail()
    return int(value)

def secret(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        fail()
    return value

try:
    address = '[' + host + ']' if ':' in host and not host.startswith('[') else host
    if kind == 'ss':
        data = json.loads(read(config))
        p, password, method = port(data['server_port']), secret(data['password']), secret(data['method'])
        auth = quote(method + ':' + password, safe='') if method.startswith('2022-') else base64.urlsafe_b64encode((method + ':' + password).encode()).decode().rstrip('=')
        output = 'SS 当前配置\nss://' + auth + '@' + address + ':' + str(p) + '#VPS'
    elif kind == 'anytls':
        lines = [line.split('=',1)[1] for line in read(config).splitlines() if line.startswith('ExecStart=')]
        if len(lines) != 1:
            fail()
        args = shlex.split(lines[0])
        if args.count('-l') != 1 or args.count('-p') != 1:
            fail()
        p = port(args[args.index('-l')+1].rsplit(':',1)[1])
        password = secret(args[args.index('-p')+1])
        output = 'AnyTLS 当前配置\nanytls://' + quote(password, safe='') + '@' + address + ':' + str(p) + '?security=tls&type=tcp&allowInsecure=1&insecure=1#VPS'
    elif kind == 'snell':
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(read(config))
        data = parser['snell-server']
        p, password = port(data['listen'].split(',')[0].rsplit(':',1)[1].strip()), secret(data['psk'])
        # Snell's client requires its installed major version. This documented
        # local -v is read-only (also used by the original manager), never an
        # update/release check. No binary is invoked for other protocols.
        major = None
        binary = Path('/usr/local/bin/snell-server')
        if binary.is_file() and os.access(binary, os.X_OK):
            try:
                result = subprocess.run([str(binary), '-v'], capture_output=True, text=True, timeout=5)
                match = re.search(r'(?i)\bv?([1-9][0-9]*)\.[0-9]+\.[0-9]+', result.stdout + result.stderr)
                if result.returncode == 0 and match:
                    major = match[1]
            except (OSError, subprocess.TimeoutExpired):
                pass
        output = 'Snell 当前配置\n地址: ' + host + '\n端口: ' + str(p) + '\n密码: ' + password + '\n模式: ' + data.get('mode', 'default') + '\nVPS = snell, ' + address + ', ' + str(p) + ', psk=' + json.dumps(password, ensure_ascii=False)
        if major:
            output += ', version=' + major
        else:
            output = output.split('\nVPS = ', 1)[0] + '\n核心版本不可读取；请沿用现有客户端 version 参数，未生成猜测节点'
        for option in ('obfs', 'obfs-host'):
            if data.get(option): output += ', ' + option + '=' + json.dumps(data[option], ensure_ascii=False)
    else:
        if not os.path.lexists(config) and os.path.lexists('/etc/xray/vless-basic.json'):
            config = Path('/etc/xray/vless-basic.json')
        data = json.loads(read(config))
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
                    summary = read(Path('/usr/local/etc/xray/client.txt'))
                    if uid not in summary or ':' + str(p) not in summary or 'security=' + security not in summary:
                        fail('现有 VLESS 客户端摘要与服务端配置不匹配或缺失；已拒绝修改')
                    output.append('VLESS 当前配置\n' + summary)
        output = '\n'.join(dict.fromkeys(output))
    print('GUKO_STATUS:已安装，直接读取当前配置')
    print(output)
except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, configparser.Error):
    fail()
'''


def remote_command(kind, action, script, answers, host, mode=None, port=''):
    if kind not in ('ss', 'anytls', 'snell', 'vless') or action not in ('install', 'ensure', 'view'):
        raise ValueError('未知操作')
    reader = 'python3 - ' + shlex.quote(kind) + ' ' + shlex.quote(host or '<服务器IP>') + " <<'GUKO_READER'\n" + READER + '\nGUKO_READER\n'
    command = 'export TERM=xterm-256color;\n' + reader + 'rc=$?;\n'
    command += 'if [ "$rc" -eq 0 ]; then exit 0; fi;\nif [ "$rc" -ne 10 ]; then exit "$rc"; fi;\n'
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
    return (command + 'cd /root || exit $?;\n'
            'tmp=$(mktemp /root/guko-' + kind + '.XXXXXX.sh) || exit $?;\n'
            'trap \'rm -f "$tmp"\' EXIT;\n'
            'curl -LfsS ' + shlex.quote(script) + ' -o "$tmp" || exit $?;\n'
            'bash -n "$tmp" || exit $?;\n'
            'echo "GUKO_STATUS:未安装，开始安装";\n' + install + '\n')
