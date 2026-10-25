import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { readPng } from "./png-diff.mjs";

const command=fileURLToPath(new URL("./capture-baseline.mjs",import.meta.url));
// A generated 1×1 RGBA white PNG with valid zlib data and CRCs, not a screenshot baseline.
const png=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg==","base64");

function compareFixture(run) {
  const root=mkdtempSync(path.join(tmpdir(),"sentinel-compare-test-"));
  const base=path.join(root,"base"),next=path.join(root,"next");
  mkdirSync(base);mkdirSync(next);
  const html='<section class="account">Synthetic comparison fixture</section>';
  for(const directory of [base,next]) {
    writeFileSync(path.join(directory,"case.html"),html);
    writeFileSync(path.join(directory,"case.raw-dom"),html);
    writeFileSync(path.join(directory,"case.png"),png);
  }
  try {
    assert.equal(readPng(path.join(base,"case.png")).width,1);
    const execute=extraEnv=>{
      const env={...process.env,ACCEPT_DOM:"",ACCEPT_RENDER:"",ONLY:"",DOM_CHANGE_REASON:"",...extraEnv};
      delete env.NODE_TEST_CONTEXT;
      return spawnSync(process.execPath,[command,"compare",base,next],{env,encoding:"utf8",timeout:10000});
    };
    run({base,next,execute});
  } finally {rmSync(root,{recursive:true,force:true});}
}

test("visual comparison rejects missing PNG instead of returning a false green DOM-only result",()=>{
  compareFixture(({next,execute})=>{
    rmSync(path.join(next,"case.png"));
    const result=execute();
    assert.equal(result.status,1,result.stderr);
    assert.match(result.stdout,/截图缺失/);
  });
});
test("accepted DOM changes are labelled separately and cannot imply accepted rendering changes",()=>{
  compareFixture(({next,execute})=>{
    writeFileSync(path.join(next,"case.raw-dom"),'<section class="account _owned_a_1">Synthetic comparison fixture</section>');
    const result=execute({ACCEPT_DOM:"case",DOM_CHANGE_REASON:"owned module class only"});
    assert.equal(result.status,0,result.stderr);
    assert.match(result.stdout,/已声明接受的 DOM 变化.*owned module class only/);
    assert.match(result.stdout,/渲染一致 1 个/);
    assert.doesNotMatch(result.stdout,/已声明接受的渲染变化/);
  });
});
test("unaccepted structure changes and missing DOM reasons still fail",()=>{
  compareFixture(({next,execute})=>{
    writeFileSync(path.join(next,"case.raw-dom"),'<section>Changed visible copy</section>');
    assert.equal(execute().status,1);
    const result=execute({ACCEPT_DOM:"case"});
    assert.equal(result.status,1);
    assert.match(result.stderr,/需要同时提供 DOM_CHANGE_REASON/);
  });
});
