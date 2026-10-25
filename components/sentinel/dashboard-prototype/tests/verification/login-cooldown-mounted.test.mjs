import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createServer } from "vite";

test("F4.22 mounted login keeps an active 429 deadline through edits and StrictMode cleanup", async () => {
  const browser = new Window({ url: "http://localhost/login" });
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
  let workflow;
  let LoginEntryPage;
  let AuthenticationProvider;
  let AstryxProvider;
  let I18nextProvider;
  let i18n;
  let now = 10_000;
  let loginCalls = 0;
  let sessionReads = 0;
  const activeIntervals = new Set();
  const intervalRegistrations = [];
  browser.setInterval = (callback, delay) => {
    const timer = { callback, delay };
    intervalRegistrations.push(timer);
    activeIntervals.add(timer);
    return timer;
  };
  browser.clearInterval = (timer) => activeIntervals.delete(timer);

  const port = (outcome) => ({
    readBootstrap: async (signal) => {
      signal.throwIfAborted();
      return { initialized: true };
    },
    readSession: async (signal) => {
      signal.throwIfAborted();
      sessionReads += 1;
      return null;
    },
    login: async (_credentials, signal) => {
      signal.throwIfAborted();
      loginCalls += 1;
      if (outcome === "rate")
        throw new AppError(AppErrorKind.RATE_LIMITED, "synthetic login cooldown", {
          status: 429,
          code: "rate_limited",
          retryAfterMs: 3_000,
        });
      throw new AppError(AppErrorKind.TIMEOUT, "synthetic private login error");
    },
    logout: async () => {},
  });

  const mount = async (host) => {
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
              React.createElement(
                AuthenticationProvider,
                { workflow },
                React.createElement(LoginEntryPage, {
                  onAuthenticated: () => assert.fail("a denied login cannot authenticate"),
                  onSetupRequired: () => assert.fail("an initialized console cannot enter setup"),
                }),
              ),
            ),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  };
  const field = (host, autocomplete) => {
    const input = host.querySelector(`input[autocomplete="${autocomplete}"]`);
    assert.ok(input, `the actual login ${autocomplete} field is mounted`);
    return input;
  };
  const setInput = async (input, value) => {
    await React.act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        browser.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(input, value);
      input.dispatchEvent(new browser.Event("input", { bubbles: true }));
      input.dispatchEvent(new browser.Event("change", { bubbles: true }));
    });
    assert.equal(input.value, value);
  };
  const submit = async (host) => {
    const form = host.querySelector("form");
    assert.ok(form, "the actual LoginEntryPage form is mounted");
    await React.act(async () => {
      form.dispatchEvent(new browser.Event("submit", { bubbles: true, cancelable: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  };
  const buttonText = (host, text) =>
    [...host.querySelectorAll("button")].find(
      (button) => button.textContent?.trim().replace(/\s+/g, " ") === text,
    );

  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { createAuthenticationWorkflow },
      loginPageModule,
      providerModule,
      astryxModule,
      reactModule,
      rootModule,
      reactI18nModule,
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/identity/application/authenticationWorkflow.ts"),
      vite.ssrLoadModule("/src/features/identity/ui/LoginEntryPage.tsx"),
      vite.ssrLoadModule("/src/features/identity/state/AuthenticationProvider.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    I18nextProvider = reactI18nModule.I18nextProvider;
    LoginEntryPage = loginPageModule.LoginEntryPage;
    AuthenticationProvider = providerModule.AuthenticationProvider;
    AstryxProvider = astryxModule.AstryxProvider;
    React = reactModule;
    createRoot = rootModule.createRoot;

    const identityMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/en-US/identity.json", import.meta.url)),
    );
    const shellMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/en-US/shell.json", import.meta.url)),
    );
    i18n = createInstance();
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

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    workflow = (
      await vite.ssrLoadModule("/src/features/identity/application/authenticationWorkflow.ts")
    ).createAuthenticationWorkflow(port("rate"), undefined, { clock: () => now });
    await mount(host);
    assert.ok(host.querySelector("form"), "anonymous authority exposes the real login form");

    await setInput(field(host, "username"), "synthetic-viewer");
    await setInput(field(host, "current-password"), "Synthetic-Login-Password");
    const reveal = host.querySelector('button[aria-label="Show password"]');
    assert.ok(reveal, "password visibility has an accessible icon control");
    assert.equal(reveal.type, "button", "visibility cannot submit credentials");
    assert.equal(reveal.parentElement.contains(field(host, "current-password")), true);
    await React.act(async () => reveal.click());
    assert.equal(field(host, "current-password").type, "text");
    assert.equal(reveal.getAttribute("aria-label"), "Hide password");
    assert.equal(reveal.getAttribute("aria-pressed"), "true");
    assert.equal(field(host, "current-password").value, "Synthetic-Login-Password");
    assert.equal(loginCalls, 0, "revealing a password never submits the form");
    await submit(host);
    assert.equal(field(host, "current-password").type, "password", "submission masks the password");
    const submitButton = host.querySelector('form button[type="submit"]');
    assert.ok(submitButton);
    assert.equal(loginCalls, 1, "one explicit login attempt reaches the production workflow Port");
    assert.equal(submitButton.disabled, true, "429 disables the mounted submit control");
    assert.equal(activeIntervals.size, 1, "the active cooldown owns one countdown interval");

    await setInput(field(host, "username"), "corrected-viewer");
    assert.equal(
      submitButton.disabled,
      true,
      "editing username cannot release the server deadline",
    );
    await setInput(field(host, "current-password"), "Corrected-Synthetic-Password");
    assert.equal(
      submitButton.disabled,
      true,
      "editing password cannot release the server deadline",
    );
    await submit(host);
    assert.equal(loginCalls, 1, "a form event during cooldown cannot dispatch a second login");
    assert.equal(
      activeIntervals.size,
      1,
      "credential edits retain a single active countdown owner",
    );

    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(activeIntervals.size, 0, "unmount during cooldown clears the interval");

    const registrationsBeforeRemount = intervalRegistrations.length;
    await mount(host);
    assert.equal(
      activeIntervals.size,
      1,
      "StrictMode effect replay leaves exactly one active cooldown timer after remount",
    );
    assert.ok(
      intervalRegistrations.length >= registrationsBeforeRemount + 2,
      "StrictMode ran setup-cleanup-setup for the active timer",
    );
    const remountedSubmit = host.querySelector('form button[type="submit"]');
    assert.ok(remountedSubmit);
    assert.equal(
      remountedSubmit.disabled,
      true,
      "the mounted page honors the same workflow deadline",
    );

    now += 3_000;
    await React.act(async () => {
      for (const timer of [...activeIntervals]) timer.callback();
      await Promise.resolve();
    });
    assert.equal(remountedSubmit.disabled, false, "deadline expiry restores explicit submission");
    assert.equal(loginCalls, 1, "deadline expiry never automatically replays login");
    assert.equal(activeIntervals.size, 0, "the countdown interval is released at expiry");

    await setInput(field(host, "username"), "explicit-retry-viewer");
    await setInput(field(host, "current-password"), "Explicit-Synthetic-Password");
    await submit(host);
    assert.equal(
      loginCalls,
      2,
      "only a new explicit form submission reaches the workflow after expiry",
    );
    assert.equal(
      remountedSubmit.disabled,
      true,
      "a new 429 starts a fresh server-directed cooldown",
    );
    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(
      activeIntervals.size,
      0,
      "the fresh cooldown interval is also released on unmount",
    );

    workflow.dispose();
    workflow = (
      await vite.ssrLoadModule("/src/features/identity/application/authenticationWorkflow.ts")
    ).createAuthenticationWorkflow(port("unknown"), undefined, { clock: () => now });
    await mount(host);
    await setInput(field(host, "username"), "synthetic-viewer");
    await setInput(field(host, "current-password"), "Synthetic-Login-Password");
    await submit(host);
    assert.equal(
      loginCalls,
      3,
      "the unknown-result probe makes exactly one explicit login attempt",
    );
    assert.equal(workflow.getSnapshot().login.status, "result-unknown");
    assert.equal(host.querySelector('form button[type="submit"]').disabled, true);
    await submit(host);
    assert.equal(loginCalls, 3, "unknown login outcome cannot be blindly replayed");
    assert.ok(
      buttonText(host, "Check current session"),
      "unknown outcome exposes session inspection",
    );
    assert.equal(activeIntervals.size, 0, "unknown outcome does not allocate a retry timer");
    await React.act(async () => root.unmount());
    mounted = false;
    workflow.dispose();
    workflow = null;
    host.remove();
  } finally {
    if (root && mounted && React) await React.act(async () => root.unmount());
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
