import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T05.4 host metrics stay visible when the SQL association directory is unavailable", async () => {
  const browser = new Window({ url: "http://localhost/#/hosts?environment=production&app=orders" });
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
  let act;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { HostDirectoryPage },
      { HOST_METRIC_CHART_KEY },
      { SessionProvider },
      { ChartThemeProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/hosts/ui/HostDirectoryPage.tsx"),
      vite.ssrLoadModule("/src/features/hosts/presentation/hostMetricChartKey.ts"),
      vite.ssrLoadModule("/src/core/session/SessionProvider.tsx"),
      vite.ssrLoadModule("/src/shared/ui/charts/ChartThemeProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const [applications, observation, shell] = await Promise.all(
      ["applications", "observation", "shell"].map(async (name) =>
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
      resources: {
        "en-US": { translation: { ...applications, ...observation, ...shell } },
      },
    });

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    const now = Date.now();
    const sourcesPort = {
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
    };
    let metricsReadCount = 0;
    const metricsPort = {
      async read() {
        metricsReadCount += 1;
        if (metricsReadCount === 1) throw new Error("synthetic Prometheus outage");
        return {
          quality: "available",
          hosts: ["host-01", "host-02"].map((hostId) => ({
            hostId,
            identity: [{ name: "host_id", value: hostId }],
            metrics: [
              {
                metric: "host_cpu_busy_ratio",
                unit: "ratio",
                quality: "available",
                samples: [{ at: new Date(now - 10_000).toISOString(), value: 0.25 }],
              },
              {
                metric: "host_memory_used_bytes",
                unit: "bytes",
                quality: "available",
                samples: [{ at: new Date(now - 10_000).toISOString(), value: 40_000_000_000 }],
              },
              {
                metric: "host_memory_used_ratio",
                unit: "ratio",
                quality: "available",
                samples: [{ at: new Date(now - 10_000).toISOString(), value: 0.6 }],
              },
              {
                metric: "host_load_1m",
                unit: "load",
                quality: "available",
                samples: [{ at: new Date(now - 10_000).toISOString(), value: 1.2 }],
              },
            ],
          })),
        };
      },
    };
    let associationDirectoryAvailable = false;
    const associationPort = {
      async read(_environmentId, filters) {
        if (!associationDirectoryAvailable)
          throw new Error("synthetic SQL association store outage");
        const items = [
          {
            sourceId: "prometheus-production",
            environmentId: "production",
            hostId: "host-01",
            appId: "orders",
            instanceId: "orders-worker-1",
            processId: "orders-process-1",
            revision: "11111111-1111-4111-8111-111111111111",
            provenance: "operator_confirmed",
            currentEpoch: "22222222-2222-4222-8222-222222222222",
            lastReceivedAt: new Date(now).toISOString(),
            reporterActive: true,
            createdAt: new Date(now - 60_000).toISOString(),
          },
          {
            sourceId: "prometheus-production",
            environmentId: "production",
            hostId: "host-01",
            appId: "billing",
            instanceId: "billing-worker-1",
            processId: "billing-process-1",
            revision: "33333333-3333-4333-8333-333333333333",
            provenance: "operator_confirmed",
            currentEpoch: "44444444-4444-4444-8444-444444444444",
            lastReceivedAt: new Date(now).toISOString(),
            reporterActive: true,
            createdAt: new Date(now - 30_000).toISOString(),
          },
        ].filter((item) => !filters.appId || item.appId === filters.appId);
        const associatedHostIds = [...new Set(items.map((item) => item.hostId))];
        return {
          environmentId: "production",
          asOf: new Date(now).toISOString(),
          page: 1,
          pageSize: filters.pageSize,
          total: items.length,
          associatedHostIds,
          hostIdsComplete: true,
          items,
        };
      },
      async associate() {
        throw new Error("not used");
      },
      async remove() {
        throw new Error("not used");
      },
      async readOperation() {
        throw new Error("not used");
      },
    };

    await act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(
            SessionProvider,
            { session: { roleId: "view", capabilities: [] } },
            React.createElement(
              ChartThemeProvider,
              { revision: "sentinel-dark" },
              React.createElement(HostDirectoryPage, {
                environmentId: "production",
                appId: "orders",
                sourcesPort,
                metricsPort,
                associationPort,
                navigate() {},
              }),
            ),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    assert.match(host.textContent ?? "", /Host metrics are unavailable/);
    const refresh = [...host.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Refresh data",
    );
    assert.ok(refresh, "the host page offers an explicit retry after a provider outage");
    await act(async () => {
      refresh.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    assert.equal(metricsReadCount, 2, "refresh retries the same source-owned host metrics query");

    assert.match(host.textContent ?? "", /host-01/, "source-scoped host remains visible");
    assert.match(
      host.textContent ?? "",
      /Container metrics are not integrated; host or process values are never used as substitutes\./,
      "the host directory explains the unavailable container scope without copying other-scope data",
    );
    assert.match(
      host.textContent ?? "",
      /temporarily unavailable.*not attributed to the selected app/i,
      "the page explains that app attribution is unavailable",
    );
    assert.match(host.textContent ?? "", /Host CPU busy/, "host metric panel remains rendered");
    assert.match(
      host.textContent ?? "",
      /40 GB/,
      "host memory bytes are rendered as a readable capacity in the accessible chart table",
    );
    assert.doesNotMatch(host.textContent ?? "", /亿B/, "capacity values must not use compact locale notation");
    assert.deepEqual(HOST_METRIC_CHART_KEY, {
      host_cpu_busy_ratio: "hostCpu",
      host_memory_used_bytes: "hostMemoryBytes",
      host_memory_used_ratio: "hostMemoryRatio",
      host_load_1m: "hostLoad",
    });
    assert.match(host.textContent ?? "", /Host association unknown/);
    assert.doesNotMatch(host.textContent ?? "", /No runtime worker is associated/);
    assert.ok(
      [...host.querySelectorAll('[role="status"]')].some((element) =>
        element.textContent?.includes("temporarily unavailable"),
      ),
      "the association outage is exposed as a status, not an empty result",
    );
    assert.equal(host.querySelector('[data-query-state="error"]'), null);

    associationDirectoryAvailable = true;
    const renderDirectory = async (selectedAppId) =>
      act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              SessionProvider,
              { session: { roleId: "view", capabilities: [] } },
              React.createElement(
                ChartThemeProvider,
                { revision: "sentinel-dark" },
                React.createElement(HostDirectoryPage, {
                  environmentId: "production",
                  appId: selectedAppId,
                  sourcesPort,
                  metricsPort,
                  associationPort,
                  navigate() {},
                }),
              ),
            ),
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 20));
      });
    const waitForAssociationRead = async () => {
      for (let attempt = 0; attempt < 30; attempt += 1) {
        if (host.textContent?.includes("Runtime instance associated")) return;
        await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
      }
    };

    await renderDirectory("orders");
    const refreshDirectory = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.trim() === "Refresh data",
    );
    assert.ok(refreshDirectory);
    await act(async () => {
      refreshDirectory.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    await waitForAssociationRead();
    const appScopedHosts = host.querySelector('[aria-label="Host directory"]');
    assert.deepEqual(
      [...(appScopedHosts?.querySelectorAll("button") ?? [])].map((button) =>
        button.textContent?.match(/host-\d+/)?.[0],
      ),
      ["host-01"],
      "a confirmed app filter includes only explicitly associated hosts",
    );

    await renderDirectory("all");
    await waitForAssociationRead();
    const allHosts = host.querySelector('[aria-label="Host directory"]');
    assert.deepEqual(
      [...(allHosts?.querySelectorAll("button") ?? [])].map((button) =>
        button.textContent?.match(/host-\d+/)?.[0],
      ),
      ["host-01", "host-02"],
      "the global directory shows each host once, including an unassociated host",
    );
    assert.match(
      allHosts?.textContent ?? "",
      /No runtime instance associated/,
      "the unassociated host is explicit rather than silently omitted",
    );
    const host01 = [...(allHosts?.querySelectorAll("button") ?? [])].find((button) =>
      button.textContent?.includes("host-01"),
    );
    assert.ok(host01);
    await act(async () => {
      host01.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const selectedHostDetail = host.querySelector('[aria-labelledby="host-detail-title"]');
    assert.match(selectedHostDetail?.textContent ?? "", /orders \/ orders-worker-1/);
    assert.match(selectedHostDetail?.textContent ?? "", /billing \/ billing-worker-1/);
  } finally {
    if (root && act) await act(async () => root.unmount());
    if (vite) await vite.close();
    browser.happyDOM.abort();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
