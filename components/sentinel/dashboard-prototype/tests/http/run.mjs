import {build} from 'esbuild';
import {after} from 'node:test';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

// Bundle actual TypeScript, but let MSW execute its installed Node runtime rather than rewriting its interceptors.
const directory=mkdtempSync(join(tmpdir(),'sentinel-http-tests-'));
after(()=>rmSync(directory,{recursive:true,force:true}));
const output=join(directory,'http.test.mjs');
await build({entryPoints:[fileURLToPath(new URL('./transport.test.mjs',import.meta.url))],outfile:output,bundle:true,platform:'node',format:'esm',logLevel:'error',plugins:[{
 name:'installed-msw-runtime',setup(builder){builder.onResolve({filter:/^msw(?:\/.*)?$/},args=>({path:import.meta.resolve(args.path),external:true}));},
}]});
await import(pathToFileURL(output).href);
