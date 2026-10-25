import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("explicit application scope keeps the page and its independent read visible when the catalog fails", async () => {
  const browser = new Window({ url: "http://localhost/#/applications?env=production&app=orders" });
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
  let instanceQuery;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { ApplicationsObservationContainer },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/applications/ui/ApplicationsObservationContainer.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;
    const catalogs = await Promise.all(
      ["applications", "shell", "observation", "realtime"].map(async (name) =>
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

    const catalogPort = {
      async readObservationCatalog() {
        throw new AppError(AppErrorKind.NETWORK, "PRIVATE_CATALOG_DETAIL");
      },
    };
    const instancePort = {
      async readCatalog(query) {
        instanceQuery = query;
        throw new AppError(AppErrorKind.NETWORK, "PRIVATE_INSTANCE_DETAIL");
      },
      async readInstance() {
        throw new Error("No instance detail should be read without an explicit instance selection");
      },
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
            React.createElement(ApplicationsObservationContainer, {
              appId: "orders",
              range: "1h",
              locale: "en-US",
              view: "",
              environmentId: "production",
              navigate() {},
              setAppId() {},
              setRange() {},
              catalogPort,
              instancePort,
            }),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    assert.match(host.textContent ?? "", /Applications and instances|应用与实例/i);
    assert.match(host.textContent ?? "", /catalog could not be read/i);
    assert.ok(host.querySelector("[data-observation-context]"), "explicit scope remains visible");
    assert.ok(host.querySelector('[data-query-state="error"]'), "failed reads stay explicit");
    assert.equal(instanceQuery?.context.environmentId, "production");
    assert.equal(instanceQuery?.context.appId, "orders");
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_(?:CATALOG|INSTANCE)_DETAIL/);

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
