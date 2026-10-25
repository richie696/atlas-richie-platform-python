import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T05.3 mounted host-collection guide separates onboarding paths from confirmed readiness", async () => {
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
  let resource;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { HostCollectionGuide },
      { createQueryResource },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/system/ui/HostCollectionGuide.tsx"),
      vite.ssrLoadModule("/src/shared/state/queryResource.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const systemMessages = JSON.parse(
      await readFile(
        new URL("../../src/app/i18n/messages/en-US/system.json", import.meta.url),
        "utf8",
      ),
    );
    const shellMessages = JSON.parse(
      await readFile(
        new URL("../../src/app/i18n/messages/en-US/shell.json", import.meta.url),
        "utf8",
      ),
    );
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      nsSeparator: false,
      interpolation: { escapeValue: false },
      resources: {
        "en-US": { translation: { ...systemMessages, ...shellMessages } },
      },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const snapshot = Object.freeze({
      catalogRevision: "host-guides-v3",
      runtimeCollector: Object.freeze({ state: "configured", endpoint: "https://collector.example.test" }),
      paths: Object.freeze([
        Object.freeze({ id: "existing", readiness: "guide-only", profileRevision: null }),
        Object.freeze({ id: "linux", readiness: "configuration-required", profileRevision: null }),
        Object.freeze({ id: "kubernetes", readiness: "guide-only", profileRevision: null }),
      ]),
    });
    let readCount = 0;
    resource = createQueryResource({
      keyOf: () => "deployment-guides",
      async read() {
        readCount += 1;
        return snapshot;
      },
      classify: () => "partial",
    });

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;
    await act(async () => {
      root.render(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(
            AstryxProvider,
            null,
            React.createElement(HostCollectionGuide, { resource }),
          ),
        ),
      );
    });

    const text = () => host.textContent ?? "";
    const waitFor = async (predicate) => {
      for (let attempt = 0; attempt < 20 && !predicate(); attempt++) {
        await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
      }
      assert.ok(predicate(), `expected mounted guide state; rendered: ${text()}`);
    };
    const buttonByName = (name) =>
      [...host.querySelectorAll("button")].find((button) => button.textContent?.trim() === name);

    await waitFor(() => text().includes("Server guide catalog revision: host-guides-v3"));
    assert.equal(readCount, 1, "initial mount reads the server-owned catalog once");
    assert.match(text(), /Prometheus stores and serves queries/);
    assert.match(text(), /https:\/\/collector\.example\.test/);
    assert.match(text(), /Operational guidance only; no validated deployment template/);

    const paths = [
      ["Linux host", "Add Linux hosts to Prometheus scraping"],
      ["Kubernetes", "Discover Kubernetes nodes through cluster collection"],
      ["Existing telemetry stack", "Reuse an existing Prometheus-compatible stack"],
    ];
    for (const [label, heading] of paths) {
      const button = buttonByName(label);
      assert.ok(button, `missing deployment path ${label}`);
      await act(async () => button.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })));
      assert.equal(button.getAttribute("aria-pressed"), "true");
      assert.ok([...host.querySelectorAll("h3")].some((node) => node.textContent === heading));
      if (label === "Linux host") {
        assert.match(text(), /Prometheus query source configuration required/);
      }
    }
    assert.equal(readCount, 1, "changing guide path never implies a new server readiness check");
  } finally {
    if (mounted) await act(async () => root.unmount());
    resource?.dispose();
    await vite?.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else Reflect.deleteProperty(globalThis, name);
    }
    browser.happyDOM.abort();
  }
});
