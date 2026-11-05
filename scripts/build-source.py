#!/usr/bin/env python3
"""Deterministic exact tracked Corresponding Source, never runtime/untracked data.
Stage reviewed new source before local pre-release verification. Release Actions
runs against the final clean tag. Legacy embedded CLI bundles are unreachable;
per-task CLI Corresponding Source is frozen with that task's official release.
"""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def source_files():
    names = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    result = []
    for name in sorted(set(filter(None,names))):
        p = PurePosixPath(name)
        if name.startswith('stream-unified/'):
            continue
        if (p.is_absolute() or '..' in p.parts or name in
            ('.env','servers.json','servers.yml','history.json','docker-compose.yml','local-source.tar.gz') or
            set(p.parts) & {'.git','keys','results','media','tmp','node_modules','__pycache__','dist'} or
            p.suffix in ('.pyc','.bak') or (ROOT/name).is_symlink()):
            raise ValueError('Unexpected private/generated source inventory path')
        if not (ROOT/name).is_file():
            raise ValueError('Missing tracked source file')
        result.append(name)
    required = {'version.txt','LICENSE','LICENSES/AGPL-3.0.txt','NOTICE-STREAM.md',
                'kat_proxy.py','tool_sources.py','stream_platforms.json','stream_terminal.py',
                'telegram-bot/bot.py','telegram-bot/Dockerfile','scripts/build-source.py'}
    if not required <= set(result):
        raise ValueError('Incomplete Corresponding Source')
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'dist'))
    args=parser.parse_args()
    version=(ROOT/'version.txt').read_text().strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version):
        raise SystemExit('Invalid release version')
    files=source_files()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    target=output/('guko-v'+version+'-source.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name in files:
            info=zipfile.ZipInfo('guko-v'+version+'/'+name,date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if (ROOT/name).stat().st_mode & 0o111 else 0o100644)<<16
            z.writestr(info,(ROOT/name).read_bytes())
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:raise SystemExit('Source archive corruption')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (output/'SHA256SUMS').write_text(digest+'  '+target.name+'\n')
    print(digest+'  '+str(target))

if __name__=='__main__':
    main()
