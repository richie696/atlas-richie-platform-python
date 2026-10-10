import {before,after,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {E2E_BASE_URL,launchBrowser} from './cdp.mjs';
let browser;before(async()=>{browser=await launchBrowser();});after(async()=>{await browser?.close();});
async function withPage(run){const page=await browser.newPage();try{
  await page.clearStorage(new URL(E2E_BASE_URL).origin);await page.goto(`${E2E_BASE_URL}/#/login`);await page.waitFor(`!!document.querySelector('.app-shell')`);
  await page.eval(`(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {PasswordProbe}=await import('/tests/e2e/probes/PasswordProbe.tsx');document.getElementById('root').style.display='none';const host=document.createElement('section');host.id='password-probe';document.body.append(host);const root=createRoot(host,{identifierPrefix:'password-probe-'});root.render(React.createElement(React.StrictMode,null,React.createElement(PasswordProbe)));window.__passwordCleanup=()=>{root.unmount();host.remove();};})()`);
  await page.waitFor(`!!document.querySelector('#password-probe [data-own-password]')`);await run(page);assert.deepEqual(page.consoleErrors,[]);await page.eval('window.__passwordCleanup()');
}finally{await page.close();}}
const status=(page,value)=>page.waitFor(`document.querySelector('#password-probe [data-password-summary]').textContent.includes(${JSON.stringify('"status":"'+value+'"')})`);
const summary=page=>page.eval(`JSON.parse(document.querySelector('#password-probe [data-password-summary]').textContent)`);
async function input(page,label,value){const id=await page.eval(`[...document.querySelectorAll('#password-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`);await page.click('#'+id.replace(/[^a-zA-Z0-9_-]/g,x=>'\\'+x));await page.eval('document.activeElement.select()');await page.send('Input.insertText',{text:value});await page.waitFor(`document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`);}
const submit=page=>page.clickByText('保存新密码','#password-probe button');
async function fill(page){await input(page,'当前密码','Synthetic-Current-Password');await input(page,'新密码','Synthetic-New-Password');await input(page,'确认新密码','Synthetic-New-Password');}
test('PASSWORD rendered: 当前会话本人目标、必填、已知拒绝保留输入并区分三类错误',async()=>withPage(async page=>{
  assert.match(await page.text('#password-probe'),/synthetic-viewer/);assert.doesNotMatch(await page.text('#password-probe'),/some-other-user/);
  await submit(page);await page.waitFor(`document.querySelector('#password-probe').textContent.includes('请输入当前密码')`);assert.equal((await summary(page)).calls,0);
  await fill(page);
  for(const [mode,text]of [['current','当前密码不正确'],['policy','新密码不符合'],['rate','请求过于频繁']]){
    await page.click(`#password-probe [data-mode="${mode}"]`);await submit(page);await status(page,'error');await page.waitFor(`document.querySelector('#password-probe').textContent.includes(${JSON.stringify(text)})`);
    assert.equal(await page.eval(`document.querySelector('#password-probe input[type=password]').value`),'Synthetic-Current-Password');
  }
  assert.equal((await summary(page)).calls,3);assert.doesNotMatch(await page.text('#password-probe'),/PRIVATE-PASSWORD-ERROR/);
}));
test('PASSWORD rendered: pending 禁重复，服务端确认后清空，只通知一次',async()=>withPage(async page=>{
  await fill(page);await page.click('#password-probe [data-hold]');await submit(page);await status(page,'pending');await submit(page);assert.equal((await summary(page)).confirmed,0);
  await page.click('#password-probe [data-release]');await status(page,'success');await page.waitFor(`document.querySelector('#password-probe [data-password-summary]').textContent.includes('"confirmed":1')`);
  assert.equal((await summary(page)).calls,1);assert.deepEqual(await page.eval(`[...document.querySelectorAll('#password-probe input[type=password]')].map(node=>node.value)`),['','','']);
}));
test('PASSWORD rendered: 超时未知不重放、不清空可核查输入，重新认证主动清理',async()=>withPage(async page=>{
  await fill(page);await page.click('#password-probe [data-mode=timeout]');await submit(page);await status(page,'result-unknown');await submit(page);assert.equal((await summary(page)).calls,1);
  const dir=artifactDirectory('sentinel-f4-password-20261007');mkdirSync(dir,{recursive:true});writeFileSync(`${dir}/unknown.png`,await page.screenshot());
  assert.doesNotMatch(await page.eval(`JSON.stringify({local:{...localStorage},session:{...sessionStorage},text:document.querySelector('#password-probe').textContent})`),/Synthetic-Current|Synthetic-New|PRIVATE-PASSWORD-ERROR/);
  await page.clickByText('重新登录核实','#password-probe button');await page.waitFor(`document.querySelector('#password-probe [data-password-summary]').textContent.includes('"reauthentications":1')`);assert.equal((await summary(page)).confirmed,0);
  assert.deepEqual(await page.eval(`[...document.querySelectorAll('#password-probe input[type=password]')].map(node=>node.value)`),['','','']);
}));
test('PASSWORD rendered: 提交期间会话过期，迟到确认不得授予成功',async()=>withPage(async page=>{
  await fill(page);await page.click('#password-probe [data-hold]');await submit(page);await status(page,'pending');await page.click('#password-probe [data-expire]');await status(page,'result-unknown');await page.click('#password-probe [data-release]');assert.equal((await summary(page)).confirmed,0);assert.equal((await summary(page)).calls,1);
}));
import {artifactDirectory} from './artifacts.mjs';
