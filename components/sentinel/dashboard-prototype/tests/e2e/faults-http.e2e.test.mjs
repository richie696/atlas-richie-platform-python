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

test("faults route reads timeline and selected evidence through the Console HTTP boundary", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/faults?env=test-env&app=app-one&range=15m`);
    await page.waitFor(
      `!!document.querySelector('[data-observed-incident="incident-resource-pressure"]')`,
      {
        label: "HTTP-backed incident timeline rendered",
      },
    );
    await page.click('[data-observed-incident="incident-resource-pressure"] button');
    await page.waitFor(
      `!!document.querySelector('[data-incident-evidence="incident-resource-pressure"]')`,
      {
        label: "selected incident evidence loaded by exact event identity",
      },
    );
    const state = await page.eval(`({
      hash: location.hash,
      facts: document.querySelectorAll('[data-incident-fact]').length,
      evidence: document.querySelector('[data-incident-evidence]')?.textContent,
      summary: document.querySelector('[data-incident-statistics]')?.textContent
    })`);
    assert.match(state.hash, /event=incident-resource-pressure/);
    assert.equal(state.facts, 2);
    assert.match(state.evidence, /incident-resource-pressure/);
    // Summary counts cover the whole selected query context, not the visible 3-item page.
    assert.match(state.summary, /全部事件12/);
    assert.match(state.summary, /影响应用1/);

    const directory = artifactDirectory("sentinel-f6-faults-http");
    mkdirSync(directory, { recursive: true });
    writeFileSync(`${directory}/faults.png`, await page.screenshot());
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
