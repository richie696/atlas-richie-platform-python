import { after, before, test } from "node:test";
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
async function withSetup(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    const origin = new URL(E2E_BASE_URL).origin;
    await page.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `if(location.origin===${JSON.stringify(origin)}){localStorage.setItem('sentinel.mock.initialized','false');localStorage.setItem('sentinel.mock.operator-authorized','true');}`,
    });
    await page.goto(`${E2E_BASE_URL}/#/setup`);
    await page.waitFor(`!!document.querySelector('.setup-form-grid')`);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
}
async function field(page, label) {
  return page.eval(
    `(()=>{const node=[...document.querySelectorAll('.setup-workspace label')].find(element=>element.textContent===${JSON.stringify(label)});return document.getElementById(node.htmlFor).value;})()`,
  );
}
async function typeField(page, label, value) {
  const id = await page.eval(
    `(()=>{const node=[...document.querySelectorAll('.setup-workspace label')].find(element=>element.textContent===${JSON.stringify(label)});return node.htmlFor;})()`,
  );
  await page.click(`#${CSSescape(id)}`);
  await page.eval(`document.activeElement.select()`);
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
  );
}
const CSSescape = (value) => value.replace(/[^a-zA-Z0-9_-]/g, (character) => `\\${character}`);
async function sourceStep(page) {
  await typeField(page, "主机", "db.synthetic.internal");
  await typeField(page, "数据库名", "sentinel_e2e");
  await typeField(page, "用户名", "synthetic");
  await typeField(page, "密码", "SYNTHETIC-DB");
  await page.clickByText("下一步");
  await page.waitFor(
    `document.querySelector('.setup-workspace').textContent.includes('创建内置管理员')`,
  );
  await typeField(page, "管理员密码", "Synthetic-only-Password-42");
  await typeField(page, "确认管理员密码", "Synthetic-only-Password-42");
  await page.clickByText("下一步");
  await page.waitFor(`!!document.querySelector('.setup-authentication')`);
}
test("SETUP-VALIDATE rendered: 必填/端口失败不前进，修正后进入管理员步骤且保留非敏感输入", async () => {
  await withSetup(async (page) => {
    await page.clickByText("下一步");
    await page.waitFor(`document.querySelectorAll('.setup-workspace input[aria-invalid="true"]').length > 0`);
    await typeField(page, "主机", "db.synthetic.internal");
    await typeField(page, "数据库名", "sentinel_e2e");
    await typeField(page, "用户名", "synthetic");
    await typeField(page, "密码", "SYNTHETIC-DB");
    await typeField(page, "端口", "65536");
    await page.clickByText("下一步");
    await page.waitFor(`document.querySelector('.setup-workspace').textContent.includes('65535')`);
    assert.equal(await field(page, "主机"), "db.synthetic.internal");
    await typeField(page, "端口", "5432");
    await page.clickByText("下一步");
    await page.waitFor(
      `document.querySelector('.setup-workspace').textContent.includes('创建内置管理员')`,
    );
    await page.clickByText("上一步");
    await page.waitFor(`!!document.querySelector('.setup-workspace input[autocomplete="off"]')`);
    assert.equal(await field(page, "主机"), "db.synthetic.internal");
  });
});
test("SETUP-SECRET rendered: DB/provider/auth 切换清理秘密，切回也不会复活旧密码或 Token", async () => {
  await withSetup(async (page) => {
    await typeField(page, "密码", "SYNTHETIC-DB");
    await page.clickByText("MySQL", ".astryx-radio-list-item");
    await page.waitFor(`document.querySelector('.setup-workspace').textContent.includes('MySQL')`);
    assert.equal(await field(page, "密码"), "");
    assert.equal(await field(page, "端口"), "3306");
    await sourceStep(page);
    await page.clickByText("在控制台填写凭证", ".setup-authentication .astryx-radio-list-item");
    await page.waitFor(`!!document.querySelector('.setup-workspace input[type="password"]')`);
    await typeField(page, "Nacos 用户名", "synthetic-user");
    await typeField(page, "Nacos 密码", "SYNTHETIC-NACOS");
    await page.clickByText("不启用认证", ".setup-authentication .astryx-radio-list-item");
    await page.clickByText("在控制台填写凭证", ".setup-authentication .astryx-radio-list-item");
    await page.waitFor(`!!document.querySelector('.setup-workspace input[type="password"]')`);
    assert.equal(await field(page, "Nacos 密码"), "");
    await typeField(page, "Nacos 密码", "SYNTHETIC-NACOS");
    await page.clickByText("Consul", ".astryx-radio-list-item");
    await page.waitFor(
      `document.querySelector('.setup-workspace').textContent.includes('Consul ACL Token')`,
    );
    assert.equal(await field(page, "Consul ACL Token"), "");
    await typeField(page, "Consul ACL Token", "SYNTHETIC-CONSUL");
    await page.clickByText("Nacos", ".astryx-radio-list-item");
    await page.waitFor(
      `document.querySelector('.setup-workspace').textContent.includes('Nacos 密码')`,
    );
    assert.equal(await field(page, "Nacos 密码"), "");
    assert.doesNotMatch(
      await page.eval(
        `JSON.stringify({local:{...localStorage},session:{...sessionStorage},url:location.href})`,
      ),
      /SYNTHETIC-DB|SYNTHETIC-NACOS|SYNTHETIC-CONSUL/,
    );
  });
});
test("SETUP-STEP rendered: 未填写服务地址不能确认，完整确认页不显示任何凭证且拆分保持字段布局", async () => {
  await withSetup(async (page) => {
    await sourceStep(page);
    await page.clickByText("不启用认证", ".setup-authentication .astryx-radio-list-item");
    await page.clickByText("下一步");
    await page.waitFor(`document.querySelectorAll('.setup-workspace input[aria-invalid="true"]').length > 0`);
    await typeField(page, "服务地址", "https://nacos.synthetic.internal/nacos");
    const directory = artifactDirectory("sentinel-f4-setup-20261007");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/source.png`, await page.screenshot());
    await page.clickByText("下一步");
    await page.waitFor(`!!document.querySelector('.setup-summary')`);
    assert.doesNotMatch(await page.text(".setup-summary"), /Password|password|口令|凭证|SYNTHETIC/);
    writeFileSync(`${directory}/review.png`, await page.screenshot());
  });
});
import { artifactDirectory } from "./artifacts.mjs";
