import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { E2E_BASE_URL, launchBrowser } from "./cdp.mjs";
import { artifactDirectory } from "./artifacts.mjs";

let browser;
before(async () => {
  browser = await launchBrowser();
});
after(async () => {
  await browser?.close();
});

test("realtime route polls metrics through HTTP and pause stops only browser reads", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/realtime?env=test-env&app=app-one&range=15m`);
    await page.waitFor(`!!document.querySelector('[data-metric-card="http_qps"]')`, {
      label: "HTTP-backed realtime metric cards rendered",
    });
    assert.match(await page.text('[data-metric-card="http_qps"]'), /42/);
    assert.match(await page.text('[data-metric-card="tps"]'), /尚未接入|Not integrated/);
    await page.waitFor(
      `document.querySelector('[data-monitor-status] strong')?.textContent !== "读取中"`,
    );

    const directory = artifactDirectory("sentinel-f6-realtime-http");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/realtime.png`, await page.screenshot());
    await page.clickByText("暂停刷新", "[data-monitor-status] button");
    await page.waitFor(
      `document.querySelector('[data-monitor-status] strong')?.textContent.includes("暂停")`,
    );
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
