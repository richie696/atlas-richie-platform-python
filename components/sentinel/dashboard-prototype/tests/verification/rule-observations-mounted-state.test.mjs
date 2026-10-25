import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("mounted rules panel keeps provider, current runtime, and historical load evidence distinct", async () => {
  const browser = new Window({ url: "http://localhost/#/rules?environment=production" });
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
  let mounted = false;
  let act;
  let bindingStates;
  let loadObservations;
  let loadObservationHistory;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { RuleRuntimeObservationPanel },
      {
        createRuleBindingStatesResource,
        createRuleLoadObservationResource,
        createRuleLoadObservationHistoryResource,
      },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/rules/ui/RuleRuntimeObservationPanel.tsx"),
      vite.ssrLoadModule("/src/features/rules/application/ruleObservationResources.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;
    const catalogs = await Promise.all(
      ["rules", "shell", "observation"].map(async (name) =>
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

    const binding = {
      id: "flow-orders",
      environmentId: "production",
      appId: "orders",
      kind: "flow",
      profile: "sentinel-python-v1",
      sourceId: "nacos-prod",
      sourceLabel: "Nacos production",
      location: "public/DEFAULT_GROUP/flow-rules.json",
    };
    const states = [
      ["current_with_rules", 2, true, "rev-1"],
      ["configured_empty", 0, true, "rev-2"],
      ["target_missing", null, false, null],
      ["content_invalid", null, true, null],
      ["unsupported_profile", null, false, null],
      ["source_unavailable", null, true, null],
      ["not_read", null, false, null],
    ];
    const bindingPage = {
      query: { environmentId: "production", appId: null, kind: null, page: 1, pageSize: 100 },
      asOf: "2026-10-16T08:00:00.000Z",
      coverage: "complete",
      total: states.length,
      hasMore: false,
      items: states.map(([state, ruleCount, hasLastKnownGood, sourceRevision], index) => ({
        binding: { ...binding, id: `binding-${index}`, kind: index === 1 ? "flow" : binding.kind },
        state,
        ruleCount,
        sourceRevision,
        lastAttemptAt: state === "not_read" ? null : "2026-10-16T07:59:00.000Z",
        freshness:
          state === "not_read"
            ? "not_read"
            : hasLastKnownGood && !["current_with_rules", "configured_empty"].includes(state)
              ? "stale"
              : "current",
        hasLastKnownGood,
      })),
    };
    const runtimePage = {
      query: {
        environmentId: "production",
        appId: "orders",
        bindingId: "flow-orders",
        instanceId: null,
        page: 1,
        pageSize: 100,
      },
      asOf: "2026-10-16T08:00:00.000Z",
      coverage: "complete",
      targets: {
        source: "active_reporter_enrollment",
        expected: 2,
        observed: 1,
        stale: 1,
        notObserved: 1,
      },
      total: 2,
      hasMore: false,
      items: [
        {
          bindingId: "flow-orders",
          instanceId: "worker-0",
          processId: "pid-100",
          processEpoch: "epoch-1",
          profileId: "sentinel-python-v1",
          loadState: "applied",
          eventKind: "snapshot_applied",
          activeSnapshot: {
            sourceRevision: "rev-1",
            canonicalRulesSha256: "a".repeat(64),
            membershipComplete: false,
            members: [],
          },
          attempt: null,
          observedAt: "2026-10-16T07:58:00.000Z",
          receivedAt: "2026-10-16T07:58:01.000Z",
          freshness: "stale",
        },
        {
          bindingId: "flow-orders",
          instanceId: "worker-1",
          processId: "pid-101",
          processEpoch: "epoch-2",
          profileId: null,
          loadState: "not_observed",
          eventKind: null,
          activeSnapshot: null,
          attempt: null,
          observedAt: null,
          receivedAt: null,
          freshness: "unknown",
        },
      ],
    };
    const calls = [];
    let historyIsEmpty = false;
    const port = {
      async readBindingStates(query) {
        calls.push(["binding", query]);
        return bindingPage;
      },
      async readRuleLoadObservations(query) {
        calls.push(["runtime", query]);
        return runtimePage;
      },
      async readRuleLoadObservationHistory(query) {
        calls.push(["history", query]);
        if (historyIsEmpty)
          return {
            query,
            asOf: "2026-10-17T08:00:00.000Z",
            coverage: "complete",
            total: 0,
            hasMore: false,
            items: [],
          };
        return {
          query,
          asOf: "2026-10-17T08:00:00.000Z",
          coverage: "complete",
          total: 2,
          hasMore: query.page === 1,
          items: [
            {
              observationId: `observation-old-${query.page}`,
              epochStatus: "superseded",
              observation: {
                ...runtimePage.items[0],
                processEpoch: `epoch-old-${query.page}`,
                receivedAt: "2026-10-15T08:00:00.000Z",
              },
            },
          ],
        };
      },
    };
    const access = {
      read: () => ({ ownerKey: "admin", allowed: true }),
      subscribe: () => () => {},
    };
    bindingStates = createRuleBindingStatesResource(port, access);
    loadObservations = createRuleLoadObservationResource(port, access);
    loadObservationHistory = createRuleLoadObservationHistoryResource(port, access);
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
            React.createElement(RuleRuntimeObservationPanel, {
              bindingStates,
              loadObservations,
              loadObservationHistory,
              query: {
                environmentId: "production",
                appId: null,
                kind: null,
                page: 1,
                pageSize: 100,
              },
              selectedBinding: binding,
              onSelectBinding() {},
            }),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    for (const key of states.map(([state]) => `rules.observations.bindingState.${state}`))
      assert.ok(host.textContent?.includes(i18n.t(key)), `visible provider state ${key}`);
    assert.match(host.textContent ?? "", /2 expected|Expected 2|expected: 2/i);
    assert.match(host.textContent ?? "", /worker-0/);
    assert.match(host.textContent ?? "", /worker-1/);
    assert.match(host.textContent ?? "", /Rule membership is unknown/);
    assert.match(host.textContent ?? "", /unknown/i);
    assert.equal(calls.filter(([kind]) => kind === "binding").length, 1);
    assert.equal(calls.filter(([kind]) => kind === "runtime").length, 1);
    assert.doesNotMatch(host.textContent ?? "", /unsupported.*not loaded|not loaded.*unsupported/i);

    const historyButton = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes(i18n.t("rules.observations.showHistory")),
    );
    assert.ok(historyButton, "history is opt-in and separately presented");
    await React.act(async () => {
      historyButton.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.match(host.textContent ?? "", /Historical process observations/);
    assert.match(host.textContent ?? "", /Superseded by a newer process epoch/);
    assert.match(host.textContent ?? "", /epoch-old/);
    assert.equal(calls.filter(([kind]) => kind === "history").length, 1);
    assert.equal(calls.find(([kind]) => kind === "history")[1].bindingId, "flow-orders");
    assert.match(host.textContent ?? "", /2 expected|Expected 2|expected: 2/i);
    assert.match(host.textContent ?? "", /epoch-old-1/);
    const nextHistoryPage = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes(i18n.t("rules.observations.historyNext")),
    );
    assert.ok(nextHistoryPage, "server pagination exposes the next page");
    await React.act(async () => {
      nextHistoryPage.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.match(host.textContent ?? "", /epoch-old-2/);
    const historyQueries = calls.filter(([kind]) => kind === "history").map(([, query]) => query);
    assert.deepEqual(
      historyQueries.map(({ bindingId, page }) => [bindingId, page]),
      [
        ["flow-orders", 1],
        ["flow-orders", 2],
      ],
    );

    const hideHistoryButton = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes(i18n.t("rules.observations.hideHistory")),
    );
    assert.ok(hideHistoryButton, "history can be collapsed after a successful read");
    await React.act(async () => {
      hideHistoryButton.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    historyIsEmpty = true;
    const showHistoryAgain = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes(i18n.t("rules.observations.showHistory")),
    );
    assert.ok(showHistoryAgain);
    await React.act(async () => {
      showHistoryAgain.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.ok(host.textContent?.includes(i18n.t("rules.observations.historyEmpty")));
    assert.ok(
      [...host.querySelectorAll("button")].some((button) =>
        button.textContent?.includes(i18n.t("rules.observations.hideHistory")),
      ),
      "empty history still offers a way to collapse the section",
    );

    await React.act(async () => root.unmount());
    mounted = false;
    host.remove();
  } finally {
    bindingStates?.cancel();
    loadObservations?.cancel();
    loadObservationHistory?.cancel();
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
