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

test("applications route reads an authorized HTTP catalog and restores explicit instance detail from URL", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/applications?env=test-env&app=app-one&range=15m`);
    await page.waitFor(`!!document.querySelector('[data-observed-instance="instance-1"]')`, {
      label: "HTTP-backed instance directory rendered",
    });
    assert.equal(await page.count("[data-observed-instance]"), 2);
    assert.match(await page.text('[data-observed-instance="instance-2"]'), /需关注|Attention/);

    await page.click('[data-observed-instance="instance-1"] button');
    await page.waitFor(`!!document.querySelector('[data-instance-receipt]')`, {
      label: "selected instance detail loaded through its exact HTTP path",
    });
    const selected = await page.eval(`({
      url: location.hash,
      receipt: document.querySelector('[data-instance-receipt]')?.textContent,
      metric: document.querySelector('[data-metric-card="http_qps"]')?.textContent
    })`);
    assert.match(selected.url, /instance=instance-1/);
    assert.match(selected.url, /scope=process/);
    assert.match(selected.receipt, /当前进程已加载|Applied/);
    assert.match(selected.metric, /42/);

    const directory = artifactDirectory("sentinel-f6-applications-http");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/applications.png`, await page.screenshot());
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
