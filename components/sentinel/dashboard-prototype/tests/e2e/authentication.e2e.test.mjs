import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { E2E_BASE_URL, launchBrowser } from './cdp.mjs';
let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });
async function withProbe(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/accounts`);
    await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
    await page.eval(`(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {AuthenticationProbe}=await import('/tests/e2e/probes/AuthenticationProbe.tsx');const host=document.createElement('section');host.id='authentication-probe';document.body.prepend(host);const root=createRoot(host);root.render(React.createElement(React.StrictMode,null,React.createElement(AuthenticationProbe)));window.__authenticationCleanup=()=>{root.unmount();host.remove();};})()`);
    await phase(page, '"decision":"login"');
    await page.type('#authentication-probe input', 'SYNTHETIC-SECRET');
    await run(page);
    await page.eval('window.__authenticationCleanup()');
    assert.deepEqual(page.consoleErrors, []);
  } finally { await page.close(); }
}
const click = (page, selector) => page.click(`#authentication-probe ${selector}`);
const phase = (page, part) => page.waitFor(`document.querySelector('#authentication-probe output')?.textContent.includes(${JSON.stringify(part)})`);
const history = page => page.eval(`JSON.parse(document.querySelector('#authentication-probe [data-auth-history]').textContent)`);
test('F2 authentication React: StrictMode 恢复、重复登录、回读未确认不放行、退出立即撤身份', async () => {
  await withProbe(async page => {
    await click(page, '[data-hold-login]'); await click(page, '[data-hold-session]');
    await click(page, '[data-login]'); await phase(page, '"phase":"authenticating"');
    await click(page, '[data-login]');
    await click(page, '[data-release-login]'); await phase(page, '"phase":"checking"');
    assert.equal((await history(page)).calls.filter(value => value === 'login').length, 1);
    await click(page, '[data-release-session]'); await phase(page, '"decision":"allow"');
    await click(page, '[data-hold-session]'); await click(page, '[data-logout]');
    await phase(page, '"phase":"checking"');
    await click(page, '[data-release-session]'); await phase(page, '"decision":"login"');
    const captured = await history(page);
    assert.equal(captured.calls.filter(value => value === 'logout').length, 1);
    assert.doesNotMatch(JSON.stringify(captured), /SYNTHETIC-SECRET|PRIVATE-TRANSPORT/);
  });
});
test('F2 authentication React: 超时未知不重放，只能显式调查当前会话', async () => {
  await withProbe(async page => {
    await click(page, '[data-fail-login]'); await click(page, '[data-login]');
    await phase(page, '"login":"result-unknown"');
    await click(page, '[data-login]');
    assert.equal((await history(page)).calls.filter(value => value === 'login').length, 1);
    await click(page, '[data-inspect]'); await phase(page, '"login":"idle"');
    await phase(page, '"decision":"login"');
    await click(page, '[data-expire]'); await phase(page, '"phase":"expired"');
    assert.doesNotMatch(await page.text('#authentication-probe'), /PRIVATE-TRANSPORT-ERROR/);
  });
});
