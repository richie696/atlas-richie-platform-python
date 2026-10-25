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
async function withPage(run, options = {}) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await mountReactProbe(page, E2E_BASE_URL, {
      id: "login-entry-probe",
      modulePath: "/tests/e2e/probes/LoginEntryProbe.tsx",
      componentName: "LoginEntryProbe",
      cleanupName: "__loginEntryCleanup",
      topologyName: "__loginEntryTopology",
      props: options,
    });
    await page.waitFor(`!!document.querySelector('#login-entry-probe [data-login-summary]')`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__loginEntryCleanup()");
  } finally {
    await page.close();
  }
}
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#login-entry-probe [data-login-summary]').textContent)`,
  );
async function input(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll('#login-entry-probe label')].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.eval("document.activeElement.select()");
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
const submit = (page) => page.clickByText("登录", "#login-entry-probe button");
async function ready(page) {
  await page.waitFor(`!!document.querySelector('#login-entry-probe form')`);
}
async function fill(page) {
  await ready(page);
  await input(page, "登录名", "synthetic-viewer");
  await input(page, "密码", "Synthetic-Login-Password");
}
test("LOGIN rendered: 必填、密码可见性、错误凭证不透露账号存在、429 可修正输入", async () =>
  withPage(async (page) => {
    await ready(page);
    await submit(page);
    await page.waitFor(
      `document.querySelector('#login-entry-probe').textContent.includes('请输入登录名和密码')`,
    );
    assert.equal((await summary(page)).calls, 0);
    await fill(page);
    await page.clickByText("显示密码", "#login-entry-probe button");
    assert.equal(
      await page.eval(
        `document.querySelector('#login-entry-probe input[autocomplete="current-password"]').type`,
      ),
      "text",
    );
    await page.clickByText("隐藏密码", "#login-entry-probe button");
    for (const [mode, copy] of [
      ["invalid", "账号或密码错误，或当前账号无法登录"],
      ["blocked", "账号或密码错误，或当前账号无法登录"],
      ["rate", "登录受限"],
    ]) {
      await page.click(`#login-entry-probe [data-mode=${mode}]`);
      await submit(page);
      await page.waitFor(
        `document.querySelector('#login-entry-probe').textContent.includes(${JSON.stringify(copy)})`,
      );
      assert.equal(
        await page.eval(
          `document.querySelector('#login-entry-probe input[autocomplete=username]').value`,
        ),
        "synthetic-viewer",
      );
    }
    const submitSelector = '#login-entry-probe form button[type="submit"]';
    await page.waitFor(`document.querySelector(${JSON.stringify(submitSelector)}).disabled`);
    await input(page, "密码", "Corrected-After-Cooldown");
    assert.equal(
      await page.eval(`document.querySelector(${JSON.stringify(submitSelector)}).disabled`),
      true,
      "editing credentials must not clear server cooldown",
    );
    await page.waitFor(`!document.querySelector(${JSON.stringify(submitSelector)}).disabled`);
    assert.equal((await summary(page)).calls, 3);
    assert.equal((await summary(page)).navigations, 0);
    assert.doesNotMatch(await page.text("#login-entry-probe"), /PRIVATE-LOGIN-ERROR/);
    const dir = artifactDirectory("sentinel-f4-login-20261007");
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/known-error.png`, await page.screenshot());
  }));
test("LOGIN rendered: Enter 单次提交，独立 session 确认前不导航，确认后清密码只通知一次", async () =>
  withPage(async (page) => {
    await fill(page);
    await page.clickByText("显示密码", "#login-entry-probe button");
    assert.equal(
      await page.eval(
        `document.querySelector('#login-entry-probe input[autocomplete="current-password"]').type`,
      ),
      "text",
    );
    await page.click("#login-entry-probe [data-hold-confirmation]");
    await page.click("#login-entry-probe input[autocomplete=current-password]");
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
      text: "\r",
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
    });
    await page.waitFor(
      `(()=>{const summary=JSON.parse(document.querySelector('#login-entry-probe [data-login-summary]').textContent);return summary.login==='success'&&summary.phase==='checking'})()`,
    );
    assert.equal(
      await page.eval(
        `document.querySelector('#login-entry-probe input[autocomplete="current-password"]').type`,
      ),
      "password",
      "submitting must remask the password immediately",
    );
    assert.equal((await summary(page)).navigations, 0);
    assert.equal(
      await page.eval(
        `[...document.querySelectorAll('#login-entry-probe button')].some(button=>button.disabled&&button.textContent.includes('显示密码'))`,
      ),
      true,
      "password reveal stays disabled while session confirmation is pending",
    );
    await page.click("#login-entry-probe [data-release-confirmation]");
    await page.waitFor(
      `document.querySelector('#login-entry-probe [data-login-summary]').textContent.includes('"navigations":1')`,
    );
    assert.equal((await summary(page)).calls, 1);
    assert.equal(
      (await summary(page)).credentialFormRemovedAtConfirmation,
      true,
      "confirmed login must remove the credential form before notifying route navigation",
    );
    assert.equal(
      await page.eval(
        `!document.querySelector('#login-entry-probe input[autocomplete=current-password]')`,
      ),
      true,
      "confirmed login removes the credential input from the document",
    );
  }));
test("LOGIN rendered: 超时未知不重放；显式核查当前 session 才能恢复准入", async () =>
  withPage(async (page) => {
    await fill(page);
    await page.clickByText("显示密码", "#login-entry-probe button");
    assert.equal(
      await page.eval(
        `document.querySelector('#login-entry-probe input[autocomplete="current-password"]').type`,
      ),
      "text",
    );
    await page.click("#login-entry-probe [data-mode=timeout]");
    await submit(page);
    await page.waitFor(
      `document.querySelector('#login-entry-probe').textContent.includes('登录结果尚未确认')`,
    );
    assert.equal(
      await page.eval(
        `document.querySelector('#login-entry-probe input[autocomplete="current-password"]').type`,
      ),
      "password",
      "unknown login outcomes must remain masked",
    );
    assert.equal(
      await page.eval(
        `[...document.querySelectorAll('#login-entry-probe button')].some(button=>button.disabled&&button.textContent.includes('显示密码'))`,
      ),
      true,
      "password reveal stays disabled for unknown outcomes",
    );
    await submit(page);
    assert.equal((await summary(page)).calls, 1);
    await page.clickByText("检查当前会话", "#login-entry-probe button");
    await page.waitFor(
      `document.querySelector('#login-entry-probe [data-login-summary]').textContent.includes('"navigations":1')`,
    );
    assert.equal((await summary(page)).calls, 1);
    assert.doesNotMatch(
      await page.eval(
        `JSON.stringify({local:{...localStorage},session:{...sessionStorage},text:document.querySelector('#login-entry-probe').textContent})`,
      ),
      /Synthetic-Login-Password|PRIVATE-LOGIN-ERROR/,
    );
  }));
test("LOGIN rendered: 未初始化通知 setup、不出现登录表单；bootstrap 失败不推断初始化成功", async () => {
  await withPage(
    async (page) => {
      await page.waitFor(
        `document.querySelector('#login-entry-probe [data-login-summary]').textContent.includes('"setupRequests":1')`,
      );
      assert.equal(await page.eval(`!!document.querySelector('#login-entry-probe form')`), false);
      assert.equal((await summary(page)).calls, 0);
    },
    { initialized: false },
  );
  await withPage(
    async (page) => {
      await page.waitFor(
        `document.querySelector('#login-entry-probe').textContent.includes('无法确认控制台状态')`,
      );
      assert.equal(await page.eval(`!!document.querySelector('#login-entry-probe form')`), false);
      assert.equal((await summary(page)).setupRequests, 0);
    },
    { failBootstrap: true },
  );
});
test("LOGIN rendered: 三语认证拒绝保留可修正账号且不泄露凭证或原始异常", async () => {
  for (const [locale, message] of [
    ["zh-CN", "账号或密码错误，或当前账号无法登录"],
    ["en-US", "Incorrect credentials, or this account cannot sign in."],
    ["ja-JP", "認証情報が正しくないか、このアカウントはログインできません。"],
  ])
    await withPage(async (page) => {
      await fill(page);
      await page.eval(
        `(async()=>{const [{changeLocale},{writeStoredLocale}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);})()`,
      );
      await page.click("#login-entry-probe [data-mode=invalid]");
      await page.click('#login-entry-probe form button[type="submit"]');
      await page.waitFor(
        `document.querySelector('#login-entry-probe').textContent.includes(${JSON.stringify(message)})`,
      );
      assert.equal(
        await page.eval(
          `document.querySelector('#login-entry-probe input[autocomplete="username"]').value`,
        ),
        "synthetic-viewer",
      );
      assert.equal(
        await page.eval(
          `document.querySelector('#login-entry-probe input[autocomplete="current-password"]').type`,
        ),
        "password",
      );
      assert.doesNotMatch(
        await page.text("#login-entry-probe"),
        /synthetic-viewer|Synthetic-Login-Password|PRIVATE-LOGIN-ERROR/,
      );
      assert.doesNotMatch(
        await page.eval(`JSON.stringify({local:{...localStorage},session:{...sessionStorage}})`),
        /Synthetic-Login-Password|PRIVATE-LOGIN-ERROR/,
      );
    });
});
test("F5.2 rendered: login credential draft survives locale changes without changing URL or submitting", async () =>
  withPage(async (page) => {
    await fill(page);
    const originalUrl = await page.eval("location.href");
    for (const locale of ["en-US", "ja-JP", "zh-CN"]) {
      await page.eval(
        `(async()=>{const [{changeLocale},{writeStoredLocale}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);})()`,
      );
      await page.waitFor(
        `[...document.querySelectorAll('#login-entry-probe label')].find(label=>document.getElementById(label.htmlFor)?.autocomplete==='username')?.textContent.trim()===${JSON.stringify(locale === "zh-CN" ? "登录名" : locale === "en-US" ? "Username" : "ログイン名")}`,
      );
      assert.equal(
        await page.eval(
          'document.querySelector(`#login-entry-probe input[autocomplete="username"]`).value',
        ),
        "synthetic-viewer",
      );
      assert.equal(
        await page.eval(
          'document.querySelector(`#login-entry-probe input[autocomplete="current-password"]`).value',
        ),
        "Synthetic-Login-Password",
      );
      assert.equal(await page.eval('localStorage.getItem("sentinel.locale")'), locale);
      assert.equal(
        await page.eval("location.href"),
        originalUrl,
        "locale preference must not rewrite login navigation",
      );
      assert.equal((await summary(page)).calls, 0, "changing locale must not submit credentials");
      assert.doesNotMatch(
        await page.eval(
          `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
        ),
        /Synthetic-Login-Password/,
      );
    }
  }));
import { artifactDirectory } from "./artifacts.mjs";
