import { before, after, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";
let browser;
before(async () => {
  browser = await connectIabBrowser();
});
after(async () => {
  await browser?.close();
});
const root = "#guard-probe";
const state = (page) =>
  page.eval(`JSON.parse(document.querySelector('${root} [data-guard-summary]').textContent)`);
const wait = (page, predicate) =>
  page.waitFor(
    `(()=>{const state=JSON.parse(document.querySelector('${root} [data-guard-summary]')?.textContent??'{}');return ${predicate};})()`,
  );
const click = (page, id) => page.click(`${root} [data-guard-${id}]`);
const dialog = (page, text) => page.clickByText(text, `${root} dialog[open] button`);
async function withPage(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/tests/e2e/probes/host.html`);
    await page.eval(
      `(async()=>{await import('/src/app/i18n/config.ts');const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {NavigationGuardProbe}=await import('/tests/e2e/probes/NavigationGuardProbe.tsx');const {createRuleWorkspaceTopology}=await import('/tests/e2e/probes/RuleSetWorkspaceProbe.tsx');history.replaceState(history.state,'','#/setup');const host=document.createElement('section');host.id='guard-probe';document.body.append(host);const topology=createRuleWorkspaceTopology(),root=createRoot(host,{identifierPrefix:'guard-probe-'});root.render(React.createElement(React.StrictMode,null,React.createElement(NavigationGuardProbe,{topology})));window.__guardTopology=topology;window.__guardCleanup=()=>{root.unmount();topology.dispose();host.remove();};})()`,
    );
    await wait(page, `state.route==='setup'&&state.index===0`);
    await click(page, "rules");
    await wait(page, `state.route==='rules'&&state.source==='ready'`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__guardCleanup()");
  } finally {
    await page.close();
  }
}
async function edit(page, value = "37") {
  await page.click(`${root} [data-rule-action=begin]`);
  const id = await page.eval(
    `[...document.querySelectorAll('${root} label')].find(node=>node.textContent==='单机阈值').htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
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
  await wait(page, `state.dirty&&state.value.count===${value}`);
}
test("NAVIGATION rendered: cancelling programmatic leave retains URL and form; confirming abandons only local edit without a server write", async () =>
  withPage(async (page) => {
    await edit(page);
    const original = await state(page);
    await click(page, "next");
    await wait(page, `state.prompt==='dirty'`);
    assert.equal(await page.eval("location.hash"), original.hash);
    assert.equal((await state(page)).route, "rules");
    await dialog(page, "留在当前页面");
    await wait(page, `state.prompt===null`);
    assert.equal((await state(page)).value.count, 37);
    await click(page, "next");
    await dialog(page, "放弃更改并离开");
    await wait(page, `state.route==='realtime'&&!state.editing`);
    assert.equal((await state(page)).writes, 0);
    await click(page, "back");
    await wait(page, `state.route==='rules'`);
    assert.equal((await state(page)).dirty, false);
    assert.equal((await state(page)).editing, false);
  }));
test("NAVIGATION rendered: replace intent stays replacement after confirmation and never manufactures an extra history entry", async () =>
  withPage(async (page) => {
    await edit(page);
    const length = await page.eval("history.length"),
      index = (await state(page)).index;
    await click(page, "replace");
    await wait(page, `state.prompt==='dirty'`);
    await dialog(page, "留在当前页面");
    assert.equal(await page.eval("history.length"), length);
    await click(page, "replace");
    await dialog(page, "放弃更改并离开");
    await wait(page, `state.route==='accounts'`);
    assert.equal(await page.eval("history.length"), length);
    assert.equal((await state(page)).index, index);
    await click(page, "back");
    await wait(page, `state.route==='setup'`);
  }));
test("NAVIGATION rendered: native back restores original managed position before prompting; cancel and forward retain dirty edit without history growth", async () =>
  withPage(async (page) => {
    await click(page, "next");
    await click(page, "rules");
    await edit(page, "38");
    const original = await state(page),
      length = await page.eval("history.length");
    await click(page, "back");
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    assert.equal((await state(page)).index, original.index);
    assert.equal(await page.eval("location.hash"), original.hash);
    assert.equal((await state(page)).route, "rules");
    assert.equal((await state(page)).value.count, 38);
    await dialog(page, "留在当前页面");
    assert.equal(await page.eval("history.length"), length);
    await click(page, "back");
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    await dialog(page, "放弃更改并离开");
    await wait(page, `state.route==='realtime'&&!state.restoring`);
    assert.equal(await page.eval("history.length"), length);
    await click(page, "forward");
    await wait(page, `state.route==='rules'`);
    assert.equal((await state(page)).index, original.index);
    assert.equal((await state(page)).editing, false);
  }));
test("NAVIGATION rendered: unknown write blocks programmatic and native leave; pending receipt cannot unlock or resend original command", async () =>
  withPage(async (page) => {
    await edit(page);
    await click(page, "unknown");
    await page.click(`${root} [data-rule-action=save]`);
    await wait(page, `state.operation==='result-unknown'`);
    await click(page, "next");
    await wait(page, `state.prompt==='locked'`);
    assert.equal(await page.count(`${root} dialog[open] button`), 2);
    assert.ok(
      !(await page.eval(
        `[...document.querySelectorAll('${root} dialog[open] button')].some(node=>node.textContent==='放弃更改并离开')`,
      )),
    );
    await dialog(page, "留在当前页面");
    await click(page, "back");
    await wait(page, `state.prompt==='locked'&&!state.restoring`);
    await dialog(page, "留在当前页面");
    await click(page, "pending");
    await page.clickByText("检查执行结果", `${root} [data-command-state] button`);
    await wait(page, `state.lookups===1&&!state.inspecting`);
    await click(page, "next");
    await wait(page, `state.prompt==='locked'`);
    await dialog(page, "留在当前页面");
    await click(page, "confirm");
    await page.clickByText("检查执行结果", `${root} [data-command-state] button`);
    await wait(page, `state.operation==='success'&&!state.dirty`);
    await click(page, "next");
    await wait(page, `state.route==='realtime'`);
    assert.equal((await state(page)).writes, 1);
    assert.equal((await state(page)).lookups, 2);
  }));
test("NAVIGATION rendered: unmanaged manual hash cannot mount its destination before dirty confirmation; native close is cancelled only while protected", async () =>
  withPage(async (page) => {
    const cancelled = () =>
      page.eval(
        `(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;})()`,
      );
    assert.equal(await cancelled(), false);
    await edit(page);
    assert.equal(await cancelled(), true);
    const original = (await state(page)).hash;
    await page.eval(`location.hash='#/not-a-dashboard-route'`);
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    assert.equal(await page.eval("location.hash"), original);
    assert.equal((await state(page)).historical, false);
    assert.equal((await state(page)).route, "rules");
    await dialog(page, "留在当前页面");
    assert.equal((await state(page)).value.count, 37);
    await click(page, "next");
    await dialog(page, "放弃更改并离开");
    await wait(page, `state.route==='realtime'`);
    assert.equal(await cancelled(), false);
  }));
test("NAVIGATION rendered: Japanese narrow and desktop confirmation fits and Escape leaves editor untouched", async () =>
  withPage(async (page) => {
    await edit(page);
    await page.eval(
      `(async()=>{const [{changeLocale},{writeStoredLocale}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts')]);await changeLocale('ja-JP',writeStoredLocale);})()`,
    );
    await click(page, "next");
    await wait(page, `state.prompt==='dirty'`);
    const dir = artifactDirectory("sentinel-f4-navigation-20261007");
    mkdirSync(dir, { recursive: true });
    for (const [name, width, height] of [
      ["desktop-ja", 1280, 950],
      ["narrow-ja", 320, 950],
    ]) {
      await page.send("Emulation.setDeviceMetricsOverride", {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await page.eval(
        `new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`,
      );
      assert.ok(
        await page.eval(
          `(()=>{const rect=document.querySelector('${root} dialog[open]').getBoundingClientRect();return rect.left>=0&&rect.right<=innerWidth+1&&rect.top>=0&&rect.bottom<=innerHeight+1;})()`,
        ),
      );
      writeFileSync(`${dir}/${name}.png`, await page.screenshot());
    }
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
    await wait(page, `state.prompt===null`);
    assert.equal((await state(page)).value.count, 37);
    assert.equal((await state(page)).route, "rules");
  }));
test("NAVIGATION rendered: dirty forward restores the selected history entry; cancellation preserves edit and confirmation consumes the original forward target", async () =>
  withPage(async (page) => {
    await click(page, "next");
    await click(page, "back");
    await wait(page, `state.route==='rules'`);
    await edit(page, "39");
    const original = await state(page),
      length = await page.eval("history.length");
    await click(page, "forward");
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    assert.equal((await state(page)).index, original.index);
    assert.equal(await page.eval("location.hash"), original.hash);
    await dialog(page, "留在当前页面");
    assert.equal((await state(page)).value.count, 39);
    await click(page, "forward");
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    await dialog(page, "放弃更改并离开");
    await wait(page, `state.route==='realtime'&&!state.restoring`);
    assert.equal(await page.eval("history.length"), length);
    assert.equal((await state(page)).writes, 0);
  }));
test("NAVIGATION rendered: unsent version metadata is protected; top confirmation Tab/Escape cannot lose the lower form or trap focus behind it", async () =>
  withPage(async (page) => {
    await page.click(`${root} [data-rule-action=begin]`);
    await page.click(`${root} [data-rule-action=save]`);
    await wait(page, `state.operation==='success'&&!state.dirty`);
    await page.click(`${root} [data-rule-action=validate]`);
    await page.waitFor(`!document.querySelector('${root} [data-rule-action=freeze]').disabled`);
    await page.click(`${root} [data-rule-action=freeze]`);
    const id = await page.eval(
      `[...document.querySelectorAll('${root} dialog[open] label')].find(node=>node.textContent==='版本名称').htmlFor`,
    );
    await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
    await page.send("Input.insertText", { text: "Preserved version name" });
    await page.eval("history.back()");
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    assert.equal(await page.count(`${root} dialog[open]`), 2);
    for (let step = 0; step < 8; step++) {
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
      assert.ok(
        await page.eval(
          `(()=>{const dialogs=document.querySelectorAll('${root} dialog[open]');return dialogs[dialogs.length-1].contains(document.activeElement);})()`,
        ),
      );
    }
    // Astryx's close-button tooltip is itself a dismissible layer. Test that
    // native Escape closes exactly one layer, never the form behind it.
    await page.eval(
      `(()=>{const dialogs=document.querySelectorAll('${root} dialog[open]');dialogs[dialogs.length-1].querySelector('button').focus();})()`,
    );
    await page.waitFor(`!!document.querySelector('[role=tooltip]:popover-open')`);
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
    await page.waitFor(`!document.querySelector('[role=tooltip]:popover-open')`);
    assert.equal((await state(page)).prompt, "dirty");
    assert.equal(await page.count(`${root} dialog[open]`), 2);
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
    await wait(page, `state.prompt===null`);
    assert.equal(await page.count(`${root} dialog[open]`), 1);
    assert.equal(
      await page.eval(`document.getElementById(${JSON.stringify(id)}).value`),
      "Preserved version name",
    );
    assert.equal((await state(page)).writes, 1);
    await page.eval("history.back()");
    await wait(page, `state.prompt==='dirty'&&!state.restoring`);
    await dialog(page, "放弃更改并离开");
    await wait(page, `state.route==='setup'`);
    assert.equal(await page.count(`${root} dialog[open]`), 0);
    assert.equal((await state(page)).writes, 1);
  }));
import { artifactDirectory } from "./artifacts.mjs";
