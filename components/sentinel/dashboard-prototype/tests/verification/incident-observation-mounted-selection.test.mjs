import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { StateStore } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted IncidentObservationPage selects an event and reads only its evidence", async () => {
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
  let resources;
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
      { createIncidentResources },
      { evidenceFor, incidentPageFor, incidentQuery },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/faults/ui/IncidentObservationPage.tsx"),
      vite.ssrLoadModule("/src/features/faults/application/incidentResources.ts"),
      vite.ssrLoadModule("/tests/fixtures/incidents.ts"),
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

    const access = new StateStore({ ownerKey: "incident-selection-session", allowed: true });
    const evidenceQueries = [];
    resources = createIncidentResources(
      {
        async readTimeline(query) {
          return incidentPageFor(query);
        },
        async readEvidence(query) {
          evidenceQueries.push(query);
          return evidenceFor(query);
        },
      },
      { read: access.getSnapshot, subscribe: access.subscribe },
    );
    const baseQuery = { ...incidentQuery, pageSize: 20 };
    let selectedEventId = null;
    const queryChanges = [];
    const navigations = [];
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;

    const renderPage = async () => {
      await React.act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              AstryxProvider,
              null,
              React.createElement(IncidentObservationPage, {
                resources,
                instanceSnapshot: { status: "empty", key: "catalog", data: { items: [] } },
                instances: [],
                selectedInstance: null,
                instanceTotal: 0,
                query: baseQuery,
                selectedEventId,
                onQueryChange: (next) => queryChanges.push(next),
                onSelect: (id) => {
                  selectedEventId = id;
                },
                onInstanceChange: () => {},
                environments: [{ id: baseQuery.context.environmentId, name: "Production" }],
                applications: [{ id: "app-one", name: "Orders" }],
                navigate: (...args) => navigations.push(args),
              }),
            ),
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    };

    await renderPage();
    assert.equal(host.querySelectorAll("[data-observed-incident]").length, 3);
    assert.equal(host.querySelector("[data-incident-statistics]") !== null, true);
    assert.match(host.textContent ?? "", /Select an event to inspect evidence/);
    assert.equal(evidenceQueries.length, 0, "no evidence is selected implicitly");

    const selectEvent = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("View event event-c"),
    );
    assert.ok(selectEvent, "the actual timeline exposes an explicit event selection action");
    await React.act(async () =>
      selectEvent.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(selectedEventId, "event-c");
    await renderPage();

    assert.equal(evidenceQueries.length, 1);
    assert.deepEqual(evidenceQueries[0], {
      context: baseQuery.context,
      eventId: "event-c",
      severity: null,
      category: null,
    });
    assert.ok(host.querySelector('[data-incident-evidence="event-c"]'));
    assert.deepEqual(queryChanges, [], "selecting evidence does not rewrite URL filters");
    assert.deepEqual(navigations, [], "reading evidence does not perform suggested navigation");

    await React.act(async () => root.unmount());
    mounted = false;
    host.remove();
  } finally {
    if (root && mounted && act) await act(async () => root.unmount());
    resources?.dispose();
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
