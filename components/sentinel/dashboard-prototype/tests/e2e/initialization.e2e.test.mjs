import { after, before, test } from "node:test";
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
async function withPage(run, alreadyInitialized = false) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await mountReactProbe(page, E2E_BASE_URL, {
      id: "initialization-probe",
      modulePath: "/tests/e2e/probes/InitializationProbe.tsx",
      componentName: "InitializationProbe",
      cleanupName: "__initializationCleanup",
      topologyName: "__initializationTopology",
      props: { alreadyInitialized },
    });
    await page.waitFor(`!!document.querySelector('#initialization-probe [data-probe-summary]')`);
    if (!alreadyInitialized)
      await page.waitFor(`!!document.querySelector('#initialization-probe .setup-controls')`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
    await page.eval("window.__initializationCleanup()");
  } finally {
    await page.close();
  }
}
async function clickText(page, text) {
  await page.clickByText(text, "#initialization-probe button");
}
const phase = (page, value) =>
  page.waitFor(
    `document.querySelector('#initialization-probe [data-probe-summary]')?.textContent.includes(${JSON.stringify('"status":"' + value + '"')})`,
  );
const summary = (page) =>
  page.eval(
    `JSON.parse(document.querySelector('#initialization-probe [data-probe-summary]').textContent)`,
  );
async function input(page, label, value) {
  const id = await page.eval(
    `(()=>{const label=[...document.querySelectorAll('#initialization-probe label')].find(node=>node.textContent===${JSON.stringify(label)});return label.htmlFor;})()`,
  );
  await page.click("#" + id.replace(/[^a-zA-Z0-9_-]/g, (x) => "\\" + x));
  await page.eval("document.activeElement.select()");
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
async function review(page) {
  await input(page, "主机", "db.synthetic.internal");
  await input(page, "用户名", "synthetic");
  await input(page, "密码", "SYNTHETIC-DB-PASSWORD");
  await clickText(page, "测试数据库连接");
  await page.waitFor(
    `document.querySelector('#initialization-probe').textContent.includes('连接可达')`,
  );
  await input(page, "主机", "db.synthetic-two.internal");
  await page.waitFor(
    `!document.querySelector('#initialization-probe').textContent.includes('连接可达')`,
  );
  await clickText(page, "下一步");
  await page.waitFor(
    `document.querySelector('#initialization-probe').textContent.includes('确认管理员密码')`,
  );
  await input(page, "管理员密码", "Synthetic-only-Password-42");
  await input(page, "确认管理员密码", "Synthetic-only-Password-42");
  await clickText(page, "下一步");
  await page.waitFor(`!!document.querySelector('#initialization-probe .setup-authentication')`);
  await page.clickByText("不启用认证", "#initialization-probe .astryx-radio-list-item");
  await input(page, "服务地址", "http://nacos.synthetic.internal");
  await clickText(page, "测试规则源连接");
  await page.waitFor(
    `document.querySelector('#initialization-probe').textContent.includes('连接可达')`,
  );
  await clickText(page, "下一步");
  await page.waitFor(`!!document.querySelector('#initialization-probe .setup-summary')`);
}
test("SETUP-COMMAND rendered: 实际向导连接检查/失效、pending 禁重复与返回，确认完成只通知一次", async () => {
  await withPage(async (page) => {
    await review(page);
    await page.click("#initialization-probe [data-hold]");
    await clickText(page, "完成初始化");
    await phase(page, "submitting");
    await page.waitFor(`document.querySelector('#initialization-probe .setup-controls').disabled`);
    await clickText(page, "完成初始化");
    assert.equal((await summary(page)).completions, 0);
    await page.click("#initialization-probe [data-release]");
    await phase(page, "ready");
    await page.waitFor(
      `document.querySelector('#initialization-probe [data-probe-summary]').textContent.includes('"completions":1')`,
    );
    assert.equal((await summary(page)).writes, 1);
    assert.equal((await summary(page)).checks, 2);
    assert.doesNotMatch(
      await page.text("#initialization-probe"),
      /PRIVATE-INIT-ERROR|Synthetic-only-Password/,
    );
  });
});
test("SETUP-COMMAND rendered: 提交后超时不重放，原请求核查确认初始化才通知完成", async () => {
  await withPage(async (page) => {
    await review(page);
    await page.click("#initialization-probe [data-timeout]");
    await clickText(page, "完成初始化");
    await phase(page, "result-unknown");
    assert.equal((await summary(page)).completions, 0);
    await clickText(page, "完成初始化");
    assert.equal((await summary(page)).writes, 1);
    const directory = artifactDirectory("sentinel-f4-initialization-20261007");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/unknown.png`, await page.screenshot());
    await clickText(page, "检查执行结果");
    await phase(page, "ready");
    const result = await summary(page);
    assert.equal(result.writes, 1);
    assert.equal(result.lookups, 1);
    await page.waitFor(
      `document.querySelector('#initialization-probe [data-probe-summary]').textContent.includes('"completions":1')`,
    );
    assert.doesNotMatch(
      await page.eval(
        `JSON.stringify({local:{...localStorage},session:{...sessionStorage},url:location.href,text:document.querySelector('#initialization-probe').textContent})`,
      ),
      /PRIVATE-INIT-ERROR|Synthetic-only-Password/,
    );
  });
});
test("SETUP-COMMAND rendered: 字段拒绝保留可修正密码，已初始化实例不渲染表单", async () => {
  await withPage(async (page) => {
    await review(page);
    await page.click("#initialization-probe [data-validation]");
    await clickText(page, "完成初始化");
    await phase(page, "error");
    await clickText(page, "上一步");
    await clickText(page, "上一步");
    await page.waitFor(`!!document.querySelector('#initialization-probe input[type="password"]')`);
    assert.equal(
      await page.eval(
        `(()=>{const fields=[...document.querySelectorAll('#initialization-probe .setup-form-grid input')];return Boolean(fields.length===3&&fields.filter(field=>field.type==='password').length===2&&document.querySelector('#initialization-probe [data-setup-state="error"]'))})()`,
      ),
      true,
      "Admin fields must remain mounted when validation feedback is rendered",
    );
    assert.equal(
      await page.eval(
        `document.querySelector('#initialization-probe input[type="password"]').value`,
      ),
      "Synthetic-only-Password-42",
    );
    assert.equal((await summary(page)).completions, 0);
  });
  await withPage(async (page) => {
    await page.waitFor(
      `document.querySelector('#initialization-probe').textContent.includes('引导窗口已关闭')`,
    );
    assert.equal(
      await page.eval(`!!document.querySelector('#initialization-probe .setup-controls')`),
      false,
    );
    assert.equal((await summary(page)).writes, 0);
  }, true);
});
test("SETUP-LIFECYCLE rendered: mounted 初始化页收到外部闭窗后在再次开放时不保留秘密草稿", async () => {
  await withPage(async (page) => {
    await review(page);
    await clickText(page, "上一步");
    await page.waitFor(`!!document.querySelector('#initialization-probe .setup-authentication')`);
    await page.clickByText("在控制台填写凭证", "#initialization-probe .astryx-radio-list-item");
    await page.waitFor(
      `!![...document.querySelectorAll('#initialization-probe label')].find(label=>label.textContent==='Nacos 用户名')`,
    );
    await input(page, "Nacos 用户名", "synthetic-nacos-user");
    await input(page, "Nacos 密码", "SYNTHETIC-NACOS-PASSWORD");
    await clickText(page, "下一步");
    await page.waitFor(`!!document.querySelector('#initialization-probe .setup-summary')`);
    await clickText(page, "Close setup from another initializer");
    await page.waitFor(`!document.querySelector('#initialization-probe .setup-controls')`);
    await page.click("#initialization-probe [data-reopen-after-close]");
    await page.waitFor(`!!document.querySelector('#initialization-probe .setup-controls')`);
    await clickText(page, "上一步");
    await page.waitFor(`!!document.querySelector('#initialization-probe .setup-authentication')`);
    assert.equal(
      await page.eval(
        `(()=>{const label=[...document.querySelectorAll('#initialization-probe label')].find(node=>node.textContent==='Nacos 用户名');return document.getElementById(label.htmlFor).value})()`,
      ),
      "",
    );
    assert.equal(
      await page.eval(
        `(()=>{const label=[...document.querySelectorAll('#initialization-probe label')].find(node=>node.textContent==='Nacos 密码');return document.getElementById(label.htmlFor).value})()`,
      ),
      "",
    );
    await clickText(page, "上一步");
    await page.waitFor(
      `!![...document.querySelectorAll('#initialization-probe input[type="password"]')].find(input=>input.autocomplete==='new-password')`,
    );
    assert.equal(
      await page.eval(
        `([...document.querySelectorAll('#initialization-probe input[type="password"]')].find(input=>input.autocomplete==='new-password')?.value??null)`,
      ),
      "",
    );
    await clickText(page, "上一步");
    await page.waitFor(
      `!!document.querySelector('#initialization-probe input[autocomplete="username"]')`,
    );
    assert.equal(
      await page.eval(
        `document.querySelector('#initialization-probe input[autocomplete="username"]').value`,
      ),
      "",
    );
    assert.equal(
      await page.eval(
        `(()=>{const label=[...document.querySelectorAll('#initialization-probe label')].find(node=>node.textContent==='密码');return document.getElementById(label.htmlFor).value})()`,
      ),
      "",
    );
    assert.doesNotMatch(
      await page.eval(
        `JSON.stringify({text:document.querySelector('#initialization-probe').textContent,local:{...localStorage},session:{...sessionStorage}})`,
      ),
      /SYNTHETIC-DB-PASSWORD|Synthetic-only-Password-42|SYNTHETIC-NACOS-PASSWORD|synthetic-nacos-user|PRIVATE-INIT-ERROR/,
    );
  });
});
test("F5.2 rendered: setup database and administrator drafts survive locale changes without persisting secrets", async () =>
  withPage(async (page) => {
    const url = await page.eval("location.href");
    await input(page, "主机", "db.locale.synthetic.internal");
    await input(page, "用户名", "locale-operator");
    await input(page, "密码", "SYNTHETIC-LOCALE-DB-PASSWORD");
    await clickText(page, "下一步");
    await input(page, "管理员密码", "SYNTHETIC-LOCALE-ADMIN-PASSWORD");
    await input(page, "确认管理员密码", "SYNTHETIC-LOCALE-ADMIN-PASSWORD");

    const fieldValue = (label) =>
      page.eval(
        `(()=>{const node=[...document.querySelectorAll('#initialization-probe label')].find(item=>item.textContent===${JSON.stringify(label)});if(!node)throw new Error('Missing localized field label: '+${JSON.stringify(label)});return document.getElementById(node.htmlFor)?.value??null})()`,
      );
    for (const [locale, labels] of [
      [
        "en-US",
        { adminPassword: "Administrator password", adminConfirm: "Confirm administrator password" },
      ],
      ["ja-JP", { adminPassword: "管理者パスワード", adminConfirm: "管理者パスワード（確認）" }],
      ["zh-CN", { adminPassword: "管理员密码", adminConfirm: "确认管理员密码" }],
    ]) {
      await page.eval(
        `(async()=>{const [{changeLocale},{writeStoredLocale},{default:i18n}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts'),import('/src/app/i18n/config.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);if((i18n.resolvedLanguage??i18n.language)!==${JSON.stringify(locale)})throw new Error('locale was not applied');})()`,
      );
      assert.equal(
        await page.eval("location.href"),
        url,
        "locale changes must not rewrite the setup route",
      );
      assert.equal(await fieldValue(labels.adminPassword), "SYNTHETIC-LOCALE-ADMIN-PASSWORD");
      assert.equal(await fieldValue(labels.adminConfirm), "SYNTHETIC-LOCALE-ADMIN-PASSWORD");
      assert.equal(
        (await summary(page)).checks,
        0,
        "locale changes must not dispatch connectivity checks",
      );
      assert.equal(
        (await summary(page)).writes,
        0,
        "locale changes must not submit initialization",
      );
      assert.doesNotMatch(
        await page.eval(
          `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
        ),
        /SYNTHETIC-LOCALE-DB-PASSWORD|SYNTHETIC-LOCALE-ADMIN-PASSWORD|locale-operator/,
      );
    }
    await clickText(page, "上一步");
    for (const [locale, hostLabel, userLabel, passwordLabel] of [
      ["zh-CN", "主机", "用户名", "密码"],
      ["en-US", "Host", "Username", "Password"],
      ["ja-JP", "ホスト", "ユーザー名", "パスワード"],
    ]) {
      await page.eval(
        `(async()=>{const [{changeLocale},{writeStoredLocale}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);})()`,
      );
      assert.equal(await fieldValue(hostLabel), "db.locale.synthetic.internal");
      assert.equal(await fieldValue(userLabel), "locale-operator");
      assert.equal(await fieldValue(passwordLabel), "SYNTHETIC-LOCALE-DB-PASSWORD");
      assert.equal(
        await page.eval("location.href"),
        url,
        "switching back to storage fields must preserve route state",
      );
      assert.doesNotMatch(
        await page.eval(
          `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
        ),
        /SYNTHETIC-LOCALE-DB-PASSWORD|SYNTHETIC-LOCALE-ADMIN-PASSWORD|locale-operator/,
      );
    }
  }));
import { artifactDirectory } from "./artifacts.mjs";
