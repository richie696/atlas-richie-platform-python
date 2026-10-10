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
      `(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {FleetObservationProbe,createFleetProbeTopology}=await import('/tests/e2e/probes/FleetObservationProbe.tsx');document.getElementById('root').style.display='none';const host=document.createElement('section');host.id='fleet-probe';document.body.append(host);const topology=createFleetProbeTopology(),root=createRoot(host,{identifierPrefix:'fleet-probe-'});root.render(React.createElement(React.StrictMode,null,React.createElement(FleetObservationProbe,{topology})));window.__fleetCleanup=()=>{root.unmount();topology.dispose();host.remove();};})()`,
    );
    await page.waitFor(`!!document.querySelector('#fleet-probe [data-fleet-application]')`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__fleetCleanup()");
  } finally {
    await page.close();
  }
}
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#fleet-probe [data-fleet-probe-summary]').textContent)`,
  );
const click = (page, text) => page.clickByText(text, "#fleet-probe button");
test("FLEET rendered: unknown inventory preserves measurements without manufacturing a complete denominator", async () =>
  withPage(async (page) => {
    assert.match(
      await page.text("#fleet-probe [data-metric-card=http_qps]"),
      /实例目录来源：synthetic-inventory/,
    );
    await page.click("#fleet-probe [data-fleet-inventory-unknown]");
    await click(page, "刷新数据");
    await state(page, "partial");
    const card = await page.text("#fleet-probe [data-metric-card=http_qps]");
    assert.match(card, /189/);
    assert.match(card, /已上报 3；实例总数未知/);
    assert.doesNotMatch(card, /采样覆盖|test-inventory/);
    assert.match(
      await page.text("#fleet-probe tr[data-fleet-application=app-one]"),
      /已上报 1；实例总数未知/,
    );
    await page.eval(
      `(async()=>{const {default:i18n}=await import('/src/app/i18n/config.ts');await i18n.changeLanguage('en-US');})()`,
    );
    await page.waitFor(
      `document.querySelector('#fleet-probe [data-metric-card=http_qps]').textContent.includes('total instance count unknown')`,
    );
    assert.doesNotMatch(
      await page.text("#fleet-probe"),
      /observation\.coverageUnknown|observation\.inventorySource/,
    );
  }));
const state = (page, status) =>
  page.waitFor(
    `JSON.parse(document.querySelector('#fleet-probe [data-fleet-probe-summary]').textContent).status===${JSON.stringify(status)}`,
  );
async function textInput(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('#fleet-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.eval("document.activeElement.select()");
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
async function select(page, label, value) {
  const selector = await page.eval(
    `[...document.querySelectorAll('#fleet-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + selector.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.waitFor(
    `[...document.querySelectorAll('[role=option]')].some(node=>node.textContent.trim()===${JSON.stringify(value)}&&node.getBoundingClientRect().width>0&&node.getBoundingClientRect().height>0)`,
  );
  const index = await page.eval(
    `[...document.querySelectorAll('[role=option]')].findIndex(node=>node.textContent.trim()===${JSON.stringify(value)}&&node.getBoundingClientRect().width>0&&node.getBoundingClientRect().height>0)`,
  );
  await page.click("[role=option]", { index });
}
test("FLEET rendered: totals/pagination/filter are real queries, missing TPS is unavailable and ratios convert once", async () =>
  withPage(async (page) => {
    assert.match(await page.text("#fleet-probe"), /已登记应用 3 · 需关注 1/);
    assert.equal(await page.count("#fleet-probe tr[data-fleet-application]"), 2);
    assert.match(await page.text("#fleet-probe [data-metric-card=tps]"), /尚未接入/);
    assert.doesNotMatch(await page.text("#fleet-probe [data-metric-card=tps]"), /0txn/);
    assert.match(await page.text("#fleet-probe [data-metric-card=cpu_ratio]"), /25%/);
    await click(page, "下一页");
    await page.waitFor(
      `!!document.querySelector('#fleet-probe tr[data-fleet-application=app-three]')`,
    );
    assert.match(await page.text("#fleet-probe"), /全范围 3 个/);
    await textInput(page, "应用名称筛选", "app-one");
    await click(page, "查询");
    await page.waitFor(
      `document.querySelectorAll('#fleet-probe tr[data-fleet-application]').length===1`,
    );
    assert.match(await page.text("#fleet-probe"), /已筛选 1 个 · 全范围 3 个/);
    await select(page, "应用", "app-two");
    await page.waitFor(
      `JSON.parse(document.querySelector('#fleet-probe [data-fleet-probe-summary]').textContent).query.context.appId==='app-two'`,
    );
    await textInput(page, "应用名称筛选", "");
    await click(page, "查询");
    await page.waitFor(
      `!!document.querySelector('#fleet-probe tr[data-fleet-application=app-two]')`,
    );
    assert.match(await page.text("#fleet-probe [data-metric-card=http_qps]"), /84/);
    assert.equal(await page.count("#fleet-probe tr[data-fleet-application=app-one]"), 0);
  }));
test("FLEET rendered: stale refresh retains labeled trusted data, wrong context never renders and revoke drops cards", async () =>
  withPage(async (page) => {
    await page.click("#fleet-probe [data-fleet-mode=offline]");
    await click(page, "刷新数据");
    await state(page, "stale");
    assert.match(await page.text("#fleet-probe"), /并非最新状态/);
    assert.ok((await page.count("#fleet-probe [data-metric-card]")) > 0);
    assert.doesNotMatch(await page.text("#fleet-probe"), /PRIVATE-FLEET-ERROR/);
    await page.click("#fleet-probe [data-fleet-mode=success]");
    await click(page, "重试读取");
    await state(page, "partial");
    await page.click("#fleet-probe [data-fleet-mode=wrong]");
    await page.click("#fleet-probe [data-fleet-env]");
    await state(page, "error");
    assert.equal(await page.count("#fleet-probe [data-metric-card]"), 0);
    await page.click("#fleet-probe [data-fleet-mode=success]");
    await click(page, "重试读取");
    await state(page, "partial");
    await page.click("#fleet-probe [data-fleet-revoke]");
    await state(page, "denied");
    assert.equal(await page.count("#fleet-probe [data-metric-card]"), 0);
    assert.match(await page.text("#fleet-probe"), /没有查看该数据的权限/);
  }));
test("FLEET rendered: changed owner query aborts pending read, no old values paired with new environment; missing target stays empty", async () =>
  withPage(async (page) => {
    await page.click("#fleet-probe [data-fleet-mode=held]");
    await click(page, "刷新数据");
    await state(page, "refreshing");
    await page.click("#fleet-probe [data-fleet-env]");
    await state(page, "loading");
    assert.equal(await page.count("#fleet-probe [data-metric-card]"), 0);
    assert.ok((await summary(page)).aborts >= 1);
    await page.click("#fleet-probe [data-fleet-release]");
    await state(page, "partial");
    assert.match((await summary(page)).key, /other-env/);
    await page.click("#fleet-probe [data-fleet-mode=success]");
    await page.click("#fleet-probe [data-fleet-missing]");
    await state(page, "empty");
    assert.equal(await page.count("#fleet-probe tr[data-fleet-application]"), 0);
    assert.equal(await page.count("#fleet-probe [data-metric-card]"), 0);
  }));
test("FLEET rendered: exact-window drill-down, between-sample publication marker and Japanese 320px layout", async () =>
  withPage(async (page) => {
    await click(page, "查看需关注应用");
    const first = (await summary(page)).navigation;
    assert.equal(first.route, "applications");
    assert.equal(first.context.appId, "app-one");
    assert.equal(first.context.from, "2026-10-06T23:55:00.000Z");
    assert.equal(first.context.to, "2026-10-07T00:10:00.000Z");
    await page.waitFor(
      `[...document.querySelectorAll('#fleet-probe svg text')].some(node=>node.textContent==='规则发布')`,
    );
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 320,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await page.eval(
      `(async()=>{const {default:i18n}=await import('/src/app/i18n/config.ts');await i18n.changeLanguage('ja-JP');await Promise.all(document.getAnimations().filter(animation=>animation.playState==='running'&&Number.isFinite(animation.effect?.getTiming().iterations)).map(animation=>animation.finished.catch(()=>{})));})()`,
    );
    const directory = artifactDirectory("sentinel-f4-observation-20261007");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/fleet-narrow-ja.png`, await page.screenshot());
    const geometry = await page.eval(
      `({width:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('#fleet-probe *')].filter(node=>node.getBoundingClientRect().right>321&&getComputedStyle(node).position!=='absolute').slice(0,15).map(node=>({tag:node.tagName,classes:node.className,text:node.textContent.slice(0,60),right:node.getBoundingClientRect().right}))})`,
    );
    assert.ok(geometry.width <= 321, JSON.stringify(geometry));
    assert.match(await page.text("#fleet-probe"), /業務 TPS|未接続/);
  }));
import { artifactDirectory } from "./artifacts.mjs";
