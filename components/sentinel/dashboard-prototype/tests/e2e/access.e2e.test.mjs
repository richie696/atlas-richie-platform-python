import {after,before,test} from 'node:test';
import assert from 'node:assert/strict';
import {E2E_BASE_URL,connectIabBrowser} from './cdp.mjs';
let browser;
before(async()=>{browser=await connectIabBrowser();});after(async()=>{await browser?.close();});
async function withProbe(run){
  const page=await browser.newPage();
  try{
    await page.clearStorage(new URL(E2E_BASE_URL).origin);await page.goto(`${new URL(E2E_BASE_URL).origin}/tests/e2e/probes/host.html`);await page.waitFor(`!!document.querySelector('#root')`);
    await page.eval(`(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {AccessProbe}=await import('/tests/e2e/probes/AccessProbe.tsx');const host=document.createElement('section');host.id='access-probe';document.body.prepend(host);const root=createRoot(host);root.render(React.createElement(React.StrictMode,null,React.createElement(AccessProbe)));window.__accessCleanup=()=>{root.unmount();host.remove();};})()`);
    await page.waitFor(`document.querySelector('#access-probe output')?.textContent.includes('"decision":"allow"')`);await run(page);await page.eval(`window.__accessCleanup()`);assert.deepEqual(page.consoleErrors,[]);
  }finally{await page.close();}
}
test('F2 bootstrap: 换身份首个 commit 不呈现旧管理员、匿名/初始化/断网不伪装成功',async()=>{
  await withProbe(async page=>{
    for(const [owner,decision] of [['view','denied'],['anonymous','login'],['uninitialized','setup'],['unavailable','unavailable'],['admin','allow']]){
      await page.click(`#access-probe [data-access-owner="${owner}"]`);
      await page.waitFor(`document.querySelector('#access-probe output').textContent.includes(${JSON.stringify(`"decision":"${decision}"`)})`);
    }
    const history=await page.eval(`JSON.parse(document.querySelector('#access-probe [data-access-history]').textContent)`);
    assert.ok(history.commits.every(commit=>commit.accountId===null||commit.accountId===commit.owner),JSON.stringify(history.commits));
    assert.equal(history.calls.filter(call=>call==='session:uninitialized'||call==='session:unavailable').length,0);
    assert.doesNotMatch(await page.text('#access-probe'),/PRIVATE-ERROR-NOT-UI/);
  });
});
test('F2 bootstrap: 刷新时撤掉准入，过期请求释放后也不重新授予管理员',async()=>{
  await withProbe(async page=>{
    await page.click('#access-probe [data-hold]');await page.click('#access-probe [data-refresh]');
    await page.waitFor(`document.querySelector('#access-probe output').textContent.includes('"decision":"wait"')`);
    await page.click('#access-probe [data-access-owner="anonymous"]');
    await page.click('#access-probe [data-release]');
    await page.waitFor(`document.querySelector('#access-probe output').textContent.includes('"decision":"login"')`);
    const history=await page.eval(`JSON.parse(document.querySelector('#access-probe [data-access-history]').textContent)`);
    assert.ok(history.commits.filter(commit=>commit.owner==='anonymous').every(commit=>commit.decision!=='allow'&&commit.accountId===null),JSON.stringify(history));
    assert.equal(history.calls.filter(call=>call==='session:admin').length,1);
  });
});
