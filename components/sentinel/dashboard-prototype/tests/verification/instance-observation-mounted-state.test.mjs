import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted InstanceObservationPage retries into the catalog and requires explicit incarnation selection", async () => {
  const browser = new Window({ url: "http://localhost/#/applications?environment=production" });
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
      { InstanceObservationPage },
      { instanceCatalogKey },
      { catalogFor },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/applications/ui/InstanceObservationPage.tsx"),
      vite.ssrLoadModule("/src/features/applications/model/instanceObservation.ts"),
      vite.ssrLoadModule("/tests/fixtures/instances.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const catalogs = await Promise.all(
      ["applications", "observation", "shell", "rules", "realtime"].map(async (name) =>
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
      attentionOnly: false,
    };
    const key = instanceCatalogKey(query);
    const error = new AppError(AppErrorKind.NETWORK, "PRIVATE_INSTANCE_DIRECTORY_DETAIL");
    let snapshot = Object.freeze({ status: "error", key, error });
    const listeners = new Set();
    let reads = 0;
    const catalog = {
      keyOf: instanceCatalogKey,
      getSnapshot: () => snapshot,
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      async load(receivedQuery) {
        reads += 1;
        assert.equal(
          instanceCatalogKey(receivedQuery),
          key,
          "initial read and retry must preserve the exact instance directory query",
        );
        if (reads > 1) {
          snapshot = Object.freeze({
            status: "ready",
            key,
            data: catalogFor(query),
            receivedAt: query.context.window.toMs,
          });
          for (const listener of listeners) listener();
        }
      },
      cancel() {},
      reset() {
        for (const listener of listeners) listener();
      },
      dispose() {},
    };
    const detail = {
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
    const queryChanges = [];
    const selectionChanges = [];
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
            React.createElement(InstanceObservationPage, {
              resources: { catalog, detail },
              query,
              selection: null,
              onQueryChange: (next) => queryChanges.push(next),
              onSelectionChange: (next) => selectionChanges.push(next),
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
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_INSTANCE_DIRECTORY_DETAIL/);
    assert.equal(host.querySelectorAll("[data-observed-instance]").length, 0);
    assert.match(host.textContent ?? "", /select a specific instance/i);
    assert.match(host.textContent ?? "", /production/i);
    const retry = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry reading"),
    );
    assert.ok(retry, "actual page exposes a retry for the authoritative directory read");
    await React.act(async () =>
      retry.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(reads, 2, "the catalog is read initially and once on explicit retry");
    assert.equal(host.querySelector('[data-query-state="ready"]') !== null, true);
    const rows = [...host.querySelectorAll("[data-observed-instance]")];
    assert.ok(rows.length > 0, "a successful authority read renders the returned directory");
    assert.deepEqual(
      selectionChanges,
      [],
      "a successful read still does not auto-select an instance",
    );

    const firstInstanceId = rows[0].getAttribute("data-observed-instance");
    const inspect = [...rows[0].querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Inspect"),
    );
    assert.ok(inspect, "each real directory row offers an explicit inspect action");
    await React.act(async () =>
      inspect.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(selectionChanges.length, 1, "only the user's inspect action selects an instance");
    assert.equal(selectionChanges[0].context.environmentId, "production");
    assert.equal(selectionChanges[0].context.instanceId, firstInstanceId);
    assert.ok(selectionChanges[0].processEpoch, "selection binds the current process incarnation");
    assert.equal(selectionChanges[0].context.window.fromMs, query.context.window.fromMs);
    assert.equal(selectionChanges[0].context.window.toMs, query.context.window.toMs);
    assert.deepEqual(queryChanges, [], "retry does not silently change URL-owned filters");

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
