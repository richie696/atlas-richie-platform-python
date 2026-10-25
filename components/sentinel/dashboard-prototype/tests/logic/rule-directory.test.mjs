import {test} from 'node:test';
import assert from 'node:assert/strict';
import {StateStore,AppError,AppErrorKind} from '@richie696/react-framework';
import {validBindingQuery,validBindingPage,bindingQueryKey} from '../../src/features/rules/model/ruleDirectory';
import {createRuleBindingDirectory,createRuleBindingSnapshot,createStoredDraftDirectory} from '../../src/features/rules/application/ruleDirectoryResources';
import {createRuleOperation} from '../../src/features/rules/application/ruleOperation';
import {ruleSet} from '../fixtures/ruleSets';
const query={environmentId:ruleSet.binding.environmentId,appId:null,kind:null,search:'',page:1,pageSize:20};
const page={query,total:1,items:[ruleSet.binding]};
const draft={id:'draft-one',revision:'r1',bindingId:ruleSet.binding.id,kind:ruleSet.binding.kind,profile:ruleSet.binding.profile,baseVersionId:ruleSet.versionId,baseChecksum:ruleSet.checksum,sourceRevision:ruleSet.sourceRevision,updatedAtMs:ruleSet.asOfMs,records:ruleSet.records};
const owner=()=>{const state=new StateStore({ownerKey:'directory-session',allowed:true});return {state,access:{read:state.getSnapshot,subscribe:state.subscribe}};};
test('BINDING-QUERY: bounded integer pagination and every filter identity enter the ownership key',()=>{
 assert.equal(validBindingQuery(query),true);
 for(const patch of [{environmentId:''},{appId:''},{kind:'unknown'},{page:0},{page:1.5},{pageSize:101},{pageSize:NaN},{search:'x'.repeat(201)}])assert.equal(validBindingQuery({...query,...patch}),false);
 for(const patch of [{environmentId:'other'},{appId:'app'}, {kind:'system'},{search:'find'},{page:2},{pageSize:1}])assert.notEqual(bindingQueryKey({...query,...patch}),bindingQueryKey(query));
});
test('BINDING-PAGE: matching scope/profile/type, page capacity, total and duplicate identities are checked',()=>{
 assert.equal(validBindingPage(page,query),true);
 for(const value of [{...page,query:{...query,page:2}},{...page,total:0},{...page,total:NaN},{...page,total:2,items:[ruleSet.binding,ruleSet.binding]},{...page,items:[{...ruleSet.binding,environmentId:'foreign'}]},{...page,items:[{...ruleSet.binding,profile:''}]}])assert.equal(validBindingPage(value,query),false);
 assert.equal(validBindingPage({...page,query:{...query,kind:'system'}},{...query,kind:'system'}),false);
});
test('BINDING-READ: filtered/paged empty stays distinct; same-key missing and new-session reads never reuse old rows',async()=>{
 const x=owner();let missing=false,reads=0;const resource=createRuleBindingDirectory({async readBindings(q){reads++;if(missing)throw new AppError(AppErrorKind.PROTOCOL,'PRIVATE',{status:404});return {query:q,total:q.page===2?1:1,items:q.page===2?[]:[ruleSet.binding]};}},x.access);
 await resource.load(query);await resource.load({...query,page:2});assert.equal(resource.getSnapshot().status,'filtered-empty');await resource.load(query);missing=true;await assert.rejects(resource.load(query));assert.equal(resource.getSnapshot().status,'error');assert.ok(!('data' in resource.getSnapshot()));x.state.set({ownerKey:'directory-session',allowed:false});await assert.rejects(resource.load(query));assert.equal(reads,4);resource.dispose();x.state.complete();
});
test('BINDING-LATE: changing query aborts old request and a late foreign page cannot populate current rows',async()=>{
 const x=owner();let release,signal;const resource=createRuleBindingDirectory({readBindings(q,s){if(q.search==='held'){signal=s;return new Promise(done=>{release=done;});}return Promise.resolve({...page,query:q});}},x.access);
 const old=resource.load({...query,search:'held'});await Promise.resolve();await resource.load(query);assert.equal(signal.aborted,true);release({...page,query:{...query,search:'held'}});await assert.rejects(old);assert.equal(resource.getSnapshot().data.query.search,'');resource.dispose();x.state.complete();
});
test('BINDING-SNAPSHOT-LATE: an ignored abort cannot replace the currently selected deep link',async()=>{
 const x=owner();let release,oldSignal;const selected={...ruleSet,binding:{...ruleSet.binding,id:'binding-two'}};
 const resource=createRuleBindingSnapshot({readSnapshot(id,signal){if(id==='binding-one'){oldSignal=signal;return new Promise(done=>{release=done;});}return Promise.resolve(selected);}},x.access);
 const old=resource.load('binding-one');await Promise.resolve();const current=resource.load('binding-two');assert.equal(oldSignal.aborted,true);await current;release(ruleSet);await assert.rejects(old);assert.equal(resource.getSnapshot().data.binding.id,'binding-two');resource.dispose();x.state.complete();
});
test('BINDING-SNAPSHOT: response identity must match the selected deep-link binding',async()=>{
 const x=owner();const resource=createRuleBindingSnapshot({async readSnapshot(){return {...ruleSet,binding:{...ruleSet.binding,id:'foreign-binding'}};}},x.access);
 await assert.rejects(resource.load('binding-one'));assert.equal(resource.getSnapshot().status,'error');assert.ok(!('data' in resource.getSnapshot()));resource.dispose();x.state.complete();
});
test('DRAFT-DIRECTORY: confirmed save/delete refresh exactly once; unknown never reloads until original receipt is confirmed',async()=>{
 const x=owner();let key=0,latest,unknown=false,reads=0,items=[];
 const complete=m=>({status:'completed',bindingId:m.bindingId,requestKey:m.requestKey,result:m.kind==='save_draft'?{kind:'save_draft',draft}:{kind:'delete_draft',draftId:draft.id}});
 const operation=createRuleOperation(ruleSet.binding.id,{async mutateRuleSet(m){latest=m;items=m.kind==='save_draft'?[draft]:[];if(unknown)throw new AppError(AppErrorKind.NETWORK,'PRIVATE');return complete(m);},async readRuleOperation(){return complete(latest);}},x.access,()=> 'dir-request-'+ ++key);
 const resource=createStoredDraftDirectory(ruleSet.binding,{async readDrafts(){reads++;return {bindingId:ruleSet.binding.id,asOfMs:ruleSet.asOfMs,items};}},x.access,operation);
 const save={kind:'save_draft',draftId:null,expectedRevision:null,candidate:{bindingId:ruleSet.binding.id,kind:ruleSet.binding.kind,profile:ruleSet.binding.profile,baseVersionId:ruleSet.versionId,baseChecksum:ruleSet.checksum,sourceRevision:ruleSet.sourceRevision,rules:ruleSet.records.map(r=>({recordId:r.id,rule:r.rule}))}};
 await resource.load(ruleSet.binding.id);await operation.run(save);await new Promise(resolve=>setTimeout(resolve,0));assert.equal(reads,2);assert.equal(resource.getSnapshot().data.items[0].id,draft.id);
 unknown=true;await assert.rejects(operation.run({kind:'delete_draft',draftId:draft.id,expectedRevision:'r1'}));assert.equal(reads,2);await operation.inspect();await new Promise(resolve=>setTimeout(resolve,0));assert.equal(reads,3);assert.equal(resource.getSnapshot().status,'empty');
 x.state.set({ownerKey:'other-session',allowed:true});await assert.rejects(resource.load(ruleSet.binding.id));assert.equal(reads,3);resource.dispose();operation.dispose();x.state.complete();
});
test('DRAFT-DIRECTORY: foreign binding/profile and duplicate records cannot masquerade as the selected saved draft',async()=>{
 const x=owner();const operation={getSnapshot:()=>({command:{status:'idle'}}),subscribe:()=>()=>{}};
 for(const items of [[{...draft,profile:'foreign'}],[{...draft,bindingId:'foreign'}],[draft,draft]]){const resource=createStoredDraftDirectory(ruleSet.binding,{async readDrafts(){return {bindingId:ruleSet.binding.id,asOfMs:ruleSet.asOfMs,items};}},x.access,operation);await assert.rejects(resource.load(ruleSet.binding.id));assert.ok(!('data' in resource.getSnapshot()));resource.dispose();}x.state.complete();
});
