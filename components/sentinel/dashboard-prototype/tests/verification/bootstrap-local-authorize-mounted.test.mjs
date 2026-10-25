import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { initReactI18next, I18nextProvider } from "react-i18next";
import { createServer } from "vite";

test("local first-run setup obtains a code-free grant and opens the wizard", async () => {
  const browser = new Window({ url: "http://localhost/setup" });
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
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [{ BootstrapAuthorizationGate }, ReactModule, { createRoot }] = await Promise.all([
      vite.ssrLoadModule("/src/features/identity/ui/BootstrapAuthorizationGate.tsx"),
      import("react"),
      import("react-dom/client"),
    ]);
    React = ReactModule;

    const messages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/zh-CN/identity.json", import.meta.url)),
    );
    const i18n = createInstance();
    await i18n.use(initReactI18next).init({
      lng: "zh-CN",
      fallbackLng: false,
      nsSeparator: false,
      resources: { "zh-CN": { translation: messages } },
    });

    let localAuthorizationCalls = 0;
    let codeAuthorizationCalls = 0;
    const listeners = new Set();
    let snapshot = {
      gate: {
        status: "ready",
        key: "local-first-run",
        data: { kind: "open", authorized: false },
        receivedAt: 1,
      },
      command: { status: "idle" },
    };
    const workflow = {
      getSnapshot: () => snapshot,
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      async restore() {
        return snapshot.gate.data;
      },
      async authorizeLocal() {
        localAuthorizationCalls += 1;
        snapshot = {
          gate: {
            status: "ready",
            key: "local-first-run-authorized",
            data: { kind: "open", authorized: true },
            receivedAt: 2,
          },
          command: { status: "success" },
        };
        listeners.forEach((listener) => listener());
      },
      async authorize() {
        codeAuthorizationCalls += 1;
        throw new Error("local setup must not ask for a deployment code");
      },
      async inspect() {
        return snapshot.gate.data;
      },
      cancel() {},
      dispose() {},
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
            BootstrapAuthorizationGate,
            { workflow },
            React.createElement("div", { "data-setup-wizard": true }, "INITIALIZATION_WIZARD"),
          ),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    assert.equal(
      localAuthorizationCalls,
      1,
      "local install automatically uses the bounded local grant",
    );
    assert.equal(codeAuthorizationCalls, 0, "local install never submits an operator code");
    assert.ok(host.querySelector("[data-setup-wizard]"), "the authorized setup wizard is rendered");
    assert.equal(
      host.querySelector('input[type="password"]'),
      null,
      "no code field remains visible",
    );
  } finally {
    if (root && mounted) await React.act(async () => root.unmount());
    await vite?.close();
    browser.happyDOM.abort();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
