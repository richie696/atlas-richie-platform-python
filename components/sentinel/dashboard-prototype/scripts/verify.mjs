import {fileURLToPath} from 'node:url';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
import {mkdirSync,mkdtempSync,existsSync,readdirSync,writeFileSync} from 'node:fs';
import {startOwnedProcess,unusedLoopbackPort,waitForEntry} from './verification/process.mjs';

/** CLI validation is pure; a baseline is input-only, never overwritten or auto-accepted. */
export function parseVerifyOptions(args) {
  const options={staticOnly:false,browserOnly:false,artifacts:null,baseline:null};
  for(let index=0;index<args.length;index++){
    const argument=args[index];
    if(argument==='--static-only')options.staticOnly=true;
    else if(argument==='--browser-only')options.browserOnly=true;
    else if(argument==='--artifacts'||argument==='--visual-baseline'){
      const value=args[++index];if(!value||value.startsWith('--'))throw new Error(`Missing value: ${argument}`);
      options[argument==='--artifacts'?'artifacts':'baseline']=resolve(value);
    }else throw new Error(`Unknown verification option: ${argument}`);
  }
  if(options.staticOnly&&options.browserOnly)throw new Error('Conflicting verification scope');
  if(options.staticOnly&&options.baseline)throw new Error('Static scope cannot compare browser pixels');
  return Object.freeze(options);
}

/** Static → isolated Vite/browser → captured DOM/PNG → optional existing-baseline comparison. */
export async function verify(options) {
  if(options.baseline&&(!existsSync(options.baseline)||!readdirSync(options.baseline).some(name=>name.endsWith('.html'))))throw new Error('Visual baseline snapshots do not exist');
  const cwd=fileURLToPath(new URL('..',import.meta.url));
  const parent=options.artifacts??tmpdir();mkdirSync(parent,{recursive:true});
  const directory=mkdtempSync(join(parent,'sentinel-verify-'));
  const receipt={status:'running',scope:options.staticOnly?'static':options.browserOnly?'browser':'static+browser',startedAt:new Date().toISOString(),phases:[],pixelComparison:options.baseline?'requested':'not-requested'};
  const env={...process.env,SENTINEL_TEST_ARTIFACT_DIR:directory};
  for(const key of ['ONLY','ACCEPT_DOM','ACCEPT_RENDER','DOM_CHANGE_REASON','TOLERANCE_RATIO','TOLERANCE_MAX_DELTA'])delete env[key];
  const children=new Set();
  const cancellation=new AbortController();
  async function phase(name,command,args,phaseEnv=env){
    cancellation.signal.throwIfAborted();
    console.log(`VERIFY ${name} — ${directory}`);
    const started=Date.now(),child=startOwnedProcess(command,args,{cwd,env:phaseEnv,logPath:join(directory,`${name}.log`)});
    children.add(child);
    try{await child.wait();cancellation.signal.throwIfAborted();receipt.phases.push({name,status:'passed',durationMs:Date.now()-started});}
    catch(error){receipt.phases.push({name,status:'failed',durationMs:Date.now()-started});throw error;}
    finally{await child.stop();children.delete(child);}
  }
  const interrupt=()=>{cancellation.abort();for(const child of children)void child.stop();};
  process.once('SIGINT',interrupt);process.once('SIGTERM',interrupt);
  try {
    if(!options.browserOnly)await phase('static',process.platform==='win32'?'npm.cmd':'npm',['run','check']);
    if(!options.staticOnly){
      const port=await unusedLoopbackPort();env.BASE_URL=`http://127.0.0.1:${port}`;
      const server=startOwnedProcess(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd,env,logPath:join(directory,'vite.log'),timeoutMs:1_800_000});
      children.add(server);await waitForEntry(env.BASE_URL,server);
      await phase('browser',process.platform==='win32'?'npm.cmd':'npm',['run','test:e2e']);
      await phase('visual-capture',process.execPath,['tests/visual/capture-baseline.mjs','capture',join(directory,'visual')]);
      if(options.baseline){
        // Comparison never inherits acceptance lists or raised tolerances from a developer shell.
        const comparisonEnv={...env};for(const key of ['ONLY','ACCEPT_DOM','ACCEPT_RENDER','DOM_CHANGE_REASON','TOLERANCE_RATIO','TOLERANCE_MAX_DELTA'])delete comparisonEnv[key];
        await phase('visual-compare',process.execPath,['tests/visual/capture-baseline.mjs','compare',options.baseline,join(directory,'visual')],comparisonEnv);
        receipt.pixelComparison='passed';
      }
    }
    receipt.status='passed';
  }catch(error){receipt.status='failed';throw error;}
  finally{
    await Promise.all([...children].map(child=>child.stop()));
    process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',interrupt);
    receipt.finishedAt=new Date().toISOString();writeFileSync(join(directory,'receipt.json'),JSON.stringify(receipt,null,2));
    console.log(`VERIFY ${receipt.status}; pixel comparison: ${receipt.pixelComparison}; evidence: ${directory}`);
  }
  return receipt;
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{await verify(parseVerifyOptions(process.argv.slice(2)));}catch(error){console.error(error.message);process.exitCode=1;}
}
