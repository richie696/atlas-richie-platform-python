import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AppError,AppErrorKind,StateStore} from '@richie696/react-framework';
import {createRuleOperation} from '../../src/features/rules/application/ruleOperation';
import {createRuleDraftWorkflow} from '../../src/features/rules/application/ruleDraftWorkflow';
import {validStoredDraft,validValidationReport} from '../../src/features/rules/model/ruleDraftState';
import {ruleSet} from '../fixtures/ruleSets';
const draft=(candidate,id='draft-one',revision='draft-r1')=>({id,revision,bindingId:candidate.bindingId,kind:candidate.kind,profile:candidate.profile,baseVersionId:candidate.baseVersionId,baseChecksum:candidate.baseChecksum,sourceRevision:candidate.sourceRevision,updatedAtMs:100,records:candidate.rules.map((record,index)=>({id:record.recordId??`server-new-${index}`,rule:record.rule}))});
const report=candidate=>({bindingId:candidate.bindingId,profile:candidate.profile,baseChecksum:candidate.baseChecksum,candidateChecksum:'server-candidate-checksum',validationId:'server-validation-ticket',isPublishable:true,issues:[]});
function topology(overrides={}) {
  const read=new StateStore({ownerKey:'draft-session',allowed:true}),write=new StateStore({ownerKey:'draft-session',allowed:true});
  const readAccess={read:read.getSnapshot,subscribe:read.subscribe},writeAccess={read:write.getSnapshot,subscribe:write.subscribe};
  let key=0,latest,lastDraft=null;
  const counts={writes:0,validates:0};
  const complete=mutation=>{
    let result;
    if(mutation.kind==='save_draft') {lastDraft=draft(mutation.candidate,mutation.draftId??'draft-one',`draft-r${counts.writes}`);result={kind:'save_draft',draft:lastDraft};}
    else if(mutation.kind==='freeze_version') result={kind:'freeze_version',draftId:mutation.draftId,draftRevision:mutation.expectedRevision,version:{id:'immutable-version',bindingId:mutation.bindingId,kind:lastDraft.kind,profile:lastDraft.profile,baseVersionId:lastDraft.baseVersionId,checksum:mutation.candidateChecksum,name:mutation.name,note:mutation.note,createdAtMs:200,createdById:'actor-one',records:lastDraft.records}};
    else result={kind:'delete_draft',draftId:mutation.draftId};
    return {bindingId:mutation.bindingId,requestKey:mutation.requestKey,status:'completed',result};
  };
  const operation=createRuleOperation(ruleSet.binding.id,{
    async mutateRuleSet(mutation,signal) {counts.writes++;latest=mutation;return overrides.write ? overrides.write(mutation,signal,complete) : complete(mutation);},
    async readRuleOperation(){return overrides.lookup ? overrides.lookup(latest,complete) : complete(latest);}
  },writeAccess,()=>`draft-operation-${++key}`);
  const workflow=createRuleDraftWorkflow(ruleSet.binding,{
    readSnapshot:async()=>overrides.source ? overrides.source() : structuredClone(ruleSet),
    readDraft:async()=>overrides.readDraft ? overrides.readDraft() : lastDraft,
    validateCandidate:async(candidate,signal)=>{counts.validates++;return overrides.validate ? overrides.validate(candidate,signal) : report(candidate);},
    compareCandidate:async candidate=>({bindingId:candidate.bindingId,baseChecksum:candidate.baseChecksum,candidateChecksum:'server-candidate-checksum',changes:[]}),
  },readAccess,writeAccess,operation);
  const change=count=>{const state=workflow.getSnapshot(),first=state.editing.records[0];workflow.change(first.formKey,{...first.rule,draft:{...first.rule.draft,count}});};
  return {workflow,operation,read,write,counts,change,last:()=>latest,dispose(){workflow.dispose();operation.dispose();read.complete();write.complete();}};
}
test('RULE-DRAFT baseline: refresh cannot replace dirty content; explicit discard adopts new source and readonly has no writes',async()=>{
  let source=ruleSet;const x=topology({source:()=>source});await x.workflow.refreshSource();x.workflow.begin();x.change('30');source={...ruleSet,versionId:'new-live',checksum:'new-live-checksum',records:[]};await x.workflow.refreshSource();assert.equal(x.workflow.getSnapshot().editing.records[0].rule.draft.count,'30');assert.equal(x.workflow.getSnapshot().editing.baseline.versionId,ruleSet.versionId);assert.throws(()=>x.workflow.begin());assert.throws(()=>x.workflow.close());x.workflow.begin(true);assert.equal(x.workflow.getSnapshot().editing.baseline.versionId,'new-live');assert.equal(x.workflow.getSnapshot().editing.records.length,0);
  x.write.set({ownerKey:'draft-session',allowed:false});assert.equal(x.workflow.getSnapshot().editing,null);assert.equal(x.workflow.getSnapshot().source.data.versionId,'new-live');await assert.rejects(async()=>x.workflow.save(),error=>error.status===403);assert.equal(x.counts.writes,0);x.dispose();
});
test('RULE-DRAFT save: full candidate/server revision is preserved; local edits invalidate validation/diff and no freeze before saved validation',async()=>{
  const x=topology();await x.workflow.refreshSource();x.workflow.begin();x.change('30');await x.workflow.validate();await x.workflow.compare();await assert.rejects(async()=>x.workflow.freeze('Release',''),error=>error.status===422);await x.workflow.save();assert.equal(x.last().candidate.rules.length,2);assert.equal(x.last().candidate.rules[1].rule.value.count,40);assert.equal(x.workflow.getSnapshot().dirty,false);assert.deepEqual(x.workflow.getSnapshot().savedIdentity,{id:'draft-one',revision:'draft-r1'});assert.equal(x.workflow.getSnapshot().validation.status,'idle');await x.workflow.validate();await x.workflow.freeze(' Release ','Version note');assert.equal(x.last().kind,'freeze_version');assert.equal(x.last().expectedRevision,'draft-r1');assert.equal(x.last().validationId,'server-validation-ticket');assert.equal(x.workflow.getSnapshot().operation.command.result.version.id,'immutable-version');assert.equal(x.workflow.getSnapshot().source.data.versionId,'version-one');assert.equal(x.workflow.getSnapshot().validation.status,'idle');
  await x.workflow.validate();await x.workflow.compare();x.change('31');assert.equal(x.workflow.getSnapshot().validation.status,'idle');assert.equal(x.workflow.getSnapshot().diff.status,'idle');await assert.rejects(async()=>x.workflow.freeze('Second',''));assert.equal(x.counts.writes,2);x.dispose();
});
test('RULE-DRAFT validation: late report aborts and cannot green-light a different edit generation; invalid whole set never reaches Port',async()=>{
  let release,signal;const x=topology({validate:(candidate,s)=>{signal=s;return new Promise(done=>{release=()=>done(report(candidate));});}});await x.workflow.refreshSource();x.workflow.begin();const pending=x.workflow.validate();await Promise.resolve();x.change('31');assert.equal(signal.aborted,true);release();await assert.rejects(pending);assert.equal(x.workflow.getSnapshot().validation.status,'idle');x.change('');await assert.rejects(async()=>x.workflow.save(),error=>error.status===422);assert.equal(x.counts.writes,0);assert.equal(x.workflow.getSnapshot().issues[0].issue.path,'count');x.dispose();
});
test('RULE-DRAFT-WIRE: cross-runtime blank version names never dispatch freeze',async()=>{
  const x=topology();await x.workflow.refreshSource();x.workflow.begin();x.change('31');await x.workflow.validate();await x.workflow.compare();await x.workflow.save();await x.workflow.validate();await assert.rejects(async()=>x.workflow.freeze('\u0085','Version note'),error=>error.status===422);assert.equal(x.counts.writes,1);x.dispose();
});
test('RULE-DRAFT conflict/unknown: input persists; outcome lookup adopts confirmed draft without replay or invented identities',async()=>{
  let mode='conflict';const x=topology({write:(mutation,signal,complete)=>{if(mode==='conflict')return {bindingId:mutation.bindingId,requestKey:mutation.requestKey,status:'rejected',reason:'conflict'};complete(mutation);throw new AppError(AppErrorKind.NETWORK,'PRIVATE-DRAFT-ACK');}});await x.workflow.refreshSource();x.workflow.begin();x.change('35');await assert.rejects(x.workflow.save());assert.equal(x.workflow.getSnapshot().operation.command.status,'conflict');assert.equal(x.workflow.getSnapshot().editing.records[0].rule.draft.count,'35');mode='unknown';await assert.rejects(x.workflow.save());assert.equal(x.workflow.getSnapshot().operation.command.status,'result-unknown');assert.throws(()=>x.change('36'));assert.throws(()=>x.workflow.discard());await assert.rejects(async()=>x.workflow.save());await x.workflow.inspect();assert.equal(x.counts.writes,2);assert.equal(x.workflow.getSnapshot().dirty,false);assert.equal(x.workflow.getSnapshot().editing.records[0].rule.draft.count,35);assert.equal(x.workflow.getSnapshot().savedIdentity.id,'draft-one');x.dispose();
});
test('RULE-DRAFT persisted resume: original checksum/revision survives changed live source; missing/wrong draft cannot replace current dirty values',async()=>{
  let stored;const x=topology({source:()=>({...ruleSet,versionId:'live-two',checksum:'live-two-checksum'}),readDraft:()=>stored});await x.workflow.refreshSource();x.workflow.begin();x.change('33');await x.workflow.save();stored=x.workflow.getSnapshot().operation.command.result.draft;await x.workflow.close();await x.workflow.openDraft(stored.id);assert.equal(x.workflow.getSnapshot().editing.baseline.checksum,'live-two-checksum');stored={...stored,baseVersionId:'original-version',baseChecksum:'original-checksum',sourceRevision:'original-native'};await x.workflow.openDraft(stored.id);x.change('34');await assert.rejects(x.workflow.openDraft('other'));assert.equal(x.workflow.getSnapshot().editing.records[0].rule.draft.count,'34');stored={...stored,bindingId:'wrong-binding'};await assert.rejects(x.workflow.openDraft('draft-one',true));assert.equal(x.workflow.getSnapshot().editing.baseline.checksum,'original-checksum');await x.workflow.save();assert.equal(x.last().candidate.baseChecksum,'original-checksum');assert.equal(x.last().candidate.sourceRevision,'original-native');
  x.dispose();
});
test('RULE-DRAFT revocation: first notification hides reports/editor; changed owner cannot reload inherited binding or receive late source',async()=>{
  const x=topology();await x.workflow.refreshSource();x.workflow.begin();await x.workflow.validate();const states=[];const unsubscribe=x.workflow.subscribe(()=>states.push(x.workflow.getSnapshot()));states.length=0;x.write.set({ownerKey:'new-session',allowed:true});assert.equal(states[0].editing,null);assert.equal(states[0].validation.status,'idle');assert.equal(states[0].savedIdentity,null);x.read.set({ownerKey:'new-session',allowed:true});await assert.rejects(async()=>x.workflow.refreshSource(),error=>error.status===403);assert.ok(!('data' in x.workflow.getSnapshot().source));unsubscribe();x.dispose();
});
test('RULE-DRAFT read guards: foreign binding/profile/record indices and raw error paths cannot become publishable',()=>{
  const candidate={bindingId:ruleSet.binding.id,profile:ruleSet.binding.profile,baseChecksum:ruleSet.checksum,rules:[]};const good=report(candidate);assert.equal(validValidationReport(good,candidate),true);assert.equal(validValidationReport({...good,profile:'other'},candidate),false);assert.equal(validValidationReport({...good,issues:[{code:'unknown_field',recordIndex:0,path:'resource'}]},candidate),false);assert.equal(validValidationReport({...good,isPublishable:false,issues:[{code:'validation',recordIndex:null,path:'PRIVATE user input'}]},candidate),false);
  const value={id:'draft-one',revision:'r1',bindingId:ruleSet.binding.id,kind:'flow',profile:ruleSet.binding.profile,baseVersionId:null,baseChecksum:'base',sourceRevision:null,updatedAtMs:100,records:[]};assert.equal(validStoredDraft(value,ruleSet.binding,'draft-one'),true);assert.equal(validStoredDraft({...value,profile:'other'},ruleSet.binding,'draft-one'),false);
});
test('RULE-DRAFT read revocation: completed mutation contents are hidden even before write-access projection changes',async()=>{
  const x=topology();await x.workflow.refreshSource();x.workflow.begin();await x.workflow.save();const states=[];const stop=x.workflow.subscribe(()=>states.push(x.workflow.getSnapshot()));states.length=0;x.read.set({ownerKey:'draft-session',allowed:false});assert.equal(states[0].editing,null);assert.equal(states[0].operation.authorized,false);assert.deepEqual(states[0].operation.command,{status:'idle'});stop();x.dispose();
});
