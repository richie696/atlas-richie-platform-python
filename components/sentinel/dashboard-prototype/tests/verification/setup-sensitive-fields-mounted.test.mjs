import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { initReactI18next, I18nextProvider } from "react-i18next";
import { createServer } from "vite";

const SYNTHETIC = Object.freeze({
  databaseUsername: "synthetic-db-operator",
  databasePassword: "SYNTHETIC-DB-PASSWORD",
  administratorPassword: "Synthetic-Admin-Password-42",
  sourceUsername: "synthetic-nacos-operator",
  sourcePassword: "SYNTHETIC-NACOS-PASSWORD",
});

test("F4.20/F4.21 mounted setup discards only credential material and clears after a confirmed receipt", async () => {
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
  let workflow;
  let registry;
  let portState;
  let clearSensitiveInvocations = 0;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { InitializationPage },
      { createInitializationWorkflow },
      { NavigationProtectionProvider },
      { createNavigationProtectionRegistry },
      { AstryxProvider },
      ReactModule,
      { createRoot },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/identity/ui/InitializationPage.tsx"),
      vite.ssrLoadModule("/src/features/identity/application/initializationWorkflow.ts"),
      vite.ssrLoadModule("/src/shared/state/NavigationProtectionProvider.tsx"),
      vite.ssrLoadModule("/src/shared/state/navigationProtection.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
    ]);
    React = ReactModule;

    const identityMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/zh-CN/identity.json", import.meta.url)),
    );
    const shellMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/zh-CN/shell.json", import.meta.url)),
    );
    const i18n = createInstance();
    await i18n.use(initReactI18next).init({
      lng: "zh-CN",
      fallbackLng: false,
      nsSeparator: false,
      resources: { "zh-CN": { translation: { ...identityMessages, ...shellMessages } } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("zh-CN");

    const mount = async (outcome) => {
      portState = { initialized: false, writes: 0, lookups: 0, outcome, submitted: null };
      workflow = createInitializationWorkflow(
        {
          readBootstrap: async (signal) => {
            signal.throwIfAborted();
            return {
              initialized: portState.initialized,
              setupAvailable: !portState.initialized,
              operatorAuthorized: !portState.initialized,
            };
          },
          checkDatabase: async () => ({ status: "reachable" }),
          checkSource: async () => ({ status: "reachable" }),
          initialize: async (request, signal) => {
            signal.throwIfAborted();
            portState.writes += 1;
            portState.submitted = request.input;
            assert.equal(request.input.database.password, SYNTHETIC.databasePassword);
            assert.equal(request.input.admin.password, SYNTHETIC.administratorPassword);
            assert.equal(request.input.source.authentication.password, SYNTHETIC.sourcePassword);
            if (portState.outcome === "unknown") {
              // Simulate a commit whose response was lost. The form must remain intact
              // until the exact operation is read back and confirmed.
              portState.initialized = true;
              throw new AppError(AppErrorKind.TIMEOUT, "synthetic lost response");
            }
            portState.initialized = true;
            return {
              status: "completed",
              requestKey: request.requestKey,
              operationId: "synthetic-setup-operation",
            };
          },
          readInitialization: async (requestKey, signal) => {
            signal.throwIfAborted();
            portState.lookups += 1;
            return {
              status: "completed",
              requestKey,
              operationId: "synthetic-setup-operation",
            };
          },
        },
        () => `synthetic-setup-request-${portState.writes + 1}`,
      );
      clearSensitiveInvocations = 0;
      const pageWorkflow = {
        getSnapshot: workflow.getSnapshot,
        subscribe: workflow.subscribe,
        restore: workflow.restore,
        checkDatabase: workflow.checkDatabase,
        checkSource: workflow.checkSource,
        invalidateCheck: workflow.invalidateCheck,
        invalidateChecks: () => {
          clearSensitiveInvocations += 1;
          workflow.invalidateChecks();
        },
        initialize: workflow.initialize,
        inspect: workflow.inspect,
        cancel: workflow.cancel,
        dispose: workflow.dispose,
      };
      registry = createNavigationProtectionRegistry();
      const host = browser.document.createElement("main");
      browser.document.body.append(host);
      root = createRoot(host);
      mounted = true;
      let completions = 0;
      await React.act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              AstryxProvider,
              null,
              React.createElement(
                NavigationProtectionProvider,
                { registry },
                React.createElement(InitializationPage, {
                  workflow: pageWorkflow,
                  onCompleted: () => {
                    completions += 1;
                  },
                }),
              ),
            ),
          ),
        );
        await Promise.resolve();
        await Promise.resolve();
      });
      await React.act(async () => {
        await workflow.restore();
      });
      assert.ok(host.querySelector(".setup-controls"), "the real initialization wizard is mounted");
      return {
        host,
        completions: () => completions,
        dispose: async () => {
          if (root && mounted) await React.act(async () => root.unmount());
          mounted = false;
          host.remove();
          workflow?.dispose();
          workflow = undefined;
          registry = undefined;
        },
      };
    };

    const messages = {
      host: identityMessages["setup.field.host"],
      databaseName: identityMessages["setup.field.databaseName"],
      username: identityMessages["setup.field.username"],
      password: identityMessages["setup.field.password"],
      adminPassword: identityMessages["setup.field.adminPassword"],
      adminConfirm: identityMessages["setup.field.adminConfirm"],
      serviceAddress: identityMessages["setup.field.serviceAddress"],
      namespace: identityMessages["setup.field.namespace"],
      nacosUsername: identityMessages["setup.field.nacosUsername"],
      nacosPassword: identityMessages["setup.field.nacosPassword"],
      next: identityMessages["setup.action.next"],
      back: identityMessages["setup.action.back"],
      finish: identityMessages["setup.action.finish"],
      direct: identityMessages["setup.option.direct.label"],
      inspect: shellMessages["shell.feedback.inspectOutcome"],
    };
    const field = (host, label) => {
      const labelNode = [...host.querySelectorAll("label")].find(
        (candidate) => candidate.textContent?.trim() === label,
      );
      assert.ok(labelNode, `mounted form contains the ${label} field label`);
      const input = host.ownerDocument.getElementById(labelNode.htmlFor);
      assert.ok(input, `${label} label points to a mounted control`);
      return input;
    };
    const setField = async (host, label, value) => {
      const input = field(host, label);
      await React.act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
          browser.HTMLInputElement.prototype,
          "value",
        ).set;
        setter.call(input, value);
        input.dispatchEvent(new browser.Event("input", { bubbles: true }));
        input.dispatchEvent(new browser.Event("change", { bubbles: true }));
      });
      assert.equal(input.value, value, `${label} accepts the synthetic input`);
    };
    const clickButton = async (host, text) => {
      const button = [...host.querySelectorAll("button")].find(
        (candidate) => candidate.textContent?.trim().replace(/\s+/g, " ") === text,
      );
      assert.ok(button, `mounted form has the ${text} action`);
      await React.act(async () => button.click());
    };
    const enterSensitiveDraft = async (host) => {
      await setField(host, messages.host, "db.setup.synthetic.internal");
      await setField(host, messages.databaseName, "sentinel_synthetic");
      await setField(host, messages.username, SYNTHETIC.databaseUsername);
      await setField(host, messages.password, SYNTHETIC.databasePassword);
      await clickButton(host, messages.next);
      await setField(host, messages.adminPassword, SYNTHETIC.administratorPassword);
      await setField(host, messages.adminConfirm, SYNTHETIC.administratorPassword);
      await clickButton(host, messages.next);
      await setField(host, messages.serviceAddress, "https://nacos.synthetic.example");
      await setField(host, messages.namespace, "synthetic-namespace");
      const directOption = [...host.querySelectorAll(".astryx-radio-list-item")].find((node) =>
        node.textContent?.includes(messages.direct),
      );
      assert.ok(directOption, "the direct-credential source mode is mounted");
      await React.act(async () => directOption.click());
      await setField(host, messages.nacosUsername, SYNTHETIC.sourceUsername);
      await setField(host, messages.nacosPassword, SYNTHETIC.sourcePassword);
      await clickButton(host, messages.next);
      assert.ok(host.querySelector(".setup-summary"), "the actual review step is mounted");
    };
    const allSecretsAbsentFromWorkflow = () => {
      const serialized = JSON.stringify(workflow.getSnapshot());
      for (const secret of Object.values(SYNTHETIC))
        assert.doesNotMatch(serialized, new RegExp(secret));
    };

    // Explicitly confirming app-level discard invokes the page's real registered cleanup callback.
    let page = await mount("completed");
    try {
      await enterSensitiveDraft(page.host);
      assert.deepEqual(registry.getSnapshot(), { dirty: true, locked: false });
      assert.equal(clearSensitiveInvocations, 0);
      allSecretsAbsentFromWorkflow();
      await React.act(async () => {
        assert.equal(registry.discard(), "done", "confirmed navigation discard is accepted");
        await Promise.resolve();
      });
      assert.equal(portState.writes, 0, "abandoning setup does not call initialization");
      await clickButton(page.host, messages.back);
      assert.equal(
        field(page.host, messages.serviceAddress).value,
        "https://nacos.synthetic.example",
      );
      assert.equal(field(page.host, messages.namespace).value, "synthetic-namespace");
      assert.equal(field(page.host, messages.nacosUsername).value, "");
      assert.equal(field(page.host, messages.nacosPassword).value, "");
      await clickButton(page.host, messages.back);
      assert.equal(field(page.host, messages.adminPassword).value, "");
      assert.equal(field(page.host, messages.adminConfirm).value, "");
      await clickButton(page.host, messages.back);
      assert.equal(field(page.host, messages.host).value, "db.setup.synthetic.internal");
      assert.equal(field(page.host, messages.databaseName).value, "sentinel_synthetic");
      assert.equal(field(page.host, messages.username).value, "");
      assert.equal(field(page.host, messages.password).value, "");
      assert.equal(registry.getSnapshot().locked, false);
      assert.equal(
        clearSensitiveInvocations,
        1,
        "confirmed discard invokes the mounted secret cleanup once",
      );
      allSecretsAbsentFromWorkflow();
    } finally {
      await page.dispose();
    }

    // An ambiguous response is not a confirmed discard or completion: preserve the draft,
    // prohibit a second write, then clean only after the original receipt is confirmed.
    page = await mount("unknown");
    try {
      await enterSensitiveDraft(page.host);
      await clickButton(page.host, messages.finish);
      await React.act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
      assert.equal(
        clearSensitiveInvocations,
        0,
        "an unknown write result cannot run success/discard cleanup before receipt lookup",
      );
      assert.equal(page.completions(), 0);
      await clickButton(page.host, messages.finish);
      assert.equal(portState.writes, 1, "an unknown result cannot replay initialization");
      await clickButton(page.host, messages.inspect);
      await React.act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      assert.equal(workflow.getSnapshot().initialization.status, "ready");
      assert.equal(clearSensitiveInvocations, 1, "confirmed receipt clears the setup draft once");
      assert.equal(portState.lookups, 1, "the original request receipt is read once");
      assert.equal(page.completions(), 1, "completion callback requires the confirmed receipt");
      assert.equal(
        page.host.querySelector(".setup-controls"),
        null,
        "completed form is removed from the DOM",
      );
      assert.equal(registry.getSnapshot().locked, false);
      allSecretsAbsentFromWorkflow();
      assert.doesNotMatch(
        page.host.textContent ?? "",
        new RegExp(Object.values(SYNTHETIC).join("|")),
        "completed UI does not render submitted secrets",
      );
    } finally {
      await page.dispose();
    }
  } finally {
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
