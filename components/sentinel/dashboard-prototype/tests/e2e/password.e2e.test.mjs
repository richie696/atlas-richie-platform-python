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
      id: "password-probe",
      modulePath: "/tests/e2e/probes/PasswordProbe.tsx",
      componentName: "PasswordProbe",
      cleanupName: "__passwordCleanup",
      topologyName: "__passwordTopology",
    });
    await page.waitFor(`!!document.querySelector('#password-probe [data-own-password]')`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__passwordCleanup()");
  } finally {
    await page.close();
  }
}
const status = (page, value) =>
  page.waitFor(
    `document.querySelector('#password-probe [data-password-summary]').textContent.includes(${JSON.stringify('"status":"' + value + '"')})`,
  );
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#password-probe [data-password-summary]').textContent)`,
  );
async function input(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('#password-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.eval("document.activeElement.select()");
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
const submit = (page) => page.clickByText("保存新密码", "#password-probe button");
async function fill(page) {
  await input(page, "当前密码", "Synthetic-Current-Password");
  await input(page, "新密码", "Synthetic-New-Password");
  await input(page, "确认新密码", "Synthetic-New-Password");
}
test("F5.2 rendered: own-password draft survives locale changes without changing URL, writing or persisting secrets", async () =>
  withPage(async (page) => {
    await fill(page);
    const url = await page.eval("location.href");
    for (const locale of ["en-US", "ja-JP", "zh-CN"]) {
      await page.eval(
        `(async()=>{const [{changeLocale},{writeStoredLocale},{default:i18n}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts'),import('/src/app/i18n/config.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);if((i18n.resolvedLanguage??i18n.language)!==${JSON.stringify(locale)})throw new Error('locale was not applied');})()`,
      );
      assert.equal(
        await page.eval("location.href"),
        url,
        "locale changes must not rewrite the password route",
      );
      assert.deepEqual(
        await page.eval(
          `[...document.querySelectorAll('#password-probe input[type=password]')].map(node=>({value:node.value,autocomplete:node.autocomplete}))`,
        ),
        [
          { value: "Synthetic-Current-Password", autocomplete: "current-password" },
          { value: "Synthetic-New-Password", autocomplete: "new-password" },
          { value: "Synthetic-New-Password", autocomplete: "new-password" },
        ],
      );
      assert.doesNotMatch(
        await page.eval(
          `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
        ),
        /Synthetic-Current-Password|Synthetic-New-Password/,
      );
      assert.equal(
        (await summary(page)).calls,
        0,
        "changing locale must not submit a password command",
      );
    }
  }));
test("PASSWORD rendered: 当前会话本人目标、必填、已知拒绝保留输入并区分三类错误", async () =>
  withPage(async (page) => {
    assert.match(await page.text("#password-probe"), /synthetic-viewer/);
    assert.doesNotMatch(await page.text("#password-probe"), /some-other-user/);
    assert.deepEqual(
      await page.eval(
        `[...document.querySelectorAll('#password-probe input')].map(({type,autocomplete})=>({type,autocomplete}))`,
      ),
      [
        { type: "password", autocomplete: "current-password" },
        { type: "password", autocomplete: "new-password" },
        { type: "password", autocomplete: "new-password" },
      ],
    );
    await submit(page);
    await page.waitFor(
      `document.querySelector('#password-probe').textContent.includes('请输入当前密码')`,
    );
    assert.equal((await summary(page)).calls, 0);
    await fill(page);
    assert.doesNotMatch(
      await page.eval(
        `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
      ),
      /Synthetic-Current-Password|Synthetic-New-Password/,
    );
    for (const [mode, text] of [
      ["current", "当前密码不正确"],
      ["policy", "新密码不符合"],
      ["rate", "请求过于频繁"],
    ]) {
      await page.click(`#password-probe [data-mode="${mode}"]`);
      await submit(page);
      await status(page, "error");
      await page.waitFor(
        `document.querySelector('#password-probe').textContent.includes(${JSON.stringify(text)})`,
      );
      assert.equal(
        await page.eval(`document.querySelector('#password-probe input[type=password]').value`),
        "Synthetic-Current-Password",
      );
    }
    assert.equal((await summary(page)).calls, 3);
    assert.doesNotMatch(await page.text("#password-probe"), /PRIVATE-PASSWORD-ERROR/);
  }));
test("PASSWORD rendered: pending 禁重复，服务端确认后清空，只通知一次", async () =>
  withPage(async (page) => {
    await fill(page);
    await page.click("#password-probe [data-hold]");
    await submit(page);
    await status(page, "pending");
    await submit(page);
    assert.equal((await summary(page)).confirmed, 0);
    await page.click("#password-probe [data-release]");
    await status(page, "success");
    await page.waitFor(
      `document.querySelector('#password-probe [data-password-summary]').textContent.includes('"confirmed":1')`,
    );
    assert.equal((await summary(page)).calls, 1);
    assert.deepEqual(
      await page.eval(
        `[...document.querySelectorAll('#password-probe input[type=password]')].map(node=>node.value)`,
      ),
      ["", "", ""],
    );
  }));
test("PASSWORD rendered: 超时未知不重放、不清空可核查输入，重新认证主动清理", async () =>
  withPage(async (page) => {
    await fill(page);
    await page.click("#password-probe [data-mode=timeout]");
    await submit(page);
    await status(page, "result-unknown");
    await submit(page);
    assert.equal((await summary(page)).calls, 1);
    const dir = artifactDirectory("sentinel-f4-password-20261007");
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/unknown.png`, await page.screenshot());
    assert.doesNotMatch(
      await page.eval(
        `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage},text:document.querySelector('#password-probe').textContent})`,
      ),
      /Synthetic-Current|Synthetic-New|PRIVATE-PASSWORD-ERROR/,
    );
    await page.clickByText("重新登录核实", "#password-probe button");
    await page.waitFor(
      `document.querySelector('#password-probe [data-password-summary]').textContent.includes('"reauthentications":1')`,
    );
    assert.equal((await summary(page)).confirmed, 0);
    assert.deepEqual(
      await page.eval(
        `[...document.querySelectorAll('#password-probe input[type=password]')].map(node=>node.value)`,
      ),
      ["", "", ""],
    );
  }));
test("PASSWORD rendered: 提交期间会话过期，迟到确认不得授予成功", async () =>
  withPage(async (page) => {
    await fill(page);
    await page.click("#password-probe [data-hold]");
    await submit(page);
    await status(page, "pending");
    await page.click("#password-probe [data-expire]");
    await status(page, "result-unknown");
    await page.click("#password-probe [data-release]");
    assert.equal((await summary(page)).confirmed, 0);
    assert.equal((await summary(page)).calls, 1);
  }));
import { artifactDirectory } from "./artifacts.mjs";
