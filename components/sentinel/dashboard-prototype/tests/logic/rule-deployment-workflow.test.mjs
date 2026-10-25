import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AppError,AppErrorKind,StateStore} from '@richie696/react-framework';
import {createRuleOperation} from '../../src/features/rules/application/ruleOperation';
import {createRuleDeploymentWorkflow} from '../../src/features/rules/application/ruleDeploymentWorkflow';
import {createRuleDraftWorkflow} from '../../src/features/rules/application/ruleDraftWorkflow';
import {validRuleSetVersion,validRuleActivationPlan,validRuleCollection} from '../../src/features/rules/model/ruleDeploymentState';
import {ruleSet} from '../fixtures/ruleSets';
const success={state:'succeeded',observedAtMs:100,reason:null};
const waiting={state:'awaiting',observedAtMs:null,reason:null};
const daily={id:'version-one',bindingId:'binding-one',kind:'flow',profile:'test-profile',baseVersionId:null,checksum:ruleSet.checksum,name:'Daily',note:'',createdAtMs:100,createdById:'actor',records:ruleSet.records};
const event={...daily,id:'event-version',baseVersionId:'version-one',checksum:'event-checksum',name:'Event',records:[ruleSet.records[0]]};
const schedule={bindingId:'binding-one',versionId:event.id,restoreVersionId:daily.id,activateAtMs:1000,deactivateAtMs:2000,timeZone:'UTC'};
const activePlan={...schedule,id:'plan-one',revision:'plan-r1',state:'pending',activationPublicationId:null,restorePublicationId:null};
const publication={id:'publication-one',bindingId:'binding-one',targetVersionId:event.id,targetChecksum:event.checksum,baseVersionId:'version-one',createdAtMs:100,validation:success,configurationWrite:success,readBack:success};
const receiptPage={publicationId:'publication-one',bindingId:'binding-one',page:1,pageSize:20,asOfMs:200,total:3,expected:3,inventorySource:'test-inventory',applied:1,pending:1,failed:0,unknown:0,restartRequired:1,items:[
  {instanceId:'i1',processEpoch:'current-epoch',loadedProcessEpoch:'current-epoch',targetVersionId:event.id,loadedVersionId:event.id,loadedChecksum:event.checksum,appliedAtMs:150,lastReportAtMs:160,state:'applied'},
  {instanceId:'i2',processEpoch:'other-epoch',loadedProcessEpoch:null,targetVersionId:event.id,loadedVersionId:null,loadedChecksum:null,appliedAtMs:null,lastReportAtMs:null,state:'pending'},
  {instanceId:'i3',processEpoch:'restart-epoch',loadedProcessEpoch:'restart-epoch',targetVersionId:event.id,loadedVersionId:event.id,loadedChecksum:event.checksum,appliedAtMs:155,lastReportAtMs:165,state:'restart_required'},
]};
function publish(x,text,expected=x.workflow.preparePublication()){return x.workflow.publishVersion(text,expected);}
function topology(overrides={}) {
  const read=new StateStore({ownerKey:'deployment-session',allowed:true}),write=new StateStore({ownerKey:'deployment-session',allowed:true});
  const readAccess={read:read.getSnapshot,subscribe:read.subscribe},writeAccess={read:write.getSnapshot,subscribe:write.subscribe};
  const source=new StateStore({status:'ready',key:'source',receivedAt:100,data:ruleSet});
  let key=0,latest,result,plans=[];
  const counts={writes:0,lookups:0,receipts:0};
  const complete=mutation=>{
    if(mutation.kind==='publish') result={kind:'publish',publication:{...publication,targetVersionId:mutation.versionId,targetChecksum:mutation.versionChecksum,baseVersionId:mutation.expectedVersionId,configurationWrite:waiting,readBack:waiting}};
    else if(mutation.kind==='create_plan') {const plan={...mutation.schedule,id:'plan-one',revision:'plan-r1',state:'pending',activationPublicationId:null,restorePublicationId:null};plans=[plan];result={kind:'create_plan',plan};}
    else if(mutation.kind==='cancel_plan') {const plan={...plans[0],revision:'plan-r2',state:'cancelled'};plans=[plan];result={kind:'cancel_plan',plan};}
    return {status:'completed',bindingId:mutation.bindingId,requestKey:mutation.requestKey,result};
  };
  const operation=createRuleOperation('binding-one',{
    async mutateRuleSet(mutation,signal){counts.writes++;latest=mutation;return overrides.write ? overrides.write(mutation,signal,complete) : complete(mutation);},
    async readRuleOperation(){counts.lookups++;return overrides.lookup ? overrides.lookup(latest,complete) : complete(latest);}
  },writeAccess,()=>`deployment-request-${++key}`);
  const collection=items=>({bindingId:'binding-one',asOfMs:100,items});
  const workflow=createRuleDeploymentWorkflow(ruleSet.binding,{
    async readVersions(){return overrides.versions ? overrides.versions() : collection([daily,event]);},
    async readVersion(binding,id,signal){return overrides.version ? overrides.version(id,signal) : [daily,event].find(v=>v.id===id);},
    async readPublications(){return collection([publication]);},
    async readPublication(binding,id){return overrides.publication ? overrides.publication(id) : publication;},
    async readReceipts(query){counts.receipts++;return overrides.receipts ? overrides.receipts(query) : receiptPage;},
    async readPlans(){return overrides.plans ? overrides.plans() : collection(plans);},
    async readPublicationTarget(bindingId){return overrides.publicationTarget ? overrides.publicationTarget(bindingId) : {bindingId,target:null};},
  },readAccess,writeAccess,operation,source,()=>500);
  return {workflow,operation,read,write,source,counts,last:()=>latest,setPlans:values=>{plans=values;},dispose(){workflow.dispose();operation.dispose();read.complete();write.complete();source.complete();}};
}
test('DEPLOY-PUBLISH: explicit immutable target and fresh source base; rollback shares publication, neither command nor read-back changes live rules',async()=>{
  const x=topology();assert.throws(()=>publish(x,'Change window'));await x.workflow.selectVersion(event.id);await publish(x,' Change window ');assert.equal(x.last().reason,'Change window');assert.equal(x.last().expectedChecksum,ruleSet.checksum);assert.equal(x.last().expectedSourceRevision,ruleSet.sourceRevision);assert.equal(x.source.getSnapshot().data.versionId,daily.id);assert.equal(x.workflow.getSnapshot().publicationId,publication.id);assert.equal(x.workflow.getSnapshot().publication.status,'idle');
  await x.workflow.refreshPublication();assert.equal(x.workflow.getSnapshot().publication.data.readBack.state,'succeeded');assert.equal(x.source.getSnapshot().data.versionId,daily.id);
  x.source.set({...x.source.getSnapshot(),data:{...ruleSet,versionId:event.id,checksum:event.checksum,sourceRevision:'new-source'}});await x.workflow.selectVersion(daily.id);await publish(x,'Rollback contents');assert.equal(x.last().kind,'publish');assert.equal(x.last().versionId,daily.id);assert.equal(x.last().expectedVersionId,event.id);assert.equal(x.last().expectedChecksum,event.checksum);assert.equal(x.source.getSnapshot().data.versionId,event.id);x.dispose();
});
test('DEPLOY-FRESHNESS: stale/refreshing source or target cannot authorize writes; authoritative missing version clears old content',async()=>{
  let missing=false;const x=topology({version:id=>{if(missing)throw new AppError(AppErrorKind.SERVER,'PRIVATE-VERSION',{status:404});return id===event.id?event:daily;}});await x.workflow.selectVersion(event.id);
  for(const status of ['stale','refreshing','partial']){x.source.set({...x.source.getSnapshot(),status});assert.throws(()=>publish(x,'reason'));}
  x.source.set({...x.source.getSnapshot(),status:'ready'});missing=true;await assert.rejects(x.workflow.refreshVersion());assert.equal(x.workflow.getSnapshot().version.status,'error');assert.ok(!('data' in x.workflow.getSnapshot().version));assert.throws(()=>publish(x,'reason'));assert.equal(x.counts.writes,0);x.dispose();
});
test('DEPLOY-READ: wrong binding/profile/version and late superseded selection cannot populate the selected version',async()=>{
  let resolve,signal;const x=topology({version:(id,s)=>id==='held' ? new Promise(done=>{resolve=done;signal=s;}) : event});const old=x.workflow.selectVersion('held');await Promise.resolve();await x.workflow.selectVersion(event.id);assert.equal(signal.aborted,true);resolve({...event,id:'held'});await assert.rejects(old);assert.equal(x.workflow.getSnapshot().versionId,event.id);assert.equal(x.workflow.getSnapshot().version.data.id,event.id);x.dispose();
  const wrong=topology({version:()=>({...event,profile:'foreign-profile'})});await assert.rejects(wrong.workflow.selectVersion(event.id));assert.ok(!('data' in wrong.workflow.getSnapshot().version));assert.equal(wrong.counts.writes,0);wrong.dispose();
});
test('DEPLOY-RECEIPTS: all-instance counts and restart-required remain partial; old-incarnation positive receipt is rejected',async()=>{
  let bad=false;const x=topology({receipts:()=>bad?{...receiptPage,items:[{...receiptPage.items[0],loadedProcessEpoch:'previous-epoch'}]}:receiptPage});await x.workflow.selectPublication(publication.id);await x.workflow.loadReceipts();const value=x.workflow.getSnapshot().receipts;assert.equal(value.status,'partial');assert.equal(value.data.expected,3);assert.equal(value.data.applied,1);assert.equal(value.data.restartRequired,1);bad=true;await assert.rejects(x.workflow.loadReceipts());assert.equal(x.workflow.getSnapshot().receipts.status,'stale');assert.equal(x.workflow.getSnapshot().receipts.data.applied,1);await x.workflow.selectPublication(null);assert.equal(x.workflow.getSnapshot().receipts.status,'idle');assert.equal(x.counts.writes,0);x.dispose();
});
test('DEPLOY-PLAN: explicit target/restore, finite future interval and complete overlap facts required; cancel uses a fresh server revision',async()=>{
  const x=topology();assert.throws(()=>x.workflow.createPlan(schedule));await x.workflow.refreshCatalog();for(const invalid of [{...schedule,restoreVersionId:event.id},{...schedule,restoreVersionId:'foreign'},{...schedule,activateAtMs:500},{...schedule,timeZone:'invalid/zone'},{...schedule,bindingId:'foreign'}])assert.throws(()=>x.workflow.createPlan(invalid));assert.equal(x.counts.writes,0);await x.workflow.createPlan(schedule);assert.equal(x.last().kind,'create_plan');assert.equal(x.workflow.getSnapshot().plans.status,'idle');await x.workflow.refreshPlans();assert.throws(()=>x.workflow.createPlan(schedule));assert.throws(()=>x.workflow.cancelPlan('plan-one','stale-revision','cancel'));await x.workflow.cancelPlan('plan-one','plan-r1','cancel');assert.equal(x.last().expectedRevision,'plan-r1');assert.equal(x.counts.writes,2);await x.workflow.refreshPlans();assert.equal(x.workflow.getSnapshot().plans.data.items[0].state,'cancelled');assert.throws(()=>x.workflow.cancelPlan('plan-one','plan-r2','again'));x.dispose();
});
test('DEPLOY-WIRE: cross-runtime blank reasons never dispatch publication',async()=>{
  const x=topology();await x.workflow.selectVersion(event.id);assert.throws(()=>publish(x,'\u0085'));assert.equal(x.counts.writes,0);x.dispose();
});
test('DEPLOY-UNKNOWN: shared operation prevents draft/other mutations; pending/not-found lookup never replays or unlocks the command',async()=>{
  let status='not-found';const x=topology({write:(mutation,signal,complete)=>{complete(mutation);throw new AppError(AppErrorKind.NETWORK,'PRIVATE-PUBLISH');},lookup:(mutation,complete)=>status==='completed'?complete(mutation):{status,bindingId:mutation.bindingId,requestKey:mutation.requestKey}});await x.workflow.selectVersion(event.id);await assert.rejects(publish(x,'Publish'));assert.equal(x.workflow.getSnapshot().operation.command.status,'result-unknown');assert.throws(()=>publish(x,'Again'));await assert.rejects(x.operation.run({kind:'delete_draft',draftId:'draft',expectedRevision:'r1'}));
  for(const next of ['not-found','pending']){status=next;await x.workflow.inspect();assert.equal(x.workflow.getSnapshot().operation.command.status,'result-unknown');}status='completed';await x.workflow.inspect();assert.equal(x.counts.writes,1);assert.equal(x.counts.lookups,3);assert.equal(x.workflow.getSnapshot().publicationId,publication.id);assert.equal(x.source.getSnapshot().data.versionId,daily.id);x.dispose();
});
test('DEPLOY-OWNER: first read revocation hides every fact including command results; another session cannot inherit selection or reload',async()=>{
  const x=topology();await x.workflow.refreshCatalog();await x.workflow.selectVersion(event.id);await publish(x,'Publish');const states=[];const stop=x.workflow.subscribe(()=>states.push(x.workflow.getSnapshot()));states.length=0;x.read.set({ownerKey:'deployment-session',allowed:false});assert.equal(states[0].versionId,null);assert.equal(states[0].version.status,'idle');assert.equal(states[0].operation.authorized,false);assert.deepEqual(states[0].operation.command,{status:'idle'});x.read.set({ownerKey:'another-session',allowed:true});await assert.rejects(async()=>x.workflow.refreshCatalog(),error=>error.status===403);assert.throws(()=>publish(x,'Again'));stop();x.dispose();
});
test('DEPLOY-FACTS: versions, complete collections and plans reject foreign kinds, malformed values, duplicates and invalid UTC windows',()=>{
  assert.equal(validRuleSetVersion(event,ruleSet.binding),true);for(const patch of [{kind:'system'},{profile:'foreign'},{createdAtMs:NaN},{records:[ruleSet.records[0],ruleSet.records[0]]},{records:[{...ruleSet.records[0],rule:{kind:'flow',value:{...ruleSet.records[0].rule.value,count:NaN}}}]}])assert.equal(validRuleSetVersion({...event,...patch},ruleSet.binding),false);
  assert.equal(validRuleActivationPlan(activePlan,'binding-one'),true);assert.equal(validRuleActivationPlan({...activePlan,deactivateAtMs:1000},'binding-one'),false);assert.equal(validRuleCollection({bindingId:'binding-one',asOfMs:100,items:[event,event]},'binding-one',v=>validRuleSetVersion(v,ruleSet.binding)),false);
});
test('DEPLOY-CONFIRM: external source change after confirmation opens cannot silently replace the baseline the user approved',async()=>{
  const x=topology();await x.workflow.selectVersion(event.id);const expected={versionId:event.id,versionChecksum:event.checksum,expectedVersionId:ruleSet.versionId,expectedChecksum:ruleSet.checksum,expectedSourceRevision:ruleSet.sourceRevision};x.source.set({...x.source.getSnapshot(),data:{...ruleSet,checksum:'external-change',sourceRevision:'external-native'}});assert.throws(()=>publish(x,'Publish',expected),error=>error.status===409);assert.equal(x.counts.writes,0);x.dispose();
});
test('DEPLOY-ORIGIN: the draft inspector cannot consume a publication result and lose deployment selection',async()=>{
 const x=topology({write:()=>{throw new AppError(AppErrorKind.NETWORK,'PRIVATE');}});
 const draft=createRuleDraftWorkflow(ruleSet.binding,{}, {read:x.read.getSnapshot,subscribe:x.read.subscribe},{read:x.write.getSnapshot,subscribe:x.write.subscribe},x.operation);
 await x.workflow.selectVersion(event.id);await assert.rejects(publish(x,'Publish'));
 await assert.rejects(draft.inspect());assert.equal(x.counts.lookups,0);assert.equal(x.operation.getSnapshot().command.status,'result-unknown');
 await x.workflow.inspect();assert.equal(x.workflow.getSnapshot().publicationId,publication.id);assert.equal(x.counts.writes,1);draft.dispose();x.dispose();
});
