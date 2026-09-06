#!/usr/bin/env python3
"""Re-extract the exact standalone terminal from the audited official bundle.

Usage: python3 extract_official.py /path/to/nq-bundle.js /path/to/nq.css
No networking. Source hashes must match the frozen manifest before extraction.
The private font is deliberately not an input or output of this tool.
"""
import hashlib
import json
import re
import sys
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extract(bundle_path, css_path, output):
    bundle_bytes, css_bytes = Path(bundle_path).read_bytes(), Path(css_path).read_bytes()
    manifest_path = output / 'manifest.json'
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        assert sha(bundle_bytes) == existing['sources']['bundle']['sha256'], 'Bundle source mismatch'
        assert sha(css_bytes) == existing['sources']['css']['sha256'], 'CSS source mismatch'
    bundle, css = bundle_bytes.decode(), css_bytes.decode()
    start = bundle.index('var Ci={exports:{}},To;function du()')
    end = bundle.index('var pc=du()', start)
    runtime = bundle[start:end]
    assert runtime.endswith('}(Ci)),Ci.exports}')
    license_start = css.index('/**\n * Copyright (c) 2014 The xterm.js authors.')
    license_end = css.index('*/', license_start) + 2
    license_text = css[license_start:license_end]
    # Keep rule order, including Check.Place's color / scrollbar overrides.
    # All source xterm rules are flat; assert coverage rather than dropping a rule.
    rules = [m.group(0).strip() for m in re.finditer(r'[^{}]+\{[^{}]*\}', css[:license_start] + css[license_end:])
             if '.xterm' in m.group(0).split('{')[0]]
    assert sum(rule.count('.xterm') for rule in rules) == css.count('.xterm'), 'Nested CSS rules require review'
    theme_start = bundle.index(',d={foreground:', bundle.index('function _u()')) + 3
    theme_end = bundle.index('},b={', theme_start) + 1
    theme_literal = bundle[theme_start:theme_end]
    theme = json.loads(re.sub(r'(\w+):', r'"\1":', theme_literal))
    assets = {
        'xterm.js': (license_text + '\n(function(){\n' + runtime + '\nwindow.nqTerminal=du().Terminal;\n})();\n').encode(),
        'xterm.css': (license_text + '\n' + '\n'.join(rules) + '\n').encode(),
        'theme-adventure-time.json': (json.dumps(theme, indent=2) + '\n').encode(),
        'LICENSE.xterm': (license_text + '\n').encode(),
    }
    for name, data in assets.items():
        (output / name).write_bytes(data)
    manifest = {
        'version': 'official-index-HO53nBUc-content-addressed (upstream semver not asserted)',
        'sources': {
            'bundle': {'url': 'https://nodequality.com/assets/index-HO53nBUc.js', 'sha256': sha(bundle_bytes)},
            'css': {'description': 'Official CSS saved as nq.css alongside audited bundle', 'sha256': sha(css_bytes)},
        },
        'extraction': {'runtimeStartCharacters': start, 'runtimeEndCharacters': end,
                       'runtimeUnmodifiedSha256': sha(runtime.encode()), 'xtermCSSRules': len(rules)},
        'files': {name: {'sha256': sha(data), 'bytes': len(data)} for name, data in assets.items()},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    extract(sys.argv[1], sys.argv[2], Path(__file__).resolve().parent)
