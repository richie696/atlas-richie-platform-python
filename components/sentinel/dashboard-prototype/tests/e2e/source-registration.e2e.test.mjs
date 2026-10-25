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
      id: "source-probe",
      modulePath: "/tests/e2e/probes/SourceRegistrationProbe.tsx",
      componentName: "SourceRegistrationProbe",
      topologyFactoryName: "createSourceRegistrationTopology",
      cleanupName: "__sourceCleanup",
      topologyName: "__sourceTopology",
    });
    await wait(page, `state.registry==='ready'`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__sourceCleanup()");
  } finally {
    await page.close();
  }
}
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#source-probe [data-source-summary]').textContent)`,
  );
const wait = (page, predicate) =>
  page.waitFor(
    `(()=>{const state=JSON.parse(document.querySelector('#source-probe [data-source-summary]')?.textContent??'{}');return ${predicate};})()`,
  );
const dialog = "#source-probe dialog[open]";
async function field(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('${dialog} label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.eval(`document.getElementById(${JSON.stringify(id)}).select()`);
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
async function select(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('${dialog} label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.waitFor(
    `[...document.querySelectorAll('[role=option]')].some(node=>node.offsetParent&&node.textContent.trim()===${JSON.stringify(value)})`,
  );
  const index = await page.eval(
    `[...document.querySelectorAll('[role=option]')].findIndex(node=>node.offsetParent&&node.textContent.trim()===${JSON.stringify(value)})`,
  );
  await page.click("[role=option]", { index });
  await page.waitFor(
    `![...document.querySelectorAll('[role=option]')].some(node=>node.offsetParent)`,
  );
}
const click = (page, text) => page.clickByText(text, `${dialog} button`);
async function edit(page) {
  await page.clickByText("修改配置中心", "#source-probe [data-source-id=source-one] button");
  await page.waitFor(`!!document.querySelector('${dialog}')`);
}
test("SOURCE rendered: editing keeps existing credentials without readback; successful save refreshes actual revision and does not claim rule publication", async () =>
  withPage(async (page) => {
    await edit(page);
    assert.equal(await page.count(`${dialog} input[type=password]`), 0);
    await field(page, "连接名称", "Updated connection");
    await click(page, "测试连接");
    await wait(page, `state.check==='ready'`);
    assert.equal((await summary(page)).counts.writes, 0);
    await click(page, "保存登记");
    await wait(page, `state.command==='success'&&state.registry==='ready'`);
    await page.waitFor(`!document.querySelector('${dialog}')`);
    assert.equal((await summary(page)).counts.keep, true);
    assert.equal((await summary(page)).counts.writes, 1);
    assert.match(
      await page.text("#source-probe [data-source-id=source-one]"),
      /Updated connection/,
    );
    assert.match(await page.text("#source-probe"), /不表示规则已发布/);
  }));
test("SOURCE rendered: provider and policy changes discard inactive secrets; checks are invalidated by edits and cannot write registration", async () =>
  withPage(async (page) => {
    await page.clickByText("登记配置中心", "#source-probe button");
    await field(page, "连接名称", "Consul config");
    await select(page, "配置中心类型", "Consul");
    await field(page, "服务地址", "https://consul.test");
    await field(page, "Consul 数据中心", "dc-one");
    await select(page, "认证方式", "直接录入凭证");
    await field(page, "Consul ACL 令牌", "PRIVATE-ACL-TOKEN");
    await click(page, "测试连接");
    await wait(page, `state.check==='ready'`);
    await field(page, "连接名称", "Consul config revised");
    await wait(page, `state.check==='idle'`);
    assert.doesNotMatch(await page.text(dialog), /连接测试成功/);
    await select(page, "认证方式", "无需认证");
    assert.equal(await page.count(`${dialog} input[type=password]`), 0);
    await click(page, "保存登记");
    await wait(page, `state.command==='success'`);
    assert.equal((await summary(page)).counts.writes, 1);
    assert.match(await page.text("#source-probe [data-source-id]"), /Internal config/);
    assert.doesNotMatch(await page.text("#source-probe"), /PRIVATE-ACL-TOKEN/);
  }));
test("F5.2 rendered: changing locale preserves a source-registration draft, URL and provider wire values", async () =>
  withPage(async (page) => {
    await page.clickByText("登记配置中心", "#source-probe button");
    await field(page, "连接名称", "Consul metrics");
    await select(page, "配置中心类型", "Consul");
    await field(page, "服务地址", "https://consul.test");
    await field(page, "Consul 数据中心", "dc-one");
    await select(page, "认证方式", "直接录入凭证");
    await field(page, "Consul ACL 令牌", "PRIVATE-LOCALE-TOKEN");
    const originalUrl = await page.eval("location.href"),
      readForm = () =>
        page.eval(
          `([...document.querySelectorAll('${dialog} input')].map(input=>({type:input.type,value:input.value})))`,
        ),
      originalForm = await readForm();
    assert.equal((await summary(page)).counts.writes, 0);
    for (const locale of ["en-US", "ja-JP", "zh-CN"]) {
      await page.eval(
        `(async()=>{const [{changeLocale},{writeStoredLocale},{default:i18n}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts'),import('/src/app/i18n/config.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);if((i18n.resolvedLanguage??i18n.language)!==${JSON.stringify(locale)})throw new Error('locale was not applied');})()`,
      );
      assert.equal(await page.eval("location.href"), originalUrl);
      assert.deepEqual(await readForm(), originalForm);
      assert.equal((await summary(page)).counts.writes, 0);
    }
    await click(page, "测试连接");
    await wait(page, `state.check==='ready'`);
    await click(page, "保存登记");
    await wait(page, `state.command==='success'`);
    const saved = await summary(page);
    assert.equal(saved.counts.writes, 1);
    assert.deepEqual(saved.counts.lastMutation, {
      kind: "register",
      name: "Consul metrics",
      provider: "consul",
      endpoint: "https://consul.test",
      location: "dc-one",
      authenticationMode: "direct",
    });
    assert.equal(await page.eval("location.href"), originalUrl);
    assert.doesNotMatch(await page.text("#source-probe"), /PRIVATE-LOCALE-TOKEN/);
  }));
test("SOURCE rendered: check-source 429 honors retryAfterMs without automatic retry", async () =>
  withPage(async (page) => {
    await page.clickByText("登记配置中心", "#source-probe button");
    await field(page, "连接名称", "Rate limited config");
    await field(page, "服务地址", "https://nacos.test");
    await field(page, "Nacos 命名空间标识", "namespace-rate-limit");
    await page.eval("window.__sourceTopology.rateLimitCheck()");
    await click(page, "测试连接");
    await wait(page, `state.check==='error'`);
    const checkButton = `[...document.querySelectorAll('${dialog} button')].find(node=>node.textContent.trim()==='测试连接')`;
    assert.equal(await page.eval(`${checkButton}.disabled`), true);
    assert.equal((await summary(page)).counts.checks, 1);
    assert.doesNotMatch(await page.text(dialog), /PRIVATE-CHECK-RATE-LIMIT/);
    await page.waitFor(`!${checkButton}.disabled`);
    await click(page, "测试连接");
    await wait(page, `state.check==='ready'`);
    assert.equal((await summary(page)).counts.checks, 2);
  }));
test("SOURCE rendered: command 429 cooldown also blocks form Enter submission", async () =>
  withPage(async (page) => {
    await page.click("#source-probe [data-source-rate-limit-mutation]");
    await edit(page);
    await field(page, "连接名称", "Rate limited update");
    await click(page, "保存登记");
    await wait(page, `state.command==='error'`);
    const saveButton = `[...document.querySelectorAll('${dialog} button')].find(node=>node.textContent.trim()==='保存登记')`,
      form = `document.querySelector('${dialog} form')`;
    assert.equal(await page.eval(`${saveButton}.disabled`), true);
    assert.equal((await summary(page)).counts.writes, 1);
    assert.doesNotMatch(await page.text(dialog), /PRIVATE-SOURCE-RATE-LIMIT/);
    await page.eval(`${form}.requestSubmit()`);
    await new Promise((resolve) => setTimeout(resolve, 100));
    assert.equal((await summary(page)).counts.writes, 1);
    await page.waitFor(`!${saveButton}.disabled`);
    await page.eval(`${form}.requestSubmit()`);
    await wait(page, `state.command==='success'`);
    assert.equal((await summary(page)).counts.writes, 2);
  }));
test("SOURCE rendered: operation-inspection 429 disables only manual lookup until retryAfterMs", async () =>
  withPage(async (page) => {
    await page.click("#source-probe [data-source-lost]");
    await edit(page);
    await click(page, "保存登记");
    await wait(page, `state.command==='result-unknown'`);
    await page.eval("window.__sourceTopology.rateLimitLookup()");
    await click(page, "检查执行结果");
    await wait(page, `state.counts.lookups===1`);
    const inspectButton = `[...document.querySelectorAll('${dialog} button')].find(node=>node.textContent.trim()==='检查执行结果')`;
    assert.equal(await page.eval(`${inspectButton}.disabled`), true);
    assert.equal((await summary(page)).counts.writes, 1);
    assert.doesNotMatch(await page.text(dialog), /PRIVATE-LOOKUP-RATE-LIMIT/);
    await page.waitFor(`!${inspectButton}.disabled`);
    await click(page, "检查执行结果");
    await wait(page, `state.counts.lookups===2`);
    assert.equal((await summary(page)).counts.writes, 1);
    assert.equal(
      await page.eval(
        `document.querySelector('${dialog} [data-command-state="result-unknown"]')!==null`,
      ),
      true,
    );
  }));
test("SOURCE rendered: lost acknowledgement clears credentials and locks resend; closing still allows only original-operation inspection", async () =>
  withPage(async (page) => {
    await page.click("#source-probe [data-source-lost]");
    await edit(page);
    await select(page, "已有凭证处理方式", "替换认证配置");
    await field(page, "Nacos 登录账号", "source-admin");
    await field(page, "Nacos 登录密码", "PRIVATE-PASSWORD");
    await click(page, "保存登记");
    await wait(page, `state.command==='result-unknown'`);
    assert.equal(
      await page.eval(`document.querySelector('${dialog} input[type=password]').value`),
      "",
    );
    assert.equal(
      await page.eval(
        `[...document.querySelectorAll('${dialog} button')].find(node=>node.textContent==='保存登记').disabled`,
      ),
      true,
    );
    await click(page, "关闭");
    await page.waitFor(`!document.querySelector('${dialog}')`);
    await page.clickByText("检查执行结果", "#source-probe button");
    await wait(page, `state.counts.lookups===1`);
    assert.equal((await summary(page)).command, "result-unknown");
    await page.click("#source-probe [data-source-confirm]");
    await page.clickByText("检查执行结果", "#source-probe button");
    await wait(page, `state.command==='success'`);
    assert.equal((await summary(page)).counts.writes, 1);
    assert.doesNotMatch(await page.text("#source-probe"), /PRIVATE/);
  }));
test("SOURCE rendered: conflict retains correctable input without overwrite; revocation unmounts credentials and no modal is resurrected", async () =>
  withPage(async (page) => {
    await page.click("#source-probe [data-source-conflict]");
    await edit(page);
    await field(page, "连接名称", "Preserved edit");
    await click(page, "保存登记");
    await wait(page, `state.command==='conflict'`);
    assert.equal(
      await page.eval(
        `[...document.querySelectorAll('${dialog} input')].find(node=>node.value==='Preserved edit')?.value`,
      ),
      "Preserved edit",
    );
    await page.eval(
      `window.__sourceTopology.access.set({ownerKey:'source-probe-session',allowed:false})`,
    );
    await wait(page, `!state.authorized`);
    assert.equal(await page.count(dialog), 0);
    assert.equal(await page.count("#source-probe [data-source-id]"), 0);
    await page.click("#source-probe [data-source-allow]");
    await wait(page, `state.registry==='ready'`);
    assert.equal(await page.count(dialog), 0);
    assert.equal((await summary(page)).counts.writes, 1);
  }));
test("SOURCE rendered: Japanese desktop and narrow dialog fields fit without clipping or native-control skin overrides", async () =>
  withPage(async (page) => {
    await page.eval(
      `(async()=>{const [{changeLocale},{writeStoredLocale}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts')]);await changeLocale('ja-JP',writeStoredLocale);})()`,
    );
    await page.clickByText("設定センターを登録", "#source-probe button");
    const dir = artifactDirectory("sentinel-f4-source-20261007");
    mkdirSync(dir, { recursive: true });
    for (const [name, width, height] of [
      ["desktop-ja", 1280, 1050],
      ["narrow-ja", 320, 1050],
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
          `(()=>{return [...document.querySelectorAll('${dialog} .sentinel-form-fields input,${dialog} .sentinel-form-fields button[aria-haspopup="listbox"]')].filter(node=>node.offsetParent).every(node=>{const rect=node.getBoundingClientRect();return rect.left>=0&&rect.right<=innerWidth+1;});})()`,
        ),
      );
      const capture = await page.send("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false,
      });
      writeFileSync(`${dir}/${name}.png`, Buffer.from(capture.data, "base64"));
    }
  }));
import { artifactDirectory } from "./artifacts.mjs";
