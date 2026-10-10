import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNavigationProtectionRegistry } from '../../src/shared/state/navigationProtection';
import { createHashNavigationController } from '../../src/app/router/hashNavigationController';
function topology(overrides={}) {
  let location={hash:'#/rules',index:0},listener=null,commits=0,moves=0,replacements=0;
  const registry=createNavigationProtectionRegistry();
  const port={read:()=>location,commit:(hash,options)=>{commits++;location={hash,index:options.history==='replace'?location.index:location.index+1};return location;},replaceUnmanaged:hash=>{replacements++;location={hash,index:null};return location;},moveTo:async target=>{moves++;location=target;listener?.();return location;},subscribe:notify=>{listener=notify;return()=>{listener=null;};},...overrides};
  const controller=createHashNavigationController(port,registry);controller.start();
  return {registry,controller,port,native:target=>{location=target;listener?.();},location:()=>location,counts:()=>({commits,moves,replacements}),listeners:()=>listener!==null};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('NAVIGATION-REGISTER: independent owners aggregate locks before dirty; cleanup is idempotent and never stores form values',()=>{
  const registry=createNavigationProtectionRegistry();let discarded=0;
  const dirty=registry.register({dirty:true,locked:false,discard:()=>discarded++}),locked=registry.register({dirty:false,locked:true});
  assert.deepEqual(registry.getSnapshot(),{dirty:true,locked:true});assert.equal(registry.discard(),'blocked');assert.equal(discarded,0);locked();locked();assert.equal(registry.discard(),'done');assert.equal(discarded,1);dirty();dirty();assert.deepEqual(registry.getSnapshot(),{dirty:false,locked:false});
});
test('NAVIGATION-REQUEST: dirty push/replace never changes accepted URL before confirmation; cancel keeps inputs, duplicate confirmation does not navigate twice',async()=>{
  const t=topology();let discarded=0;const clear=t.registry.register({dirty:true,locked:false,discard:()=>discarded++});
  t.controller.request('#/roles',{history:'replace'});assert.equal(t.location().hash,'#/rules');assert.equal(t.controller.getSnapshot().prompt.kind,'dirty');t.controller.cancel();assert.equal(discarded,0);
  t.controller.request('#/accounts');await t.controller.confirm();await t.controller.confirm();assert.equal(t.location().hash,'#/accounts');assert.equal(discarded,1);assert.equal(t.counts().commits,1);clear();t.controller.request('#/system',{history:'replace'});assert.equal(t.location().index,1);t.controller.stop();
});
test('NAVIGATION-HISTORY: browser tentative back never reaches route readers; cancel restores original position, acceptance traverses without an extra push',async()=>{
  const t=topology();t.controller.request('#/accounts');let discarded=0;const clear=t.registry.register({dirty:true,locked:false,discard:()=>discarded++});const observed=[];t.controller.subscribe(()=>observed.push(t.controller.getSnapshot().location.hash));
  t.native({hash:'#/rules',index:0});assert.equal(t.controller.getSnapshot().location.hash,'#/accounts');await tick();assert.equal(t.location().hash,'#/accounts');assert.equal(t.controller.getSnapshot().prompt.historical,true);assert.ok(observed.every(hash=>hash==='#/accounts'));t.controller.cancel();assert.equal(discarded,0);
  t.native({hash:'#/rules',index:0});await tick();await t.controller.confirm();assert.equal(t.controller.getSnapshot().location.hash,'#/rules');assert.equal(t.location().index,0);assert.equal(t.counts().commits,1);assert.equal(discarded,1);clear();t.controller.stop();
});
test('NAVIGATION-LOCK: a new unresolved write upgrades an open dirty prompt; no abandon/replay is possible before original outcome is known',async()=>{
  const t=topology();let discarded=0;const dirty=t.registry.register({dirty:true,locked:false,discard:()=>discarded++});t.controller.request('#/overview');const unlock=t.registry.register({dirty:false,locked:true});assert.equal(t.controller.getSnapshot().prompt.kind,'locked');await t.controller.confirm();assert.equal(t.counts().commits,0);assert.equal(discarded,0);unlock();assert.equal(t.controller.getSnapshot().prompt.kind,'dirty');await t.controller.confirm();assert.equal(t.counts().commits,1);dirty();t.controller.stop();
});
test('NAVIGATION-FOREIGN: unknown history positions use explicit restoration, not a guessed delta; raw non-hash destinations cannot leave the SPA',async()=>{
  const t=topology();const clear=t.registry.register({dirty:true,locked:false});t.native({hash:'#/missing',index:null});await tick();assert.equal(t.location().hash,'#/rules');assert.equal(t.counts().moves,0);assert.equal(t.controller.getSnapshot().prompt.historical,false);await t.controller.confirm();assert.equal(t.location().hash,'#/missing');assert.throws(()=>t.controller.request('https://foreign.test'));clear();t.controller.stop();
});
test('NAVIGATION-FAILURE: failed history recovery or abandonment does not report a successful navigation or clear an unresolved transaction',async()=>{
  const t=topology({moveTo:async()=>{throw Error('PRIVATE-HISTORY');}});t.controller.request('#/accounts');const clear=t.registry.register({dirty:true,locked:false});t.native({hash:'#/rules',index:0});await tick();assert.equal(t.controller.getSnapshot().prompt.kind,'history-failed');await t.controller.confirm();assert.equal(t.controller.getSnapshot().location.hash,'#/accounts');clear();t.controller.cancel();const failed=t.registry.register({dirty:true,locked:false,discard:()=>{throw Error('PRIVATE-DISCARD');}});t.controller.request('#/overview');await t.controller.confirm();assert.equal(t.controller.getSnapshot().prompt.kind,'discard-failed');assert.equal(t.counts().commits,1);failed();t.controller.stop();
});
test('NAVIGATION-CLEANUP: StrictMode-style repeated start/stop detaches effects and pending history observation can be aborted',()=>{
  let signal;const t=topology({moveTo:(_target,s)=>{signal=s;return new Promise((_resolve,reject)=>s.addEventListener('abort',()=>reject(Error('cancelled')),{once:true}));}});const clear=t.registry.register({dirty:true,locked:false});t.native({hash:'#/accounts',index:1});assert.equal(t.controller.getSnapshot().restoring,true);t.controller.stop();assert.equal(signal.aborted,true);assert.equal(t.listeners(),false);assert.equal(t.controller.getSnapshot().restoring,false);clear();t.controller.start();t.controller.start();assert.equal(t.listeners(),true);t.controller.stop();t.controller.stop();
});
