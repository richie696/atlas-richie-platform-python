import {build} from 'esbuild';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

// Deterministic generated artifact, not hand-maintained schemas. Delete only this invocation's temporary build.
const root=fileURLToPath(new URL('../..',import.meta.url));
const target=resolve(root,'../docs/protocol/console-api.openapi.json');
const check=process.argv.includes('--check');
if(process.argv.slice(2).some(value=>value!=='--check'))throw new Error('Unknown contract export option');
const temporary=mkdtempSync(join(tmpdir(),'sentinel-contract-export-'));
try{
 const output=join(temporary,'contract.mjs');
 await build({entryPoints:[join(root,'src/app/api/consoleContract.ts')],outfile:output,bundle:true,platform:'node',format:'esm',logLevel:'error'});
 const {createConsoleOpenApi}=await import(pathToFileURL(output).href);
 const document=createConsoleOpenApi(),content=JSON.stringify(document,null,2)+'\n';
 if(check){if(readFileSync(target,'utf8')!==content)throw new Error('Console OpenAPI differs from runtime DTO/endpoint declarations');}
 else{mkdirSync(resolve(target,'..'),{recursive:true});writeFileSync(target,content);}
 console.log(`Console OpenAPI ${check?'verified':'generated'}: ${Object.keys(document.paths).length} paths; ${document['x-contract-status']}; ${target}`);
}finally{rmSync(temporary,{recursive:true,force:true});}
