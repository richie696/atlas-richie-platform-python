import { before, after, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { E2E_BASE_URL, launchBrowser } from "./cdp.mjs";
let browser;
before(async () => {
  browser = await launchBrowser();
});
after(async () => {
  await browser?.close();
});
async function withPage(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/login`);
    await page.waitFor(`!!document.querySelector('.app-shell')`);
    await page.eval(
      `(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {SystemObservationProbe,createSystemObservationTopology}=await import('/tests/e2e/probes/SystemObservationProbe.tsx');document.getElementById('root').style.display='none';const host=document.createElement('section');host.id='system-probe';document.body.append(host);const topology=createSystemObservationTopology(),root=createRoot(host,{identifierPrefix:'system-probe-'});root.render(React.createElement(React.StrictMode,null,React.createElement(SystemObservationProbe,{topology})));window.__systemCleanup=()=>{root.unmount();topology.dispose();host.remove();};})()`,
    );
    await wait(
      page,
      `state.connections==='partial'&&state.protocols==='partial'&&state.audit==='ready'`,
    );
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__systemCleanup()");
  } finally {
    await page.close();
  }
}
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#system-probe [data-system-summary]').textContent)`,
  );
test("SYSTEM permissions rendered: current session facts are readonly, view has no write grant and expiry removes all identity facts", async () => withPage(async (page) => {
  assert.match(await page.text('#system-probe [data-session-permissions]'), /system-admin/);
  assert.match(await page.text('#system-probe [data-session-capability="rules:write"]'), /已授予/);
  assert.equal(await page.count('#system-probe [data-session-permissions] input,#system-probe [data-session-permissions] button'),0);
  await page.click('#system-probe [data-session-view]');
  await page.waitFor(`document.querySelector('#system-probe [data-session-permissions]').textContent.includes('system-view')`);
  assert.match(await page.text('#system-probe [data-session-capability="rules:write"]'), /未授予/);
  assert.match(await page.text('#system-probe [data-session-capability="metrics:view"]'), /已授予/);
  await page.click('#system-probe [data-session-expire]');
  await page.waitFor(`!document.querySelector('#system-probe [data-session-permissions]')`);
  assert.doesNotMatch(await page.text('#system-probe'),/system-admin|system-view|account-view-test/);
}));
const wait = (page, predicate) =>
  page.waitFor(
    `(()=>{const state=JSON.parse(document.querySelector('#system-probe [data-system-summary]')?.textContent??'{}');return ${predicate};})()`,
  );
async function field(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('#system-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.eval(`document.getElementById(${JSON.stringify(id)}).select()`);
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
test("SYSTEM rendered: independent probe failures, expired/absent observations and supported versus negotiated versions stay distinguishable", async () =>
  withPage(async (page) => {
    assert.match(
      await page.text("#system-probe [data-system-connection=config-nacos]"),
      /探测成功/,
    );
    assert.match(
      await page.text("#system-probe [data-system-connection=config-consul]"),
      /已经过期/,
    );
    assert.match(await page.text("#system-probe [data-system-connection=collector]"), /尚未配置/);
    assert.match(await page.text("#system-probe [data-system-protocol=agent-reporting]"), /V2/);
    assert.match(
      await page.text("#system-probe [data-system-protocol=agent-reporting]"),
      /版本不兼容/,
    );
    assert.match(await page.text("#system-probe [data-system-protocol=cluster-token]"), /尚无观测/);
    await page.click("#system-probe [data-system-offline]");
    await page.clickByText("刷新连接探测", "#system-probe button");
    await wait(page, `state.connections==='stale'`);
    assert.equal((await summary(page)).protocols, "partial");
    assert.equal((await summary(page)).audit, "ready");
    assert.doesNotMatch(await page.text("#system-probe"), /PRIVATE-CONNECTION/);
    await page.click("#system-probe [data-system-online]");
    await page.clickByText("刷新连接探测", "#system-probe button");
    await wait(page, `state.connections==='partial'`);
  }));
test("AUDIT rendered: explicit filtered paging and publication identity never borrow chart scope or optimistic mutation facts", async () =>
  withPage(async (page) => {
    await page.clickByText("查看关联发布", "#system-probe button");
    assert.equal((await summary(page)).selected.publicationId, "publication-one");
    assert.equal((await summary(page)).selected.bindingId, "binding-one");
    await page.click("#system-probe [data-audit-next]");
    await wait(page, `state.query.page===2&&state.audit==='ready'`);
    assert.equal(await page.count("#system-probe [data-system-audit=audit-account]"), 1);
    assert.equal(await page.count("#system-probe [data-system-audit=audit-publish]"), 0);
    await field(page, "操作账号标识", "admin-two");
    await page.clickByText("应用审计筛选", "#system-probe button");
    await wait(
      page,
      `state.query.actorId==='admin-two'&&state.query.page===1&&state.audit==='ready'`,
    );
    assert.equal(
      await page.eval(`document.querySelector('#system-probe [data-audit-next]').disabled`),
      true,
    );
    await field(page, "操作账号标识", "absent");
    await page.clickByText("应用审计筛选", "#system-probe button");
    await wait(page, `state.audit==='filtered-empty'`);
    assert.equal(await page.count("#system-probe [data-system-audit]"), 0);
    assert.match(await page.text("#system-probe"), /0 条符合条件/);
  }));
test("AUDIT rendered: invalid calendar/range is editable but cannot dispatch or replace the active UTC query", async () =>
  withPage(async (page) => {
    const before = await summary(page);
    await field(page, "开始时间（UTC）", "2026-02-30T12:00");
    await page.clickByText("应用审计筛选", "#system-probe button");
    assert.match(await page.text("#system-probe"), /审计筛选无效/);
    assert.deepEqual((await summary(page)).query, before.query);
    assert.equal((await summary(page)).counts.audit, before.counts.audit);
    assert.equal(await page.count("#system-probe [data-system-audit=audit-publish]"), 1);
    await field(page, "开始时间（UTC）", "2026-10-07T11:00");
    await field(page, "结束时间（UTC，不含）", "2026-12-07T12:00");
    await page.clickByText("应用审计筛选", "#system-probe button");
    assert.equal((await summary(page)).counts.audit, before.counts.audit);
  }));
test("SYSTEM rendered: first permission notification hides privileged facts; ignored late protocol response cannot repopulate revoked data", async () =>
  withPage(async (page) => {
    await page.click("#system-probe [data-system-deny-audit]");
    await wait(page, `state.audit==='denied'`);
    assert.equal(await page.count("#system-probe [data-system-audit]"), 0);
    assert.equal(await page.count("#system-probe form"), 0);
    const before = (await summary(page)).counts.audit;
    await page.clickByText("刷新审计记录", "#system-probe button");
    assert.equal((await summary(page)).counts.audit, before);
    await page.click("#system-probe [data-system-hold]");
    await page.clickByText("刷新协议状态", "#system-probe button");
    await wait(page, `state.protocols==='refreshing'`);
    await page.click("#system-probe [data-system-deny]");
    await wait(
      page,
      `state.protocols==='denied'&&state.connections==='denied'&&state.counts.aborts>0`,
    );
    await page.click("#system-probe [data-system-release]");
    assert.equal(await page.count("#system-probe [data-system-protocol]"), 0);
    assert.equal(await page.count("#system-probe [data-system-connection]"), 0);
  }));
test("SYSTEM rendered: Japanese narrow filters stay visible and UTC audit/probe tables retain their own scroll regions", async () =>
  withPage(async (page) => {
    await page.eval(
      `(async()=>{const {default:i18n}=await import('/src/app/i18n/config.ts');await i18n.changeLanguage('ja-JP');})()`,
    );
    const dir = artifactDirectory("sentinel-f4-system-20261007");
    mkdirSync(dir, { recursive: true });
    for (const [name, width, height] of [
      ["desktop-ja", 1280, 1100],
      ["narrow-ja", 320, 1100],
    ]) {
      await page.send("Emulation.setDeviceMetricsOverride", {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await page.eval(
        `(async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);document.querySelector('#system-probe form').scrollIntoView({block:'start',behavior:'instant'});})()`,
      );
      assert.ok(await page.eval("document.documentElement.scrollWidth<=innerWidth+1"));
      assert.ok(
        await page.eval(
          `(()=>{const root=document.querySelector('#system-probe');return [...root.querySelectorAll('form input')].filter(node=>node.offsetParent).every(node=>{const r=node.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1;});})()`,
        ),
      );
      assert.doesNotMatch(await page.text("#system-probe"), /system\.(observed|audit)\./);
      writeFileSync(`${dir}/${name}.png`, await page.screenshot());
    }
  }));
import {artifactDirectory} from './artifacts.mjs';
