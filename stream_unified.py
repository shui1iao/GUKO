"""Official CLI execution/transport only, AGPL-3.0-only.

The CLI owns catalogue, verdicts, geography and presentation. GUKO only
accepts a complete supported machine envelope and safely relays its original
terminal/report. No imports perform network I/O. SSH policy remains in bot.py.
"""
import asyncio
import hashlib
import json
import os
import re
import shlex
import signal
import uuid
import tool_sources

MAX_OUTPUT = 2 * 1024 * 1024
FORMAT = 'guko-unified-v1'
SGR = re.compile(r'\x1b\[[0-9;:]{0,120}m')


def normalize_terminal(text):
    # Name retained for callers; intentionally no normalization/reconstruction.
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_OUTPUT:
        raise ValueError('CLI terminal is empty or oversized')
    plain = SGR.sub('', text)
    if any(ord(c) < 32 and c not in '\n\r\t' or 0x7f <= ord(c) <= 0x9f for c in plain):
        raise ValueError('Unsafe terminal control; only SGR/text is supported')
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def validate_output(raw, code, *, family='auto'):
    """Minimal --machine execution contract, never business validation.

    Exit 1 with a complete envelope is upstream's inconclusive report. We do
    not count Unknowns or compare any verdict, ID, country, row or ANSI style.
    Additional envelope/report fields are preserved, not an adapter upgrade.
    """
    if family not in ('auto', '4', '6') or type(code) is not int or code not in (0, 1):
        raise ValueError('CLI execution failed; no previous version used')
    if not isinstance(raw, str) or not raw.strip() or len(raw.encode('utf-8')) > MAX_OUTPUT:
        raise ValueError('CLI machine output is empty or oversized')
    try:
        doc = json.loads(raw, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        if not isinstance(doc, dict) or doc.get('format') != FORMAT or not isinstance(doc.get('report'), dict) or not doc['report']:
            raise ValueError('Unsupported or incomplete CLI machine envelope')
        # Reject invalid Unicode even inside untrusted raw report metadata.
        json.dumps(doc, ensure_ascii=False).encode('utf-8', errors='strict')
        terminal = normalize_terminal(doc.get('terminal'))
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise ValueError('Invalid CLI JSON/UTF8 envelope') from None
    return doc['report'], terminal, code == 1


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


async def remote_run(server, ssh_args, ssh_env, *, region="auto", family="auto", runner=process, identity_out=None):
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
            raise RuntimeError('Unified architecture probe failed; no previous version used')
        architectures = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}
        target = architectures.get(arch.strip())
        if not target:
            raise RuntimeError('Unified unsupported architecture; no previous version used')
        data, source = await asyncio.to_thread(tool_sources.stream_source, target)
        if identity_out is not None:
            identity_out.update(source)
        digest = source['binary']['sha256']
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Unified frozen binary SHA256 mismatch; not executed')
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
                cleanup_error = 'Unified scoped cleanup failed; manual review required'
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
