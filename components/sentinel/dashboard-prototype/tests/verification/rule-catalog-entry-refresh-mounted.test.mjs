import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T03.4/T06.7 mounted rule directory keeps provider and stale instance facts distinct", async () => {
  const browser = new Window({ url: "http://localhost/#/rules?env=prod&app=all" });
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
  let React;
  let createRoot;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { RuleConsoleContainer },
      { AstryxProvider },
      { SessionProvider },
      ReactModule,
      ReactDom,
      { I18nextProvider },
      { SESSION_CAPABILITY },
      { loadAstryxLocaleCatalog },
      { ruleMemberFingerprint },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/rules/ui/RuleConsoleContainer.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      vite.ssrLoadModule("/src/core/session/SessionProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
      vite.ssrLoadModule("/src/core/session/capabilities.ts"),
      vite.ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts"),
      vite.ssrLoadModule("/src/features/rules/application/ruleMemberFingerprint.ts"),
    ]);
    React = ReactModule;
    createRoot = ReactDom.createRoot;
    await loadAstryxLocaleCatalog("en-US");
    const catalogs = await Promise.all(
      ["rules", "shell"].map(async (name) =>
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

    const calls = [];
    const navigationCalls = [];
    const now = Date.UTC(2026, 9, 16, 8);
    const asOf = new Date(now).toISOString();
    const binding = {
      id: "checkout-prod-flow",
      environmentId: "prod",
      appId: "checkout",
      kind: "flow",
      profile: "sentinel-java-v1",
      sourceId: "nacos-prod",
      sourceLabel: "Production Nacos",
      location: "checkout-flow-rules",
    };
    const catalogEntry = {
      binding,
      record: {
        id: "checkout-submit",
        rule: {
          kind: "flow",
          value: {
            resource: "POST /checkout",
            limitApp: "default",
            grade: 1,
            count: 17,
            strategy: 0,
            controlBehavior: 0,
            clusterMode: false,
          },
        },
      },
      snapshot: {
        checksum: "nacos-md5-checksum-1",
        sourceRevision: "nacos-revision-1",
        versionId: null,
        asOf,
      },
      read: { freshness: "current", lastAttemptAt: asOf },
    };
    const fingerprint = await ruleMemberFingerprint(catalogEntry);
    assert.ok(fingerprint);
    const ruleSetPort = {
      async refreshRuleCatalog(environmentId, appId, signal) {
        signal.throwIfAborted();
        calls.push(["refresh", environmentId, appId]);
        return {
          scope: { environmentId, appId },
          asOf,
          coverage: "complete",
          bindings: { total: 1, attempted: 1, current: 1, stale: 0, notRead: 0 },
        };
      },
      async readRuleCatalog(receivedQuery, signal) {
        signal.throwIfAborted();
        calls.push(["catalog", receivedQuery.environmentId]);
        return {
          query: receivedQuery,
          asOf,
          coverage: "complete",
          bindings: { total: 1, current: 1, stale: 0, notRead: 0 },
          total: 1,
          hasMore: false,
          items: [catalogEntry],
          issues: [],
        };
      },
      async readBindings(receivedQuery, signal) {
        signal.throwIfAborted();
        return { query: receivedQuery, total: 0, items: [] };
      },
      async readSnapshot(bindingId, signal) {
        signal.throwIfAborted();
        assert.equal(bindingId, binding.id);
        return {
          binding,
          versionId: null,
          checksum: "baseline-checksum",
          sourceRevision: "nacos-revision-1",
          asOfMs: now,
          records: [],
        };
      },
      async readDrafts(bindingId, signal) {
        signal.throwIfAborted();
        return { bindingId, asOfMs: now, items: [] };
      },
      async readVersions(bindingId, signal) {
        signal.throwIfAborted();
        return { bindingId, asOfMs: now, items: [] };
      },
      async readPublications(bindingId, signal) {
        signal.throwIfAborted();
        calls.push(["publications", bindingId]);
        return { bindingId, asOfMs: now, items: [] };
      },
      async readPlans(bindingId, signal) {
        signal.throwIfAborted();
        return { bindingId, asOfMs: now, items: [] };
      },
      async readPublicationTarget(bindingId, signal) {
        signal.throwIfAborted();
        return { bindingId, target: null };
      },
      async readPublication() {
        throw new Error("no publication should be selected automatically");
      },
      async readReceipts() {
        throw new Error("receipts require explicit publication selection");
      },
    };
    const runtimeObservation = (index) =>
      index === 21
        ? {
            bindingId: binding.id,
            instanceId: `checkout-worker-${index}`,
            processId: `pid-${2000 + index}`,
            processEpoch: null,
            profileId: null,
            loadState: "not_observed",
            eventKind: null,
            activeSnapshot: null,
            attempt: null,
            observedAt: null,
            receivedAt: null,
            freshness: "unknown",
          }
        : {
            bindingId: binding.id,
            instanceId: `checkout-worker-${index}`,
            processId: `pid-${2000 + index}`,
            processEpoch: `epoch-live-${index}`,
            profileId: binding.profile,
            loadState: "applied",
            eventKind: "snapshot_applied",
            activeSnapshot: {
              sourceRevision: "nacos-revision-1",
              canonicalRulesSha256: "a".repeat(64),
              membershipComplete: true,
              members: [{ ruleKind: "flow", fingerprintSha256: fingerprint }],
            },
            attempt: null,
            observedAt: asOf,
            receivedAt: asOf,
            freshness: index === 2 ? "stale" : "current",
          };
    const observationPort = {
      async readBindingStates(query) {
        return {
          query,
          asOf,
          coverage: "complete",
          total: 1,
          hasMore: false,
          items: [
            {
              binding,
              state: "current_with_rules",
              ruleCount: 1,
              sourceRevision: "nacos-revision-1",
              lastAttemptAt: asOf,
              freshness: "current",
              hasLastKnownGood: true,
            },
          ],
        };
      },
      async readRuleLoadObservations(query) {
        const items = Array.from({ length: 21 }, (_, index) => runtimeObservation(index + 1)).slice(
          (query.page - 1) * query.pageSize,
          query.page * query.pageSize,
        );
        return {
          query,
          asOf,
          coverage: "complete",
          targets: {
            source: "active_reporter_enrollment",
            expected: 21,
            observed: 20,
            stale: 1,
            notObserved: 1,
          },
          total: 21,
          hasMore: (query.page - 1) * query.pageSize + items.length < 21,
          items,
        };
      },
    };
    const scopePort = {
      async readRuleBindingScopes(signal) {
        signal.throwIfAborted();
        return {
          asOfMs: now,
          environments: [{ id: "prod", name: "Production" }],
          applications: [],
        };
      },
    };
    const sourceCatalogPort = {
      async readSources() {
        return { asOfMs: now, items: [] };
      },
    };
    const props = {
      scopePort,
      ruleSetPort,
      observationPort,
      sourceCatalogPort,
      appId: "all",
      range: "1h",
      navigate(...args) {
        navigationCalls.push(args);
      },
      setAppId() {},
      setRange() {},
      locale: "en-US",
      view: "all",
      environmentId: "prod",
      bindingId: binding.id,
    };
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
            React.createElement(
              SessionProvider,
              {
                session: {
                  roleId: "admin",
                  capabilities: [SESSION_CAPABILITY.MetricsView, SESSION_CAPABILITY.RulesWrite],
                },
              },
              React.createElement(RuleConsoleContainer, props),
            ),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const refreshIndex = calls.findIndex(([kind]) => kind === "refresh");
    assert.notEqual(refreshIndex, -1, "mount actively refreshes the registered provider scope");
    assert.deepEqual(calls[refreshIndex], ["refresh", "prod", null]);
    assert.notEqual(
      calls.findIndex(([kind], index) => index > refreshIndex && kind === "catalog"),
      -1,
      "a successful provider refresh reloads the confirmed SQL projection",
    );
    assert.equal(host.textContent.includes("POST /checkout"), true);
    assert.equal(host.textContent.includes("17"), true);
    assert.equal(
      host.textContent.includes("Unavailable; runtime reports resource-level traffic only"),
      true,
    );
    assert.equal(host.textContent.includes("Production Nacos"), true);
    assert.ok(
      host.querySelector("[data-rule-workspace]"),
      "explicitly routed binding keeps its workbench mounted",
    );
    await React.act(async () => host.querySelector('[data-rule-action="begin"]')?.click());
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    await React.act(async () => host.querySelector('[data-rule-action="add"]')?.click());
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    const dirtyDraft = host.querySelector("[data-rule-dirty]");
    assert.ok(dirtyDraft, "a local draft is started before switching detail panes");
    assert.equal(dirtyDraft.textContent, i18n.t("rules.workspace.unsaved"));
    assert.equal(
      host.textContent.includes(
        i18n.t("rules.catalog.instanceUsage", {
          loaded: "19",
          expected: "21",
          notIncluded: "0",
          unconfirmed: "2",
        }),
      ),
      true,
      "complete inventory keeps confirmed loaded and unconfirmed counts visible",
    );
    assert.equal(
      host.querySelector('[data-rule-binding-open="checkout-prod-flow"]') !== null,
      true,
    );
    assert.equal(host.querySelector("[data-rule-detail-panel]"), null, "no rule is auto-selected");
    const toggle = host.querySelector("[data-rule-usage-toggle]");
    assert.ok(toggle, "each catalog rule can open exact runtime membership details");
    const loadedCount = host.querySelector("[data-rule-loaded-count]");
    assert.ok(loadedCount, "the confirmed loaded count is an accessible detail entry point");
    await React.act(async () => loadedCount.click());
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    assert.equal(
      host.querySelector('[data-rule-detail-pane="instances"]').getAttribute("aria-selected"),
      "true",
    );
    assert.equal(
      host.querySelector("[data-rule-detail-panel]").getAttribute("data-rule-detail-panel"),
      "instances",
    );
    assert.equal(host.textContent.includes("checkout-worker-1"), true);
    assert.equal(host.textContent.includes("epoch-live-1"), true);
    assert.equal(host.textContent.includes("The active snapshot includes this rule"), true);
    const instanceRows = host.querySelectorAll('[data-rule-detail-panel="instances"] tr');
    const staleRow = [...instanceRows].find((row) =>
      row.textContent?.includes("checkout-worker-2"),
    );
    assert.ok(staleRow);
    assert.equal(staleRow.textContent.includes(i18n.t("rules.catalog.membership.unknown")), true);
    const nextInstances = host.querySelector("[data-instance-page-next]");
    assert.ok(nextInstances);
    assert.equal(nextInstances.disabled, false);
    await React.act(async () => nextInstances.click());
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    assert.equal(host.textContent.includes("checkout-worker-21"), true);
    const unobservedRow = [
      ...host.querySelectorAll('[data-rule-detail-panel="instances"] tr'),
    ].find((row) => row.textContent?.includes("checkout-worker-21"));
    assert.ok(unobservedRow);
    assert.equal(
      unobservedRow.textContent.includes(i18n.t("rules.catalog.membership.unknown")),
      true,
    );

    await React.act(async () => toggle.click());
    await React.act(async () => toggle.click());
    assert.equal(
      host.querySelector('[data-rule-detail-pane="configuration"]').getAttribute("aria-selected"),
      "true",
    );
    assert.ok(
      host.querySelector("[data-rule-configuration]"),
      "configuration is the default pane when explicitly opened",
    );
    await React.act(async () => host.querySelector('[data-rule-detail-pane="effects"]').click());
    assert.equal(host.textContent.includes(i18n.t("rules.catalog.ruleEffectUnavailable")), true);
    await React.act(async () => host.querySelector('[data-rule-detail-pane="history"]').click());
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    assert.ok(host.querySelector("[data-rule-publication-history]"));
    assert.equal(
      calls.some(([kind, id]) => kind === "publications" && id === binding.id),
      true,
    );
    assert.equal(
      calls.some(([kind]) => kind === "catalog"),
      true,
    );
    assert.equal(
      host.querySelector("[data-publication-detail]"),
      null,
      "history does not auto-select a publication",
    );
    assert.deepEqual(
      navigationCalls,
      [],
      "detail-pane navigation does not change the routed binding",
    );
    assert.equal(
      host.querySelector("[data-rule-dirty]")?.textContent,
      i18n.t("rules.workspace.unsaved"),
    );
  } finally {
    if (mounted) await React.act(async () => root.unmount());
    await vite?.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
