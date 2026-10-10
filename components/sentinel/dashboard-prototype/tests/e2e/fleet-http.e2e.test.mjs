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

test("overview route reads catalog and fleet data through the configured HTTP boundary", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/overview`);
    await page.waitFor(`!!document.querySelector('[data-fleet-application="app-one"]')`, {
      label: "HTTP-backed fleet rows rendered",
    });

    const evidence = await page.eval(`({
      rows: [...document.querySelectorAll('[data-fleet-application]')].map(row => row.dataset.fleetApplication),
      qps: document.querySelector('[data-metric-card="http_qps"]')?.textContent
    })`);
    assert.deepEqual(evidence.rows, ["app-one", "app-two", "app-three"]);
    assert.match(evidence.qps, /189/);
    const artifactDir = artifactDirectory("sentinel-f6-fleet-http");
    mkdirSync(artifactDir, { recursive: true });
    writeFileSync(`${artifactDir}/overview.png`, await page.screenshot());
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
