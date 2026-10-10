import {before,after,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {E2E_BASE_URL,launchBrowser} from './cdp.mjs';
let browser;before(async()=>{browser=await launchBrowser();});after(async()=>{await browser?.close();});
async function withPage(run,options={}){const page=await browser.newPage();try{
  await page.clearStorage(new URL(E2E_BASE_URL).origin);await page.goto(`${E2E_BASE_URL}/#/login`);await page.waitFor(`!!document.querySelector('.app-shell')`);
  await page.eval(`(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {AccountManagementProbe}=await import('/tests/e2e/probes/AccountManagementProbe.tsx');document.getElementById('root').style.display='none';const host=document.createElement('section');host.id='management-probe';document.body.append(host);const root=createRoot(host,{identifierPrefix:'management-probe-'});root.render(React.createElement(React.StrictMode,null,React.createElement(AccountManagementProbe,${JSON.stringify(options)})));window.__managementCleanup=()=>{root.unmount();host.remove();};})()`);
  await page.waitFor(`!!document.querySelector('#management-probe [data-management-summary]')`);await run(page);assert.deepEqual(page.consoleErrors,[]);await page.eval('window.__managementCleanup()');
}finally{await page.close();}}
const summary=page=>page.eval(`JSON.parse(document.querySelector('#management-probe [data-management-summary]').textContent)`);
const status=(page,value)=>page.waitFor(`document.querySelector('#management-probe [data-management-summary]').textContent.includes(${JSON.stringify('"mutation":"'+value+'"')})`);
async function input(page,label,value){const id=await page.eval(`[...document.querySelectorAll('#management-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`);await page.click('#'+id.replace(/[^a-zA-Z0-9_-]/g,x=>'\\'+x));await page.eval('document.activeElement.select()');await page.send('Input.insertText',{text:value});await page.waitFor(`document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`);}
const click=(page,text)=>page.clickByText(text,'#management-probe button');
// Port controls are test seams, not user actions. Native modal inertness must not block arranging responses.
const control=(page,attribute)=>page.eval(`document.querySelector('#management-probe [data-${attribute}]').click()`);
const settleAnimations=page=>page.eval(`(async()=>{await Promise.all(document.getAnimations().filter(animation=>animation.playState==='running'&&Number.isFinite(animation.effect?.getTiming().iterations)).map(animation=>animation.finished.catch(()=>{})));})()`);
async function openCreate(page){await page.waitFor(`!!document.querySelector('#management-probe [data-account-id]')`);await click(page,'新增账号');await page.waitFor(`!!document.querySelector('#management-probe dialog[open]')`);}
async function fillCreate(page){await input(page,'账号名','synthetic-new');await input(page,'密码','Synthetic-Create-Password');}
test('ACCOUNT rendered: 新增仅三个字段、已知重名留在弹窗、pending 单次、确认后清空且列表刷新',async()=>withPage(async page=>{
  await openCreate(page);assert.equal(await page.eval(`document.querySelectorAll('#management-probe dialog input').length`),2);assert.doesNotMatch(await page.text('#management-probe dialog'),/确认密码|显示名称/);
  await click(page,'创建账号');assert.equal((await summary(page)).writes,0);await fillCreate(page);await control(page,'mode=duplicate');await click(page,'创建账号');await status(page,'conflict');
  assert.equal(await page.eval(`document.querySelector('#management-probe dialog input[type=password]').value`),'Synthetic-Create-Password');assert.match(await page.text('#management-probe dialog'),/账号名已被使用/);
  await control(page,'mode=success');await control(page,'hold');await click(page,'创建账号');await status(page,'pending');await click(page,'创建账号');await page.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await page.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});assert.equal(await page.eval(`!!document.querySelector('#management-probe dialog[open]')`),true);
  await control(page,'release');await status(page,'success');await page.waitFor(`!document.querySelector('#management-probe dialog[open]')`);assert.equal((await summary(page)).writes,2);assert.equal((await summary(page)).records,4);
  await openCreate(page);assert.deepEqual(await page.eval(`[...document.querySelectorAll('#management-probe dialog input')].map(node=>node.value)`),['','']);
  await settleAnimations(page);const dir=artifactDirectory('sentinel-f4-management-20261007');mkdirSync(dir,{recursive:true});writeFileSync(`${dir}/create.png`,await page.screenshot());
}));
test('ACCOUNT rendered: unknown 不关闭/不重放，核查原操作后关闭；只读角色立即清理管理数据',async()=>withPage(async page=>{
  await openCreate(page);await fillCreate(page);await control(page,'mode=timeout');await click(page,'创建账号');await status(page,'result-unknown');await click(page,'创建账号');assert.equal((await summary(page)).writes,1);
  await click(page,'检查执行结果');await status(page,'success');await page.waitFor(`!document.querySelector('#management-probe dialog[open]')`);assert.equal((await summary(page)).lookups,1);
  assert.doesNotMatch(await page.eval(`JSON.stringify({local:{...localStorage},session:{...sessionStorage},text:document.querySelector('#management-probe').textContent})`),/Synthetic-Create-Password|PRIVATE-ACCOUNT-PASSWORD/);
  await control(page,'reader');await page.waitFor(`!document.querySelector('#management-probe table')`);assert.match(await page.text('#management-probe'),/只有当前管理员/);
}));
test('ACCOUNT rendered: 分页/筛选是真查询、启停需要确认、内置管理员禁停',async()=>withPage(async page=>{
  await page.waitFor(`!!document.querySelector('#management-probe tr[data-account-id=builtin]')`);assert.equal(await page.eval(`[...document.querySelectorAll('#management-probe tr[data-account-id=builtin] button')].find(button=>button.textContent==='停用').disabled`),true);
  await click(page,'下一页');await page.waitFor(`!!document.querySelector('#management-probe tr[data-account-id=two]')`);assert.equal(await page.eval(`!!document.querySelector('#management-probe tr[data-account-id=one]')`),false);
  await input(page,'账号名筛选','reader-one');await click(page,'查询');await page.waitFor(`!!document.querySelector('#management-probe tr[data-account-id=one]')`);
  await page.click('#management-probe tr[data-account-id=one] button:nth-child(2)');await page.waitFor(`!!document.querySelector('#management-probe dialog[open]')`);assert.equal((await summary(page)).writes,0);
  await click(page,'取消');assert.equal((await summary(page)).writes,0);await page.click('#management-probe tr[data-account-id=one] button:nth-child(2)');await click(page,'确认变更');await status(page,'success');await page.waitFor(`document.querySelector('#management-probe tr[data-account-id=one]').textContent.includes('已停用')`);assert.equal((await summary(page)).writes,1);
}));
test('ROLE rendered: radio 只改本地草稿，取消恢复，冲突保留，读取最新后显式保存',async()=>withPage(async page=>{
  await page.waitFor(`!!document.querySelector('#management-probe [data-role-editor]')`);await page.click('#management-probe input[type=radio][value=admin]');assert.equal((await summary(page)).writes,0);await click(page,'放弃修改');assert.equal(await page.eval(`document.querySelector('#management-probe input[type=radio][value=view]').checked`),true);
  await page.click('#management-probe input[type=radio][value=admin]');await page.click('#management-probe [data-external-revision]');await page.waitFor(`document.querySelector('#management-probe').textContent.includes('账号已被其他操作修改')`);await click(page,'保存角色');await status(page,'conflict');assert.equal((await summary(page)).writes,0);assert.equal(await page.eval(`document.querySelector('#management-probe input[type=radio][value=admin]').checked`),true);
  await click(page,'读取最新版本');await page.waitFor(`document.querySelector('#management-probe input[type=radio][value=view]').checked`);await page.click('#management-probe input[type=radio][value=admin]');await click(page,'保存角色');await status(page,'success');assert.equal((await summary(page)).roles.find(record=>record.id==='one').roleId,'admin');assert.equal((await summary(page)).writes,1);
  const dir=artifactDirectory('sentinel-f4-management-20261007');mkdirSync(dir,{recursive:true});writeFileSync(`${dir}/role.png`,await page.screenshot());
},{initialPage:'roles'}));
test('ROLE rendered: 未保存切账号确认、无效目标不回落，unknown 禁换目标直到核查完成',async()=>withPage(async page=>{
  await page.waitFor(`!!document.querySelector('#management-probe [data-role-editor]')`);await page.click('#management-probe input[type=radio][value=admin]');
  const selector=await page.eval(`document.querySelector('#management-probe [role=combobox]').id`);await page.click('#'+selector.replace(/[^a-zA-Z0-9_-]/g,x=>'\\'+x));await page.waitFor(`!!document.querySelector('#management-probe [role=option]')`);await page.clickByText('reader-two','[role=option]');await page.waitFor(`!!document.querySelector('#management-probe dialog[open]')`);assert.equal((await summary(page)).accountId,'one');await click(page,'继续编辑');assert.equal((await summary(page)).writes,0);
  await control(page,'mode=timeout');await click(page,'保存角色');await status(page,'result-unknown');await click(page,'保存角色');assert.equal((await summary(page)).writes,1);await click(page,'检查执行结果');await status(page,'success');
  await page.click('#management-probe [data-missing]');await page.waitFor(`!document.querySelector('#management-probe [data-role-editor]')`);assert.match(await page.text('#management-probe'),/未找到账号/);
},{initialPage:'roles'}));
import {artifactDirectory} from './artifacts.mjs';
