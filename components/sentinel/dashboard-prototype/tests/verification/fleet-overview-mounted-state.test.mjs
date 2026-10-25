import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted FleetOverviewPage keeps the page and unavailable metric layout visible on read failure", async () => {
  const browser = new Window({ url: "http://localhost/#/overview?app=all&range=1h" });
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
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { FleetOverviewPage },
      { FleetOverviewUnavailable },
      { fleetQueryKey },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/overview/ui/FleetOverviewPage.tsx"),
      vite.ssrLoadModule("/src/features/overview/ui/FleetOverviewUnavailable.tsx"),
      vite.ssrLoadModule("/src/features/overview/model/fleet.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const catalogs = await Promise.all(
      ["overview", "observation", "shell", "applications", "rules"].map(async (name) =>
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

    const query = {
      context: {
        environmentId: "production",
        appId: null,
        instanceId: null,
        resource: null,
        scope: "fleet",
        window: { fromMs: Date.UTC(2026, 9, 14, 11), toMs: Date.UTC(2026, 9, 14, 12) },
      },
      page: 1,
      pageSize: 20,
      search: "",
      stepMs: 60_000,
    };
    const key = fleetQueryKey(query);
    const error = new AppError(AppErrorKind.NETWORK, "PRIVATE_FLEET_QUERY_DETAIL");
    const snapshot = Object.freeze({ status: "error", key, error });
    const listeners = new Set();
    let reads = 0;
    const resource = {
      keyOf: fleetQueryKey,
      getSnapshot: () => snapshot,
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      async load(receivedQuery) {
        assert.equal(fleetQueryKey(receivedQuery), key, "retry must preserve exact filters/window");
        reads += 1;
      },
      cancel() {},
      reset() {
        for (const listener of listeners) listener();
      },
      dispose() {},
    };
    const queryChanges = [];
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;

    await React.act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(
            AstryxProvider,
            null,
            React.createElement(FleetOverviewPage, {
              resource,
              query,
              onQueryChange: (next) => queryChanges.push(next),
              navigate() {},
              environments: [{ id: "production", name: "Production" }],
              applications: [{ id: "orders", name: "Orders" }],
              clock: () => Date.UTC(2026, 9, 14, 12),
            }),
          ),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    assert.equal(host.querySelector('[data-query-state="error"]') !== null, true);
    assert.match(host.textContent ?? "", /Read failed/);
    assert.ok(
      (host.textContent ?? "").indexOf("Read failed") <
        (host.textContent ?? "").indexOf("Environment"),
      "the single read warning appears beneath the page title, before filters",
    );
    assert.equal(
      [...host.querySelectorAll("button")].filter((button) =>
        button.textContent?.includes("Retry reading"),
      ).length,
      1,
      "the failed overview read has one retry action, not a duplicate banner",
    );
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_FLEET_QUERY_DETAIL/);
    assert.equal(host.querySelectorAll("[data-fleet-application]").length, 0);
    assert.equal(
      host.querySelectorAll('[data-observation-state="unavailable"]').length,
      1,
      "an unavailable fleet read keeps the metric area mounted",
    );
    assert.equal(
      host.querySelectorAll("[data-metric-card]").length,
      6,
      "the fleet overview retains all KPI cards without inventing values",
    );
    assert.equal(host.querySelectorAll(".chart-empty").length, 6);
    assert.match(
      host.textContent ?? "",
      /production/i,
      "the mounted page retains its selected environment",
    );
    const retry = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry reading"),
    );
    assert.ok(retry, "actual page exposes a read-only recovery action");
    await React.act(async () =>
      retry.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.ok(reads >= 2, "initial page read and explicit retry use the same resource");
    assert.deepEqual(queryChanges, [], "retry does not silently change the URL-owned query");

    await React.act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(
            AstryxProvider,
            null,
            React.createElement(FleetOverviewPage, {
              resource,
              query,
              onQueryChange: (next) => queryChanges.push(next),
              navigate() {},
              environments: [{ id: "production", name: "Production" }],
              applications: [{ id: "orders", name: "Orders" }],
              catalogUnavailable: true,
              clock: () => Date.UTC(2026, 9, 14, 12),
            }),
          ),
        ),
      );
      await Promise.resolve();
    });
    assert.equal(
      [...host.querySelectorAll("button")].some((button) =>
        button.textContent?.includes("Retry reading"),
      ),
      false,
      "a catalog-level warning suppresses the duplicate overview query banner",
    );
    assert.equal(host.querySelectorAll("[data-metric-card]").length, 6);

    await React.act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(AstryxProvider, null, React.createElement(FleetOverviewUnavailable)),
        ),
      );
      await Promise.resolve();
    });
    assert.equal(
      host.querySelectorAll('[data-observation-state="unavailable"]').length,
      1,
      "an absent scope still renders the overview's metric workspace",
    );
    assert.equal(host.querySelectorAll("[data-metric-card]").length, 6);
    assert.equal(host.querySelectorAll(".chart-empty").length, 6);
    assert.match(host.textContent ?? "", /Fleet overview/);

    await React.act(async () => root.unmount());
    mounted = false;
    host.remove();
  } finally {
    if (root && mounted && act) await act(async () => root.unmount());
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
