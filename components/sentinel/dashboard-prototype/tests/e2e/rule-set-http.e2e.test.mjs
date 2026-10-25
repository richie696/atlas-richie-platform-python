import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";
import { artifactDirectory } from "./artifacts.mjs";
import { mkdirSync, writeFileSync } from "node:fs";
import { gotoMockAdministrator, gotoMockSession } from "./mock-auth.mjs";

let browser;
before(async () => {
  browser = await connectIabBrowser();
});
after(async () => {
  await browser?.close();
});

async function changeField(page, label, value) {
  const id = await page.eval(
    `[...document.querySelectorAll("label")].find(node=>node.textContent===${JSON.stringify(label)}).htmlFor`,
  );
  const selector = `#${id.replace(/[^a-zA-Z0-9_-]/g, (part) => `\\${part}`)}`;
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

async function changeLanguage(page, label) {
  await page.click("button[role='combobox']", { index: 0 });
  await page.waitFor(
    `[...document.querySelectorAll('div[role="option"]')].some(option => option.offsetParent)`,
    { label: "language selector opened" },
  );
  await page.clickByText(label, "div[role='option']");
  await page.waitFor(
    `![...document.querySelectorAll('div[role="option"]')].some(option => option.offsetParent)`,
    { label: "language selector closed" },
  );
}

test("rules route uses explicit binding HTTP reads and consumes publication deep links", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=all`);
    await page.waitFor(`!!document.querySelector('[data-binding-select="binding-app-one"]')`, {
      label: "HTTP-backed ruleset binding directory rendered",
    });
    assert.equal(await page.count("[data-binding-select]"), 5);
    assert.equal(await page.count("[data-rule-workspace]"), 0, "no binding is auto-selected");

    await page.click('[data-binding-select="binding-app-one"]');
    await page.waitFor(
      `!!document.querySelector('[data-rule-workspace] [data-rule-source-summary]')`,
      { label: "complete authoritative snapshot reached the rule editor" },
    );
    assert.match(await page.hash(), /binding=binding-app-one/);
    await page.click('[data-rule-action="begin"]');
    await page.waitFor(`!!document.querySelector('[data-rule-full-preview]')`, {
      label: "full rule values appear only after an explicit edit intent",
    });
    assert.match(await page.text("[data-rule-workspace]"), /POST \/api\/orders/);

    await page.goto(
      `${E2E_BASE_URL}/#/rules?env=test-env&app=app-one&binding=binding-app-one&publication=publication-20261007-01`,
    );
    await page.waitFor(`!!document.querySelector('[data-publication-detail]')`, {
      label: "publication deep link loads its exact binding and publication facts",
    });
    assert.match(await page.hash(), /publication=publication-20261007-01/);
    assert.match(await page.text("[data-publication-detail]"), /version-one/);
    assert.equal(await page.count('[data-deployment-publication="publication-20261007-01"]'), 1);

    const directory = artifactDirectory("sentinel-f6-rules-http");
    mkdirSync(directory, { recursive: true });
    await page.eval(`window.scrollTo({top:document.body.scrollHeight,behavior:"instant"})`);
    writeFileSync(`${directory}/rules-workspace.png`, await page.screenshot());
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});

test("rule HTTP workflow persists a complete draft, validates it, freezes an immutable version, and publishes explicitly", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=all`);
    await page.waitFor(`!!document.querySelector('[data-binding-select="binding-app-one"]')`);
    await page.click('[data-binding-select="binding-app-one"]');
    await page.waitFor(`!!document.querySelector('[data-rule-source-summary]')`);
    await page.click('[data-rule-action="begin"]');
    await page.waitFor(`!!document.querySelector('[data-rule-full-preview]')`);
    await changeField(page, "单机阈值", "2100");
    await page.click('[data-rule-action="save"]');
    await page.waitFor(
      `document.querySelector('[data-rule-dirty]')?.textContent.includes('当前内容无未保存修改')`,
      { label: "draft command was acknowledged by the HTTP mock" },
    );
    assert.match(await page.text("[data-rule-full-preview]"), /2100/);

    await page.click('[data-rule-action="validate"]');
    await page.waitFor(`!!document.querySelector('[data-rule-validation]')`, {
      label: "candidate validation is a separate HTTP read, not local publish approval",
    });
    await page.waitFor(`!document.querySelector('[data-rule-action="freeze"]').disabled`);
    await page.click('[data-rule-action="freeze"]');
    await page.waitFor(`!!document.querySelector('dialog[open]')`);
    await changeField(page, "版本名称", "演示容量基线");
    await page.clickByText("固化不可变版本", "dialog[open] button");
    await page.waitFor(`!document.querySelector('dialog[open]')`);

    const refreshVersions = await page.eval(
      `[...document.querySelectorAll('button')].find((button)=>button.textContent.includes('刷新版本目录'))?.outerHTML ?? null`,
    );
    assert.ok(refreshVersions, "version catalog has a separate refresh action");
    await page.clickByText("刷新版本目录");
    await page.waitFor(`document.querySelectorAll('[data-deployment-version]').length >= 2`);
    const versionIds = await page.eval(
      `[...document.querySelectorAll('[data-deployment-version]')].map((button)=>button.getAttribute('data-deployment-version'))`,
    );
    const frozenId = versionIds.find((id) => id !== "version-one");
    assert.ok(frozenId, "new immutable version is returned by the versions HTTP resource");
    await page.click(`[data-deployment-version="${frozenId}"]`);
    await page.waitFor(`!!document.querySelector('[data-version-detail]')`);
    await page.click("[data-deployment-publish]");
    await page.waitFor(`!!document.querySelector('[data-deployment-submit-publish]')`);
    await changeField(page, "操作原因", "演示完整规则集发布流程");
    await page.click("[data-deployment-submit-publish]");
    await page.waitFor(`document.querySelector('[data-deployment-publication]') !== null`, {
      label: "successful command refreshes publication facts from the API",
    });
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});

test("rule draft and protocol URL survive switching all supported UI languages", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=all&view=flow`);
    await page.waitFor(`!!document.querySelector('[data-binding-select="binding-app-one"]')`);
    await page.click('[data-binding-select="binding-app-one"]');
    await page.waitFor(`!!document.querySelector('[data-rule-source-summary]')`);
    await page.click('[data-rule-action="begin"]');
    await page.waitFor(`!!document.querySelector('[data-rule-full-preview]')`);
    await changeField(page, "单机阈值", "2100");
    await page.waitFor(
      `document.querySelector('[data-rule-dirty]')?.textContent.includes('存在未保存修改')`,
      { label: "dirty draft before changing the UI locale" },
    );

    const protocolUrl = await page.hash();
    assert.match(protocolUrl, /binding=binding-app-one/);
    assert.match(protocolUrl, /view=flow/);

    for (const [label, dirtyText] of [
      ["English", "Unsaved changes"],
      ["日本語", "未保存の変更があります"],
      ["简体中文", "存在未保存修改"],
    ]) {
      await changeLanguage(page, label);
      await page.waitFor(
        `document.querySelector('[data-rule-dirty]')?.textContent.includes(${JSON.stringify(dirtyText)})`,
        { label: `dirty draft remains visible in ${label}` },
      );
      assert.equal(await page.hash(), protocolUrl, "locale changes must not rewrite protocol context");
      assert.match(await page.text("[data-rule-full-preview]"), /2100/);
    }
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});

test("view session can read rules but mock API also rejects privileged operations", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/setup`);
    await page.eval(`localStorage.setItem("sentinel.mock.role", "view")`);
    await gotoMockSession(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=all`, "view");
    await page.waitFor(`!!document.querySelector('[data-binding-select="binding-app-one"]')`);
    await page.click('[data-binding-select="binding-app-one"]');
    await page.waitFor(`!!document.querySelector('[data-rule-source-summary]')`);
    assert.equal(await page.count('[data-rule-action="begin"]'), 0);
    assert.equal(await page.eval(`document.querySelector('[data-deployment-create-plan]').disabled`), true);
    const result = await page.eval(`(async()=>{
      const response=await fetch("/api/v1/rulesets/binding-app-one/commands",{
        method:"POST",headers:{"content-type":"application/json"},body:"{}"
      });
      return {status:response.status,body:await response.json()};
    })()`);
    assert.equal(result.status, 403);
    assert.equal(result.body.error.code, "forbidden");
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
