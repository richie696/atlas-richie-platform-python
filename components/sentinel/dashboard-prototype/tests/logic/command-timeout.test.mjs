import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createCommandResource} from '../../src/shared/state/commandResource';
test('COMMAND-BOUND: timeout is owned by the shared mutation lifecycle; an ignored loader aborts and remains unknown, not replayable',async()=>{
  let signal,writes=0;const resource=createCommandResource(async(_input,s)=>{writes++;signal=s;return new Promise(()=>{});},{timeoutMs:10});
  let guard;try {
    await assert.rejects(Promise.race([resource.run({}),new Promise((_,reject)=>guard=setTimeout(()=>reject(new Error('test-guard-expired')),200))]),error=>error.kind==='timeout');
    assert.equal(signal.aborted,true);assert.equal(resource.getSnapshot().status,'result-unknown');await assert.rejects(resource.run({}));assert.equal(writes,1);
  }finally{clearTimeout(guard);resource.dispose();}
});
test('COMMAND-BOUND: invalid time bounds cannot create an unbounded write owner',()=>{
  for(const timeoutMs of [0,-1,Infinity,NaN])assert.throws(()=>createCommandResource(async()=>null,{timeoutMs}));
});
