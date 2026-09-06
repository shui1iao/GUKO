# Frozen Check.Place terminal display resources

These resources reproduce the **four user-approved centered ANSI screenshots**.
They are not the Report.Check.Place SVG renderer and not a replacement terminal
release. Do not update typography, padding, palette, terminal dependency, browser
or installed fonts without running the private golden suite.

## Provenance and exact extraction

- Input: audited official frontend asset `/assets/index-HO53nBUc.js`, saved as
  `nq-bundle.js`, and its stylesheet saved as `nq.css`.
- `manifest.json` records the complete input SHA-256 values, extraction boundaries,
  the untouched runtime's SHA-256, and every vendored artifact's SHA-256/size.
- `xterm.js`: the independent CommonJS/UMD-normalized xterm runtime inside that
  bundle, copied verbatim between `var Ci={exports:{}},To;function du()` and
  `var pc=du()`. A closure and `window.nqTerminal=du().Terminal` expose it locally.
  No Vue app, analytics, API signing, uploads or website startup is included.
- **Upstream xterm semver is not asserted:** the source does not supply reliable
  version metadata. This is a content-addressed pin, not a guessed npm version.
- `xterm.css`: all 43 rules whose selectors contain `.xterm`, in original order,
  including official scrollbar, foreground/background and font-stack overrides.
  No other website CSS is shipped. The tiny layout reset in `render_ansi.js`
  reproduces the approved wrapper's inherited flex layout.
- `theme-adventure-time.json`: the exact `AdventureTime` color constants from the
  same bundle; renderer exports `themeAdventureTime` and overrides only background
  and cursor to `#1d1d1e`, as the approved source does.

Re-extract with Python 3 (offline):

```sh
python3 extract_official.py /audit/nq-bundle.js /audit/ansi/nq.css
```

The extractor verifies frozen source hashes before writing, checks CSS rule
coverage, and never reads/copies a font. Runtime loads verify resource hashes.

## Licensing / private font

`LICENSE.xterm` is the **actual MIT copyright/permission header preserved from
the official xterm stylesheet**, including xterm authors and Christopher Jeffrey
attribution. It is also retained in `xterm.js` and `xterm.css`. This notice is not
an assertion that the complete Check.Place website is MIT-licensed. Site-specific
color constants/CSS overrides are retained as necessary display configuration;
no separate license declaration for those overrides was present in the audited
assets, and none is invented here.

**No font binary is included.** The runtime reads only the operator-provided
`CHECKPLACE_TERMINAL_FONT` (default `/data/fonts/xyBarNQ.ttf`) and embeds it as a
local data-URI under family `xyBarMono`. Missing/invalid font is fatal: there is
no silent substitute, remote download, conversion, or cache publication.

The supplied font's metadata says:

> Owned by xykt@GitHub
> Free to Display, Development or Commercial Use Requires Authorization

Keep its metadata/notice intact and keep it out of git and public images. Use a
private read-only bind mount for original-report display. Obtain authorization
for uses requiring it; vendoring the terminal does **not** license this font.

## CLI and runtime contract

```sh
node telegram-bot/render_ansi.js INPUT.log OUTPUT.png --kind ip
```

Kinds: `ip`, `hardware`, `net`, `backroute`. Requires Node 24, Playwright 1.59.1
and system Chromium plus the same installed fallback fonts as the audited image.
`CHECKPLACE_CHROMIUM` optionally selects a local executable (default
`/usr/bin/chromium`). The parent process owns wall-clock timeout and concurrency.

- Reads bounded UTF-8 regular files, maximum 2 MiB; empty/unprintable input fails.
- Preserves official outer-report `trim()` behavior and xterm SGR, CJK cell width,
  CR/backspace, cursor/control semantics; ANSI is only passed as data to `write`.
- Measures cells on a 400-column/500-row terminal, rejects wrapping/overflow,
  recreates with content width +4 columns and last content row +2, and asserts
  complete line identity. Limits include this safe padding.
- Fixed 14px font, official font stack/theme, 20px padding, DPR 2. Normal spans
  get 1px top padding; colored spans 3px with border-box. IP excludes `|`;
  other kinds also exclude box/block and Braille ranges.
- Fits viewport **before** labeling; asserts geometry and label padding both
  before/after screenshot. Never crops or silently changes approved appearance.
- Telegram limits: output <=10,000,000 bytes, width+height <=10,000, aspect ratio
  <=20. Extreme reports fail clearly rather than being cropped/rescaled.
- Browser HTTP routes and WebSockets are blocked; service workers/downloads are
  disabled. CSP allows only nonce-authorized local runtime, inline terminal CSS
  and data fonts; no network, frames, objects or executable report markup.
  Run with container `--network none` for browser-process-level isolation too.
- Always closes page/context/browser. Writes a mode-0600 temporary output and
  atomically renames only after validation; failures create no partial PNG.
- CLI stdout contains one JSON metadata record (sizes, hashes and invariants),
  never report text. Errors go to stderr and return a nonzero exit status.

## Tests

Synthetic fixtures contain no real IPs, reports or proprietary font data:

```sh
node --test telegram-bot/tests/test_render_ansi.js
```

For the optional private **byte-exact** four-image regression suite, additionally
set `CHECKPLACE_ANSI_AUDIT` to the directory holding `ansi/*.log` and
`approved-manifest.json`. `CHECKPLACE_ANSI_BASELINES` may remap the approved
image basenames to a read-only mount. The approved hashes are frozen in the test.

```sh
node --test telegram-bot/tests/test_render_ansi*.js
```

Initial RED: missing production renderer assertion failed. Synthetic coverage
includes SGR/truecolor/bold/italic/CJK/combining characters, CR/backspace, literal
HTML/OSC links, actual CSP enforcement, span geometry, graph exclusions,
empty/oversized/invalid UTF-8 input, row/column/Telegram limits, missing font and
resource tampering. Private acceptance matched all four PNG SHA-256 values and
all dimensions exactly; independent pixel comparison found zero differing pixels.
