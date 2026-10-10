import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {artifactDirectory} from './artifacts.mjs';
test('ARTIFACTS: caller-owned portable root and independent suite paths; no traversal or broad target',()=>{
  const root=mkdtempSync(join(tmpdir(),'sentinel-artifacts-test-'));
  try {
    assert.equal(artifactDirectory('navigation',root),join(root,'navigation'));assert.ok(existsSync(join(root,'navigation')));
    assert.equal(artifactDirectory('rules',root),join(root,'rules'));
    for(const name of ['','..','../outside','/','/tmp','a/b','A','a'.repeat(102)])assert.throws(()=>artifactDirectory(name,root));
  }finally{rmSync(root,{recursive:true,force:true});}
});
