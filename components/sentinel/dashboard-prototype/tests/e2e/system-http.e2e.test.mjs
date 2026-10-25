import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";
import { artifactDirectory } from "./artifacts.mjs";
import { gotoMockAdministrator } from "./mock-auth.mjs";

let browser;
before(async () => {
  browser = await connectIabBrowser();
});
after(async () => {
  await browser?.close();
});

test("system observations use HTTP and audit is an independently addressable tab", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/system?view=connections`);
    await page.waitFor(
      `!!document.querySelector('[data-system-connection="source-nacos-primary"]')`,
      {
        label: "HTTP-backed system connection probes rendered",
      },
    );
    assert.equal(await page.count("[data-system-connection]"), 3);

    await page.clickByText("协议与版本");
    await page.waitFor(`!!document.querySelector('[data-system-protocol="rule-config"]')`, {
      label: "HTTP-backed negotiated protocol facts rendered",
    });
    assert.equal(await page.count("[data-system-protocol]"), 3);

    await page.clickByText("操作审计");
    await page.waitFor(`!!document.querySelector('[data-system-audit="audit-rule-publication"]')`, {
      label: "HTTP-backed audit events rendered",
    });
    assert.match(await page.hash(), /view=audit/);
    assert.equal(await page.count("[data-system-audit]"), 2);
    assert.doesNotMatch(await page.text("body"), /PRIVATE-PASSWORD|password=|traceback/i);

    const directory = artifactDirectory("sentinel-f6-system-http");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/system-audit.png`, await page.screenshot());
    await page.click('[data-system-audit="audit-rule-publication"] button');
    await page.waitFor(`location.hash.startsWith("#/rules?")`);
    assert.match(await page.hash(), /env=test-env/);
    assert.match(await page.hash(), /app=app-one/);
    assert.match(await page.hash(), /publication=publication-20261007-01/);
    assert.match(await page.hash(), /binding=binding-app-one/);
    try {
      await page.waitFor(`!!document.querySelector('[data-publication-detail]')`, {
        label: "audit cross-link resolves the exact rule binding and publication over HTTP",
      });
    } catch (error) {
      throw new Error(`${error.message}\nHash: ${await page.hash()}\nBody: ${await page.text("body")}`);
    }
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
