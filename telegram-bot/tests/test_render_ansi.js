'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const rendererPath = path.join(__dirname, '..', 'render_ansi.js');
const available = fs.existsSync(rendererPath);
test('offline ANSI renderer exists', () => assert.ok(available, 'missing production render_ansi.js'));
if (available) {
  const {renderAnsi, readInput, parseArgs, assertTelegramPhoto, buildDocument} = require(rendererPath);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ansi-tests-'));
  const input = (name, data) => {const p=path.join(dir,name+'.log');fs.writeFileSync(p,data);return p;};
  test.after(() => fs.rmSync(dir,{recursive:true,force:true}));
  test('CLI accepts only explicit report kinds and paths', () => {
    assert.deepEqual(parseArgs(['a.log','b.png','--kind','ip']),{input:'a.log',output:'b.png',kind:'ip'});
    for(const args of [[],['a','b'],['a','b','--kind','svg'],['a','b','--kind','ip','extra']]) assert.throws(()=>parseArgs(args),/Usage|kind/);
    assert.notEqual(spawnSync(process.execPath,[rendererPath],{encoding:'utf8'}).status,0);
  });
  test('input rejects empty, oversized, invalid UTF-8 and non-file', () => {
    assert.throws(()=>readInput(input('empty',' \n\t')),/empty/i);
    assert.throws(()=>readInput(input('large',Buffer.alloc(2*1024*1024+1,65))),/2 MiB/);
    assert.throws(()=>readInput(input('utf8',Buffer.from([0xff]))),/UTF-8/);
    assert.throws(()=>readInput(dir),/regular file/);
  });
  test('Telegram dimensions, aspect ratio and bytes have hard limits', () => {
    assert.doesNotThrow(()=>assertTelegramPhoto(2206,3956,900000));
    for (const v of [[5000,5001,1],[21,1,1],[1,21,1],[100,100,10000001],[0,100,1]]) assert.throws(()=>assertTelegramPhoto(...v),/Telegram/);
  });
  test('document contains restrictive offline CSP and local font only', () => {
    const html=buildDocument('AA==','testnonce');
    assert.match(html,/default-src 'none'/);
    assert.match(html,/connect-src 'none'/);
    assert.match(html,/font-src data:/);
    assert.doesNotMatch(html,/https?:|file:\/\/|unsafe-eval/);
    assert.match(html,/font-family:xyBarMono/);
  });
  test('CSP blocks executable HTML and outbound requests in real Chromium', async () => {
    const {chromium}=require('playwright');
    const browser=await chromium.launch({executablePath:process.env.CHECKPLACE_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
    try {
      const context=await browser.newContext({serviceWorkers:'block'});let requests=0;
      await context.route('**/*',r=>{requests++;return r.abort();});
      const page=await context.newPage();await page.setContent(buildDocument('AA==','testnonce'));
      const state=await page.evaluate(async()=>{
        const script=document.createElement('script');script.textContent='window.__unsafe=true';document.head.appendChild(script);
        const image=document.createElement('img');image.src='https://invalid.test/image';image.setAttribute('onerror','window.__unsafe=true');document.body.appendChild(image);
        let blocked=false;try{await fetch('https://invalid.test/collect')}catch{blocked=true}
        await new Promise(r=>setTimeout(r,50));
        return {unsafe:window.__unsafe===true,blocked};
      });
      assert.deepEqual(state,{unsafe:false,blocked:true});assert.equal(requests,0);
    } finally {await browser.close();}
  });
  test('vendored resources are hash-pinned and contain no private font', async () => {
    const crypto=require('node:crypto');
    const resourceDir=path.join(__dirname,'..','resources','checkplace-terminal');
    const manifest=JSON.parse(fs.readFileSync(path.join(resourceDir,'manifest.json'),'utf8'));
    for(const [name,entry] of Object.entries(manifest.files)) {
      const bytes=fs.readFileSync(path.join(resourceDir,name));assert.equal(bytes.length,entry.bytes);
      assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),entry.sha256);
    }
    assert.ok(fs.readdirSync(resourceDir).every(name=>!(/\.(ttf|woff2?|otf)$/i.test(name))));
    assert.equal(manifest.extraction.xtermCSSRules,43);
    const copy=path.join(dir,'tampered');fs.mkdirSync(copy);fs.copyFileSync(rendererPath,path.join(copy,'render_ansi.js'));
    fs.cpSync(path.join(__dirname,'..','resources'),path.join(copy,'resources'),{recursive:true});
    fs.appendFileSync(path.join(copy,'resources','checkplace-terminal','xterm.css'),'/*tampered*/');
    await assert.rejects(require(path.join(copy,'render_ansi.js')).renderAnsi({input:input('integrity','data'),output:path.join(dir,'integrity.png'),kind:'ip'}),/integrity mismatch/);
  });
  test('synthetic terminal preserves CJK, SGR, CR, backspace, HTML and centered geometry', async () => {
    const fixture=path.join(__dirname,'fixtures','terminal-synthetic.ansi');
    const metrics=await renderAnsi({input:fixture,output:path.join(dir,'synthetic.png'),kind:'hardware'});
    assert.equal(metrics.contentsPreserved,true);
    assert.equal(metrics.cellGeometryUnchanged,true);
    assert.equal(metrics.networkRequests,0);
    assert.ok(metrics.text.includes('progress 100%'));
    assert.ok(metrics.text.includes('abZ'));
    assert.ok(metrics.text.includes('<img src="https://invalid.test/x" onerror="alert(1)">'));
    assert.ok(metrics.text.includes('中文 é 😀'));
    const labels=metrics.spans.filter(s=>s.text.includes('机房'));
    assert.ok(labels.length>0); assert.ok(labels.every(s=>s.padding==='3px'));
    for(const span of metrics.spans.filter(s=>/[|\u2500-\u259f\u2800-\u28ff]/u.test(s.text))) assert.equal(span.padding,'1px');
    assert.equal(metrics.width,fs.readFileSync(path.join(dir,'synthetic.png')).readUInt32BE(16));
    assert.equal(metrics.height,fs.readFileSync(path.join(dir,'synthetic.png')).readUInt32BE(20));
    assert.ok(metrics.spans.every(s=>s.boxSizing==='border-box'));
  });
  test('all report headers center within the final canvas without changing terminal data', async () => {
    for (const [kind,title,width] of [['ip','IP质量体检报告',72],['hardware','硬件质量体检报告',80],['net','网络质量体检报告',80],['backroute','网络质量体检报告',80]]) {
      const divider = '#'.repeat(width);
      const raw = [divider, '    \x1b[1;33m'+title+'：192.0.2.123\x1b[0m',
        '     https://github.com/xykt/Test', '    bash test', '  报告时间：2026-01-01', divider,
        '\x1b[47;30m机房\x1b[0m '+(kind==='backroute'?'A'.repeat(120):'body'),
        '         正文缩进不能变', divider].join('\n\r');
      const metrics = await renderAnsi({input:input('header-'+kind,raw),output:path.join(dir,'header-'+kind+'.png'),kind});
      assert.equal(metrics.headerRows?.length,6,kind+' header must be measured and centered');
      assert.equal(metrics.headerGeometryOnly,true);
      assert.equal(metrics.contentsPreserved,true);
      assert.ok(metrics.text.includes('         正文缩进不能变'));
      for (const row of metrics.headerRows) {
        assert.ok(Math.abs(row.centerX-metrics.width/4)<0.5,`${kind} row ${row.row} not centered`);
        assert.ok(row.left>=20 && row.right<=metrics.width/2-20,kind+' header clipped');
      }
      assert.ok(metrics.spans.filter(s=>s.text.includes('机房')).every(s=>s.padding==='3px'));
    }
  });
  test('unknown terminal content is not mistaken for a report header', async () => {
    const metrics=await renderAnsi({input:input('no-header','####################\n    ordinary title\n####################\nbody'),output:path.join(dir,'no-header.png'),kind:'ip'});
    assert.deepEqual(metrics.headerRows,[]);
  });
  test('incomplete or mismatched header dividers never move body rows', async () => {
    const divider='#'.repeat(72);
    const header=[divider,'    IP质量体检报告：192.0.2.1','    https://github.com/xykt/IPQuality','    bash test','    报告时间：2026-01-01'];
    for (const [name,tail] of [
      ['missing',['body','more body',divider]],
      ['different-type',['*'.repeat(72),'body']],
      ['different-width',['#'.repeat(70),'body']],
      ['early',[divider,'body']],
    ]) {
      const lines=name==='early'?[...header.slice(0,4),...tail]:[...header,...tail];
      const metrics=await renderAnsi({input:input('bad-header-'+name,lines.join('\n')),output:path.join(dir,'bad-header-'+name+'.png'),kind:'ip'});
      assert.deepEqual(metrics.headerRows,[],name+' must preserve original layout');
    }
  });
  test('English IP header and negative shifts preserve colored header cells', async () => {
    const divider='#'.repeat(100);
    const raw=[divider,' '.repeat(65)+'\x1b[1;43m  IP QUALITY CHECK REPORT: 192.0.2.1  \x1b[0m',
      '   https://github.com/xykt/IPQuality','   bash test','   Report time: 2026-01-01',divider,'body'].join('\n');
    const metrics=await renderAnsi({input:input('english-header',raw),output:path.join(dir,'english-header.png'),kind:'ip'});
    assert.equal(metrics.headerRows.length,6);
    assert.ok(metrics.headerRows[1].shift<0,'title should move left');
    for (const row of metrics.headerRows) assert.ok(Math.abs(row.centerX-metrics.width/4)<0.1);
    const title=metrics.spans.find(s=>s.text.includes('IP QUALITY CHECK REPORT'));
    assert.equal(title.colored,true);
    assert.equal(title.padding,'3px');
    assert.equal(metrics.headerGeometryOnly,true);
  });
  test('IP excludes vertical risk markers but permits colored box glyph labels', async () => {
    const metrics=await renderAnsi({input:input('ip','\x1b[47;30m机房\x1b[0m \x1b[41m|||\x1b[0m\n\x1b[42m─图\x1b[0m'),output:path.join(dir,'ip.png'),kind:'ip'});
    assert.equal(metrics.spans.find(s=>s.text.includes('|||')).padding,'1px');
    assert.equal(metrics.spans.find(s=>s.text.includes('─')).padding,'3px');
  });
  test('overflow and nonprinting reports fail without partial output', async () => {
    for (const [name,raw] of [['wide','W'.repeat(401)],['safety','W'.repeat(397)],['tall',Array(501).fill('row').join('\n')],['blank','\x1b[31m\x1b[0m']]) {
      const output=path.join(dir,name+'.png');
      await assert.rejects(renderAnsi({input:input(name,raw),output,kind:'net'}),/limit|empty|wrap/i);
      assert.equal(fs.existsSync(output),false);
    }
  });
  test('missing private font fails explicitly with no fallback', async () => {
    const old=process.env.CHECKPLACE_TERMINAL_FONT;process.env.CHECKPLACE_TERMINAL_FONT=path.join(dir,'missing.ttf');
    try {await assert.rejects(renderAnsi({input:input('font','data'),output:path.join(dir,'font.png'),kind:'ip'}),/font/i);}
    finally {if(old===undefined)delete process.env.CHECKPLACE_TERMINAL_FONT;else process.env.CHECKPLACE_TERMINAL_FONT=old;}
  });
}
