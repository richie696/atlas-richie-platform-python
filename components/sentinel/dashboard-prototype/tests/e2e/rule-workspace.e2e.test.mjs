import {before,after,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {E2E_BASE_URL,launchBrowser} from './cdp.mjs';
let browser;before(async()=>{browser=await launchBrowser();});after(async()=>{await browser?.close();});
async function withPage(run){const page=await browser.newPage();try{
  await page.clearStorage(new URL(E2E_BASE_URL).origin);await page.goto(`${E2E_BASE_URL}/#/login`);await page.waitFor(`!!document.querySelector('.app-shell')`);
  await page.eval(`(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {RuleSetWorkspaceProbe,createRuleWorkspaceTopology}=await import('/tests/e2e/probes/RuleSetWorkspaceProbe.tsx');document.getElementById('root').style.display='none';const host=document.createElement('section');host.id='rule-probe';document.body.append(host);const topology=createRuleWorkspaceTopology(),root=createRoot(host,{identifierPrefix:'rules-probe-'});root.render(React.createElement(React.StrictMode,null,React.createElement(RuleSetWorkspaceProbe,{topology})));window.__ruleCleanup=()=>{root.unmount();topology.dispose();host.remove();};})()`);
  await wait(page,`state.source==='ready'`);await run(page);assert.deepEqual(page.consoleErrors,[]);await page.eval('window.__ruleCleanup()');
}finally{await page.close();}}
const state=page=>page.eval(`JSON.parse(document.querySelector('#rule-probe [data-rule-summary]').textContent)`);
const wait=(page,predicate)=>page.waitFor(`(()=>{const state=JSON.parse(document.querySelector('#rule-probe [data-rule-summary]')?.textContent??'{}');return ${predicate};})()`);
const action=(page,id)=>page.click(`#rule-probe [data-rule-action=${id}]`);
const mode=(page,id)=>page.click(`#rule-probe [data-rule-mode=${id}]`);
const dialogAction=(page,label)=>page.clickByText(label,'#rule-probe dialog[open] button');
async function field(page,label,value,root='#rule-probe',commit=true) {
  const id=await page.eval(`[...document.querySelectorAll(${JSON.stringify(root+' label')})].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`);
  const selector='#'+id.replace(/[^a-zA-Z0-9_-]/g,x=>'\\'+x);await page.click(selector);await page.eval(`document.getElementById(${JSON.stringify(id)}).select()`);await page.send('Input.insertText',{text:value});await page.waitFor(`document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`);
  // Astryx NumberInput commits on blur/Enter. Exercise native Tab, not a business-state mutation.
  if(commit){await page.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await page.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});}
}
test('RULE-WORKSPACE rendered: complete snapshot edits preserve other rules and server draft revision; freeze is separate from publication',async()=>withPage(async page=>{
  await action(page,'begin');await field(page,'单机阈值','30');await wait(page,`state.dirty&&state.ruleValue.count===30`);const preview=JSON.parse(await page.text('#rule-probe [data-rule-full-preview]'));assert.equal(preview.length,2);assert.equal(preview[0].count,30);assert.equal(preview[1].count,40);
  await action(page,'save');await wait(page,`state.operation==='success'&&!state.dirty`);assert.equal((await state(page)).savedIdentity.id,'persisted-draft');assert.equal((await state(page)).lastCandidate.rules[1].recordId,'rule-two');assert.equal(await page.eval(`document.querySelector('#rule-probe [data-rule-action=freeze]').disabled`),true);
  await action(page,'validate');await wait(page,`state.validation==='ready'`);await action(page,'freeze');await page.waitFor(`!!document.querySelector('#rule-probe dialog[open]')`);await field(page,'版本名称','Weekend rules','#rule-probe dialog[open]');await dialogAction(page,'固化不可变版本');await page.waitFor(`!document.querySelector('#rule-probe dialog[open]')`);assert.equal((await state(page)).writes,2);assert.equal((await state(page)).sourceVersion,'version-one');assert.match(await page.text('#rule-probe'),/不是配置中心发布/);
}));
test('RULE-WORKSPACE rendered: add/delete keeps local ids private, field errors align, intentional empty full set is explicit',async()=>withPage(async page=>{
  await action(page,'begin');await action(page,'add');assert.equal((await state(page)).ruleCount,3);await action(page,'save');assert.equal((await state(page)).writes,0);assert.match(await page.text('#rule-probe'),/资源名称不能为空/);assert.ok(await page.count('#rule-probe [aria-invalid=true]')>0);
  await field(page,'资源名称','PATCH /orders');await field(page,'单机阈值','5');await action(page,'save');await wait(page,`state.operation==='success'`);assert.equal((await state(page)).lastCandidate.rules[2].recordId,null);assert.ok(!JSON.stringify((await state(page)).lastCandidate).includes('local-form-'));
  for(const id of ['rule-one','rule-two','assigned-rule-2']){await page.click(`#rule-probe [data-rule-record=${id}]`);await action(page,'remove');await dialogAction(page,'确认继续');await page.waitFor(`!document.querySelector('#rule-probe dialog[open]')`);}
  assert.equal((await state(page)).ruleCount,0);assert.deepEqual(JSON.parse(await page.text('#rule-probe [data-rule-full-preview]')),[]);assert.match(await page.text('#rule-probe'),/发布会清空/);await action(page,'save');await wait(page,`state.writes===2&&state.operation==='success'`);assert.deepEqual((await state(page)).lastCandidate.rules,[]);
}));
test('RULE-WORKSPACE rendered: conflict preserves inputs; unknown command is single-flight and original pending/not-found lookup cannot unlock',async()=>withPage(async page=>{
  await action(page,'begin');await field(page,'单机阈值','35');await mode(page,'conflict');await action(page,'save');await wait(page,`state.operation==='conflict'`);assert.equal((await state(page)).ruleValue.count,35);await mode(page,'unknown');await action(page,'save');await wait(page,`state.operation==='result-unknown'`);assert.equal((await state(page)).writes,2);assert.equal(await page.eval(`document.querySelector('#rule-probe [data-rule-action=save]').disabled`),true);assert.doesNotMatch(await page.text('#rule-probe'),/PRIVATE-RULE/);
  let lookups=0;for(const value of ['pending','not-found']) {await page.click(`#rule-probe [data-rule-lookup=${value}]`);await page.clickByText('检查执行结果','#rule-probe [data-command-state] button');await wait(page,`state.operation==='result-unknown'&&!state.inspecting&&state.lookups===${++lookups}`);assert.equal((await state(page)).writes,2);}
  await page.click('#rule-probe [data-rule-lookup=completed]');await page.clickByText('检查执行结果','#rule-probe [data-command-state] button');await wait(page,`state.operation==='success'&&!state.dirty`);assert.equal((await state(page)).writes,2);assert.equal((await state(page)).savedIdentity.id,'persisted-draft');
}));
test('RULE-WORKSPACE rendered: editing cancels late validation, unsupported target never enables freeze; no modal can trap unknown operation',async()=>withPage(async page=>{
  await action(page,'begin');await action(page,'save');await wait(page,`state.operation==='success'`);await mode(page,'held-validation');await action(page,'validate');await wait(page,`state.validation==='loading'`);await field(page,'单机阈值','31');await wait(page,`state.ruleValue.count===31&&state.validation==='idle'`);assert.ok((await state(page)).aborts>0);await page.click('#rule-probe [data-rule-validation-release]');await wait(page,`state.validation==='idle'`);
  await mode(page,'success');await action(page,'save');await wait(page,`state.operation==='success'&&!state.dirty`);await mode(page,'unsupported');await action(page,'validate');await wait(page,`state.validation==='partial'`);assert.equal(await page.eval(`document.querySelector('#rule-probe [data-rule-action=freeze]').disabled`),true);
  await mode(page,'success');await action(page,'validate');await wait(page,`state.validation==='ready'`);await action(page,'freeze');await field(page,'版本名称','Frozen','#rule-probe dialog[open]');await modeViaScript(page,'unknown');await dialogAction(page,'固化不可变版本');await wait(page,`state.operation==='result-unknown'`);assert.equal(await page.count('#rule-probe dialog[open]'),1);await dialogAction(page,'检查执行结果');await page.waitFor(`!document.querySelector('#rule-probe dialog[open]')`);assert.equal((await state(page)).writes,3);
}));
async function modeViaScript(page,value){await page.eval(`document.querySelector('#rule-probe [data-rule-mode=${value}]').click()`);}
test('RULE-WORKSPACE rendered: source refresh retains dirty baseline; discard is explicit and permission revocation clears pending dialog intents',async()=>withPage(async page=>{
  await action(page,'begin');await field(page,'单机阈值','32');await page.click('#rule-probe [data-rule-source-change]');await page.clickByText('刷新权威快照','#rule-probe button');await wait(page,`state.sourceVersion==='external-version'`);assert.equal((await state(page)).editingVersion,'version-one');assert.equal((await state(page)).ruleValue.count,32);await action(page,'restart');await dialogAction(page,'取消并保留编辑');assert.equal((await state(page)).ruleValue.count,32);await action(page,'restart');await dialogAction(page,'确认继续');await page.waitFor(`!document.querySelector('#rule-probe dialog[open]')`);assert.equal((await state(page)).editingVersion,'external-version');assert.equal((await state(page)).ruleValue.count,999);
  await action(page,'close');await page.eval(`document.querySelector('#rule-probe [data-rule-revoke]').click()`);await wait(page,`!state.authorized`);assert.equal(await page.count('#rule-probe dialog[open]'),0);assert.equal(await page.count('#rule-probe .rule-form'),0);await page.click('#rule-probe [data-rule-grant]');await wait(page,`state.authorized`);assert.equal(await page.count('#rule-probe dialog[open]'),0);assert.equal((await state(page)).ruleCount,undefined);
}));
test('RULE-WORKSPACE rendered: numeric blur invalidates a saved validation before freeze can use the old ticket',async()=>withPage(async page=>{
  await action(page,'begin');await action(page,'save');await wait(page,`state.operation==='success'`);await action(page,'validate');await wait(page,`state.validation==='ready'`);
  await field(page,'单机阈值','33','#rule-probe',false);await action(page,'freeze');await wait(page,`state.ruleValue.count===33&&state.dirty&&state.validation==='idle'`);
  assert.equal((await state(page)).writes,1);assert.equal(await page.count('#rule-probe dialog[open]'),0);assert.equal(await page.eval(`document.querySelector('#rule-probe [data-rule-action=freeze]').disabled`),true);
}));
test('F5.2 rendered: changing locale preserves a dirty draft and URL, and only the later save writes unchanged protocol values',async()=>withPage(async page=>{
  await action(page,'begin');await field(page,'单机阈值','37');
  const originalUrl=await page.eval('location.href');
  const original=(await state(page));
  assert.equal(original.dirty,true);assert.equal(original.ruleValue.count,37);assert.equal(original.writes,0);
  const translations={'zh-CN':'界面语言','en-US':'Language','ja-JP':'表示言語'};
  for(const locale of ['zh-CN','en-US','ja-JP']) {
    await page.eval(`(async()=>{const [{changeLocale},{writeStoredLocale},{default:i18n}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts'),import('/src/app/i18n/config.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);if((i18n.resolvedLanguage??i18n.language)!==${JSON.stringify(locale)})throw new Error('locale was not applied');if(i18n.t('shell.language')!==${JSON.stringify(translations[locale])})throw new Error('locale catalog was not rendered');if(localStorage.getItem('sentinel.locale')!==${JSON.stringify(locale)})throw new Error('locale preference was not persisted');})()`);
    const current=await state(page);
    assert.equal(await page.eval('location.href'),originalUrl);
    assert.equal(current.dirty,true);assert.equal(current.ruleValue.count,37);assert.equal(current.writes,0);
    assert.equal(current.lastCandidate,null);
  }
  await action(page,'save');await wait(page,`state.operation==='success'&&!state.dirty`);
  const saved=await state(page);assert.equal(saved.writes,1);assert.equal(saved.lastCandidate.bindingId,'binding-one');
  assert.equal(saved.lastCandidate.profile,'test-profile');assert.equal(saved.lastCandidate.baseChecksum,'server-checksum-one');
  assert.equal(saved.lastCandidate.rules[0].rule.value.count,37);
  assert.equal(await page.eval('location.href'),originalUrl);
}));
test('RULE-WORKSPACE rendered: desktop and Japanese 320px full editor retains aligned fields, readable actions and bounded JSON',async()=>withPage(async page=>{
  await action(page,'begin');await page.send('Emulation.setDeviceMetricsOverride',{width:320,height:950,deviceScaleFactor:1,mobile:false});await page.eval(`(async()=>{const {default:i18n}=await import('/src/app/i18n/config.ts');await i18n.changeLanguage('ja-JP');await Promise.all(document.getAnimations().filter(a=>a.playState==='running'&&Number.isFinite(a.effect?.getTiming().iterations)).map(a=>a.finished.catch(()=>{})));})()`);assert.ok(await page.eval(`document.documentElement.scrollWidth<=321`));assert.doesNotMatch(await page.text('#rule-probe'),/rules\.workspace\./);
  const directory=artifactDirectory('sentinel-f4-rules-20261007');mkdirSync(directory,{recursive:true});
  await page.eval(`document.querySelector('#rule-probe .rule-form').scrollIntoView({block:'start',behavior:'instant'})`);await page.waitFor(`document.querySelector('#rule-probe .rule-form').getBoundingClientRect().top>=-1&&document.querySelector('#rule-probe .rule-form').getBoundingClientRect().top<100`);writeFileSync(`${directory}/rule-editor-narrow-ja.png`,await page.screenshot());
  await page.send('Emulation.setDeviceMetricsOverride',{width:1280,height:1300,deviceScaleFactor:1,mobile:false});await page.eval(`(async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);document.querySelector('#rule-probe [data-ruleset-editor]').scrollIntoView({block:'start',behavior:'instant'});})()`);await page.waitFor(`(()=>{const rect=document.querySelector('#rule-probe .rule-form').getBoundingClientRect();return rect.top>=0&&rect.top<innerHeight-150;})()`);writeFileSync(`${directory}/rule-editor-desktop-ja.png`,await page.screenshot());
}));
import {artifactDirectory} from './artifacts.mjs';
