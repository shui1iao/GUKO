"""GUKO Kat SS/AnyTLS adapter, AGPL-3.0-only. No import-time I/O.

The remote side is a bounded, read-only POSIX collector. Never run Kat, a
manager, jq/Python or an API to read nodes. Unknown authority fails closed.
"""
import base64
import hashlib
import ipaddress
import json
import re
import shlex
from urllib.parse import quote

KINDS = ('ss', 'anytls')
PROTOCOL = {'ss': 'shadowsocks', 'anytls': 'anytls'}
METHODS = {'2022-blake3-aes-128-gcm': 16, '2022-blake3-aes-256-gcm': 32,
           '2022-blake3-chacha20-poly1305': 32, 'aes-128-gcm': 0,
           'aes-256-gcm': 0, 'chacha20-ietf-poly1305': 0}
VERSIONS = ('0.7.1', '0.7.2')
MAX_FILE = 1 << 20
MAX_TOTAL = 4 << 20
MAX_WIRE = 18 << 20
SNAPSHOT_EXIT = 20
ERROR = 'Kat发现不完整、配置不受支持或存在后端冲突；已拒绝安装/修改，请手动检查'
HEAD = 'GUKO_KAT_V1\n'
TAIL = 'GUKO_KAT_END\n'


class KatError(ValueError):
    """Only fixed secret-free text crosses the bot boundary."""


def reject(message=ERROR):
    raise KatError(message)


# No writes, temp files, eval, sourced configuration or network on this path.
SHELL = r'''
export LC_ALL=C
bad() { printf '%s\n' 'GUKO_STATUS:Kat发现不完整或配置变化，已拒绝安装/修改' >&2; exit 23; }
for t in systemctl stat od readlink sha256sum sort awk tr dirname id uname; do
 command -v "$t" >/dev/null 2>&1 || bad
done
[ "$(id -u)" = 0 ] || bad
[ -d /proc/1 ] || bad
secure() {
 p=$1
 case "$p" in /*) :;; *) bad;; esac
 case "$p" in *[!A-Za-z0-9_./+@:-]*|*/../*|*/./*|*//*) bad;; esac
 [ -f "$p" ] && [ -r "$p" ] && [ ! -L "$p" ] || bad
 mode=$(stat -c %a -- "$p") || bad
 [ "$((0$mode & 0444))" -ne 0 ] || bad
 while [ "$p" != / ]; do
  [ ! -L "$p" ] || bad
  [ "$(stat -c %u -- "$p")" = 0 ] || bad
  mode=$(stat -c %a -- "$p") || bad
  [ "$((0$mode & 0022))" -eq 0 ] || bad
  p=$(dirname -- "$p") || bad
 done
}
emit() {
 key=$1; name=$2; value=$3
 nh=$(printf '%s' "$name" | od -An -v -tx1 | tr -d ' \n') || bad
 printf 'KAT_RECORD %s %s\n' "$key" "$nh"
 printf '%s' "$value" | od -An -v -tx1 || bad
 printf '\nKAT_END\n'
}
file_record() {
 typ=$1; name=$2; path=$3
 secure "$path"
 sig=$(stat -c '%d:%i:%s:%Y:%Z:%a:%u:%g' -- "$path") || bad
 size=$(stat -c %s -- "$path") || bad
 [ "$size" -le 1048576 ] || bad
 total=$((total + size)); [ "$total" -le 4194304 ] || bad
 sum=$(sha256sum -- "$path"); sum=${sum%% *}
 nh=$(printf '%s' "$name" | od -An -v -tx1 | tr -d ' \n') || bad
 printf 'KAT_RECORD %s %s\n' "$typ" "$nh"
 od -An -v -tx1 -N 1048577 -- "$path" || bad
 printf '\nKAT_END\n'
 [ "$sig" = "$(stat -c '%d:%i:%s:%Y:%Z:%a:%u:%g' -- "$path")" ] || bad
 after=$(sha256sum -- "$path"); after=${after%% *}; [ "$sum" = "$after" ] || bad
}
props() {
 properties=$(systemctl show --no-pager -p Id -p LoadState -p ActiveState -p SubState -p MainPID -p FragmentPath -p DropInPaths -p NeedDaemonReload -p UnitFileState -p ExecStart -- "$1" 2>/dev/null)
 rc=$?
 if [ "$rc" -ne 0 ]; then
  case "$properties" in *'LoadState=not-found'*) :;; *) bad;; esac
 fi
}
discover() {
 total=0
 [ ! -L /etc/kat ] || bad
 list1=$(systemctl list-unit-files --type=service --no-legend --no-pager 'kat-*.service' 2>/dev/null) || bad
 list2=$(systemctl list-units --all --type=service --no-legend --no-pager --plain 'kat-*.service' 2>/dev/null) || bad
 units=$(printf '%s\n%s\nkat-ss.service\nkat-anytls.service\n' "$list1" "$list2" | awk 'NF {print $1}')
 # Include custom-named active services, anchored ONLY by an actual Kat exe.
 proc_count=0
 for proc in /proc/[0-9]*; do
  proc_count=$((proc_count+1)); [ "$proc_count" -le 8192 ] || bad
  [ -L "$proc/exe" ] || continue
  exe=$(readlink -- "$proc/exe" 2>/dev/null) || {
   [ ! -d "$proc" ] && continue
   # Kernel threads have an exe symlink but no userspace executable. Confirm
   # PF_KTHREAD from the kernel stat record; never skip unreadable user tasks.
   flags=$(awk '{sub(/^.*\) /, ""); print $7; exit}' "$proc/stat" 2>/dev/null) || bad
   case "$flags" in ''|*[!0-9]*) bad;; esac
   [ "$((flags & 2097152))" -ne 0 ] && continue
   bad
  }
  case "$exe" in
   /usr/local/bin/kat) :;;
   */kat|*'/kat (deleted)') bad;;
   *) continue;;
  esac
  cg=$(od -An -v -tx1 -N 16385 -- "$proc/cgroup" 2>/dev/null) || bad
  [ "$(stat -c %s -- "$proc/cgroup")" -le 16384 ] || bad
  unit=$(awk -F/ '{for(i=1;i<=NF;i++) if($i ~ /\.service$/) print $i}' "$proc/cgroup" | sort -u) || bad
  case "$unit" in ''|*'
'*) bad;; esac
  units=$(printf '%s\n%s\n' "$units" "$unit")
 done
 units=$(printf '%s\n' "$units" | sort -u)
 count=0
 for unit in $units; do
  case "$unit" in *[!A-Za-z0-9_.@:-]*|''|[!A-Za-z0-9]*) bad;; esac
  case "$unit" in *.service) :;; *) bad;; esac
  count=$((count+1)); [ "$count" -le 32 ] || bad
  props "$unit"; emit unit "$unit" "$properties"
  fragment=$(printf '%s\n' "$properties" | awk -F= '$1=="FragmentPath" {print substr($0,14)}')
  pid=$(printf '%s\n' "$properties" | awk -F= '$1=="MainPID" {print $2}')
  case "$pid" in ''|*[!0-9]*) bad;; esac
  if [ -n "$fragment" ]; then
   canonical=$(readlink -f -- "$fragment") || bad
   # Permit the ordinary /lib -> /usr/lib system alias, not redirected units.
   case "$fragment" in /lib/systemd/system/*) :;; *) [ "$canonical" = "$fragment" ] || bad;; esac
   file_record unitfile "$unit" "$canonical"
  fi
  if [ "$pid" -gt 0 ]; then
   [ "$(readlink -- "/proc/$pid/exe")" = /usr/local/bin/kat ] || bad
   disk=$(sha256sum /usr/local/bin/kat); disk=${disk%% *}
   live=$(sha256sum "/proc/$pid/exe"); live=${live%% *}; [ "$live" = "$disk" ] || bad
   # proc files have st_size=0: use bounded od, then bound bytes in bot parser.
   printf 'KAT_RECORD cmdline '; printf '%s' "$unit" | od -An -v -tx1 | tr -d ' \n'; printf '\n'
   od -An -v -tx1 -N 16385 -- "/proc/$pid/cmdline" || bad
   printf '\nKAT_END\n'
   cg=$(od -An -v -tx1 -N 16385 -- "/proc/$pid/cgroup") || bad
   emit cgroup "$unit" "$cg"
   props "$unit"
   [ "$(printf '%s\n' "$properties" | awk -F= '$1=="MainPID" {print $2}')" = "$pid" ] || bad
  fi
 done
 for kind in ss anytls; do
  legacy=anytls; bin=anytls-server; config=/etc/systemd/system/anytls.service; dir=/etc/anytls
  if [ "$kind" = ss ]; then legacy=ss-rust; bin=ss-rust; config=/etc/ss-rust/config.json; dir=/etc/ss-rust; fi
  props "$legacy.service"; emit legacy "$kind" "$properties"
  trace=0
  for f in "/usr/local/bin/$bin" "$config" "$dir" "/etc/systemd/system/$legacy.service" "/usr/lib/systemd/system/$legacy.service" "/lib/systemd/system/$legacy.service"; do
   if [ -e "$f" ] || [ -L "$f" ]; then trace=1; fi
  done
  emit legacy_trace "$kind" "$trace"
 done
 if [ -e /usr/local/bin/kat ] || [ -L /usr/local/bin/kat ]; then
  secure /usr/local/bin/kat
  [ "$(stat -c %s /usr/local/bin/kat)" -le 268435456 ] || bad
  sum=$(sha256sum /usr/local/bin/kat); emit binary kat "${sum%% *}"
 else emit binary kat absent; fi
 if [ -e /var/lib/kat-manager/kernel.json ] || [ -L /var/lib/kat-manager/kernel.json ]; then
  file_record kernel kat /var/lib/kat-manager/kernel.json
 else emit kernel kat absent; fi
 count=0
 for f in /etc/kat/*.json; do
  if [ -e "$f" ] || [ -L "$f" ]; then
   count=$((count+1)); [ "$count" -le 32 ] || bad
   secure "$f"; [ "$(stat -c %s -- "$f")" -le 1048576 ] || bad
   emit configpath "$f" "$f"
   sig=$(stat -c '%d:%i:%s:%Y:%Z:%a:%u:%g' -- "$f") || bad
   hash=$(sha256sum -- "$f"); hash=${hash%% *}
   emit configsig "$f" "$sig:$hash"
  fi
 done
 # Partial standard-unit traces never count as clean absence.
 for d in /etc/systemd/system /usr/lib/systemd/system /lib/systemd/system; do
  for f in "$d"/kat-*.service.d; do
   if [ -e "$f" ] || [ -L "$f" ]; then bad; fi
  done
 done
}
'''


def collector_command():
    return SHELL + "\nprintf 'GUKO_KAT_V1\\n'\ndiscover\nprintf 'GUKO_KAT_END\\n'\nexit 20\n"


def safe_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./+@:-]+', value) or any(x in value.split('/') for x in ('..', '.')) or '//' in value:
        reject()
    return value


def records(raw):
    if not isinstance(raw, str) or len(raw) > MAX_WIRE or not raw.startswith(HEAD) or not raw.endswith(TAIL):
        reject()
    body = raw[len(HEAD):-len(TAIL)]
    result = {}
    for block in body.split('KAT_END\n')[:-1]:
        header, sep, encoded = block.partition('\n')
        match = re.fullmatch(r'KAT_RECORD ([a-z_]+) ([0-9a-f]+)', header)
        if not sep or not match or not re.fullmatch(r'[0-9a-f \n]*', encoded):
            reject()
        try:
            name = bytes.fromhex(match[2]).decode('utf-8')
            data = bytes.fromhex(encoded)
        except (ValueError, UnicodeError):
            reject()
        key = (match[1], name)
        if key in result or len(name) > 256 or len(data) > MAX_FILE:
            reject()
        result[key] = data
    if not body.endswith('KAT_END\n') or body.split('KAT_END\n')[-1] or len(result) > 240:
        reject()
    return result


def text(data):
    try:
        value = data.decode('utf-8')
    except (UnicodeError, AttributeError):
        reject()
    if any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in value):
        reject()
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject()
        result[key] = value
    return result


def loads(data):
    try:
        return json.loads(text(data), object_pairs_hook=unique, parse_constant=lambda _: reject())
    except (ValueError, TypeError, RecursionError):
        reject()


def properties(data):
    result = {}
    for line in text(data).splitlines():
        key, sep, value = line.partition('=')
        if not sep or key in result:
            reject()
        result[key] = value
    return result


def unit_config(raw):
    allowed = {'Description', 'After', 'Wants', 'Type', 'User', 'Group', 'ExecStart',
               'Restart', 'RestartSec', 'LimitNOFILE', 'WantedBy'}
    seen, marks, start, section = set(), {}, None, None
    for line in text(raw).splitlines():
        if not line or line.startswith('#'):
            if line.startswith('# KatManager'):
                key, sep, value = line[12:].partition('=')
                if not sep or key not in ('SHA256', 'TLS', 'SNI', 'Adopted') or key in marks:
                    reject()
                marks[key] = value
            continue
        if line.startswith('['):
            if line not in ('[Unit]', '[Service]', '[Install]'):
                reject()
            section = line
            continue
        key, sep, value = line.partition('=')
        if not sep or key not in allowed or key in seen:
            reject()
        seen.add(key)
        if key == 'ExecStart':
            if section != '[Service]':
                reject()
            try:
                start = shlex.split(value)
            except ValueError:
                reject()
    if not start or len(start) != 3 or start[:2] != ['/usr/local/bin/kat', 'run']:
        reject()
    return safe_path(start[2]), marks, start


def discovery(raw):
    r = records(raw)
    allowed = {'unit','unitfile','cmdline','cgroup','legacy','legacy_trace','binary','kernel','configpath','configsig'}
    if any(k not in allowed for k, _ in r):
        reject()
    try:
        digest = text(r['binary', 'kat'])
        kernel_raw = r['kernel', 'kat']
        core = None if kernel_raw == b'absent' else loads(kernel_raw)
        if digest == 'absent':
            if core is not None:
                reject()
        elif not re.fullmatch(r'[0-9a-f]{64}', digest) or not isinstance(core, dict) or core.get('sha256') != digest or core.get('version') not in VERSIONS:
            reject('Kat内核记录/内容不一致或版本契约未知，已停止；不接管或升级内核')
        instances, paths = [], set()
        for (typ, name), data in r.items():
            if typ == 'configpath':
                if text(data) != name:
                    reject()
                paths.add(safe_path(name))
            if typ != 'unit':
                continue
            p = properties(data)
            if p.get('LoadState') == 'not-found':
                if p.get('FragmentPath') or p.get('MainPID') not in ('0', ''):
                    reject()
                continue
            if p.get('LoadState') != 'loaded' or p.get('Id') != name or p.get('DropInPaths') or p.get('NeedDaemonReload') != 'no':
                reject()
            state = p.get('ActiveState')
            if state not in ('active', 'inactive', 'failed') or state == 'active' and p.get('SubState') != 'running':
                reject()
            path, marks, argv = unit_config(r['unitfile', name])
            if not p.get('FragmentPath') or core is None:
                reject()
            # systemd structured ExecStart includes dynamic timestamps; only a
            # single exact executable/argv and no ignored failures are allowed.
            start = p.get('ExecStart', '')
            match = re.fullmatch(r'\{ path=/usr/local/bin/kat ; argv\[\]=/usr/local/bin/kat run ([/A-Za-z0-9_.+@:-]+) ; ignore_errors=no ;[^{}]*\}', start)
            if not match or match[1] != path:
                reject()
            if 'SHA256' in marks and marks['SHA256'] != digest:
                reject()
            if state == 'active':
                args = r['cmdline', name]
                if len(args) > 16384 or not args.endswith(b'\0') or args.split(b'\0')[:-1] != [v.encode() for v in argv]:
                    reject()
                cg_hex = text(r['cgroup', name])
                cg = text(bytes.fromhex(cg_hex))
                if len(cg) > 16384 or not any(line.endswith('/' + name) for line in cg.splitlines()):
                    reject()
            elif p.get('MainPID') != '0':
                reject()
            instances.append({'unit': name, 'path': path, 'state': state, 'markers': marks})
            paths.add(path)
        legacy = {}
        for kind in KINDS:
            p = properties(r['legacy', kind])
            trace = text(r['legacy_trace', kind])
            if trace not in ('0', '1'):
                reject()
            active = p.get('ActiveState')
            if active not in ('active', 'inactive', 'failed'):
                reject()
            legacy[kind] = {'trace': trace == '1' or p.get('LoadState') != 'not-found',
                            'conflict': active != 'inactive' or p.get('UnitFileState', '') not in ('', 'disabled', 'not-found', 'masked')}
        return {'digest': hashlib.sha256(raw.encode()).hexdigest(), 'records': r,
                'instances': instances, 'paths': sorted(paths), 'core': core, 'legacy': legacy}
    except (KeyError, ValueError, TypeError, UnicodeError):
        reject()


def config_command(plan):
    if len(plan['paths']) > 32 or not re.fullmatch(r'[0-9a-f]{64}', plan['digest']):
        reject()
    result = SHELL + '\nfirst=$(discover) || bad\n'
    result += 'sum=$(printf "%s\\n" "GUKO_KAT_V1" "$first" "GUKO_KAT_END" | sha256sum); sum=${sum%% *}\n'
    result += '[ "$sum" = ' + shlex.quote(plan['digest']) + ' ] || bad\n'
    result += 'printf "GUKO_KAT_V1\\n"\nprintf "%s\\n" "$first"\ntotal=0\n'
    for index, path in enumerate(plan['paths']):
        q = shlex.quote(safe_path(path))
        var = 'hash' + str(index)
        result += var+'=$(sha256sum '+q+'); '+var+'=${'+var+'%% *}\n'
        result += 'file_record config ' + q + ' ' + q + '\n'
    result += 'last=$(discover) || bad\n[ "$first" = "$last" ] || bad\n'
    for index, path in enumerate(plan['paths']):
        result += 'h=$(sha256sum '+shlex.quote(path)+'); h=${h%% *}; [ "$h" = "$hash'+str(index)+'" ] || bad\n'
    result += 'printf "GUKO_KAT_END\\n"\nexit 20\n'
    return result


def checked_string(value):
    if not isinstance(value, str) or not 1 <= len(value.encode()) <= 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        reject()
    return value


def endpoint(value):
    value = checked_string(value)
    match = re.fullmatch(r'(\[[^\]]+\]|[^:]+):([0-9]+)', value)
    if not match:
        reject()
    host = match[1].strip('[]')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        reject()
    if (ip.version == 6) != match[1].startswith('[') or not 1 <= int(match[2]) <= 65535:
        reject()
    return ip, int(match[2])


def parse_nodes(kind, plan, raw):
    if kind not in KINDS:
        reject()
    r = records(raw)
    for key, value in plan['records'].items():
        if r.get(key) != value:
            reject()
    configs = {name: loads(data) for (typ, name), data in r.items() if typ == 'config'}
    if set(configs) != set(plan['paths']) or len(r) != len(plan['records']) + len(configs):
        reject()
    nodes, target_paths = [], set()
    for path, data in configs.items():
        if not isinstance(data, dict) or not isinstance(data.get('inbounds'), list) or not 1 <= len(data['inbounds']) <= 64:
            reject()
        # We do not interpret or execute routing/provider/API blocks. The
        # supported export contract is the explicit 0.7.1/0.7.2 inbound shape.
        known_root = {'inbounds','limits','dns','routing','udp_bind_ipv4','udp_bind_ipv6','providers','outbounds','groups','rule_sets','geoip','geosite','asn','log','stats','api','security','direct'}
        if data.keys() - known_root:
            reject()
        for key in data.keys() - {'inbounds','udp_bind_ipv4','udp_bind_ipv6'}:
            expected = list if key in ('providers','outbounds','groups','rule_sets') else dict
            if not isinstance(data[key], expected):
                reject()
        for index, inbound in enumerate(data['inbounds']):
            if not isinstance(inbound, dict) or inbound.get('protocol') not in ('shadowsocks','anytls','trojan','socks5','snell','vless'):
                reject()
            ip, port = endpoint(inbound.get('listen'))
            if inbound['protocol'] != PROTOCOL[kind]:
                continue
            target_paths.add(path)
            if inbound.keys() - {'protocol','listen','users','tls','allow_insecure','ss','anytls','tcp_fast_open','sources','name','sniff'}:
                reject()
            if any(key in inbound and not isinstance(inbound[key],dict) for key in ('sources','sniff')):
                reject()
            if inbound.get('users', []) != [] or type(inbound.get('tcp_fast_open', False)) is not bool or type(inbound.get('allow_insecure', False)) is not bool:
                reject()
            owners = [item for item in plan['instances'] if item['path'] == path]
            if not owners:
                reject('存在无权威Kat服务对应的协议配置，已拒绝安装/导出')
            for owner in owners:
                if owner['unit'] in ('kat-ss.service', 'kat-anytls.service') and owner['unit'] != 'kat-' + kind + '.service':
                    reject()
                node = dict(owner, index=index+1, bind=str(ip), port=port,
                            name=checked_string(inbound['name']) if 'name' in inbound else '')
                if kind == 'ss':
                    if 'tls' in inbound or 'anytls' in inbound or not isinstance(inbound.get('ss'), dict):
                        reject()
                    ss = inbound['ss'];method = ss.get('method')
                    if method not in METHODS or ss.keys() - {'method','key','password','tcp_salts','salts_2017','sessions','udp_rcvbuf_2017'}:
                        reject()
                    field, other = ('key','password') if METHODS[method] else ('password','key')
                    password = checked_string(ss.get(field))
                    if other in ss:
                        reject()
                    if METHODS[method]:
                        try:
                            decoded = base64.b64decode(password, validate=True)
                        except ValueError:
                            reject()
                        if len(decoded) != METHODS[method] or base64.b64encode(decoded).decode() != password:
                            reject()
                    capacities = {'tcp_salts':1<<20,'sessions':1<<20,'salts_2017':32<<20,'udp_rcvbuf_2017':1048576}
                    for key in ss.keys()-{'method','key','password'}:
                        if type(ss[key]) is not int or not 0 <= ss[key] <= capacities[key]:
                            reject()
                    if ss.get('udp_rcvbuf_2017',0) not in (0,1048576) or METHODS[method] and ss.get('udp_rcvbuf_2017',0):
                        reject()
                    node.update(method=method, password=password, tls_supported=True)
                else:
                    options = inbound.get('anytls')
                    if 'ss' in inbound or not isinstance(options, dict) or options.keys() - {'password','padding_scheme','max_sessions','max_streams','session_streams','stream_bytes','session_bytes','slow_timeout'}:
                        reject()
                    node['password'] = checked_string(options.get('password'))
                    if 'slow_timeout' in options and not isinstance(options['slow_timeout'],str):
                        reject()
                    if 'padding_scheme' in options and not isinstance(options['padding_scheme'], str):
                        reject()
                    capacities = {'max_sessions':65536,'max_streams':65536,'session_streams':64,'stream_bytes':4<<20,'session_bytes':16<<20}
                    for key in capacities:
                        if key in options and (type(options[key]) is not int or not 0 <= options[key] <= capacities[key]):
                            reject()
                    if options.get('stream_bytes',0) and options['stream_bytes'] < 65542:
                        reject()
                    if (options.get('session_bytes') or 1048576) < (options.get('stream_bytes') or 131072):
                        reject()
                    marks = owner['markers']
                    policy = marks.get('TLS')
                    if 'SNI' in marks or policy not in (None,'random-insecure','legacy-insecure'):
                        reject()
                    if 'tls' not in inbound:
                        if policy not in (None, 'random-insecure'):
                            reject()
                        node['tls_supported'] = True
                    else:
                        tls = inbound['tls']
                        if not isinstance(tls, dict) or not tls:
                            reject()
                        if policy == 'random-insecure':
                            reject()
                        pair = set(tls) == {'cert','key'}
                        if pair:
                            safe_path(tls['cert']);safe_path(tls['key'])
                        node['tls_supported'] = pair and policy == 'legacy-insecure'
                        if node['tls_supported']:
                            node['tls_paths'] = [(tls['cert'],False),(tls['key'],True)]
                nodes.append(node)
    plan['config_hashes'] = {path: hashlib.sha256(r['config',path]).hexdigest() for path in configs}
    legacy = plan['legacy'][kind]
    if legacy['conflict'] or not nodes and legacy['trace']:
        reject('存在旧后端运行/残留或状态不明；不回退旧配置、不自动安装')
    if not nodes:
        # Standard/custom instance for this protocol must not be mistaken for
        # absence just because it points to another protocol's JSON.
        if any(i['unit'] == 'kat-' + kind + '.service' or i['unit'].startswith('kat-' + kind + '-') for i in plan['instances']):
            reject()
    return nodes


def quote_surge(value):
    return '"' + value.replace('\\','\\\\').replace('"','\\"') + '"'


def render(kind, host, nodes):
    host = checked_string(host)
    if not re.fullmatch(r'[A-Za-z0-9.:_-]+', host):
        reject()
    address = '[' + host + ']' if ':' in host and not host.startswith('[') else host
    lines = ['Kat实例配置文件中的节点信息，未验证连接/当前生效凭据。']
    complete = True
    for n in nodes:
        label = n['unit'] + '/' + str(n['index']) + (('/' + n['name']) if n['name'] else '')
        lines += ['-'*42, 'Kat ' + kind + ' · ' + label,
                  '配置: ' + n['path'], '状态: ' + n['state'], '地址: ' + host, '端口: ' + str(n['port'])]
        ip = ipaddress.ip_address(n['bind'])
        if not n['tls_supported'] or (not ip.is_unspecified and (ip.is_loopback or ip.is_private or ip.is_link_local)):
            complete = False
            lines.append('unsupported：TLS验证/SNI或绑定可达性无法确定，未生成完整客户端项。')
            continue
        p, password = str(n['port']), n['password']
        lines += ['密码: ' + password]
        if kind == 'ss':
            method = n['method']
            auth = method + ':' + quote(password,safe='') if METHODS[method] else base64.urlsafe_b64encode((method+':'+password).encode()).decode().rstrip('=')
            lines += ['加密: ' + method, 'Surge:', 'VPS = ss, '+address+', '+p+', encrypt-method='+method+', password='+quote_surge(password)+', udp-relay=true',
                      'URI:', 'ss://'+auth+'@'+address+':'+p+'#'+quote(label,safe='')]
        else:
            entry = {'name':label,'type':'anytls','server':host,'port':n['port'],'password':password,'skip-cert-verify':True,'udp':True}
            lines += ['Surge:', 'VPS = anytls, '+address+', '+p+', password='+quote_surge(password)+', skip-cert-verify=true, udp-relay=true',
                      'Mihomo:', '- '+json.dumps(entry,ensure_ascii=False,separators=(',',':')),
                      'URI:', 'anytls://'+quote(password,safe='')+'@'+address+':'+p+'?security=tls&type=tcp&allowInsecure=1&insecure=1#'+quote(label,safe='')]
    if len('\n'.join(lines)) > 200000:
        reject('Kat节点输出超出安全限额，未静默截断；请缩小实例范围后人工检查')
    return '\n'.join(lines), complete


PREFLIGHT = r'''
for t in bash python3 curl sha256sum mktemp timeout; do
 command -v "$t" >/dev/null 2>&1 || bad
done
[ "$(uname -s)" = Linux ] || bad
case "$(uname -m)" in x86_64|amd64) :;; *) bad;; esac
[ -d /run/systemd/system ] || bad
printf 'GUKO_KAT_PREFLIGHT_OK\n'
'''


def preflight_command():
    return SHELL + '\n' + PREFLIGHT


def install_command(kind, host, default_port, plan, source):
    """A final discovery+configuration guard BEFORE downloads or mutation.

    The Manager lock and own install refusal remain additional guardrails. No
    update action, dependency bootstrap or implicit installation from ensure.
    """
    from tool_sources import shell_download
    if kind not in KINDS:
        reject()
    host = checked_string(host)
    if not re.fullmatch(r'[A-Za-z0-9.:_-]+', host):
        reject()
    if default_port and (not str(default_port).isascii() or not str(default_port).isdigit() or not 1 <= int(default_port) <= 65535):
        reject('Kat默认端口不合法，已停止')
    if set(plan['paths']) != set(plan.get('config_hashes',{})):
        reject()
    command = SHELL + '\n' + PREFLIGHT.replace("printf 'GUKO_KAT_PREFLIGHT_OK\\n'", '')
    command += '\nfirst=$(discover) || bad\nsum=$(printf "%s\\n" "GUKO_KAT_V1" "$first" "GUKO_KAT_END" | sha256sum); sum=${sum%% *}\n'
    command += '[ "$sum" = ' + shlex.quote(plan['digest']) + ' ] || bad\n'
    # JSON bytes from the parsed full snapshot must ALSO remain unchanged.
    for path, digest in plan.get('config_hashes', {}).items():
        q=shlex.quote(safe_path(path))
        if not re.fullmatch(r'[0-9a-f]{64}',digest):
            reject()
        command += 'secure '+q+'; sum=$(sha256sum '+q+'); sum=${sum%% *}; [ "$sum" = '+shlex.quote(digest)+' ] || bad\n'
    command += 'umask 077; work=$(mktemp -d /tmp/guko-kat-install.XXXXXXXX) || bad\ntrap \'rm -rf -- "$work"\' EXIT\ntrap \'exit 130\' HUP INT TERM\n'
    for name in ('kat.sh','kat_manager.py','kat_config.py'):
        command += shell_download(source['files'][name], '"$work/'+name+'"')+'\n'
    args = ['install',kind,'--host',host]
    if default_port:
        args += ['--port',str(default_port)]
    core = source['server']
    if core['mode'] == 'new':
        command += shell_download(core['binary'],'"$work/core"')+'\nchmod 700 "$work/core"\n'
        extra = ' --binary "$work/core" --sha256 '+shlex.quote(core['sha256'])+' --version '+shlex.quote(core['version'].lstrip('v'))
    elif core['mode'] == 'reuse':
        extra = ' --version '+shlex.quote(core['version'])
    else:
        reject()
    # No credential-bearing installer output crosses SSH/history/error logs.
    command += 'timeout 1500 bash "$work/kat.sh" '+shlex.join(args)+extra+' >"$work/install.log" 2>&1\nrc=$?\nprintf "GUKO_KAT_INSTALL_RC:%s\\n" "$rc"\nexit "$rc"\n'
    return command



def tls_metadata_command(paths):
    if len(paths) > 64:
        reject()
    command = SHELL + '\n'
    for path, is_key in paths:
        q = shlex.quote(safe_path(path))
        # Only stat metadata. Never read/hash private key or certificate bytes.
        command += 'secure ' + q + '\n'
        if is_key:
            command += 'mode=$(stat -c %a '+q+'); [ "$((0$mode & 0077))" -eq 0 ] || bad\n'
    return command + "printf 'GUKO_KAT_TLS_METADATA_OK\\n'\n"
