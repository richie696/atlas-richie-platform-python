import {test} from 'node:test';
import assert from 'node:assert/strict';
import {prepareRuleSchedule,hasRuleScheduleChanges,INITIAL_RULE_SCHEDULE_DRAFT} from '../../src/features/rules/model/ruleScheduleDraft';
import {canCancelRulePlan,resolveCivilMinute} from '../../src/features/rules/model/ruleActivation';
import {scheduleOccurrenceOptions} from '../../src/features/rules/presentation/scheduleTime';
import {getSystemTimeZone,setSystemTimeZone} from '../../src/shared/presentation/systemTimeZone';
const draft={versionId:'event',restoreVersionId:'daily',timeZone:'UTC',startsAt:'2026-11-01T01:30',endsAt:'2026-11-01T03:30',startOccurrence:'',endOccurrence:''};
test('SCHEDULE-DIRTY: every local field protects unsent input; pristine clones and reset are clean',()=>{
 assert.equal(Object.isFrozen(INITIAL_RULE_SCHEDULE_DRAFT),true);
 assert.equal(hasRuleScheduleChanges({...INITIAL_RULE_SCHEDULE_DRAFT}),false);
 for(const key of Object.keys(INITIAL_RULE_SCHEDULE_DRAFT))assert.equal(hasRuleScheduleChanges({...INITIAL_RULE_SCHEDULE_DRAFT,[key]:'changed'}),true,key);
 assert.equal(hasRuleScheduleChanges(INITIAL_RULE_SCHEDULE_DRAFT),false);
});
test('SCHEDULE-FORM: explicit target/restore and increasing UTC interval, not a browser timer',()=>{
 const result=prepareRuleSchedule('binding',draft);assert.equal(result.valid,true);assert.equal(result.schedule.activateAtMs,Date.parse('2026-11-01T01:30:00Z'));
 for(const patch of [{restoreVersionId:''},{restoreVersionId:'event'},{endsAt:draft.startsAt},{endsAt:'invalid'},{timeZone:'invalid/zone'},{startOccurrence:'999'}])assert.equal(prepareRuleSchedule('binding',{...draft,...patch}).valid,false);
 assert.equal(prepareRuleSchedule('',draft).valid,false);
});
test('SCHEDULE-DST: nonexistent time rejected; repeated time requires an explicit matching UTC occurrence',()=>{
 const ny={...draft,timeZone:'America/New_York'};assert.equal(prepareRuleSchedule('binding',ny).valid,false);
 const candidates=resolveCivilMinute(ny.startsAt,ny.timeZone);assert.equal(candidates.length,2);
 for(const utc of candidates){const result=prepareRuleSchedule('binding',{...ny,startOccurrence:String(utc)});assert.equal(result.valid,true);assert.equal(result.schedule.activateAtMs,utc);}
 assert.equal(prepareRuleSchedule('binding',{...ny,startsAt:'2026-03-08T02:30',endsAt:'2026-03-08T04:30'}).valid,false);
 assert.equal(prepareRuleSchedule('binding',{...draft,startOccurrence:String(candidates[0])}).valid,false);
});
test('F5.2 SCHEDULE-LOCALE: DST occurrence values stay stable while labels follow locale and the configured zone',()=>{
 const values=resolveCivilMinute('2026-11-01T01:30','America/New_York');
 const original=[...values];
 const originalZone=getSystemTimeZone();
 try{
  setSystemTimeZone('Asia/Shanghai');
  const options=Object.fromEntries(['zh-CN','en-US','ja-JP'].map(locale=>[
   locale,scheduleOccurrenceOptions(values,locale,'Choose occurrence')
  ]));
  for(const locale of Object.keys(options)){
   assert.deepEqual(options[locale].map(option=>option.value),['',...values.map(String)]);
   for(const option of options[locale].slice(1))assert.match(option.label,/ GMT\+8$/);
  }
  assert.notEqual(options['zh-CN'][1].label,options['en-US'][1].label);
  assert.deepEqual(values,original);
  assert.throws(()=>scheduleOccurrenceOptions([-1],'en-US','Choose occurrence'),RangeError);
 }finally{setSystemTimeZone(originalZone);}
});
test('SCHEDULE-CANCEL: presentation and commands share the same cancellation policy',()=>{
 for(const state of ['pending','blocked'])assert.equal(canCancelRulePlan({state}),true);
 for(const state of ['activating','active','restoring','completed','cancelled'])assert.equal(canCancelRulePlan({state}),false);
});
