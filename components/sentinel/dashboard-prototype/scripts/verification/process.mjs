import {spawn} from 'node:child_process';
import {createWriteStream} from 'node:fs';
import {createServer} from 'node:net';
import {setTimeout as delay} from 'node:timers/promises';

/** A private subprocess/process-group owner, never an arbitrary PID killer. */
export function startOwnedProcess(command,args,{cwd,env,logPath,timeoutMs=900_000}) {
  if (!Number.isFinite(timeoutMs)||timeoutMs<=0)throw new Error('Invalid process timeout');
  const log=createWriteStream(logPath);
  const child=spawn(command,args,{cwd,env,detached:process.platform!=='win32',stdio:['ignore','pipe','pipe']});
  child.stdout.pipe(log,{end:false});child.stderr.pipe(log,{end:false});
  let ended=false,failure=null,timedOut=false;
  const signal=kind=>{
    if(!child.pid||ended)return;
    try {if(process.platform==='win32')child.kill(kind);else process.kill(-child.pid,kind);}catch(error){if(error.code!=='ESRCH')throw error;}
  };
  let forcedKill;
  const timer=setTimeout(()=>{timedOut=true;signal('SIGTERM');forcedKill=setTimeout(()=>signal('SIGKILL'),2000);},timeoutMs);
  const done=new Promise(resolve=>{
    child.once('error',error=>{failure=error;});
    child.once('close',(code,exitSignal)=>{ended=true;clearTimeout(timer);clearTimeout(forcedKill);log.end(()=>resolve({code,signal:exitSignal,timedOut,error:failure}));});
  });
  const finish=async()=>{
    const result=await done;
    if(result.error||result.timedOut||result.code!==0)
      throw new Error(`Verification subprocess failed (${result.timedOut?'timeout':result.error?.code??result.code??result.signal}); log: ${logPath}`);
  };
  return Object.freeze({
    wait:finish,
    failure:()=>failure??(ended?new Error(`Verification service exited; log: ${logPath}`):null),
    async stop(){
      signal('SIGTERM');
      let stopTimer;
      const closed=await Promise.race([done.then(()=>true),new Promise(resolve=>{stopTimer=setTimeout(()=>resolve(false),2000);})]);
      clearTimeout(stopTimer);
      if(!closed){signal('SIGKILL');await done;}
    },
  });
}

/** Pick an unused loopback port; Vite strictPort must fail rather than reuse another service if the race is lost. */
export async function unusedLoopbackPort() {
  const server=createServer();
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const port=server.address().port;
  await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
  return port;
}

/** Bounded readiness is a healthy React entry document, not mere TCP connectivity. */
export async function waitForEntry(url,owner,{timeoutMs=30_000}={}) {
  const deadline=Date.now()+timeoutMs;
  while(Date.now()<deadline){
    const failure=owner.failure();if(failure)throw failure;
    try {
      const response=await fetch(url,{signal:AbortSignal.timeout(1000)});
      if(response.ok&&(await response.text()).includes('id="root"'))return;
    }catch{}
    await delay(100);
  }
  throw new Error('Verification React entry did not become healthy within its deadline');
}
