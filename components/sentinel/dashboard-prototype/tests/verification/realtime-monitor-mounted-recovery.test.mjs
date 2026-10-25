import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted realtime page keeps query identity through explicit retry and renders recovered data", async () => {
  const browser = new Window({ url: "http://localhost/#/realtime" });
  const priorGlobals = new Map();
  const installGlobal = (name, value) => {
    priorGlobals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  };
  for (const name of [
    "window",
    "document",
    "navigator",
    "HTMLElement",
    "Element",
    "Node",
    "Event",
    "MouseEvent",
    "MutationObserver",
    "requestAnimationFrame",
    "cancelAnimationFrame",
  ])
    installGlobal(name, browser[name] ?? browser.document);
  installGlobal("IS_REACT_ACT_ENVIRONMENT", true);

  let vite;
  let root;
  let mounted = false;
  let act;
  let monitor;
  const requests = [];
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { createRealtimeMonitor },
      { WINDOW_MODE },
      { LiveMonitoringPage },
      { AstryxProvider },
      { ChartThemeProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/realtime/application/realtimeMonitor.ts"),
      vite.ssrLoadModule("/src/features/realtime/model/monitoring.ts"),
      vite.ssrLoadModule("/src/features/realtime/ui/LiveMonitoringPage.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      vite.ssrLoadModule("/src/shared/ui/charts/ChartThemeProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const catalogs = await Promise.all(
      ["realtime", "observation", "applications", "shell"].map(async (name) =>
        JSON.parse(
          await readFile(
            new URL(`../../src/app/i18n/messages/en-US/${name}.json`, import.meta.url),
            "utf8",
          ),
        ),
      ),
    );
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      nsSeparator: false,
      resources: { "en-US": { translation: Object.assign({}, ...catalogs) } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const fromMs = Date.UTC(2026, 9, 14, 11);
    const selection = {
      context: {
        environmentId: "production",
        appId: null,
        instanceId: null,
        resource: null,
        scope: "fleet",
        window: { fromMs, toMs: fromMs + 60_000 },
      },
      metrics: ["http_qps"],
      stepMs: 60_000,
      windowMode: WINDOW_MODE.Fixed,
    };
    const coverage = { expected: 1, reporting: 0, inventorySource: "test-catalog" };
    const metricPort = {
      async readMetrics(query) {
        requests.push(query);
        if (requests.length === 1)
          throw new AppError(AppErrorKind.NETWORK, "PRIVATE_METRICS_ENDPOINT_DETAILS");
        if (requests.length === 3)
          throw new AppError(AppErrorKind.FORBIDDEN, "PRIVATE_AUTHORIZATION_DETAILS", {
            status: 403,
          });
        return {
          query,
          asOfMs: query.context.window.toMs,
          summary: [
            {
              metric: "http_qps",
              unit: "requests_per_second",
              source: "sentinel-reporter-v2",
              denominator: "completed_http_requests",
              coverage,
              quality: "no_samples",
              value: null,
              sampledAtMs: null,
            },
          ],
          series: [
            {
              metric: "http_qps",
              unit: "requests_per_second",
              source: "sentinel-reporter-v2",
              denominator: "completed_http_requests",
              coverage,
              quality: "no_samples",
              samples: [],
            },
          ],
          annotations: [],
        };
      },
    };
    monitor = createRealtimeMonitor(metricPort, undefined, { intervalMs: 60_000 });

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;
    await React.act(async () => {
      root.render(
        React.createElement(
          React.StrictMode,
          null,
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              AstryxProvider,
              null,
              React.createElement(
                ChartThemeProvider,
                { revision: 0 },
                React.createElement(LiveMonitoringPage, {
                  monitor,
                  selection,
                  onSelectionChange: () => {},
                  environments: [{ id: "production", name: "Production" }],
                  applications: [],
                  instances: [],
                  selectedInstanceId: null,
                  instanceCatalogLoading: false,
                  queryReady: true,
                  instanceTargetMissing: false,
                  instanceTargetUnsupported: false,
                }),
              ),
            ),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 20));
      await Promise.resolve();
    });
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 10)));

    assert.equal(host.querySelector('[data-query-state="error"]') !== null, true);
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_METRICS_ENDPOINT_DETAILS/);
    assert.equal(host.querySelectorAll('[data-observation-state="unavailable"]').length, 1);
    assert.equal(
      host.querySelectorAll("[data-metric-card]").length,
      6,
      "a failed read retains the empty metric-card layout without fabricated zeroes",
    );
    assert.equal(host.querySelectorAll(".chart-empty").length, 6);
    assert.ok(
      (host.textContent ?? "").indexOf("Read failed") <
        (host.textContent ?? "").indexOf("Environment"),
      "the single read warning appears below the page title, before controls",
    );
    const retry = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry reading"),
    );
    assert.ok(retry, "the actual realtime page exposes an explicit retry after a failed read");

    await React.act(async () => {
      retry.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 20));
      await Promise.resolve();
    });
    assert.equal(requests.length, 2, "retry performs one new authority read");
    assert.deepEqual(requests[0], requests[1], "retry preserves the exact selected query");
    assert.equal(
      host.querySelector('[data-query-state="partial"]') !== null,
      true,
      "the successful no-sample response is visible as partial, not fabricated zero data",
    );
    assert.equal(host.querySelector('[data-metric-card="http_qps"]') !== null, true);
    assert.match(host.textContent ?? "", /No samples/);
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_METRICS_ENDPOINT_DETAILS/);

    const pause = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Pause refresh"),
    );
    assert.ok(pause, "the mounted page exposes its browser-local polling control");
    await React.act(async () => {
      pause.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    const resume = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Resume and read latest window"),
    );
    assert.ok(resume, "paused monitoring offers an explicit read resume");
    await React.act(async () => {
      resume.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 20));
      await Promise.resolve();
    });
    assert.equal(requests.length, 3, "resume makes one new read against the same authority");
    assert.deepEqual(requests[1], requests[2], "permission recovery keeps the selected query");
    assert.equal(host.querySelector('[data-query-state="denied"]') !== null, true);
    assert.equal(
      host.querySelector('[data-metric-card="http_qps"]')?.getAttribute("data-quality"),
      "unavailable",
      "denied reads clear trusted values while retaining the empty metric layout",
    );
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_AUTHORIZATION_DETAILS/);

    await React.act(async () => root.unmount());
    mounted = false;
    host.remove();
  } finally {
    if (root && mounted && act) await act(async () => root.unmount());
    monitor?.dispose();
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
