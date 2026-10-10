import assert from 'node:assert/strict';
import {test} from 'node:test';
import {http,HttpResponse} from 'msw/http';
import {setupServer} from 'msw/node';
import {createConsoleTransport} from '../../src/core/api/transport/consoleTransport';
import {createAccountManagementHttp} from '../../src/features/identity/api/accountManagementHttp';
import {createOwnPasswordHttp} from '../../src/features/identity/api/ownPasswordHttp';
import {createIdentityHttp} from '../../src/features/identity/api/identityHttp';
import {createAccountManagementWorkflow} from '../../src/features/identity/application/accountManagementWorkflow';
import {createOwnPasswordWorkflow} from '../../src/features/identity/application/ownPasswordWorkflow';

const origin='http://account-http.test',csrf='D'.repeat(48),signal=()=>new AbortController().signal;
const record={id:'account/用户',username:'operator',roleId:'view',status:'active',builtIn:false,lastLoginAt:null,revision:'1',lastActiveAdmin:false};
const identity={accountId:'admin-account',username:'admin',roleId:'admin',capabilities:['metrics:view','rules:write'],sessionEpoch:'session-one'};
const session={read:()=>({phase:'resolved',facts:{kind:'authenticated',identity}}),subscribe:()=>()=>{}};
const response=(request,body,status=200)=>HttpResponse.json(body,{status,headers:{'x-request-id':request.headers.get('x-request-id'),'x-sentinel-csrf':csrf}});
async function runHttp(handlers,run){
 const server=setupServer(http.get(`${origin}/api/v1/auth/me`,({request})=>response(request,identity)),...handlers);server.listen({onUnhandledRequest:'error'});let sequence=0;
 const transport=createConsoleTransport({baseUrl:origin,owner:()=> 'account-owner',onUnauthorized:()=>{},requestId:()=>`accounts-${++sequence}`});
 try{await createIdentityHttp(transport).readSession(signal());await run(createAccountManagementHttp(transport),createOwnPasswordHttp(transport));}finally{transport.dispose();server.close();}
}
test('ACCOUNT-HTTP: server page/encoded target are explicit; nullable absence is not a substitute row',async()=>{
 let query;
 await runHttp([http.get(`${origin}/api/v1/accounts`,({request})=>{query=new URL(request.url).searchParams;return response(request,{items:[record],page:2,pageSize:1,total:2});}),http.get(`${origin}/api/v1/accounts/:id`,({request,params})=>response(request,params.id===record.id?record:null))],async port=>{
  assert.deepEqual(await port.listAccounts({page:2,pageSize:1,search:' 用户 ',status:'active'},signal()),{items:[record],page:2,pageSize:1,total:2});assert.deepEqual([...query],[['page','2'],['pageSize','1'],['search',' 用户 '],['status','active']]);assert.deepEqual(await port.readAccount(record.id,signal()),record);assert.equal(await port.readAccount('missing',signal()),null);
 });
});
test('ACCOUNT-READ: foreign/stale page, duplicate IDs, inconsistent administrator facts and credentials fail closed',async()=>{
 const page={items:[record],page:1,pageSize:2,total:1};
 for(const body of [{...page,page:2},{...page,total:3},{...page,items:[record,record],total:2},{...page,items:[{...record,lastActiveAdmin:true}]},{...page,items:[{...record,builtIn:true}]},{...page,items:[{...record,password:'PRIVATE-READ'}]},{...page,items:[{...record,lastLoginAt:'today'}]}])await runHttp([http.get(`${origin}/api/v1/accounts`,({request})=>response(request,body))],async port=>{await assert.rejects(port.listAccounts({page:1,pageSize:2,search:''},signal()),error=>error.code==='console_response_invalid'&&!JSON.stringify(error).includes('PRIVATE'));});
 await runHttp([http.get(`${origin}/api/v1/accounts/:id`,({request})=>response(request,{...record,id:'foreign'}))],async port=>{await assert.rejects(port.readAccount(record.id,signal()),error=>error.code==='console_response_invalid');});
});
test('ACCOUNT-REVISION-WIRE: signed BIGINT revisions stay canonical decimal strings above JS safe integer',async()=>{
 const revision='9223372036854775807',maximumRecord={...record,revision};
 await runHttp([http.get(`${origin}/api/v1/accounts`,({request})=>response(request,{items:[maximumRecord],page:1,pageSize:1,total:1}))],async port=>{
  assert.equal((await port.listAccounts({page:1,pageSize:1,search:''},signal())).items[0].revision,revision);
 });
 await runHttp([http.post(`${origin}/api/v1/accounts/commands`,async({request})=>{
  const body=await request.json();assert.equal(body.revision,revision);
  return response(request,{status:'rejected',requestKey:body.requestKey,reason:'conflict'});
 })],async port=>{
  assert.deepEqual(await port.mutateAccount({kind:'status',requestKey:'max-revision',accountId:record.id,revision,status:'disabled'},signal()),{status:'rejected',requestKey:'max-revision',reason:'conflict'});
 });
});
test('ACCOUNT-COMMAND: three closed variants preserve original key/revision, safe lookup permits not-found',async()=>{
 const inputs=[{kind:'create',requestKey:'create-one',input:{username:'operator',password:'PRIVATE-NEW-PASSWORD',roleId:'view'}},{kind:'status',requestKey:'status-one',accountId:record.id,revision:record.revision,status:'disabled'},{kind:'role',requestKey:'role-one',accountId:record.id,revision:record.revision,roleId:'admin'}];let writes=0;
 await runHttp([http.post(`${origin}/api/v1/accounts/commands`,async({request})=>{const body=await request.json();assert.deepEqual(body,inputs[writes++]);assert.equal(request.headers.get('idempotency-key'),body.requestKey);assert.equal(request.headers.get('x-sentinel-csrf'),csrf);return response(request,{status:'completed',requestKey:body.requestKey,account:{...record,revision:'2',...(body.kind==='status'?{status:body.status}:body.kind==='role'?{roleId:body.roleId}:{})}});}),http.get(`${origin}/api/v1/accounts/operations/:key`,({request,params})=>response(request,{status:'not-found',requestKey:params.key}))],async port=>{
  for(const input of inputs)assert.equal((await port.mutateAccount(input,signal())).status,'completed');assert.deepEqual(await port.readAccountOperation('create-one',signal()),{status:'not-found',requestKey:'create-one'});assert.equal(writes,3);
 });
});
test('ACCOUNT-ACK: unverifiable command stays unknown; original-key inspection does not replay or release on not-found',async()=>{
 for(const receipt of [{status:'not-found',requestKey:'original-key'},{status:'completed',requestKey:'other-key',account:record},{status:'completed',requestKey:'original-key',account:{...record,username:'foreign'}},{status:'completed',requestKey:'original-key',account:{...record,password:'PRIVATE-REPLY'}}]){
  let writes=0,lookups=0;
  await runHttp([http.post(`${origin}/api/v1/accounts/commands`,({request})=>{writes++;return response(request,receipt);}),http.get(`${origin}/api/v1/accounts/operations/:key`,({request,params})=>{lookups++;return response(request,{status:'not-found',requestKey:params.key});})],async port=>{
   const workflow=createAccountManagementWorkflow(port,identity,session,()=> 'original-key');try{await assert.rejects(workflow.create({username:'operator',password:'PRIVATE-NEW-PASSWORD',roleId:'view'}));assert.equal(workflow.getSnapshot().mutation.status,'result-unknown');await assert.rejects(workflow.create({username:'operator',password:'PRIVATE-NEW-PASSWORD',roleId:'view'}));assert.equal((await workflow.inspect()).status,'not-found');assert.equal(workflow.getSnapshot().mutation.status,'result-unknown');assert.equal(writes,1);assert.equal(lookups,1);assert.equal(JSON.stringify(workflow.getSnapshot()).includes('PRIVATE'),false);}finally{workflow.dispose();}
  });
 }
});
test('ACCOUNT-REVISION: a changed target/effect or unchanged revision cannot acknowledge the requested status mutation',async()=>{
 for(const account of [record,{...record,id:'foreign',revision:'2',status:'disabled'},{...record,revision:'2'}])await runHttp([http.post(`${origin}/api/v1/accounts/commands`,({request})=>response(request,{status:'completed',requestKey:'status-one',account}))],async port=>{await assert.rejects(port.mutateAccount({kind:'status',requestKey:'status-one',accountId:record.id,revision:record.revision,status:'disabled'},signal()),error=>error.code==='console_response_invalid');});
});
test('IDENTITY-WRITE: inactive/confirmation/target secrets and invalid paging never dispatch; safe domain rejection stays distinct from HTTP denial',async()=>{
 let dispatched=0;
 await runHttp([http.all(`${origin}/api/v1/accounts*`,({request})=>{dispatched++;return response(request,{status:'rejected',requestKey:'original-key',reason:'last_admin'});}),http.post(`${origin}/api/v1/auth/password`,({request})=>{dispatched++;return response(request,{});})],async(port,password)=>{
  for(const input of [{kind:'role',requestKey:'original-key',accountId:record.id,revision:'1',roleId:'admin',password:'PRIVATE'},{kind:'create',requestKey:'original-key',input:{username:'operator',password:'PRIVATE-NEW-PASSWORD',roleId:'view',displayName:'bad'}}])await assert.rejects(port.mutateAccount(input,signal()),error=>error.code==='console_request_invalid');
  for(const revision of ['revision-one','0','01','9223372036854775808'])await assert.rejects(port.mutateAccount({kind:'status',requestKey:'invalid-revision',accountId:record.id,revision,status:'disabled'},signal()),error=>error.code==='console_request_invalid');
  await assert.rejects(port.listAccounts({page:0,pageSize:1,search:''},signal()));await assert.rejects(password.changeOwnPassword({currentPassword:'PRIVATE-CURRENT',newPassword:'PRIVATE-NEW-PASSWORD',accountId:'foreign'},signal()));await assert.rejects(password.changeOwnPassword({currentPassword:'PRIVATE-CURRENT',newPassword:'PRIVATE-NEW-PASSWORD',confirm:'PRIVATE-NEW-PASSWORD'},signal()));assert.equal(dispatched,0);
  assert.deepEqual(await port.mutateAccount({kind:'status',requestKey:'original-key',accountId:record.id,revision:record.revision,status:'disabled'},signal()),{status:'rejected',requestKey:'original-key',reason:'last_admin'});assert.equal(dispatched,1);
 });
});
test('PASSWORD-HTTP: only the implemented reauthentication policy is accepted; malformed acknowledgement stays unknown without credential replay',async()=>{
 for(const receipt of [{sessionDisposition:'reauthenticate'},{sessionDisposition:'retained'},{sessionDisposition:'retained',password:'PRIVATE-RESPONSE'},{}]){
  let writes=0;
  await runHttp([http.post(`${origin}/api/v1/auth/password`,async({request})=>{writes++;assert.equal(request.headers.get('x-sentinel-csrf'),csrf);assert.equal(request.headers.has('idempotency-key'),false);assert.deepEqual(await request.json(),{currentPassword:'PRIVATE-CURRENT',newPassword:'PRIVATE-NEW-PASSWORD'});return response(request,receipt);})],async(_port,password)=>{
   const workflow=createOwnPasswordWorkflow(password,identity,session);try{const submission=workflow.submit({current:'PRIVATE-CURRENT',next:'PRIVATE-NEW-PASSWORD',confirm:'PRIVATE-NEW-PASSWORD'});if(receipt.sessionDisposition==='reauthenticate'&&Object.keys(receipt).length===1)assert.deepEqual(await submission,receipt);else{await assert.rejects(submission);assert.equal(workflow.getSnapshot().status,'result-unknown');await assert.rejects(workflow.submit({current:'PRIVATE-CURRENT',next:'PRIVATE-NEW-PASSWORD',confirm:'PRIVATE-NEW-PASSWORD'}));}assert.equal(writes,1);assert.equal(JSON.stringify(workflow.getSnapshot()).includes('PRIVATE'),false);}finally{workflow.dispose();}
  });
 }
});
