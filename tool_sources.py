"""Task-scoped official source identities. AGPL-3.0-only.

No import-time I/O, background updater or version fallback. Only immutable
content downloads are cached; latest/entry discovery always makes a new request.
Hashes without an upstream digest establish content identity, NOT signatures.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
from datetime import datetime, timezone
import urllib.parse
import urllib.request
import zipfile


class SourceError(ValueError):
    """Fixed diagnostics only: never propagate HTTP bodies, tokens or node data."""


OFFICIAL_HOSTS = {'api.github.com', 'github.com', 'raw.githubusercontent.com',
                  'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
ENTRIES = {
    'ipq': ('https://IP.Check.Place', 'xykt/IPQuality', 'ip.sh'),
    'nq': ('https://run.NodeQuality.com', 'LloydAsp/NodeQuality', 'NodeQuality.sh'),
    'snell': ('https://snell.siaoz.si', 'shui1iao/Snell-Manager', 'snell.sh'),
}
HEX = r'[0-9a-f]{64}'


def _url(url, hosts):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
        raise SourceError('官方来源地址不符合受信范围，已停止；未回退旧版。')
    return url


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=4 * 1024 * 1024, *, hosts=OFFICIAL_HOSTS):
    _url(url, hosts)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GUKO/0.7.0',
                                                   'Cache-Control': 'no-cache'})
        with urllib.request.build_opener(_Redirect(hosts)).open(req, timeout=60) as response:
            final = _url(response.geturl(), hosts)
            body = response.read(limit + 1)
        if not body or len(body) > limit:
            raise SourceError('官方来源内容为空或超出限额，已停止。')
        return body, final
    except SourceError:
        raise
    except Exception:
        raise SourceError('无法读取官方最新版来源，已停止；未回退旧版。') from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError('官方元数据有重复字段，已停止。')
        result[key] = value
    return result


def api(path):
    data, _ = fetch('https://api.github.com/repos/' + path)
    try:
        return json.loads(data, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception:
        raise SourceError('官方版本元数据不兼容，已停止。') from None


def commit_for(repo, ref):
    data = api(repo + '/commits/' + urllib.parse.quote(ref, safe=''))
    commit = data.get('sha') if isinstance(data, dict) else None
    if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
        raise SourceError('不能确认官方版本commit，已停止。')
    return commit


def latest_release(repo):
    # Intentionally NEVER cached, including when all asset bytes already exist.
    data = api(repo + '/releases/latest')
    if not isinstance(data, dict) or data.get('draft') is not False or data.get('prerelease') is not False:
        raise SourceError('没有可确认的官方正式latest，已停止。')
    tag = data.get('tag_name')
    if not isinstance(tag, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._+-]{0,95}', tag):
        raise SourceError('官方发行tag不兼容，已停止。')
    assets = data.get('assets')
    if not isinstance(assets, list) or len({a.get('name') for a in assets}) != len(assets):
        raise SourceError('官方发行资产集合不完整，已停止。')
    commit = commit_for(repo, tag)
    return {'repository': repo, 'version': tag, 'commit': commit, 'release_id': data['id'],
            'release_url': 'https://github.com/' + repo + '/releases/tag/' + tag,
            'source_offer': 'https://github.com/' + repo + '/tree/' + commit,
            'assets': assets, 'resolved_at': datetime.now(timezone.utc).isoformat()}


def cached(url, digest, limit, expected_size=None):
    if not re.fullmatch(HEX, digest):
        raise SourceError('缺少必要SHA256，已停止。')
    root = Path(os.environ.get('TMP_DIR', '/data/tmp')) / 'guko-tool-downloads'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise SourceError('下载缓存目录不安全，已停止。')
    target = root / digest
    if target.is_symlink():
        raise SourceError('下载缓存文件不安全，已停止。')
    hit = target.is_file()
    if hit:
        if target.stat().st_size > limit:
            raise SourceError('下载缓存超出限额，已停止。')
        body = target.read_bytes()
    else:
        body, _ = fetch(url, limit)
    if not body or len(body) > limit or hashlib.sha256(body).hexdigest() != digest or (expected_size is not None and len(body) != expected_size):
        raise SourceError('官方资产或下载缓存hash/大小校验失败，已停止；不回退。')
    if not hit:
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as f:
            path = Path(f.name)
            try:
                f.write(body)
                f.close()
                os.chmod(path, 0o600)
                os.replace(path, target)
            finally:
                path.unlink(missing_ok=True)
    return body, hit, str(target)


def release_asset(release, name, limit):
    matches = [a for a in release['assets'] if a.get('name') == name]
    if len(matches) != 1:
        raise SourceError('官方同一发行缺少必要架构/摘要/源码资产，已停止。')
    a = matches[0]
    expected = 'https://github.com/%s/releases/download/%s/%s' % (release['repository'], release['version'], name)
    digest = a.get('digest', '')
    size = a.get('size')
    if a.get('browser_download_url') != expected or not re.fullmatch('sha256:' + HEX, digest) or type(size) is not int or not 0 < size <= limit:
        raise SourceError('官方发行资产身份/digest不完整，已停止。')
    body, hit, path = cached(expected, digest[7:], limit, size)
    identity = {'url': expected, 'sha256': digest[7:], 'download_cache': hit,
                'path': path, 'integrity': 'GitHub release asset SHA256 digest'}
    return body, identity


def identity(release):
    return {k: v for k, v in release.items() if k != 'assets'}


def stream_source(arch):
    if arch not in ('amd64', 'arm64'):
        raise SourceError('Service Unlock不支持此架构，已停止。')
    r = latest_release('shui1iao/service-unlock')
    if r['version'] != 'v0.5.6':
        raise SourceError('Service Unlock发行标识不兼容，已停止。')
    binary_name = 'service-unlock_linux_' + arch
    source_name = 'service-unlock-' + r['version'] + '-source.zip'
    sums, sums_id = release_asset(r, 'SHA256SUMS', 16384)
    body, binary_id = release_asset(r, binary_name, 16 * 1024 * 1024)
    source, source_id = release_asset(r, source_name, 96 * 1024 * 1024)
    try:
        lines = sums.decode('ascii').splitlines()
        pairs = [line.split() for line in lines]
        if any(len(p) != 2 or not re.fullmatch(HEX, p[0]) for p in pairs):
            raise ValueError()
        hashes = {p[1].lstrip('*'): p[0] for p in pairs}
        if len(hashes) != len(pairs) or hashes[binary_name] != binary_id['sha256'] or hashes[source_name] != source_id['sha256']:
            raise ValueError()
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            names = z.namelist()
            if any(n.startswith('/') or '..' in n.split('/') for n in names):
                raise ValueError()
            if not all(any(n.endswith('/' + f) for n in names) for f in ('go.mod', 'go.sum', 'LICENSE', 'LICENSE-AGPL-3.0.txt', 'vendor/modules.txt')):
                # Exact filename of AGPL notice is checked against available standard locations below.
                if not all(any(n.endswith('/' + f) for n in names) for f in ('go.mod', 'go.sum', 'LICENSE', 'vendor/modules.txt')) or not any('AGPL' in n.upper() and not '/vendor/' in n for n in names):
                    raise ValueError()
    except Exception:
        raise SourceError('CLI同发行SUMS/完整对应源码校验失败，已停止。') from None
    meta = identity(r)
    meta.update(arch=arch, binary=binary_id, sums=sums_id, source=source_id,
                source_offer=source_id['url'], contract='v0.5.6 raw168/platform145; schema1')
    return body, meta


def tcp_source():
    r = latest_release('ibsgss/TcpQuality')
    base = 'https://raw.githubusercontent.com/ibsgss/TcpQuality/' + r['commit']
    files = {}
    for name in ('runTcpQuality.sh', 'runTcpQuality-core.sh'):
        data, url = fetch(base + '/' + name)
        required = (b'--no-rootfs', b'runTcpQuality-core.sh', b'TCPQUALITY_RAW_BASE') if name == 'runTcpQuality.sh' else (b'TCPQUALITY',)
        if not data.startswith(b'#!') or any(token not in data for token in required):
            raise SourceError('TCP脚本接口与现有no-rootfs适配不兼容，已停止。')
        files[name] = {'url': url, 'sha256': hashlib.sha256(data).hexdigest(),
                       'download_cache': False, 'integrity': 'official HTTPS fixed commit; content identity, not signature'}
    meta = identity(r)
    meta.update(files=files, raw_base=base)
    return meta


def nexttrace_source(arch):
    architectures = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64',
                     'i386': '386', 'i686': '386', 'armv7l': 'armv7', 'armv6l': 'armv6',
                     'riscv64': 'riscv64', 'loongarch64': 'loong64', 's390x': 's390x', 'ppc64le': 'ppc64le'}
    target = architectures.get(arch)
    if not target:
        raise SourceError('NextTrace不支持此架构，已停止；未调用全局旧程序。')
    r = latest_release('nxtrace/NTrace-core')
    _, binary = release_asset(r, 'nexttrace_linux_' + target, 64 * 1024 * 1024)
    meta = identity(r)
    meta.update(arch=target, binary=binary)
    return meta


def script_source(kind):
    entry, repo, filename = ENTRIES[kind]
    hosts = OFFICIAL_HOSTS | {urllib.parse.urlsplit(entry).hostname}
    data, final = fetch(entry, hosts=hosts)
    p = urllib.parse.urlsplit(final)
    prefix = '/' + repo + '/'
    if p.hostname != 'raw.githubusercontent.com' or not p.path.startswith(prefix) or not p.path.endswith('/' + filename):
        raise SourceError('官方脚本入口来源变化，需适配后再运行。')
    ref = p.path[len(prefix):-(len(filename)+1)]
    if ref.startswith('refs/heads/'):
        ref = ref[11:]
    if not re.fullmatch('[A-Za-z0-9._/-]{1,100}', ref):
        raise SourceError('官方脚本分支不兼容，已停止。')
    commit = commit_for(repo, ref)
    fixed = 'https://raw.githubusercontent.com/' + repo + '/' + commit + '/' + filename
    frozen, _ = fetch(fixed)
    if data != frozen:
        raise SourceError('官方入口与冻结commit内容变化，已停止；请重新发起任务。')
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeError:
        raise SourceError('官方脚本编码不兼容，已停止。') from None
    if not text.startswith('#!') or '\x00' in text:
        raise SourceError('官方脚本不是受支持内容，已停止。')
    required = {'ipq': ('Report.Check.Place',),
                'nq': ('hardware_quality.log', 'ip_quality.log', 'net_quality.log', 'backroute_trace.log',
                       'rm -rf $work_dir/BenchOs'),
                'snell': ('install)', 'install_snell',)}
    if any(token not in text for token in required[kind]):
        raise SourceError('官方脚本接口与现有适配不兼容，已停止。')
    match = re.search(r'(?m)^(?:SCRIPT_VERSION|script_version|VERSION|version)=["\x27]?([vV]?[0-9][A-Za-z0-9._-]*)', text)
    return {'repository': repo, 'version': match[1] if match else None, 'commit': commit,
            'entry_url': entry, 'entry_final_url': final, 'url': fixed,
            'resolved_at': datetime.now(timezone.utc).isoformat(),
            'sha256': hashlib.sha256(data).hexdigest(), 'download_cache': False,
            'source_offer': 'https://github.com/' + repo + '/tree/' + commit,
            'integrity': 'official HTTPS fixed commit; content identity, not signature'}


def gb5_source():
    # Use only an explicit official legacy listing. Never probe guessed CDN versions,
    # select GB6, or reuse an existing 5.5.1 binary as a latest fallback.
    page_url = 'https://www.geekbench.com/download/legacy/'
    try:
        data, final = fetch(page_url, hosts={'www.geekbench.com', 'geekbench.com'})
    except SourceError:
        raise SourceError('官方页面无法确认Geekbench 5系列最新版，已停止；不使用5.5.1或6兜底。') from None
    text = data.decode('utf-8', errors='strict')
    packages = re.findall(r'https://cdn\.geekbench\.com/Geekbench-(5\.[0-9]+\.[0-9]+)-Linux\.tar\.gz', text)
    if not packages or 'Geekbench 5' not in text:
        raise SourceError('官方页面无法确认Geekbench 5系列最新版，已停止；不使用5.5.1或6兜底。')
    version = max(set(packages), key=lambda v: tuple(map(int, v.split('.'))))
    url = 'https://cdn.geekbench.com/Geekbench-' + version + '-Linux.tar.gz'
    body, final_binary = fetch(url, 160 * 1024 * 1024, hosts={'cdn.geekbench.com'})
    return {'repository': 'Primate Labs/Geekbench', 'version': version, 'commit': None,
            'resolved_at': datetime.now(timezone.utc).isoformat(),
            'listing_url': final, 'listing_sha256': hashlib.sha256(data).hexdigest(),
            'url': final_binary, 'sha256': hashlib.sha256(body).hexdigest(), 'download_cache': False,
            'source_offer': 'https://www.geekbench.com/',
            'integrity': 'official HTTPS linked package; content identity, not signature', 'arch': 'x86_64 Linux (GB5 existing product)'}


def shell_download(meta, destination):
    """Download only frozen URL and verify the exact bytes on the target too."""
    url, digest = meta['url'], meta['sha256']
    if not re.fullmatch(HEX, digest):
        raise SourceError('任务内容摘要无效，已停止。')
    _url(url, OFFICIAL_HOSTS | {'cdn.geekbench.com'})
    return ("curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 180 "
            + shlex.quote(url) + ' -o ' + destination + ' || exit 65; '
            + "printf '%s  %s\\n' " + shlex.quote(digest) + ' ' + destination
            + ' | sha256sum -c - >/dev/null || { echo "GUKO: frozen tool SHA256 mismatch"; exit 65; }; ')


def kat_install_source(existing_core=None):
    """Called ONLY after a user-confirmed install and a clean Kat snapshot.

    Current official main, not the older same-labelled v0.1.1 tag. Freeze all
    helpers as one set. Existing shared cores are never updated.
    """
    repo = 'shui1iao/Kat-Manager'
    commit = commit_for(repo, 'main')
    base = 'https://raw.githubusercontent.com/' + repo + '/' + commit
    files, bodies = {}, {}
    for name in ('kat.sh', 'kat_manager.py', 'kat_config.py'):
        body, _ = fetch(base + '/' + name, 1024 * 1024)
        try:
            text = body.decode('utf-8')
        except UnicodeError:
            raise SourceError('Kat-Manager组件编码不兼容，已停止。') from None
        if '\x00' in text:
            raise SourceError('Kat-Manager组件内容不兼容，已停止。')
        bodies[name] = text
        files[name] = {'url': base + '/' + name, 'sha256': hashlib.sha256(body).hexdigest(),
                       'download_cache': False, 'integrity': 'official HTTPS fixed commit; content identity, not signature'}
    wrapper = bodies['kat.sh']
    for name, label in (('kat_manager.py','MANAGER'), ('kat_config.py','CONFIG')):
        pins = re.findall(r'(?m)^KAT_HELPER_' + label + r'_SHA256="([0-9a-f]{64})"$', wrapper)
        if pins != [files[name]['sha256']]:
            raise SourceError('Kat脚本与同commit helper pins不一致，已停止。')
    manager = bodies['kat_manager.py']
    required = ('def do_install(self):', 'def acquire(self):', "'--credential-file'", "'--host'",
                "'https://github.com/shui1iao/Kat-Server/releases/download'",
                "'https://api.github.com/repos/shui1iao/Kat-Server/releases/latest'",
                "'复用已安装的 Kat 内核 '")
    if any(token not in manager for token in required) or 'exec python3 "$kat_dir/kat_manager.py" "$@"' not in wrapper:
        raise SourceError('Kat安装接口/共享内核复用契约变化，已停止。')
    version = re.findall(r"(?m)^VERSION = '([^']+)'$", manager)
    if len(version) != 1:
        raise SourceError('Kat-Manager版本身份不完整，已停止。')
    meta = {'repository': repo, 'version': version[0], 'commit': commit, 'files': files,
            'resolved_at': datetime.now(timezone.utc).isoformat(), 'download_cache': False,
            'source_offer': 'https://github.com/' + repo + '/tree/' + commit}
    if existing_core is not None:
        if existing_core.get('version') not in ('0.7.1','0.7.2') or not re.fullmatch(HEX, str(existing_core.get('sha256'))):
            raise SourceError('已有共享Kat内核身份不可靠，已停止；不接管或升级。')
        meta['server'] = {'mode':'reuse', 'version':existing_core['version'],
                          'sha256':existing_core['sha256'], 'version_evidence':'existing validated kernel record and binary hash',
                          'source_offer':'https://github.com/shui1iao/Kat-Server/tree/v'+existing_core['version']}
    else:
        release = latest_release('shui1iao/Kat-Server')
        if release['version'] not in ('v0.7.1','v0.7.2'):
            raise SourceError('Kat-Server最新配置契约未经支持，已停止；不回退旧版。')
        asset = 'kat-' + release['version'][1:] + '-linux-amd64'
        sums, sums_id = release_asset(release, asset + '.sha256', 4096)
        _, binary_id = release_asset(release, asset, 256 * 1024 * 1024)
        if sums.decode('ascii').strip() != binary_id['sha256'] + '  ' + asset:
            raise SourceError('Kat-Server同发行binary/SHA不一致，已停止。')
        server = identity(release)
        server.update(mode='new', binary=binary_id, checksum=sums_id, sha256=binary_id['sha256'])
        meta['server'] = server
    return meta
