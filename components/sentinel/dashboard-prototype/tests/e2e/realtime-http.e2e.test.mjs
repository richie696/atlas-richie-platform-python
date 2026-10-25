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

test("realtime route polls metrics through HTTP and pause stops only browser reads", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `(() => {
        window.__metricsHttpEvidence = [];
        const originalFetch = window.fetch.bind(window);
        window.fetch = async (input, init) => {
          const response = await originalFetch(input, init);
          const rawUrl = typeof input === "string" ? input : input.url;
          const url = new URL(rawUrl, location.href);
          if (url.pathname === "/api/v1/metrics/query") {
            window.__metricsHttpEvidence.push({
              url: url.href,
              status: response.status,
              body: await response.clone().json().catch(() => null),
            });
          }
          return response;
        };
      })()`,
    });
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/realtime?env=test-env&app=app-one&range=15m`);
    await page.waitFor(`!!document.querySelector('[data-metric-card="http_qps"]')`, {
      label: "HTTP-backed realtime metric cards rendered",
    });
    await page.waitFor(
      `window.__metricsHttpEvidence?.some(item => item.status === 200 && item.body?.summary?.some(reading => reading.metric === "http_qps" && reading.value === 42))`,
      { label: "application-scoped HTTP metrics query returned the expected QPS fact" },
    );
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
