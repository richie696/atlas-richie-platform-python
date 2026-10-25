import { before, after, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";
import { mountReactProbe } from "./probeHarness.mjs";
let browser;
before(async () => {
  browser = await connectIabBrowser();
});
after(async () => {
  await browser?.close();
});
async function withPage(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await mountReactProbe(page, E2E_BASE_URL, {
      id: "incident-probe",
      modulePath: "/tests/e2e/probes/IncidentObservationProbe.tsx",
      componentName: "IncidentObservationProbe",
      topologyFactoryName: "createIncidentProbeTopology",
      cleanupName: "__incidentCleanup",
      topologyName: "__incidentTopology",
    });
    await page.waitFor(
      `document.querySelectorAll('#incident-probe [data-observed-incident]').length===2`,
    );
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__incidentCleanup()");
  } finally {
    await page.close();
  }
}
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#incident-probe [data-incident-summary]').textContent)`,
  );
const waitState = (page, state) =>
  page.waitFor(
    `JSON.parse(document.querySelector('#incident-probe [data-incident-summary]').textContent).evidenceState===${JSON.stringify(state)}`,
  );
const click = (page, text) => page.clickByText(text, "#incident-probe button");
const selectEvent = (page, id) =>
  page.click(`#incident-probe [data-observed-incident=${id}] button`);
async function select(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('#incident-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.waitFor(`!!document.querySelector('[role=option]')`);
  await page.clickByText(value, "[role=option]");
}
test("INCIDENT rendered: explicit selection, stable cursor order, full-scope statistics and filter-empty remain distinct", async () =>
  withPage(async (page) => {
    assert.match(await page.text("#incident-probe"), /全范围 3 条 · 筛选结果 3 条 · 本页 2 条/);
    assert.match(await page.text("#incident-probe"), /请选择一个具体事件/);
    assert.equal(await page.count("#incident-probe [data-incident-evidence]"), 0);
    assert.deepEqual(
      await page.eval(
        `[...document.querySelectorAll('#incident-probe [data-observed-incident]')].map(item=>item.dataset.observedIncident)`,
      ),
      ["event-c", "event-b"],
    );
    await selectEvent(page, "event-c");
    await waitState(page, "ready");
    assert.match(await page.text("#incident-probe [data-incident-evidence]"), /CPU 使用率 90%/);
    const reads = (await summary(page)).evidenceReads;
    await click(page, "下一页");
    await page.waitFor(
      `!!document.querySelector('#incident-probe [data-observed-incident=event-a]')`,
    );
    assert.equal((await summary(page)).selection, "event-c");
    assert.equal((await summary(page)).evidenceReads, reads);
    await select(page, "事件级别", "警告");
    await page.waitFor(
      `JSON.parse(document.querySelector('#incident-probe [data-incident-summary]').textContent).selection===null`,
    );
    assert.equal(await page.count("#incident-probe [data-incident-evidence]"), 0);
    assert.match(await page.text("#incident-probe"), /全范围 3 条 · 筛选结果 1 条 · 本页 1 条/);
    await select(page, "事件类别", "规则发布");
    await page.waitFor(
      `JSON.parse(document.querySelector('#incident-probe [data-incident-summary]').textContent).timelineState==='filtered-empty'`,
    );
    assert.equal(await page.count("#incident-probe [data-incident-statistics]"), 1);
    assert.equal(await page.count("#incident-probe [data-observed-incident]"), 0);
    assert.match(await page.text("#incident-probe"), /当前筛选没有匹配事件/);
  }));
test("INCIDENT rendered: occurred/receipt UTC times and readonly version navigation use the actual event target", async () =>
  withPage(async (page) => {
    await selectEvent(page, "event-b");
    await waitState(page, "ready");
    const text = await page.text("#incident-probe [data-incident-evidence]");
    assert.match(text, /2026年10月7日 00:05:00 UTC/);
    assert.match(text, /2026年10月7日 00:12:00 UTC/);
    assert.match(text, /publication-one/);
    assert.doesNotMatch(text, /示例|自动确认根因已完成/);
    await click(page, "规则工作台");
    const target = (await summary(page)).navigation;
    assert.equal(target.route, "rules");
    assert.equal(target.context.appId, "app-one");
    assert.equal(target.context.instanceId, undefined);
    assert.equal(target.context.metricScope, "application");
    assert.equal(target.context.versionId, "version-one");
    assert.equal(target.context.eventId, "event-b");
    assert.equal(target.context.from, "2026-10-06T23:55:00.000Z");
    assert.equal(target.context.to, "2026-10-07T00:10:00.000Z");
  }));
test("INCIDENT rendered: partial/unavailable, stale and same-key missing evidence never masquerade as complete or expose errors", async () =>
  withPage(async (page) => {
    await selectEvent(page, "event-c");
    await waitState(page, "ready");
    await page.click("#incident-probe [data-incident-mode=offline]");
    await page.click("#incident-probe [data-incident-detail-refresh]");
    await waitState(page, "stale");
    assert.equal(await page.count("#incident-probe [data-incident-evidence]"), 1);
    assert.doesNotMatch(await page.text("#incident-probe"), /PRIVATE-INCIDENT-ERROR/);
    await page.click("#incident-probe [data-incident-mode=partial]");
    await click(page, "重试读取");
    await waitState(page, "partial");
    assert.equal(await page.count("#incident-probe [data-incident-fact]"), 0);
    assert.match(await page.text("#incident-probe"), /证据不完整或暂不可用/);
    await page.click("#incident-probe [data-incident-mode=unavailable]");
    await page.click("#incident-probe [data-incident-detail-refresh]");
    await waitState(page, "partial");
    assert.match(await page.text("#incident-probe"), /尚无可用的结构化证据/);
    await page.click("#incident-probe [data-incident-mode=missing]");
    await page.click("#incident-probe [data-incident-detail-refresh]");
    await waitState(page, "error");
    assert.equal(await page.count("#incident-probe [data-incident-evidence]"), 0);
    assert.match(await page.text("#incident-probe"), /对象不存在或已移除/);
    assert.equal((await summary(page)).selection, "event-c");
    await page.click("#incident-probe [data-incident-mode=wrong]");
    await selectEvent(page, "event-b");
    await waitState(page, "error");
    assert.equal(await page.count("#incident-probe [data-incident-evidence]"), 0);
    assert.doesNotMatch(await page.text("#incident-probe"), /wrong-event|PRIVATE-MISSING-INCIDENT/);
    await page.click("#incident-probe [data-incident-mode=success]");
    await click(page, "重试读取");
    await waitState(page, "ready");
    assert.equal(await page.count("#incident-probe [data-incident-fact]"), 1);
  }));
test("INCIDENT rendered: changing pending target cancels old work; permission revocation removes all facts and counters", async () =>
  withPage(async (page) => {
    await page.click("#incident-probe [data-incident-mode=held]");
    await selectEvent(page, "event-c");
    await waitState(page, "loading");
    await selectEvent(page, "event-b");
    await waitState(page, "loading");
    assert.ok((await summary(page)).aborts > 0);
    await page.click("#incident-probe [data-incident-release]");
    await waitState(page, "ready");
    assert.equal(
      await page.eval(
        `document.querySelector('#incident-probe [data-incident-evidence]').dataset.incidentEvidence`,
      ),
      "event-b",
    );
    await page.click("#incident-probe [data-incident-revoke]");
    await waitState(page, "denied");
    assert.equal(await page.count("#incident-probe [data-incident-evidence]"), 0);
    assert.equal(await page.count("#incident-probe [data-observed-incident]"), 0);
    assert.equal(await page.count("#incident-probe [data-incident-statistics]"), 0);
  }));
test("INCIDENT rendered: Japanese 320px and desktop evidence preserve readable bounded layout", async () =>
  withPage(async (page) => {
    await selectEvent(page, "event-c");
    await waitState(page, "ready");
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 320,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await page.eval(
      `(async()=>{const {changeLocale}=await import('/src/app/i18n/changeLocale.ts');await changeLocale('ja-JP');await Promise.all(document.getAnimations().filter(animation=>animation.playState==='running'&&Number.isFinite(animation.effect?.getTiming().iterations)).map(animation=>animation.finished.catch(()=>{})));})()`,
    );
    assert.ok(await page.eval("document.documentElement.scrollWidth<=321"));
    assert.doesNotMatch(await page.text("#incident-probe"), /faults\.observed\./);
    const directory = artifactDirectory("sentinel-f4-incidents-20261007");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/incident-narrow-ja.png`, await page.screenshot());
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 1280,
      height: 1300,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await page.waitFor(`!!document.querySelector('#incident-probe [data-incident-evidence]')`);
    await page.eval(
      `document.querySelector('#incident-probe [data-incident-evidence]').scrollIntoView({block:'center'})`,
    );
    writeFileSync(`${directory}/incident-evidence-ja.png`, await page.screenshot());
  }));
import { artifactDirectory } from "./artifacts.mjs";
