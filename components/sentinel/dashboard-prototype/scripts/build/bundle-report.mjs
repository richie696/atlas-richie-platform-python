import {readFileSync,writeFileSync,statSync} from 'node:fs';
import {resolve,relative,join,isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {gzipSync} from 'node:zlib';

/** Collect actual entry + transitive static dependencies; lazy chunks never hide initial bytes. */
export function createBundleReport(manifest,readAsset) {
  if(!manifest||typeof manifest!=='object'||Array.isArray(manifest))throw new Error('Invalid build manifest');
  const keys=Object.keys(manifest);
  if(!keys.length||keys.length>10_000)throw new Error('Unbounded or empty build manifest');
  const records=new Map(keys.map(key=>{
    const item=manifest[key];
    if(!item||typeof item!=='object'||Array.isArray(item)||typeof item.file!=='string')throw new Error('Invalid manifest record');
    for(const field of ['imports','dynamicImports','css','assets'])if(item[field]!==undefined&&(!Array.isArray(item[field])||item[field].some(value=>typeof value!=='string')))throw new Error('Invalid manifest dependency');
    return [key,item];
  }));
  const entries=keys.filter(key=>records.get(key).isEntry===true);
  if(!entries.length)throw new Error('Build has no application entry');
  // Check even deferred references: a missing lazy chunk must not look like a small successful build.
  for(const item of records.values())for(const key of [...(item.imports??[]),...(item.dynamicImports??[])])if(!records.has(key))throw new Error('Missing manifest dependency');
  const measured=new Map();
  function measure(file){
    if(!file||file.includes('\\')||file.includes('\0')||file.startsWith('/')||file.split('/').some(segment=>segment==='..'||segment==='.'||!segment))throw new Error('Unsafe asset path');
    if(!measured.has(file)){
      const bytes=readAsset(file);
      if(!Buffer.isBuffer(bytes))throw new Error('Asset reader must return bytes');
      measured.set(file,{file,bytes:bytes.length,gzipBytes:gzipSync(bytes,{level:9}).length});
    }
    return measured.get(file);
  }
  function staticFiles(entry){
    const visited=new Set(),files=new Set();
    function visit(key){
      if(visited.has(key))return;visited.add(key);
      const item=records.get(key);
      for(const file of [item.file,...(item.css??[]),...(item.assets??[])])files.add(file);
      for(const dependency of item.imports??[])visit(dependency);
    }
    visit(entry);return [...files].sort();
  }
  function totals(files){
    const assets=files.map(measure);
    return {files:assets,totalBytes:assets.reduce((sum,item)=>sum+item.bytes,0),gzipBytes:assets.reduce((sum,item)=>sum+item.gzipBytes,0),javascriptBytes:assets.filter(item=>item.file.endsWith('.js')).reduce((sum,item)=>sum+item.bytes,0)};
  }
  const initialFiles=[...new Set(entries.flatMap(staticFiles))].sort();
  // Measure every emitted dependency as well, so a missing deferred asset fails the gate.
  const allFiles=[...new Set([...records.values()].flatMap(item=>[item.file,...(item.css??[]),...(item.assets??[])]))].sort();
  const initialSet=new Set(initialFiles);
  return {
    schemaVersion:1,
    scope:'manifest-linked JS/CSS/assets; excludes HTML, public files, unlisted CSS URL dependencies and runtime requests',
    gzipMethod:'independent-file gzip level 9; not transfer timing',
    initial:totals(initialFiles),
    entries:entries.map(key=>({entry:key,...totals(staticFiles(key))})),
    deferred:keys.filter(key=>records.get(key).isDynamicEntry===true).map(key=>{
      const files=staticFiles(key);
      return {entry:key,...totals(files),additionalAfterInitial:totals(files.filter(file=>!initialSet.has(file)))};
    }),
    all:totals(allFiles),
  };
}

/** Read only files within this build root and write a generated measurement alongside its manifest. */
export function reportBuild(directory) {
  const root=resolve(directory),manifest=JSON.parse(readFileSync(join(root,'.vite/manifest.json'),'utf8'));
  const report=createBundleReport(manifest,file=>{
    const path=resolve(root,file),local=relative(root,path);
    if(!local||local.startsWith('..')||isAbsolute(local)||!statSync(path).isFile())throw new Error('Invalid build asset');
    return readFileSync(path);
  });
  writeFileSync(join(root,'.vite/bundle-report.json'),JSON.stringify(report,null,2));
  console.log(`BUNDLE initial JS ${report.initial.javascriptBytes}B; manifest-linked initial assets ${report.initial.totalBytes}B / gzip ${report.initial.gzipBytes}B; ${report.deferred.length} deferred entries`);
  return report;
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try {if(process.argv.length!==3)throw new Error('Usage: bundle-report.mjs <build-directory>');reportBuild(process.argv[2]);}
  catch(error){console.error(error.message);process.exitCode=1;}
}
