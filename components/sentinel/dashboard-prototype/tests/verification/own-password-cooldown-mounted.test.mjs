import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createServer } from "vite";

const identity = Object.freeze({
  accountId: "synthetic-viewer",
  username: "synthetic-viewer",
  roleId: "view",
  capabilities: ["metrics:view"],
  sessionEpoch: "synthetic-password-session",
});

test("F4.32 mounted own-password page applies 429 cooldown, releases it without auto-submit, and cleans up", async () => {
  const browser = new Window({ url: "http://localhost/change-password" });
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
  let act;
  let workflow;
  const activeIntervals = new Set();
  const setInterval = browser.setInterval.bind(browser);
  const clearInterval = browser.clearInterval.bind(browser);
  browser.setInterval = (callback, delay) => {
    const timer = setInterval(callback, delay);
    activeIntervals.add(timer);
    return timer;
  };
  browser.clearInterval = (timer) => {
    activeIntervals.delete(timer);
    return clearInterval(timer);
  };
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { OwnPasswordPage },
      { createOwnPasswordWorkflow },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/identity/ui/OwnPasswordPage.tsx"),
      vite.ssrLoadModule("/src/features/identity/application/ownPasswordWorkflow.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const identityMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/en-US/identity.json", import.meta.url)),
    );
    const shellMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/en-US/shell.json", import.meta.url)),
    );
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      nsSeparator: false,
      resources: { "en-US": { translation: { ...identityMessages, ...shellMessages } } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const access = new StateStore({
      phase: "resolved",
      facts: { kind: "authenticated", identity },
    });
    let now = 10_000;
    let calls = 0;
    workflow = createOwnPasswordWorkflow(
      {
        changeOwnPassword: async () => {
          calls += 1;
          throw new AppError(AppErrorKind.RATE_LIMITED, "synthetic rate limit", {
            status: 429,
            code: "rate_limited",
            retryAfterMs: 750,
          });
        },
      },
      identity,
      { read: access.getSnapshot, subscribe: access.subscribe },
      { clock: () => now },
    );
    await assert.rejects(
      workflow.submit({
        current: "Synthetic-Current-Password",
        next: "Synthetic-New-Password",
        confirm: "Synthetic-New-Password",
      }),
      (error) => error.code === "rate_limited",
    );
    assert.equal(calls, 1, "one synthetic rejected command creates the server cooldown");

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    const renderPage = async () => {
      root = createRoot(host);
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
                React.createElement(OwnPasswordPage, {
                  workflow,
                  identity,
                  onConfirmed: () =>
                    assert.fail("a rejected command cannot confirm password change"),
                  onReauthenticate: () => {},
                }),
              ),
            ),
          ),
        );
        await Promise.resolve();
      });
    };
    await renderPage();

    const submit = host.querySelector('form button[type="submit"]');
    assert.ok(submit, "the actual own-password form submit control is mounted");
    assert.equal(submit.disabled, true, "server-advised cooldown disables the form command");
    assert.match(host.textContent ?? "", /temporarily rate-limited/i);
    assert.equal(activeIntervals.size, 1, "the mounted cooldown owns one countdown timer");

    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(activeIntervals.size, 0, "leaving during cooldown releases its timer");

    await renderPage();
    const remountedSubmit = host.querySelector('form button[type="submit"]');
    assert.ok(remountedSubmit);
    assert.equal(remountedSubmit.disabled, true, "remount preserves the in-memory server deadline");
    assert.equal(
      activeIntervals.size,
      1,
      "remount acquires exactly one timer for the active owner",
    );

    now += 750;
    await React.act(async () => new Promise((resolve) => setTimeout(resolve, 350)));
    assert.equal(
      remountedSubmit.disabled,
      false,
      "the mounted cooldown projection observes its deadline",
    );
    assert.equal(calls, 1, "cooldown expiry enables an explicit action but never auto-submits");
    assert.equal(activeIntervals.size, 0, "the countdown timer is released when cooling completes");

    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(activeIntervals.size, 0, "unmount leaves no cooldown timer behind");
    host.remove();
  } finally {
    if (root && mounted && act) await act(async () => root.unmount());
    workflow?.dispose();
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
