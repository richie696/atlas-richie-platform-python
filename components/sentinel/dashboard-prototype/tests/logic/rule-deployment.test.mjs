import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validRulePublication,validPublicationReceipts} from '../../src/features/rules/model/ruleDeployment';
import {resolveCivilMinute,activationScheduleIssues} from '../../src/features/rules/model/ruleActivation';
const success={state:'succeeded',observedAtMs:100,reason:null};
const publication={id:'publication-one',bindingId:'binding-one',targetVersionId:'version-two',targetChecksum:'checksum-two',baseVersionId:'version-one',createdAtMs:100,validation:success,configurationWrite:success,readBack:success};
test('PUBLICATION-PHASES: validation, source write and readback remain independent; unknown write is not an ACK',()=>{
  assert.equal(validRulePublication(publication,'binding-one','publication-one'),true);
  assert.equal(validRulePublication({...publication,configurationWrite:{state:'unknown',observedAtMs:100,reason:'unavailable'}},'binding-one'),true);
  for(const value of [{...publication,validation:{state:'running',observedAtMs:null,reason:null}},{...publication,configurationWrite:{state:'failed',observedAtMs:100,reason:'conflict'}},{...publication,readBack:{...success,reason:'conflict'}},{...publication,targetVersionId:''}])assert.equal(validRulePublication(value,'binding-one'),false);
});
test('PUBLICATION-RECEIPT: only exact incarnation/version/checksum applied facts count; restart is not applied',()=>{
  const row={instanceId:'instance-one',processEpoch:'epoch-two',loadedProcessEpoch:'epoch-two',targetVersionId:'version-two',loadedVersionId:'version-two',loadedChecksum:'checksum-two',appliedAtMs:120,lastReportAtMs:130,state:'applied'};
  const page={publicationId:'publication-one',bindingId:'binding-one',page:1,pageSize:10,asOfMs:140,total:3,expected:3,inventorySource:'test-inventory',applied:1,pending:1,failed:0,unknown:0,restartRequired:1,items:[row]};
  assert.equal(validPublicationReceipts(page,publication,1,10),true);assert.equal(page.expected,3);assert.equal(page.items.length,1);
  for(const patch of [{loadedProcessEpoch:'epoch-one'},{loadedVersionId:'version-one'},{loadedChecksum:'checksum-one'},{lastReportAtMs:null},{appliedAtMs:null}])assert.equal(validPublicationReceipts({...page,items:[{...row,...patch}]},publication,1,10),false);
  assert.equal(validPublicationReceipts({...page,expected:2},publication,1,10),false);assert.equal(validPublicationReceipts({...page,items:[row,row]},publication,1,10),false);
  assert.equal(validPublicationReceipts({...page,applied:0,pending:2},publication,1,10),false);
});
test('ACTIVATION-TIME: exact civil-minute resolution rejects invalid dates and DST gaps; ambiguity stays explicit',()=>{
  assert.deepEqual(resolveCivilMinute('2026-02-30T10:00','UTC'),[]);assert.deepEqual(resolveCivilMinute('2026-10-07T25:00','UTC'),[]);assert.deepEqual(resolveCivilMinute('2026-10-07T10:00','Not/AZone'),[]);
  assert.deepEqual(resolveCivilMinute('2026-10-07T10:00','Asia/Kathmandu').map(value=>new Date(value).toISOString()),['2026-10-07T04:15:00.000Z']);
  assert.deepEqual(resolveCivilMinute('2026-03-08T02:30','America/New_York'),[]);assert.deepEqual(resolveCivilMinute('2026-11-01T01:30','America/New_York').map(value=>new Date(value).toISOString()),['2026-11-01T05:30:00.000Z','2026-11-01T06:30:00.000Z']);
});
test('PUBLICATION-INVENTORY: receipt page total is independent of unknown fleet size; absent incarnation cannot prove applied',()=>{
  const missing={instanceId:'not-reported',processEpoch:null,loadedProcessEpoch:null,targetVersionId:'version-two',loadedVersionId:null,loadedChecksum:null,appliedAtMs:null,lastReportAtMs:null,state:'unknown'};
  const page={publicationId:'publication-one',bindingId:'binding-one',page:1,pageSize:10,asOfMs:140,total:1,expected:null,inventorySource:null,applied:0,pending:0,failed:0,unknown:1,restartRequired:0,items:[missing]};
  assert.equal(validPublicationReceipts(page,publication,1,10),true);
  assert.equal(validPublicationReceipts({...page,expected:1,inventorySource:'deployment-inventory'},publication,1,10),true);
  for(const patch of [{total:0},{expected:1},{inventorySource:'deployment-inventory'},{expected:2,inventorySource:'deployment-inventory'}])assert.equal(validPublicationReceipts({...page,...patch},publication,1,10),false);
  assert.equal(validPublicationReceipts({...page,applied:1,unknown:0,items:[{...missing,state:'applied',loadedVersionId:'version-two',loadedChecksum:'checksum-two',appliedAtMs:130,lastReportAtMs:135}]},publication,1,10),false);
});
test('ACTIVATION-POLICY: explicit immutable targets and restore version, half-open overlap hints and server scheduling boundary',()=>{
  const input={bindingId:'binding-one',versionId:'version-event',restoreVersionId:'version-daily',activateAtMs:1000,deactivateAtMs:2000,timeZone:'UTC'};
  assert.deepEqual(activationScheduleIssues(input,500,[]),[]);assert.ok(activationScheduleIssues({...input,restoreVersionId:input.versionId},500,[]).includes('identity'));assert.ok(activationScheduleIssues(input,1000,[]).includes('past'));assert.ok(activationScheduleIssues({...input,deactivateAtMs:1000},500,[]).includes('window'));
  const plan={...input,id:'plan-one',revision:'one',state:'pending',activationPublicationId:null,restorePublicationId:null};assert.ok(activationScheduleIssues(input,500,[plan]).includes('overlap'));assert.deepEqual(activationScheduleIssues({...input,activateAtMs:2000,deactivateAtMs:3000},500,[plan]),[]);assert.deepEqual(activationScheduleIssues(input,500,[{...plan,state:'cancelled'}]),[]);
});
