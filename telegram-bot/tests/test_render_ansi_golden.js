'use strict';
// Optional private acceptance suite. No real reports, images or font enter git.
// CHECKPLACE_ANSI_AUDIT contains ansi/*.log and approved-manifest.json.
// CHECKPLACE_ANSI_BASELINES optionally remaps approved image basenames.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {renderAnsi} = require('../render_ansi.js');
const audit = process.env.CHECKPLACE_ANSI_AUDIT;
const kinds = {ip:'ip_quality',hardware:'hardware_quality',net:'net_quality',backroute:'backroute_trace'};
const sizes = {ip:[1362,1746],hardware:[1498,1678],net:[1498,1814],backroute:[2206,3956]};
const expectedHashes = {
  ip:'80919eda5af779c148d418003831c6e1e741d65871e3fbcf20d29f9a84169e50',
  hardware:'1c69491956c5f6f5e6121a1a5e6721563cf4be639d6171f6f91c4e4a56b2fcaf',
  net:'a9318a88a947fe3e3698514557cc78b8f7ddc9d2f186448987489e5af87c920a',
  backroute:'8e057729c29a8ab20ee0c36a779cb6751afa4ed2d66bb10a03b457a794057d30',
};
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
for (const [kind,name] of Object.entries(kinds)) {
  test(`approved ${kind} body is pixel-identical and header is centered`, {skip: !audit && 'private audit paths not configured'}, async () => {
    const approved = JSON.parse(fs.readFileSync(path.join(audit,'approved-manifest.json'),'utf8'))[kind];
    const baseline = process.env.CHECKPLACE_ANSI_BASELINES ? path.join(process.env.CHECKPLACE_ANSI_BASELINES,path.basename(approved.path)) : approved.path;
    const baselineBytes = fs.readFileSync(baseline);
    assert.equal(approved.sha256,expectedHashes[kind],'approved manifest unexpectedly changed');
    assert.equal(sha(baselineBytes),expectedHashes[kind],'approved baseline unexpectedly changed');
    const temp = fs.mkdtempSync(path.join(os.tmpdir(),'ansi-golden-'));
    try {
      const output = path.join(temp,`${kind}.png`);
      const metrics = await renderAnsi({input:path.join(audit,'ansi',`${name}.log`),output,kind});
      assert.deepEqual([metrics.width,metrics.height],sizes[kind]);
      assert.equal(metrics.contentsPreserved,true);
      assert.equal(metrics.cellGeometryUnchanged,true);
      assert.equal(metrics.networkRequests,0);
      assert.equal(metrics.headerRows.length,6);
      for (const row of metrics.headerRows) assert.ok(Math.abs(row.centerX-metrics.width/4)<0.1);
      const bodyY = Math.round(40+6*metrics.screenHeight/metrics.rows*2);
      const comparison = spawnSync('python3',['-c',
        'from PIL import Image; import sys; a=Image.open(sys.argv[1]).convert("RGB"); b=Image.open(sys.argv[2]).convert("RGB"); y=int(sys.argv[3]); assert a.size==b.size; box=(0,y,a.width,a.height); assert a.crop(box).tobytes()==b.crop(box).tobytes(), "body pixels changed"; assert a.tobytes()!=b.tobytes(), "header was not corrected"',
        baseline,output,String(bodyY)],{encoding:'utf8'});
      assert.equal(comparison.status,0,comparison.stderr);
    } finally {fs.rmSync(temp,{recursive:true,force:true});}
  });
}
