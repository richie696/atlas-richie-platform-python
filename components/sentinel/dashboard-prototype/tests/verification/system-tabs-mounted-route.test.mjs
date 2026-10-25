import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

const EMPTY_MONITORING_SOURCES = Object.freeze({
  authorized: true,
  loading: false,
  items: Object.freeze([]),
  error: null,
  busyRequestKey: null,
  unresolvedRequestKey: null,
  lastOperation: null,
});

test("T06.4 mounted system tabs render the URL-selected owner and route every tab change", async () => {
  const browser = new Window({ url: "http://localhost/#/system?view=connections" });
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
      { SystemPage },
      { SYSTEM_TABS, SYSTEM_TAB },
      { ROUTE },
      { auditQueryKey },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/system/ui/SystemPage.tsx"),
      vite.ssrLoadModule("/src/features/system/model/systemStatus.ts"),
      vite.ssrLoadModule("/src/shared/types/navigation.ts"),
      vite.ssrLoadModule("/src/features/system/model/auditObservation.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const catalogs = await Promise.all(
      ["system", "identity", "shell", "observation"].map(async (name) =>
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

    const auditQuery = {
      startMs: Date.UTC(2026, 9, 14, 11),
      endMs: Date.UTC(2026, 9, 14, 12),
      actorId: "",
      action: null,
      result: null,
      page: 1,
      pageSize: 20,
    };
    const resource = (keyOf, initialSnapshot) => {
      let listeners = new Set();
      let reads = 0;
      const snapshot = initialSnapshot ?? {
        status: "error",
        key: keyOf(keyOf === auditQueryKey ? auditQuery : null),
        error: new AppError(AppErrorKind.NETWORK, "PRIVATE_SYSTEM_PROBE_DETAIL"),
      };
      return {
        keyOf,
        getSnapshot: () => snapshot,
        subscribe(listener) {
          listeners.add(listener);
          return () => listeners.delete(listener);
        },
        async load() {
          reads += 1;
        },
        get reads() {
          return reads;
        },
        cancel() {},
        reset() {
          for (const listener of listeners) listener();
        },
        dispose() {},
      };
    };
    const observations = {
      connections: resource(() => "connections"),
      deploymentGuides: resource(() => "deployment-guides", {
        status: "partial",
        key: "deployment-guides",
        receivedAt: 1,
        data: {
          catalogRevision: "test-guides-v1",
          runtimeCollector: { state: "not_configured", endpoint: null },
          paths: ["existing", "linux", "kubernetes"].map((id) => ({
            id,
            readiness: "guide-only",
            profileRevision: null,
          })),
        },
      }),
      protocols: resource(() => "protocols"),
      audit: resource(auditQueryKey),
    };
    const monitoringSources = {
      getSnapshot: () => EMPTY_MONITORING_SOURCES,
      subscribe: () => () => {},
      async refresh() {
        return { asOf: "2026-10-17T00:00:00Z", items: [] };
      },
    };
    const access = {
      phase: "resolved",
      facts: {
        kind: "authenticated",
        identity: {
          accountId: "admin-1",
          username: "operator",
          roleId: "admin",
          capabilities: ["metrics:view", "rules:write"],
          sessionEpoch: "session-1",
        },
      },
    };
    const routeChanges = [];
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;

    const renderTab = async (view) => {
      await React.act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              AstryxProvider,
              null,
              React.createElement(SystemPage, {
                navigate: (...args) => routeChanges.push(args),
                locale: "en-US",
                view,
                identityPanels: {
                  accounts: React.createElement(
                    "p",
                    { "data-identity-panel": "accounts" },
                    "Account panel",
                  ),
                  roles: React.createElement("p", { "data-identity-panel": "roles" }, "Role panel"),
                },
                access,
                demoMode: false,
                observations,
                sourceRegistration: null,
                monitoringSources,
                canManageMonitoringSources: false,
                auditQuery,
                onAuditQueryChange() {},
              }),
            ),
          ),
        );
        await Promise.resolve();
        await Promise.resolve();
      });
    };

    const panelByTab = {
      [SYSTEM_TAB.Connections]: () =>
        assert.equal(host.querySelectorAll('[data-query-state="error"]').length, 1),
      [SYSTEM_TAB.Permissions]: () => assert.ok(host.querySelector("[data-session-permissions]")),
      [SYSTEM_TAB.Protocol]: () =>
        assert.equal(host.querySelectorAll('[data-query-state="error"]').length, 1),
      [SYSTEM_TAB.Audit]: () =>
        assert.equal(host.querySelectorAll('[data-query-state="error"]').length, 1),
      [SYSTEM_TAB.Accounts]: () =>
        assert.ok(host.querySelector('[data-identity-panel="accounts"]')),
      [SYSTEM_TAB.Roles]: () => assert.ok(host.querySelector('[data-identity-panel="roles"]')),
    };
    for (const tab of SYSTEM_TABS) {
      await renderTab(tab);
      const tabGroup = [...host.querySelectorAll('[role="group"]')].find(
        (group) => group.querySelectorAll("button").length === SYSTEM_TABS.length,
      );
      assert.ok(tabGroup?.getAttribute("aria-label"), "system tabs expose an accessible group");
      const buttons = tabGroup.querySelectorAll("button");
      const active = [...buttons].find(
        (button) => button.getAttribute("aria-pressed") === "true",
      );
      assert.ok(active, `${tab} has one active tab control`);
      assert.equal(tabGroup.querySelectorAll('button[aria-pressed="true"]').length, 1);
      panelByTab[tab]();
      assert.doesNotMatch(host.textContent ?? "", /PRIVATE_SYSTEM_PROBE_DETAIL/);

      const next = SYSTEM_TABS[(SYSTEM_TABS.indexOf(tab) + 1) % SYSTEM_TABS.length];
      const nextButton = buttons[SYSTEM_TABS.indexOf(next)];
      assert.ok(nextButton);
      await React.act(async () =>
        nextButton.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
      );
      assert.deepEqual(routeChanges.at(-1), [ROUTE.System, { view: next }]);
    }
    assert.ok(observations.connections.reads >= 1);
    assert.ok(observations.protocols.reads >= 1);
    assert.ok(observations.audit.reads >= 1);

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
