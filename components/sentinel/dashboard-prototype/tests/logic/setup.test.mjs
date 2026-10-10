import assert from 'node:assert/strict';
import { test } from 'node:test';
import { INITIAL_SETUP_DRAFT, SETUP_FIELD, SETUP_STEP, clearSetupSecrets, setupStepForField, validateSetupStep } from '../../src/features/identity/model/setup';
import { prepareSetupSubmission, prepareSetupDatabase, prepareSetupSource, changeSetupDatabase, changeSetupSource, changeSetupAuthentication } from '../../src/features/identity/model/setupSubmission';

const draft = Object.freeze({
  ...INITIAL_SETUP_DRAFT,
  database: Object.freeze({host:'db.internal',name:'sentinel_control',username:'operator',password:'SYNTHETIC-DB'}),
  admin: Object.freeze({username:' admin ',password:'SYNTHETIC-ADMIN-12',confirm:'SYNTHETIC-ADMIN-12'}),
  source: Object.freeze({address:'https://nacos.internal/nacos',namespace:'public'}),
  sourceCredentials: Object.freeze({reference:' deployment-secret ',username:'nacos-user',password:'SYNTHETIC-NACOS',consulToken:'SYNTHETIC-CONSUL'}),
});
const valid = input => {const value=prepareSetupSubmission(input);assert.equal(value.status,'valid',JSON.stringify(value));return value.submission;};

test('SETUP-SHAPE: exact database/provider/auth branches omit inactive credentials and UI confirmation',()=>{
  for(const kind of ['postgresql','mysql','sqlite']) {
    const result=valid({...draft,databaseKind:kind,databasePort:kind==='mysql'?'3306':'5432'});
    assert.equal(result.database.kind,kind);assert.equal(result.admin.username,'admin');
    assert.ok(!('confirm' in result.admin));
    if(kind==='sqlite')assert.deepEqual(result.database,{kind:'sqlite'});
    else assert.equal(result.database.port,kind==='mysql'?3306:5432);
    assert.deepEqual(result.source.authentication,{mode:'credential-reference',reference:'deployment-secret'});
    assert.doesNotMatch(JSON.stringify(result),/SYNTHETIC-NACOS|SYNTHETIC-CONSUL/);
  }
  const nacos=valid({...draft,sourceAuthenticationMode:'direct'}).source;
  assert.equal(nacos.provider,'nacos');assert.deepEqual(nacos.authentication,{mode:'direct',username:'nacos-user',password:'SYNTHETIC-NACOS'});
  assert.ok(!('datacenter' in nacos));assert.doesNotMatch(JSON.stringify(nacos),/SYNTHETIC-CONSUL|deployment-secret/);
  const consul=valid({...draft,sourceKind:'consul',sourceAuthenticationMode:'direct'}).source;
  assert.equal(consul.provider,'consul');assert.deepEqual(consul.authentication,{mode:'direct',aclToken:'SYNTHETIC-CONSUL'});
  assert.ok(!('namespace' in consul));assert.equal(consul.datacenter,'public');
  const none=valid({...draft,sourceAuthenticationMode:'none'}).source.authentication;
  assert.deepEqual(none,{mode:'none'});
  assert.ok(Object.isFrozen(draft.admin));assert.equal(draft.admin.username,' admin ');
});
test('F4.20 SETUP-CHECK-PROJECTION: each connectivity check projects only its selected input branch',()=>{
  const database=prepareSetupDatabase({
    ...draft,
    databaseKind:'mysql',
    databasePort:'3306',
    admin:{username:'',password:'SYNTHETIC-ADMIN',confirm:''},
    source:{...draft.source,address:'invalid'},
  });
  assert.deepEqual(database,{status:'valid',input:{kind:'mysql',host:'db.internal',port:3306,database:'sentinel_control',username:'operator',password:'SYNTHETIC-DB'}});
  assert.doesNotMatch(JSON.stringify(database),/SYNTHETIC-ADMIN|SYNTHETIC-NACOS|SYNTHETIC-CONSUL|deployment-secret/);

  const nacos=prepareSetupSource({
    ...draft,
    database:{host:'',name:'',username:'',password:''},
    admin:{username:'',password:'SYNTHETIC-ADMIN',confirm:''},
    sourceAuthenticationMode:'direct',
  });
  assert.deepEqual(nacos,{status:'valid',input:{provider:'nacos',endpoint:'https://nacos.internal/nacos',namespace:'public',authentication:{mode:'direct',username:'nacos-user',password:'SYNTHETIC-NACOS'}}});
  assert.doesNotMatch(JSON.stringify(nacos),/SYNTHETIC-DB|SYNTHETIC-ADMIN|SYNTHETIC-CONSUL|deployment-secret/);

  const consul=prepareSetupSource({
    ...draft,
    sourceKind:'consul',
    sourceAuthenticationMode:'direct',
  });
  assert.deepEqual(consul,{status:'valid',input:{provider:'consul',endpoint:'https://nacos.internal/nacos',datacenter:'public',authentication:{mode:'direct',aclToken:'SYNTHETIC-CONSUL'}}});
  assert.doesNotMatch(JSON.stringify(consul),/SYNTHETIC-DB|SYNTHETIC-ADMIN|SYNTHETIC-NACOS|deployment-secret/);

  const invalidDatabase=prepareSetupDatabase({...draft,database:{...draft.database,password:''}});
  const invalidSource=prepareSetupSource({...draft,sourceAuthenticationMode:'direct',sourceCredentials:{...draft.sourceCredentials,password:''}});
  assert.equal(invalidDatabase.status,'invalid');
  assert.equal(invalidSource.status,'invalid');
});
test('SETUP-VALIDATE: network storage requires host/name/user and strict port; SQLite omits irrelevant fields',()=>{
  for(const field of ['host','name','username','password']) {
    const value=field==='password'?'':' ';
    assert.equal(prepareSetupSubmission({...draft,database:{...draft.database,[field]:value}}).status,'invalid');
  }
  for(const port of ['',' ', '0','65536','1.5','5432e0','-1','Infinity','0x1538'])assert.equal(prepareSetupSubmission({...draft,databasePort:port}).status,'invalid',port);
  for(const port of ['1','5432','65535'])assert.equal(valid({...draft,databasePort:port}).database.port,Number(port));
  assert.equal(prepareSetupSubmission({...draft,databaseKind:'sqlite',database:INITIAL_SETUP_DRAFT.database,databasePort:''}).status,'valid');
  assert.ok(validateSetupStep(SETUP_STEP.Storage,INITIAL_SETUP_DRAFT).length);
});
test('SETUP-VALIDATE: every local issue has a field owner for inline feedback and correction routing',()=>{
  const databaseIssues=validateSetupStep(SETUP_STEP.Storage,{
    ...INITIAL_SETUP_DRAFT,
    database:{...INITIAL_SETUP_DRAFT.database,name:''},
  });
  assert.deepEqual(databaseIssues.map(issue=>issue.field),[
    SETUP_FIELD.DatabaseHost,SETUP_FIELD.DatabaseName,SETUP_FIELD.DatabaseUsername,SETUP_FIELD.DatabasePassword,
  ]);
  assert.ok(databaseIssues.every(issue=>issue.key==='setup.required'));
  assert.deepEqual(setupStepForField(SETUP_FIELD.DatabasePort),SETUP_STEP.Storage);

  const adminIssues=validateSetupStep(SETUP_STEP.Admin,{...INITIAL_SETUP_DRAFT,admin:{username:'',password:'short',confirm:'different'}});
  assert.deepEqual(adminIssues.map(issue=>issue.field),[
    SETUP_FIELD.AdminUsername,SETUP_FIELD.AdminPassword,SETUP_FIELD.AdminConfirm,
  ]);
  assert.deepEqual(adminIssues.map(issue=>setupStepForField(issue.field)),Array(3).fill(SETUP_STEP.Admin));

  const sourceIssues=validateSetupStep(SETUP_STEP.Sources,{
    ...INITIAL_SETUP_DRAFT,
    source:{...INITIAL_SETUP_DRAFT.source,address:'https://nacos.example.com'},
  });
  assert.deepEqual(sourceIssues.map(issue=>issue.field),[SETUP_FIELD.CredentialReference]);
  assert.equal(setupStepForField(SETUP_FIELD.CredentialReference),SETUP_STEP.Sources);
  assert.ok(databaseIssues.every(issue=>!JSON.stringify(issue).includes('SYNTHETIC')));
});
test('SETUP-VALIDATE: every provider/authentication branch maps source failures to the visible credential field',()=>{
  const withEndpoint={...INITIAL_SETUP_DRAFT,source:{...INITIAL_SETUP_DRAFT.source,address:'https://source.example.test'}};
  const referenceIssues=validateSetupStep(SETUP_STEP.Sources,withEndpoint);
  assert.deepEqual(referenceIssues.map(issue=>issue.field),[SETUP_FIELD.CredentialReference]);

  const nacosIssues=validateSetupStep(SETUP_STEP.Sources,{
    ...withEndpoint,
    sourceAuthenticationMode:'direct',
  });
  assert.deepEqual(nacosIssues.map(issue=>issue.field),[
    SETUP_FIELD.NacosUsername,
    SETUP_FIELD.NacosPassword,
  ]);
  assert.deepEqual(nacosIssues.map(issue=>setupStepForField(issue.field)),[
    SETUP_STEP.Sources,
    SETUP_STEP.Sources,
  ]);

  const consulIssues=validateSetupStep(SETUP_STEP.Sources,{
    ...withEndpoint,
    sourceKind:'consul',
    sourceAuthenticationMode:'direct',
  });
  assert.deepEqual(consulIssues.map(issue=>issue.field),[SETUP_FIELD.ConsulToken]);

  const noneIssues=validateSetupStep(SETUP_STEP.Sources,{
    ...withEndpoint,
    sourceAuthenticationMode:'none',
  });
  assert.deepEqual(noneIssues,[]);

  const endpointIssues=validateSetupStep(SETUP_STEP.Sources,{
    ...withEndpoint,
    source:{...withEndpoint.source,address:'ftp://source.example.test'},
    sourceAuthenticationMode:'none',
  });
  assert.deepEqual(endpointIssues.map(issue=>issue.field),[SETUP_FIELD.SourceAddress]);
  assert.ok([...referenceIssues,...nacosIssues,...consulIssues,...endpointIssues].every(issue=>issue.field));
});
test('SETUP-VALIDATE: reject missing/inline-secret/non-HTTP/query/hash source addresses before any submission',()=>{
  for(const address of ['', '  ', 'ftp://nacos.internal', 'http:/nacos.internal', 'http:///nacos.internal', 'http:\\nacos.internal', 'https://user:password@nacos.internal', 'https://nacos.internal?token=synthetic', 'https://nacos.internal#secret', '/nacos'])assert.equal(prepareSetupSubmission({...draft,source:{...draft.source,address}}).status,'invalid',address);
  for(const address of ['http://127.0.0.1:8848/nacos','https://nacos.internal/nacos','http://[::1]:8500'])assert.equal(prepareSetupSubmission({...draft,source:{...draft.source,address}}).status,'valid',address);
  assert.equal(prepareSetupSubmission({...draft,admin:{...draft.admin,confirm:'different'}}).status,'invalid');
  assert.equal(prepareSetupSubmission({...draft,sourceAuthenticationMode:'direct',sourceCredentials:{...draft.sourceCredentials,password:''}}).status,'invalid');
  assert.ok(validateSetupStep(SETUP_STEP.Complete,{...draft,databasePort:'0'}).length);
});
test('SETUP-SECRET: switching provider/auth/database drops irrelevant secrets and never resurrects them',()=>{
  assert.strictEqual(changeSetupAuthentication(draft,draft.sourceAuthenticationMode),draft);
  assert.strictEqual(changeSetupSource(draft,draft.sourceKind),draft);
  assert.strictEqual(changeSetupDatabase(draft,draft.databaseKind),draft);
  const direct=changeSetupAuthentication(draft,'direct');
  assert.deepEqual(direct.sourceCredentials,INITIAL_SETUP_DRAFT.sourceCredentials);
  assert.deepEqual(changeSetupAuthentication(direct,'credential-reference').sourceCredentials,INITIAL_SETUP_DRAFT.sourceCredentials);
  const consul=changeSetupSource(draft,'consul');assert.deepEqual(consul.sourceCredentials,INITIAL_SETUP_DRAFT.sourceCredentials);
  assert.deepEqual(consul.source,INITIAL_SETUP_DRAFT.source);assert.deepEqual(changeSetupSource(consul,'nacos').sourceCredentials,INITIAL_SETUP_DRAFT.sourceCredentials);
  const sqlite=changeSetupDatabase(draft,'sqlite');assert.equal(sqlite.database.password,'');assert.equal(sqlite.database.host,'');assert.equal(sqlite.database.username,'');
  assert.equal(changeSetupDatabase(sqlite,'postgresql').database.password,'');
  assert.equal(changeSetupDatabase(draft,'mysql').databasePort,'3306');assert.equal(changeSetupDatabase(draft,'mysql').database.password,'');
  assert.equal(draft.database.password,'SYNTHETIC-DB');assert.equal(draft.sourceCredentials.password,'SYNTHETIC-NACOS');
});
test('SETUP-SECRET: discard/completion clears every credential field without mutating safe setup context',()=>{
  const cleared=clearSetupSecrets(draft);
  assert.notStrictEqual(cleared,draft);
  assert.equal(cleared.database.username,'');assert.equal(cleared.database.password,'');
  assert.deepEqual(cleared.sourceCredentials,INITIAL_SETUP_DRAFT.sourceCredentials);
  assert.equal(cleared.admin.password,'');assert.equal(cleared.admin.confirm,'');
  assert.equal(cleared.admin.username,draft.admin.username);
  assert.equal(cleared.database.host,draft.database.host);assert.equal(cleared.database.name,draft.database.name);
  assert.equal(cleared.source.address,draft.source.address);assert.equal(cleared.source.namespace,draft.source.namespace);
  assert.doesNotMatch(JSON.stringify(cleared),/SYNTHETIC-DB|SYNTHETIC-ADMIN|SYNTHETIC-NACOS|SYNTHETIC-CONSUL|deployment-secret|nacos-user/);
  assert.equal(draft.database.username,'operator');assert.equal(draft.database.password,'SYNTHETIC-DB');
  assert.equal(draft.sourceCredentials.password,'SYNTHETIC-NACOS');
});
