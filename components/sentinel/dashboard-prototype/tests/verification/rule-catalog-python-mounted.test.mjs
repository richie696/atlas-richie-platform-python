import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";
import {
  startLiveRuleCatalogConsole,
  stopLiveRuleCatalogConsole,
} from "../support/liveConsoleProcess.mjs";

const SESSION = "synthetic-rule-catalog-session-token-000000000001";

test(
  "T03.4 mounted Rules page renders the authenticated Python Console catalog response",
  { timeout: 120_000 },
  async () => {
    const externalBaseUrl = process.env.SENTINEL_CONSOLE_BASE_URL;
    const console = externalBaseUrl ? null : await startLiveRuleCatalogConsole();
    const environmentId = process.env.SENTINEL_RULE_CATALOG_ENVIRONMENT ?? "prod";
    const appId = process.env.SENTINEL_RULE_CATALOG_APP ?? "checkout";
    const resource = process.env.SENTINEL_RULE_CATALOG_RESOURCE ?? "POST /checkout";
    const sourceLabel = process.env.SENTINEL_RULE_CATALOG_SOURCE ?? "Integration Nacos";
    const browser = new Window({
      url: `http://localhost/#/rules?env=${environmentId}&app=${appId}`,
    });
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
    installGlobal("CSS", {
      escape: (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&"),
    });
    installGlobal("IS_REACT_ACT_ENVIRONMENT", true);

    let vite;
    let root;
    let mounted = false;
    let React;
    let transport;
    let output = console?.output ?? (() => "");
    const httpCalls = [];
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
        { createConsoleTransport },
        { createRuleSetHttp },
        { createIdentityHttp },
      ] = await Promise.all([
        vite.ssrLoadModule("/src/features/rules/ui/RuleConsoleContainer.tsx"),
        vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
        vite.ssrLoadModule("/src/core/session/SessionProvider.tsx"),
        import("react"),
        import("react-dom/client"),
        import("react-i18next"),
        vite.ssrLoadModule("/src/core/session/capabilities.ts"),
        vite.ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts"),
        vite.ssrLoadModule("/src/core/api/transport/consoleTransport.ts"),
        vite.ssrLoadModule("/src/features/rules/api/ruleSetHttp.ts"),
        vite.ssrLoadModule("/src/features/identity/api/identityAccessHttp.ts"),
      ]);
      React = ReactModule;
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

      let csrfCookie = "";
      transport = createConsoleTransport({
        baseUrl: externalBaseUrl ?? `http://127.0.0.1:${console.port}`,
        owner: () => "rule-catalog-mounted-live-test",
        onUnauthorized: () => {},
        fetch: async (input, init) => {
          const request = new Request(input, init);
          request.headers.set(
            "cookie",
            `sentinel_session=${SESSION}${csrfCookie ? `; __Host-sentinel_csrf=${csrfCookie}` : ""}`,
          );
          request.headers.set("origin", "http://localhost:5173");
          const response = await fetch(request);
          httpCalls.push(
            `${request.method} ${new URL(request.url).pathname} -> ${response.status}`,
          );
          csrfCookie = response.headers.get("x-sentinel-csrf") ?? csrfCookie;
          return response;
        },
      });
      await createIdentityHttp(transport).readBootstrap(new AbortController().signal);
      assert.match(csrfCookie, /^[A-Za-z0-9_-]{32,256}$/);

      const ruleSetPort = {
        ...createRuleSetHttp(transport),
        async readBindings(query, signal) {
          signal.throwIfAborted();
          return { query, total: 0, items: [] };
        },
      };
      const scopePort = {
        async readRuleBindingScopes(signal) {
          signal.throwIfAborted();
          return {
            asOfMs: Date.parse("2026-10-16T08:00:00Z"),
            environments: [{ id: environmentId, name: environmentId }],
            applications: [{ id: appId, environmentId, name: appId }],
          };
        },
      };
      const sourceCatalogPort = {
        async readSources() {
          return {
            asOfMs: Date.now(),
            items: [
              {
                id: "nacos-primary",
                revision: "source-revision-1",
                name: "Primary Nacos",
                provider: "nacos",
                namespace: "public",
              },
            ],
          };
        },
      };
      const host = browser.document.createElement("main");
      browser.document.body.append(host);
      root = ReactDom.createRoot(host);
      mounted = true;
      await React.act(async () => {
        root.render(
          React.createElement(
            React.StrictMode,
            null,
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
                  React.createElement(RuleConsoleContainer, {
                    scopePort,
                    ruleSetPort,
                    sourceCatalogPort,
                    appId,
                    range: "1h",
                    navigate() {},
                    setAppId() {},
                    setRange() {},
                    locale: "en-US",
                    view: "all",
                    environmentId,
                  }),
                ),
              ),
            ),
          ),
        );
      });
      const deadline = Date.now() + 30_000;
      while (
        (!host.textContent.includes(resource) ||
          !httpCalls.some((call) => call.startsWith("POST /api/v2/rules/catalog/refresh ->"))) &&
        Date.now() < deadline
      ) {
        await React.act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
      }
      assert.equal(host.textContent.includes(resource), true);
      assert.equal(host.textContent.includes(sourceLabel), true);
      assert.match(host.textContent, /17/);
      assert.ok(
        httpCalls.some((call) => call.startsWith("POST /api/v2/rules/catalog/refresh -> 200")),
        `Refresh route did not return 200: ${httpCalls.join("; ")}\n${host.textContent}`,
      );
      assert.ok(
        httpCalls.some((call) => call.startsWith("GET /api/v2/rules/catalog -> 200")),
        `Catalog route did not return 200: ${httpCalls.join("; ")}`,
      );
      const registerButton = [...host.querySelectorAll("button")].find((button) =>
        button.textContent?.includes("Register rule binding"),
      );
      assert.ok(registerButton, "The administrator should be able to open binding registration");
      await React.act(async () => registerButton.click());
      const sourceDeadline = Date.now() + 5_000;
      while (!host.textContent.includes("Primary Nacos") && Date.now() < sourceDeadline) {
        await React.act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
      }
      assert.ok(
        host.textContent.includes("Primary Nacos"),
        `StrictMode must leave the source catalog live for the dialog: ${host.textContent}`,
      );
    } catch (error) {
      if (output()) error.message += `\nPython Console output:\n${output()}`;
      error.message += `\nObserved HTTP calls: ${httpCalls.join("; ") || "none"}`;
      throw error;
    } finally {
      if (mounted) await React.act(async () => root.unmount());
      transport?.dispose();
      await vite?.close();
      if (console) await stopLiveRuleCatalogConsole(console.child);
      for (const [name, descriptor] of priorGlobals) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
      }
      browser.happyDOM.abort();
    }
  },
);
