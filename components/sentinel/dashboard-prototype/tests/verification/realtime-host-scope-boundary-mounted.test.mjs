import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T05.4 realtime host panel declares HOST-only data and keeps capacity units readable", async () => {
  const browser = new Window({ url: "http://localhost/#/realtime?env=production" });
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
    "CSS",
    "requestAnimationFrame",
    "cancelAnimationFrame",
  ])
    installGlobal(name, browser[name] ?? browser.document);
  installGlobal("IS_REACT_ACT_ENVIRONMENT", true);

  let vite;
  let root;
  let act;
  let resources;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { HostMetricsPanel },
      { createHostMetricsResources },
      { ChartThemeProvider },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/realtime/ui/HostMetricsPanel.tsx"),
      vite.ssrLoadModule("/src/features/realtime/application/hostMetricsResources.ts"),
      vite.ssrLoadModule("/src/shared/ui/charts/ChartThemeProvider.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const messages = await Promise.all(
      ["observation", "shell"].map(async (name) =>
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
      interpolation: { escapeValue: false },
      resources: { "en-US": { translation: Object.assign({}, ...messages) } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const fromMs = Date.UTC(2026, 9, 17, 9, 0);
    const toMs = fromMs + 60 * 60_000;
    const at = new Date(toMs - 10_000).toISOString();
    const requestedWindows = [];
    let returnNoSamples = false;
    const selection = {
      context: {
        environmentId: "production",
        appId: null,
        instanceId: null,
        resource: null,
        scope: "fleet",
        window: { fromMs, toMs },
      },
      metrics: [],
      stepMs: 60_000,
      windowMode: "fixed",
    };
    resources = createHostMetricsResources(
      {
        async readSources() {
          return {
            items: [
              {
                id: "prometheus-production",
                displayName: "Production Prometheus",
                environmentId: "production",
                enabled: true,
              },
            ],
          };
        },
      },
      {
        async read(_sourceId, query) {
          requestedWindows.push(query);
          if (returnNoSamples) {
            return {
              sourceId: "prometheus-production",
              environmentId: "production",
              query,
              asOf: new Date(Date.parse(query.to) + 1_000).toISOString(),
              quality: "no_samples",
              reason: "missing_samples",
              hosts: [],
            };
          }
          return {
            sourceId: "prometheus-production",
            environmentId: "production",
            query,
            asOf: at,
            quality: "available",
            reason: null,
            hosts: [
              {
                hostId: "host-01",
                identity: [{ name: "host", value: "host-01" }],
                metrics: [
                  {
                    metric: "host_cpu_busy_ratio",
                    unit: "ratio",
                    quality: "available",
                    reason: null,
                    samples: [{ at, value: 0.25 }],
                  },
                  {
                    metric: "host_memory_used_bytes",
                    unit: "bytes",
                    quality: "available",
                    reason: null,
                    samples: [{ at, value: 40_000_000_000 }],
                  },
                  {
                    metric: "host_memory_used_ratio",
                    unit: "ratio",
                    quality: "available",
                    reason: null,
                    samples: [{ at, value: 0.6 }],
                  },
                  {
                    metric: "host_load_1m",
                    unit: "tasks",
                    quality: "available",
                    reason: null,
                    samples: [{ at, value: 1.2 }],
                  },
                ],
              },
            ],
          };
        },
      },
    );

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(
            AstryxProvider,
            null,
            React.createElement(
              ChartThemeProvider,
              { revision: "sentinel-dark" },
              React.createElement(HostMetricsPanel, {
                environmentId: "production",
                selection,
                sourcesResource: resources.sources,
                metricsResource: resources.metrics,
                onConfigure() {},
              }),
            ),
          ),
        ),
      );
    });

    for (let attempt = 0; attempt < 30 && !host.textContent?.includes("40 GB"); attempt++) {
      await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    }
    assert.match(
      host.textContent ?? "",
      /This view is HOST-scope only\. Container metrics are not integrated; host or process values are never used as substitutes\./,
    );
    assert.match(host.textContent ?? "", /40 GB/);
    assert.doesNotMatch(host.textContent ?? "", /亿B/);

    returnNoSamples = true;
    const nextWindow = { fromMs: toMs, toMs: toMs + 60 * 60_000 };
    const nextSelection = {
      ...selection,
      context: { ...selection.context, window: nextWindow },
    };
    await act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(
            AstryxProvider,
            null,
            React.createElement(
              ChartThemeProvider,
              { revision: "sentinel-dark" },
              React.createElement(HostMetricsPanel, {
                environmentId: "production",
                selection: nextSelection,
                sourcesResource: resources.sources,
                metricsResource: resources.metrics,
                onConfigure() {},
              }),
            ),
          ),
        ),
      );
    });
    for (
      let attempt = 0;
      attempt < 30 && !host.textContent?.includes("no host samples are available for this window");
      attempt++
    ) {
      await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    }
    assert.equal(requestedWindows.length, 2, "switching the selected time range issues a new read");
    assert.equal(requestedWindows[1].from, new Date(nextWindow.fromMs).toISOString());
    assert.equal(requestedWindows[1].to, new Date(nextWindow.toMs).toISOString());
    assert.match(host.textContent ?? "", /no host samples are available for this window/i);
    assert.doesNotMatch(
      host.textContent ?? "",
      /37\.25 GB/,
      "the prior window is not presented as current data",
    );
  } finally {
    if (root && act) await act(async () => root.unmount());
    resources?.sources.dispose();
    resources?.metrics.dispose();
    await vite?.close();
    browser.happyDOM.abort();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else Reflect.deleteProperty(globalThis, name);
    }
  }
});
