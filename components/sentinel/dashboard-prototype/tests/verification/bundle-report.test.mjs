import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBundleReport} from '../../scripts/build/bundle-report.mjs';

const manifest={
  'index.html':{file:'assets/root.js',isEntry:true,imports:['shared'],dynamicImports:['page'],css:['assets/root.css']},
  shared:{file:'assets/shared.js',imports:['cycle'],css:['assets/shared.css']},
  cycle:{file:'assets/cycle.js',imports:['shared']},
  page:{file:'assets/page.js',isDynamicEntry:true,imports:['shared'],css:['assets/shared.css']},
};
const bytes=file=>Buffer.from(file);
test('BUNDLE: static closure is counted once, cycles terminate and lazy size includes shared dependencies',()=>{
  const report=createBundleReport(manifest,bytes);
  assert.deepEqual(report.initial.files.map(item=>item.file),['assets/cycle.js','assets/root.css','assets/root.js','assets/shared.css','assets/shared.js']);
  assert.equal(report.initial.totalBytes,report.initial.files.reduce((sum,item)=>sum+item.file.length,0));
  assert.deepEqual(report.deferred[0].additionalAfterInitial.files.map(item=>item.file),['assets/page.js']);
  assert.ok(report.deferred[0].totalBytes>report.deferred[0].additionalAfterInitial.totalBytes);
  assert.equal(report.all.files.length,6);
});
test('BUNDLE: missing initial/deferred dependency, empty manifest and unsafe paths are failures, not a smaller passing build',()=>{
  for(const invalid of [null,[],{}, {...manifest,page:{file:'assets/page.js',imports:['absent']}}, {...manifest,page:{file:'../outside.js'}}, {...manifest,page:{file:'/outside.js'}}, {...manifest,page:{file:'assets\\outside.js'}}, {...manifest,page:{file:'assets/page.js',css:[12]}}])assert.throws(()=>createBundleReport(invalid,bytes));
  assert.throws(()=>createBundleReport(manifest,file=>{if(file==='assets/page.js')throw new Error('Missing actual file');return bytes(file);}),/Missing actual file/);
  assert.throws(()=>createBundleReport(manifest,()=>''),/bytes/);
});
