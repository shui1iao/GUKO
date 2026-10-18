#!/usr/bin/env python3
"""Build exact distributable Corresponding Source; no credentials/runtime data.
Includes fixed CLI binaries and their complete upstream source+vendor archive.
Run from a release checkout (or the uncommitted reviewed working tree).
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',default=str(ROOT/'dist'))
args=parser.parse_args()
catalogue=json.loads((ROOT/'unified_catalogue.json').read_text())
for arch,digest in catalogue['binary_sha256'].items():
    binary=ROOT/'stream-unified'/('service-unlock_linux_'+arch)
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=digest:
        raise SystemExit('Fixed CLI binary hash mismatch: '+arch)
sums={line.split()[1]:line.split()[0] for line in (ROOT/'stream-unified/source/SHA256SUMS').read_text().splitlines()}
source=ROOT/'stream-unified/source/service-unlock-v0.5.4-source.zip'
if hashlib.sha256(source.read_bytes()).hexdigest()!=sums[source.name]:raise SystemExit('CLI Corresponding Source hash mismatch')
files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
files=sorted(set(files))
for name in files:
    p=Path(name)
    if name in ('.env','history.json','servers.json','docker-compose.yml') or any(part in ('keys','results','media','node_modules','__pycache__','.git') for part in p.parts) or p.suffix=='.pyc':
        raise SystemExit('Unexpected private/generated file in source inventory: '+name)
output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
target=output/'guko-v0.6.9-source.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for name in files:
        p=ROOT/name
        if p.is_file():z.write(p,'guko-v0.6.9/'+name)
with zipfile.ZipFile(target) as z:
    if z.testzip() is not None:raise SystemExit('Source archive corruption')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
(output/'SHA256SUMS').write_text(digest+'  '+target.name+'\n')
print(digest+'  '+str(target))
