#!/usr/bin/env node
'use strict';
/** Offline ANSI display. Never load a report URL or execute log text. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const RESOURCES = path.join(__dirname, 'resources', 'checkplace-terminal');
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_COLS = 400;
const MAX_ROWS = 500;
const KINDS = new Set(['ip', 'hardware', 'net', 'backroute', 'stream']);
// Conventional xterm ANSI palette, independent of Check.Place's display theme.
const themeStream = Object.freeze({foreground: '#e5e5e5', background: '#1d1d1e',
  black: '#000000', red: '#cd0000', green: '#00cd00', yellow: '#cdcd00',
  blue: '#0000ee', magenta: '#cd00cd', cyan: '#00cdcd', white: '#e5e5e5',
  brightBlack: '#7f7f7f', brightRed: '#ff0000', brightGreen: '#00ff00', brightYellow: '#ffff00',
  brightBlue: '#5c5cff', brightMagenta: '#ff00ff', brightCyan: '#00ffff', brightWhite: '#ffffff'});
const themeAdventureTime = Object.freeze(require('./resources/checkplace-terminal/theme-adventure-time.json'));
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');

function parseArgs(args) {
  if (args.length !== 4 || args[2] !== '--kind' || !KINDS.has(args[3])) {
    throw new Error('Usage: node render_ansi.js INPUT.log OUTPUT.png --kind ip|hardware|net|backroute|stream');
  }
  return {input: args[0], output: args[1], kind: args[3]};
}

function readInput(input, preserveWhitespace = false) {
  // Read a bounded regular file through one descriptor, not stat + unbounded read.
  const fd = fs.openSync(input, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile()) throw new Error('ANSI input must be a regular file');
    if (stat.size > MAX_BYTES) throw new Error('ANSI input exceeds 2 MiB limit');
    const bytes = Buffer.alloc(MAX_BYTES + 1);
    let size = 0, n;
    do {n = fs.readSync(fd, bytes, size, bytes.length - size, null); size += n;} while (n && size < bytes.length);
    if (size > MAX_BYTES) throw new Error('ANSI input exceeds 2 MiB limit');
    let text;
    try {text = new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, size));}
    catch {throw new Error('ANSI input must be valid UTF-8');}
    // Official approved renderer trims the outside of the complete report only.
    if (!preserveWhitespace) text = text.trim();
    if (!text.trim()) throw new Error('ANSI input is empty');
    return text;
  } finally {fs.closeSync(fd);}
}

function assertTelegramPhoto(width, height, bytes) {
  if (![width, height, bytes].every(Number.isSafeInteger) || width < 1 || height < 1 || bytes < 1 ||
      width + height > 10000 || Math.max(width / height, height / width) > 20 || bytes > 10000000) {
    throw new Error('Rendered report exceeds Telegram photo limits (10 MB, width+height <= 10000, ratio <= 20); no content was cropped');
  }
}

function buildDocument(fontBase64, nonce, kind = 'ip') {
  // Only caller-supplied local font bytes and generated nonce are interpolated.
  // Logs NEVER appear in this HTML. Inline styles are necessary for xterm's DOM renderer.
  if (!/^[A-Za-z0-9+/=]+$/.test(fontBase64) || !/^[A-Za-z0-9]+$/.test(nonce)) throw new Error('Invalid local document data');
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; font-src data:; img-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; worker-src 'none'">
<style>
@font-face{font-family:${kind === 'stream' ? 'streamMono' : 'xyBarMono'};src:url(data:font/ttf;base64,${fontBase64})}
*{margin:0;padding:0}
html,body{margin:0!important;padding:0!important;background:rgb(29,29,30)!important}
body{display:flex;flex-direction:column}
#capture{display:inline-block;padding:20px;background:rgb(29,29,30)}
#terminal{height:100%;box-sizing:border-box}
.xterm-cursor-layer,.xterm-cursor{visibility:hidden!important}
</style></head><body><div id="capture"><div id="terminal"></div></div></body></html>`;
}

function loadResources() {
  const manifest = JSON.parse(fs.readFileSync(path.join(RESOURCES, 'manifest.json'), 'utf8'));
  const result = {};
  for (const name of ['xterm.js', 'xterm.css', 'theme-adventure-time.json']) {
    const data = fs.readFileSync(path.join(RESOURCES, name));
    if (sha256(data) !== manifest.files[name].sha256) throw new Error(`Terminal resource integrity mismatch: ${name}`);
    result[name] = data.toString('utf8');
  }
  return {runtime: result['xterm.js'], css: result['xterm.css'], manifest};
}

async function renderAnsi({input, output, kind}) {
  if (!KINDS.has(kind)) throw new Error('Unsupported report kind');
  if (path.resolve(input) === path.resolve(output)) throw new Error('Input and output paths must differ');
  const stream = kind === 'stream';
  const raw = readInput(input, stream);
  const resources = loadResources();
  const fontPath = stream ? '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
    : process.env.CHECKPLACE_TERMINAL_FONT || '/data/fonts/xyBarNQ.ttf';
  let font;
  try {font = fs.readFileSync(fontPath);} catch (error) {throw new Error(`Terminal font unavailable: ${fontPath} (${error.code})`);}
  if (!font.length || font.length > 8 * 1024 * 1024) throw new Error('Terminal font is empty or exceeds 8 MiB');
  const {chromium} = require('playwright');
  let browser, context, page;
  let networkRequests = 0;
  try {
    browser = await chromium.launch({executablePath: process.env.CHECKPLACE_CHROMIUM || '/usr/bin/chromium',
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking', '--disable-component-update', '--no-first-run']});
    context = await browser.newContext({viewport: {width: 1800, height: 1600}, deviceScaleFactor: 2,
      serviceWorkers: 'block', acceptDownloads: false});
    await context.route('**/*', route => {networkRequests++; return route.abort();});
    await context.routeWebSocket('**/*', socket => {networkRequests++; socket.close();});
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    const nonce = crypto.randomBytes(24).toString('hex');
    await page.setContent(buildDocument(font.toString('base64'), nonce, kind));
    await page.addStyleTag({content: resources.css});
    // Set nonce on a DOM-created script; Playwright addScriptTag has no nonce option.
    await page.evaluate(({runtime, nonce}) => {
      const script = document.createElement('script'); script.nonce = nonce; script.textContent = runtime;
      document.head.appendChild(script);
    }, {runtime: resources.runtime, nonce});
    await page.evaluate(async stream => {
      const loaded = await document.fonts.load(stream ? '14px streamMono' : '14px xyBarMono');
      await document.fonts.ready;
      if (!loaded.length || loaded.some(font => font.status !== 'loaded')) throw new Error('Terminal font failed to load');
    }, stream);
    const metrics = await page.evaluate(async ({raw, theme, maxCols, maxRows, stream}) => {
      const frame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const root = document.getElementById('terminal');
      const options = {theme: {...theme, background: '#1d1d1e', cursor: '#1d1d1e'},
        fontFamily: stream ? '"streamMono", monospace' : 'Consolas, "xyBarMono", Courier New, monospace', fontSize: 14,
        rows: maxRows, cols: maxCols, convertEol: true, scrollback: 1,
        disableStdin: true, cursorBlink: false, allowTransparency: true};
      let term;
      const write = async terminal => {
        await new Promise(resolve => terminal.write(raw + '\x1b[?25l', resolve));
        if (terminal.buffer.active.baseY > 0) throw new Error('ANSI row limit exceeded');
      };
      const measure = terminal => {
        let maxCol = 0, lastRow = -1;
        const lines = [];
        for (let y = 0; y < terminal.buffer.active.length; y++) {
          const line = terminal.buffer.active.getLine(y);
          if (line.isWrapped) throw new Error('ANSI column limit exceeded (wrapped line)');
          const text = line.translateToString(true);
          if (text.trim()) lastRow = y;
          lines.push(text);
          for (let x = 0; x < terminal.cols; x++) {
            const cell = line.getCell(x);
            if (cell.getChars().trim()) maxCol = Math.max(maxCol, x + cell.getWidth());
          }
        }
        return {maxCol, lastRow, lines};
      };
      try {
        term = new window.nqTerminal(options); term.open(root); await write(term);
        const {maxCol, lastRow, lines} = measure(term);
        if (lastRow < 0) throw new Error('ANSI report is empty after terminal parsing');
        const columns = maxCol + 4, rows = lastRow + 2;
        if (columns > maxCols || rows > maxRows) throw new Error('ANSI terminal dimension limit exceeded (including safe padding)');
        term.dispose(); root.replaceChildren();
        term = new window.nqTerminal({...options, cols: columns, rows, scrollback: 0});
        term.open(root); await write(term); term.scrollToTop(); await frame();
        const actual = measure(term).lines.slice(0, lastRow + 1);
        if (JSON.stringify(actual) !== JSON.stringify(lines.slice(0, lastRow + 1))) throw new Error('Terminal resize changed report contents');
        const dims = term.element.querySelector('.xterm-screen').getBoundingClientRect();
        const capture = document.getElementById('capture');
        capture.style.setProperty('width', (dims.width + 40) + 'px', 'important');
        capture.style.setProperty('min-width', '0', 'important');
        capture.style.setProperty('box-sizing', 'border-box', 'important');
        root.style.width = dims.width + 'px';
        window.__term = term;
        return {columns, rows, screenWidth: dims.width, screenHeight: dims.height,
          contentsPreserved: true, text: actual.join('\n')};
      } catch (error) {term?.dispose(); throw error;}
    }, {raw, theme: stream ? themeStream : themeAdventureTime, maxCols: MAX_COLS, maxRows: MAX_ROWS, stream});
    // Do not allow screenshot scrolling to trigger xterm repaint and erase label classes.
    await page.setViewportSize({width: Math.max(1800, Math.ceil(metrics.screenWidth + 40)),
      height: Math.ceil(metrics.screenHeight + 80)});
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const geometry = () => [...document.querySelectorAll('.xterm-rows > div > span')].map(span => {
      const r = span.getBoundingClientRect();
      return [r.x, r.y, r.width, r.height, getComputedStyle(span).backgroundColor, span.textContent];
    });
    const before = await page.evaluate(geometry);
    if (!stream) {
      await page.addStyleTag({content: '.xterm-rows > div > span{padding-top:1px!important;box-sizing:border-box!important}.xterm-rows > div > span.colored-label{padding-top:3px!important}'});
      await page.evaluate(kind => {
        const excluded = kind === 'ip' ? /[|]/u : /[|\u2500-\u259f\u2800-\u28ff]/u;
        for (const span of document.querySelectorAll('.xterm-rows > div > span')) {
          const bg = getComputedStyle(span).backgroundColor;
          if (bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent' && bg !== 'rgb(29, 29, 30)' && !excluded.test(span.textContent)) span.classList.add('colored-label');
        }
      }, kind);
    }
    if (JSON.stringify(before) !== JSON.stringify(await page.evaluate(geometry))) throw new Error('Background or cell geometry changed');
    // Source headers are centered with spaces for the original terminal width.
    // Safe columns and long route rows widen the PNG. Move only header rows,
    // using the rendered text bounds (including CJK), never rewrite ANSI cells.
    const headerRows = stream ? [] : await page.evaluate(kind => {
      const rows = [...document.querySelectorAll('.xterm-rows > div')];
      const lines = rows.map(row => row.textContent.trim());
      const titles = {ip: /^(?:IP质量体检报告|IP QUALITY CHECK REPORT)\s*[:：]/u,
        hardware: /^硬件质量体检报告\s*[:：]/u,
        net: /^网络质量体检报告\s*[:：]/u, backroute: /^网络质量体检报告\s*[:：]/u};
      const divider = text => /^([#*+])\1{19,}$/u.test(text);
      // Require the complete six-row frame. A missing closing divider must not
      // turn subsequent body rows into a header. Keep unknown layouts intact.
      if (!divider(lines[0] || '') || !titles[kind].test(lines[1] || '') ||
          lines[5] !== lines[0] || lines.slice(2, 5).some(line => !line || divider(line))) return [];
      const end = 5;
      const capture = document.getElementById('capture').getBoundingClientRect();
      const center = capture.x + capture.width / 2;
      const result = [];
      for (let index = 0; index <= end; index++) {
        const row = rows[index];
        const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
        const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
        const first = nodes.find(node => /\S/u.test(node.textContent));
        const last = nodes.findLast(node => /\S/u.test(node.textContent));
        if (!first) continue;
        const range = document.createRange();
        range.setStart(first, first.textContent.search(/\S/u));
        range.setEnd(last, last.textContent.trimEnd().length);
        const bounds = range.getBoundingClientRect();
        const shift = center - (bounds.left + bounds.right) / 2;
        row.style.transform = `translateX(${shift}px)`;
        const after = range.getBoundingClientRect();
        if (Math.abs((after.left + after.right) / 2 - center) > 0.1 ||
            after.left < capture.left + 19.9 || after.right > capture.right - 19.9) {
          throw new Error('Report header is not centered or would be clipped');
        }
        result.push({row: index, shift, left: after.left - capture.left,
          right: after.right - capture.left, centerX: (after.left + after.right) / 2 - capture.left});
      }
      return result;
    }, kind);
    const centeredGeometry = await page.evaluate(geometry);
    // Only header x coordinates may change; body, colors, cell sizes and text
    // must remain identical to the approved rendering.
    const rowHeight = metrics.screenHeight / metrics.rows;
    for (let i = 0; i < before.length; i++) {
      const previous = before[i], current = centeredGeometry[i];
      const row = Math.round((previous[1] - 20) / rowHeight);
      const shift = headerRows.find(header => header.row === row)?.shift || 0;
      if (!current || Math.abs(current[0] - previous[0] - shift) > 0.1 ||
          JSON.stringify(current.slice(1)) !== JSON.stringify(previous.slice(1))) {
        throw new Error('Header centering changed non-header geometry or report content');
      }
    }
    const box = await page.locator('#capture').boundingBox();
    assertTelegramPhoto(Math.round(box.width * 2), Math.round(box.height * 2), 1);
    const png = await page.locator('#capture').screenshot({type: 'png', timeout: 15000});
    const width = png.readUInt32BE(16), height = png.readUInt32BE(20);
    assertTelegramPhoto(width, height, png.length);
    // Inspect after screenshot as well: checking classes before screenshot missed a
    // real tall-report repaint bug in the prototype.
    if (JSON.stringify(centeredGeometry) !== JSON.stringify(await page.evaluate(geometry))) throw new Error('Screenshot changed terminal geometry');
    const spans = await page.evaluate(() => [...document.querySelectorAll('.xterm-rows > div > span')].map(span => ({
      text: span.textContent, padding: getComputedStyle(span).paddingTop, boxSizing: getComputedStyle(span).boxSizing,
      colored: span.classList.contains('colored-label'), background: getComputedStyle(span).backgroundColor,
      foreground: getComputedStyle(span).color,
    })));
    for (const span of stream ? [] : spans) {
      const excluded = kind === 'ip' ? /[|]/u : /[|\u2500-\u259f\u2800-\u28ff]/u;
      const colored = !['rgba(0, 0, 0, 0)', 'transparent', 'rgb(29, 29, 30)'].includes(span.background) && !excluded.test(span.text);
      if (span.padding !== (colored ? '3px' : '1px')) throw new Error('Screenshot repainted terminal label centering');
    }
    const temporary = `${output}.${crypto.randomBytes(8).toString('hex')}.tmp`;
    try {fs.writeFileSync(temporary, png, {flag: 'wx', mode: 0o600}); fs.renameSync(temporary, output);}
    finally {try {fs.unlinkSync(temporary);} catch (error) {if (error.code !== 'ENOENT') throw error;}}
    return {...metrics, width, height, bytes: png.length, sha256: sha256(png), kind,
      cellGeometryUnchanged: true, headerGeometryOnly: true, headerRows, networkRequests, fontSha256: sha256(font),
      resources: resources.manifest.files, spans};
  } finally {
    try {if (page) await page.close();}
    finally {try {if (context) await context.close();} finally {if (browser) await browser.close();}}
  }
}

module.exports = {renderAnsi, parseArgs, readInput, assertTelegramPhoto, buildDocument, themeAdventureTime};
if (require.main === module) {
  Promise.resolve().then(() => renderAnsi(parseArgs(process.argv.slice(2)))).then(({text, spans, ...metrics}) => {
    // Log only operational metadata, never private report contents.
    console.log(JSON.stringify({...metrics, terminalTextSha256: sha256(text)}));
  }).catch(error => {console.error(`ANSI render failed: ${error.message}`); process.exitCode = 1;});
}
