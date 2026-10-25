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
      id: "directory-probe",
      modulePath: "/tests/e2e/probes/RuleDirectoryProbe.tsx",
      componentName: "RuleDirectoryProbe",
      topologyFactoryName: "createRuleDirectoryTopology",
      cleanupName: "__directoryCleanup",
      topologyName: "__directoryTopology",
    });
    await page.waitFor(
      `document.querySelector('#directory-probe [data-binding-select]')&&JSON.parse(document.querySelector('#directory-probe [data-rule-summary]').textContent).source==='ready'`,
    );
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__directoryCleanup()");
  } finally {
    await page.close();
  }
}
const summary = (page, selector = "data-directory-summary") =>
  page.eval(`JSON.parse(document.querySelector('#directory-probe [${selector}]').textContent)`);
const waitRule = (page, predicate) =>
  page.waitFor(
    `(()=>{const state=JSON.parse(document.querySelector('#directory-probe [data-rule-summary]').textContent);return ${predicate};})()`,
  );
async function field(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('#directory-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  const selector = "#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x);
  await page.click(selector);
  await page.eval(`document.getElementById(${JSON.stringify(id)}).select()`);
  await page.send("Input.insertText", { text: value });
  await page.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Tab",
    code: "Tab",
    windowsVirtualKeyCode: 9,
  });
  await page.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Tab",
    code: "Tab",
    windowsVirtualKeyCode: 9,
  });
}
const action = (page, id) => page.click(`#directory-probe [data-rule-action=${id}]`);
test("RULE-DIRECTORY rendered: pagination and filtered-empty never silently select the first binding; foreign scope is rejected", async () =>
  withPage(async (page) => {
    assert.equal((await summary(page)).selectedId, null);
    await page.click("#directory-probe [data-binding-next]");
    await page.waitFor(
      `!!document.querySelector('#directory-probe [data-binding-select="binding-two"]')`,
    );
    await page.click('#directory-probe [data-binding-select="binding-two"]');
    assert.equal((await summary(page)).selectedId, "binding-two");
    assert.equal(
      await page.eval(`document.querySelector('#directory-probe [data-binding-next]').disabled`),
      true,
    );
    await field(page, "搜索绑定", "not-found");
    await page.waitFor(
      `JSON.parse(document.querySelector('#directory-probe [data-directory-summary]').textContent).directory==='filtered-empty'`,
    );
    assert.equal((await summary(page)).query.page, 1);
    assert.equal(await page.count("#directory-probe [data-binding-select]"), 0);
    assert.equal((await summary(page)).selectedId, "binding-two");
    await field(page, "搜索绑定", "");
    await page.waitFor(
      `!!document.querySelector('#directory-probe [data-binding-select="binding-one"]')`,
    );
    await page.click("#directory-probe [data-directory-invalid]");
    await page.clickByText("刷新绑定目录", "#directory-probe button");
    await page.waitFor(
      `JSON.parse(document.querySelector('#directory-probe [data-directory-summary]').textContent).directory==='stale'`,
    );
    assert.doesNotMatch(await page.text("#directory-probe"), /foreign/);
  }));
test("DRAFT-DIRECTORY rendered: confirmed save reloads catalog; dirty switch requires explicit discard and refresh never erases local edits", async () =>
  withPage(async (page) => {
    await action(page, "begin");
    await action(page, "save");
    await waitRule(page, `state.operation==='success'&&!state.dirty`);
    await page.waitFor(
      `!!document.querySelector('#directory-probe [data-draft-open="persisted-draft"]')`,
    );
    await field(page, "单机阈值", "77");
    await waitRule(page, "state.dirty");
    await page.clickByText("刷新草稿目录", "#directory-probe button");
    await page.click('#directory-probe [data-draft-open="persisted-draft"]');
    await page.waitFor(`!!document.querySelector('#directory-probe dialog[open]')`);
    await page.clickByText("取消并保留编辑", "#directory-probe dialog[open] button");
    assert.equal((await summary(page, "data-rule-summary")).ruleValue.count, 77);
    await page.click('#directory-probe [data-draft-open="persisted-draft"]');
    await page.click("#directory-probe [data-draft-confirm-switch]");
    await page.waitFor(`!document.querySelector('#directory-probe dialog[open]')`);
    await waitRule(page, "!state.dirty&&state.ruleValue.count===20");
    assert.equal((await summary(page, "data-rule-summary")).writes, 1);
  }));
test("DRAFT-DIRECTORY rendered: beforeunload guards dirty/unknown writes, revocation hides draft data and modal, unmount removes handlers", async () =>
  withPage(async (page) => {
    const guarded = () =>
      page.eval(
        `(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;})()`,
      );
    assert.equal(await guarded(), false);
    await action(page, "begin");
    await field(page, "单机阈值", "31");
    assert.equal(await guarded(), true);
    await action(page, "save");
    await waitRule(page, `state.operation==='success'&&!state.dirty`);
    assert.equal(await guarded(), false);
    await field(page, "单机阈值", "32");
    await page.click("#directory-probe [data-rule-mode=unknown]");
    await action(page, "save");
    await waitRule(page, `state.operation==='result-unknown'`);
    assert.equal(await guarded(), true);
    assert.equal(
      await page.eval(`document.querySelector('#directory-probe [data-draft-open]').disabled`),
      true,
    );
    await page.clickByText("检查执行结果", "#directory-probe [data-command-state] button");
    await waitRule(page, `state.operation==='success'&&!state.dirty`);
    assert.equal(await guarded(), false);
    await field(page, "单机阈值", "33");
    await page.click("#directory-probe [data-draft-open]");
    await page.waitFor(`!!document.querySelector('#directory-probe dialog[open]')`);
    await page.eval(`document.querySelector('#directory-probe [data-rule-revoke]').click()`);
    await waitRule(page, "!state.authorized");
    assert.equal(await page.count("#directory-probe [data-draft-open]"), 0);
    assert.equal(await page.count("#directory-probe dialog[open]"), 0);
    await page.eval("window.__directoryCleanup()");
    assert.equal(await guarded(), false);
  }));
test("RULE-DIRECTORY rendered: Japanese 320px and desktop catalog keep controls bounded and table scroll owned", async () =>
  withPage(async (page) => {
    await action(page, "begin");
    await action(page, "save");
    await page.waitFor(`!!document.querySelector('#directory-probe [data-draft-open]')`);
    await page.eval(
      `(async()=>{const {changeLocale}=await import('/src/app/i18n/changeLocale.ts');await changeLocale('ja-JP');})()`,
    );
    const dir = artifactDirectory("sentinel-f4-directory-20261007");
    mkdirSync(dir, { recursive: true });
    for (const [name, width, height] of [
      ["narrow-ja", 320, 1000],
      ["desktop-ja", 1280, 1000],
    ]) {
      await page.send("Emulation.setDeviceMetricsOverride", {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await page.eval(
        `(async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);window.scrollTo(0,0);})()`,
      );
      await page.waitFor("window.scrollY===0");
      assert.ok(await page.eval("document.documentElement.scrollWidth<=innerWidth+1"));
      assert.ok(
        await page.eval(
          `(()=>{const root=document.querySelector('#directory-probe');return [...root.querySelectorAll('.sentinel-form-fields input,.sentinel-form-fields button[aria-haspopup="listbox"]')].filter(node=>node.offsetParent).every(node=>{const rect=node.getBoundingClientRect();return rect.left>=0&&rect.right<=innerWidth+1;});})()`,
        ),
        "Visible filter controls must fit, even when a parent clips overflow",
      );
      assert.doesNotMatch(await page.text("#directory-probe"), /rules\.directory\./);
      writeFileSync(`${dir}/${name}.png`, await page.screenshot());
    }
  }));
import { artifactDirectory } from "./artifacts.mjs";
