import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted instance detail keeps incarnation ownership, clears retired data, and never borrows unsupported metrics", async () => {
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
      { instanceCatalogKey, instanceDetailKey, instanceSelection },
      { catalogFor, detailFor },
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
    const catalog = catalogFor(query);
    const selectedInstance = catalog.items[0];
    const initialSelection = instanceSelection(selectedInstance, query.context);
    const catalogKey = instanceCatalogKey(query);
    let catalogSnapshot = Object.freeze({
      status: "ready",
      key: catalogKey,
      data: catalog,
      receivedAt: query.context.window.toMs,
    });
    const catalogListeners = new Set();
    let catalogReads = 0;
    const catalogResource = {
      keyOf: instanceCatalogKey,
      getSnapshot: () => catalogSnapshot,
      subscribe(listener) {
        catalogListeners.add(listener);
        return () => catalogListeners.delete(listener);
      },
      async load(receivedQuery) {
        catalogReads += 1;
        assert.equal(instanceCatalogKey(receivedQuery), catalogKey);
        catalogSnapshot = Object.freeze({
          status: "ready",
          key: catalogKey,
          data: catalogFor(receivedQuery),
          receivedAt: receivedQuery.context.window.toMs,
        });
        for (const listener of catalogListeners) listener();
      },
      cancel() {},
      reset() {},
      dispose() {},
    };

    let detailSnapshot = Object.freeze({ status: "idle" });
    const detailListeners = new Set();
    const detailRequests = [];
    let resetCount = 0;
    const detailResource = {
      keyOf: instanceDetailKey,
      getSnapshot: () => detailSnapshot,
      subscribe(listener) {
        detailListeners.add(listener);
        return () => detailListeners.delete(listener);
      },
      async load(receivedQuery) {
        detailRequests.push(receivedQuery);
        const key = instanceDetailKey(receivedQuery);
        detailSnapshot = Object.freeze({ status: "loading", key });
        for (const listener of detailListeners) listener();
        const rejectRead = (error) => {
          detailSnapshot = Object.freeze({ status: "error", key, error });
          for (const listener of detailListeners) listener();
          throw error;
        };
        if (detailRequests.length === 1) {
          return rejectRead(new AppError(AppErrorKind.NETWORK, "PRIVATE_INSTANCE_DETAIL_ENDPOINT"));
        }
        if (detailRequests.length === 2) {
          return rejectRead(
            new AppError(AppErrorKind.SERVER, "PRIVATE_RETIRED_INSTANCE_DETAIL", {
              status: 409,
              code: "instance_incarnation_changed",
            }),
          );
        }
        if (detailRequests.length === 3) {
          return rejectRead(new AppError(AppErrorKind.NETWORK, "PRIVATE_INSTANCE_DETAIL_ENDPOINT"));
        }
        const value = detailFor(receivedQuery);
        detailSnapshot = Object.freeze({
          status: "ready",
          key,
          data: value,
          receivedAt: value.asOfMs,
        });
        for (const listener of detailListeners) listener();
        return value;
      },
      cancel() {},
      reset() {
        resetCount += 1;
        detailSnapshot = Object.freeze({ status: "idle" });
        for (const listener of detailListeners) listener();
      },
      dispose() {},
    };

    let selection = null;
    const selectionChanges = [];
    const queryChanges = [];
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;
    const renderPage = async () =>
      React.act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              AstryxProvider,
              null,
              React.createElement(InstanceObservationPage, {
                resources: { catalog: catalogResource, detail: detailResource },
                query,
                selection,
                onQueryChange: (next) => queryChanges.push(next),
                onSelectionChange: (next) => {
                  selection = next;
                  selectionChanges.push(next);
                },
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

    await renderPage();
    const firstInstanceRow = host.querySelector(
      `[data-observed-instance="${selectedInstance.instanceId}"]`,
    );
    assert.ok(firstInstanceRow);
    const inspect = [...firstInstanceRow.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Inspect"),
    );
    assert.ok(inspect);
    await React.act(async () =>
      inspect.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(instanceDetailKey(selection), instanceDetailKey(initialSelection));
    assert.equal(selection.processEpoch, selectedInstance.processEpoch);
    await renderPage();

    assert.equal(detailRequests.length, 1, "selecting an instance reads its exact detail query");
    assert.equal(detailRequests[0].context.instanceId, selectedInstance.instanceId);
    assert.equal(detailRequests[0].processEpoch, selectedInstance.processEpoch);
    assert.deepEqual(detailRequests[0].context.window, query.context.window);
    assert.equal(host.querySelector('[data-query-state="error"]') !== null, true);
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_INSTANCE_DETAIL_ENDPOINT/);

    const retry = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry reading"),
    );
    assert.ok(retry, "the mounted detail offers explicit retry after a transient failure");
    await React.act(async () =>
      retry.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(detailRequests.length, 2);
    assert.equal(
      instanceDetailKey(detailRequests[1]),
      instanceDetailKey(detailRequests[0]),
      "retry preserves the exact app, instance, process epoch, layer, and time window",
    );
    assert.match(host.textContent ?? "", /new process incarnation/i);
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_RETIRED_INSTANCE_DETAIL/);
    assert.equal(host.querySelector("[data-instance-receipt]"), null);

    const clearSelection = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Clear instance selection"),
    );
    assert.ok(clearSelection, "retired process identity offers an explicit clear action");
    await React.act(async () =>
      clearSelection.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    await renderPage();
    assert.equal(selection, null);
    assert.ok(
      resetCount > 0,
      "clearing selection resets detail state instead of retaining old facts",
    );
    assert.equal(host.querySelector("[data-instance-receipt]"), null);

    const reselectRow = host.querySelector(
      `[data-observed-instance="${selectedInstance.instanceId}"]`,
    );
    assert.ok(reselectRow);
    const inspectAgain = [...reselectRow.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Inspect"),
    );
    assert.ok(inspectAgain);
    await React.act(async () =>
      inspectAgain.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    await renderPage();
    assert.equal(detailRequests.length, 3);
    assert.equal(detailRequests[2].processEpoch, selectedInstance.processEpoch);
    const hostScope = [...host.querySelectorAll("button")].find(
      (button) =>
        button.getAttribute("aria-pressed") === "false" && button.textContent?.includes("Host"),
    );
    assert.ok(hostScope, "scope changes remain explicit and reflect the selected layer state");
    await React.act(async () =>
      hostScope.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    await renderPage();
    assert.equal(detailRequests.length, 4);
    assert.equal(detailRequests[3].context.scope, "host");
    assert.equal(detailRequests[3].processEpoch, selectedInstance.processEpoch);
    assert.equal(instanceDetailKey(detailRequests[3]), instanceDetailKey(selection));
    assert.ok(host.querySelector("[data-instance-unsupported]"));
    assert.equal(host.querySelectorAll("[data-metric-card]").length, 0);
    assert.equal(catalogReads, 1, "detail retries do not reload or mutate the directory query");
    assert.deepEqual(
      queryChanges,
      [],
      "detail selection and retry do not rewrite URL-owned filters",
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
