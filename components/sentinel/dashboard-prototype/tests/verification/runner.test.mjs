import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:http';
import {startOwnedProcess,unusedLoopbackPort,waitForEntry} from '../../scripts/verification/process.mjs';
import {parseVerifyOptions} from '../../scripts/verify.mjs';

test('VERIFY-ARGS: explicit scope, missing values and unknown flags cannot silently reduce acceptance',()=>{
  assert.equal(parseVerifyOptions([]).staticOnly,false);
  assert.equal(parseVerifyOptions(['--browser-only']).browserOnly,true);
  for(const args of [['--static-only','--browser-only'],['--visual-baseline'],['--artifacts'],['--skip-failures'],['--static-only','--visual-baseline','/tmp']])assert.throws(()=>parseVerifyOptions(args));
});
test('VERIFY-PROCESS: actual successful output is saved; nonzero, spawn error and timeout fail rather than pass',async()=>{
  const root=mkdtempSync(join(tmpdir(),'sentinel-runner-test-'));
  try {
    const options={cwd:process.cwd(),env:process.env,logPath:join(root,'process.log'),timeoutMs:2000};
    const good=startOwnedProcess(process.execPath,['-e','console.log("CHECK-PASSED")'],options);await good.wait();await good.stop();assert.match(readFileSync(options.logPath,'utf8'),/CHECK-PASSED/);
    for(const [command,args,timeoutMs] of [[process.execPath,['-e','process.exit(3)'],2000],['/sentinel-does-not-exist',[],2000],[process.execPath,['-e','setInterval(()=>{},1000)'],100],[process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],300]]){
      const bad=startOwnedProcess(command,args,{...options,timeoutMs});try{await assert.rejects(bad.wait(),/failed/);}finally{await bad.stop();}
    }
  }finally{rmSync(root,{recursive:true,force:true});}
});
test('VERIFY-READY: healthy React entry is required; refused ports or early service death are bounded failures',async()=>{
  const port=await unusedLoopbackPort();assert.ok(port>0);
  await assert.rejects(waitForEntry(`http://127.0.0.1:${port}`,{failure:()=>new Error('service failed')},{timeoutMs:200}),/service failed/);
  await assert.rejects(waitForEntry(`http://127.0.0.1:${port}`,{failure:()=>null},{timeoutMs:200}),/deadline/);
  let requests=0;
  const server=createServer((_request,response)=>{requests++;response.end('<div id="root"></div>');});
  try {
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    await waitForEntry(`http://127.0.0.1:${server.address().port}`,{failure:()=>null},{timeoutMs:1000});assert.equal(requests,1);
  }finally{await new Promise(resolve=>server.close(resolve));}
});
