import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted IncidentObservationPage does not invent events when its authority fails", async () => {
  const browser = new Window({ url: "http://localhost/#/faults?environment=production" });
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
      { IncidentObservationPage },
      { incidentQueryKey },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/faults/ui/IncidentObservationPage.tsx"),
      vite.ssrLoadModule("/src/features/faults/model/incidentObservation.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const catalogs = await Promise.all(
      ["faults", "observation", "applications", "shell", "rules", "realtime"].map(async (name) =>
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
      severity: null,
      category: null,
      cursor: null,
      pageSize: 20,
    };
    const key = incidentQueryKey(query);
    const error = new AppError(AppErrorKind.NETWORK, "PRIVATE_INCIDENT_AUTHORITY_DETAIL");
    const timelineSnapshot = Object.freeze({ status: "error", key, error });
    const listeners = new Set();
    let reads = 0;
    const timeline = {
      keyOf: incidentQueryKey,
      getSnapshot: () => timelineSnapshot,
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      async load(receivedQuery) {
        assert.equal(
          incidentQueryKey(receivedQuery),
          key,
          "retry must preserve the exact incident scope, filters, cursor, and page size",
        );
        reads += 1;
      },
      cancel() {},
      reset() {
        for (const listener of listeners) listener();
      },
      dispose() {},
    };
    const evidence = {
      keyOf: (value) => JSON.stringify(value),
      getSnapshot: () => Object.freeze({ status: "idle", key: "" }),
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      async load() {},
      cancel() {},
      reset() {},
      dispose() {},
    };
    const instanceSnapshot = Object.freeze({
      status: "error",
      key: "instance-catalog",
      error: new AppError(AppErrorKind.NETWORK, "PRIVATE_INSTANCE_CATALOG_DETAIL"),
    });
    const queryChanges = [];
    const selections = [];
    const instanceChanges = [];
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
            React.createElement(IncidentObservationPage, {
              resources: { timeline, evidence },
              instanceSnapshot,
              instances: [],
              selectedInstance: null,
              instanceTotal: 0,
              query,
              selectedEventId: null,
              onQueryChange: (next) => queryChanges.push(next),
              onSelect: (id) => selections.push(id),
              onInstanceChange: (instance) => instanceChanges.push(instance),
              environments: [{ id: "production", name: "Production" }],
              applications: [{ id: "orders", name: "Orders" }],
              navigate() {},
            }),
          ),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    assert.equal(host.querySelector('[data-query-state="error"]') !== null, true);
    assert.doesNotMatch(
      host.textContent ?? "",
      /PRIVATE_(INCIDENT_AUTHORITY|INSTANCE_CATALOG)_DETAIL/,
    );
    assert.equal(host.querySelectorAll("[data-observed-incident]").length, 0);
    assert.equal(host.querySelector("[data-incident-statistics]"), null);
    assert.match(host.textContent ?? "", /select an event to inspect evidence/i);
    const retry = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry reading"),
    );
    assert.ok(retry, "the actual incident page exposes authority-read recovery");
    await React.act(async () =>
      retry.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(reads, 2, "initial load plus explicit retry use the same timeline query");
    assert.deepEqual(queryChanges, [], "retry does not change URL-owned filters");
    assert.deepEqual(selections, [], "an unavailable event list cannot select evidence");
    assert.deepEqual(
      instanceChanges,
      [],
      "an unavailable instance catalog does not invent a selection",
    );

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
