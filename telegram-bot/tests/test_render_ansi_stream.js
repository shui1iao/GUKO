'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {renderAnsi, parseArgs} = require('../render_ansi.js');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stream-terminal-'));
test.after(() => fs.rmSync(dir, {recursive: true, force: true}));
const render = async (name, raw) => {
  const input = path.join(dir, name + '.ansi');
  fs.writeFileSync(input, raw);
  return renderAnsi({input, output: path.join(dir, name + '.png'), kind: 'stream'});
};
test('CLI accepts stream without changing existing report kinds', () => {
  for (const kind of ['stream', 'ip', 'hardware', 'net', 'backroute'])
    assert.equal(parseArgs(['in', 'out', '--kind', kind]).kind, kind);
});
test('stream preserves tabs, CR, blank lines, indentation and conventional SGR colors', async () => {
  const previous = process.env.CHECKPLACE_TERMINAL_FONT;
  process.env.CHECKPLACE_TERMINAL_FONT = '/no-private-font-for-stream.ttf';
  try {
    const raw = ' ** Checking Results Under IPv4\n\n\r Netflix:\t\t\x1b[33mOriginals Only\x1b[0m\n\r Disney+:\t\t\x1b[31mNo\x1b[0m\n\r YouTube:\t\t\x1b[32mYes\x1b[0m\n\x1b[36mISP\x1b[0m\nprogress 0%\rprogress 100%\n\x1b[41mBG\x1b[0m';
    const m = await render('controls', raw);
    assert.equal(m.text, ' ** Checking Results Under IPv4\n\n Netflix:               Originals Only\n Disney+:               No\n YouTube:               Yes\nISP\nprogress 100%\nBG');
    assert.equal(m.contentsPreserved, true);
    assert.equal(m.networkRequests, 0);
    assert.deepEqual(m.headerRows, []);
    assert.ok(m.spans.every(s => s.padding === '0px' && !s.colored));
    for (const [text, color] of [['Originals Only', 'rgb(205, 205, 0)'], ['No', 'rgb(205, 0, 0)'], ['Yes', 'rgb(0, 205, 0)'], ['ISP', 'rgb(0, 205, 205)']])
      assert.equal(m.spans.find(s => s.text === text)?.foreground, color, text);
    assert.equal(m.fontSha256, crypto.createHash('sha256').update(fs.readFileSync('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')).digest('hex'));
  } finally {
    if (previous === undefined) delete process.env.CHECKPLACE_TERMINAL_FONT;
    else process.env.CHECKPLACE_TERMINAL_FONT = previous;
  }
});
test('real upstream JP report keeps all 49 rows and original section layout', async () => {
  const raw = fs.readFileSync(path.join(__dirname, '../../tests/fixtures/rrc-live-jp.txt'), 'utf8');
  const start = raw.lastIndexOf('\n', raw.indexOf('** Checking Results Under')) + 1;
  const end = raw.indexOf('\n', raw.indexOf('Testing Done!')) + 1;
  const report = raw.slice(start, end);
  const m = await render('jp', report);
  // Every literal upstream row survives. Only xterm tab stops and CR interpretation apply.
  const expected = report.replace(/\x1b\[[0-9;]*m/g, '').replace(/\r/g, '').trimEnd().split('\n').map(line => {
    let text = '';
    for (const c of line) text += c === '\t' ? ' '.repeat(8 - text.length % 8) : c;
    return text; // Literal upstream trailing spaces are terminal cells too.
  }).join('\n');
  assert.equal(m.text, expected);
  assert.equal(m.text.split('\n').filter(line => /^ [^*].*:\s+/.test(line)).length, 49);
  assert.ok(m.text.includes('J:com On Demand:'));
  assert.ok(m.text.includes('Project Sekai: Colorful Stage:'));
  assert.ok(m.text.includes('Testing Done! Thanks for Using This Script!'));
  assert.deepEqual(m.headerRows, []);
  assert.equal(m.networkRequests, 0);
  assert.ok(m.width + m.height <= 10000);
});
test('stream fails rather than cropping long or empty reports', async () => {
  await assert.rejects(render('wide', 'W'.repeat(401)), /limit|wrap/i);
  await assert.rejects(render('blank', '\x1b[31m\x1b[0m'), /empty/i);
});
