import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { initReactI18next, I18nextProvider } from "react-i18next";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createServer } from "vite";

const identityOwner = Object.freeze({
  accountId: "operator",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "role-editor-unknown-session",
});

test("F4.29 mounted unknown role write requires operation inspection and never replays POST", async () => {
  const browser = new Window({ url: "http://localhost/role-editor-unknown" });
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
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { RoleEditor },
      { createAccountManagementWorkflow },
      { AstryxProvider },
      React,
      { createRoot },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/identity/ui/components/RoleEditor.tsx"),
      vite.ssrLoadModule("/src/features/identity/application/accountManagementWorkflow.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
    ]);
    act = React.act;

    const identityMessages = JSON.parse(
      readFileSync("src/app/i18n/messages/en-US/identity.json", "utf8"),
    );
    const shellMessages = JSON.parse(
      readFileSync("src/app/i18n/messages/en-US/shell.json", "utf8"),
    );
    const i18n = createInstance();
    await i18n.use(initReactI18next).init({
      lng: "en-US",
      resources: { "en-US": { translation: { ...identityMessages, ...shellMessages } } },
      ns: ["translation"],
      defaultNS: "translation",
      nsSeparator: false,
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
    const record = Object.freeze({
      id: "account-role-target",
      username: "target",
      roleId: "admin",
      status: "active",
      builtIn: false,
      lastActiveAdmin: false,
      lastLoginAt: null,
      revision: "8",
    });
    const updatedRecord = Object.freeze({ ...record, roleId: "view", revision: "9" });
    const access = new StateStore({
      phase: "resolved",
      facts: { kind: "authenticated", identity: identityOwner },
    });
    let writes = 0;
    let lookups = 0;
    let rejectMutation;
    const pendingMutation = new Promise((_, reject) => {
      rejectMutation = reject;
    });
    workflow = createAccountManagementWorkflow(
      {
        listAccounts: async () => ({ items: [record], page: 1, pageSize: 20, total: 1 }),
        readAccount: async () => updatedRecord,
        mutateAccount: async () => {
          writes += 1;
          return pendingMutation;
        },
        readAccountOperation: async (requestKey) => {
          lookups += 1;
          return lookups === 1
            ? { status: "not-found", requestKey }
            : { status: "completed", requestKey, account: updatedRecord };
        },
      },
      identityOwner,
      {
        read: access.getSnapshot,
        subscribe: access.subscribe,
        revalidateAccess: async () => undefined,
      },
      () => "role-save-unknown-outcome",
    );
    await workflow.select(record.id);

    await vite
      .ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts")
      .then(({ loadAstryxLocaleCatalog }) => loadAstryxLocaleCatalog("en-US"));
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;
    const render = (currentRecord) =>
      React.createElement(
        I18nextProvider,
        { i18n },
        React.createElement(
          AstryxProvider,
          null,
          React.createElement(RoleEditor, {
            workflow,
            record: currentRecord,
            sessionEpoch: identityOwner.sessionEpoch,
          }),
        ),
      );
    await React.act(async () => {
      root.render(render(record));
      await Promise.resolve();
      await Promise.resolve();
    });

    const viewRadio = () => host.querySelector('input[type="radio"][value="view"]');
    const button = (label) =>
      [...host.querySelectorAll("button")].find((item) => item.textContent?.trim() === label);
    const saveButton = button(identityMessages["management.saveRole"]);
    assert.ok(viewRadio());
    assert.ok(saveButton);
    await React.act(async () => viewRadio().click());
    await React.act(async () => {
      saveButton.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const inspectLabel = shellMessages["shell.feedback.inspectOutcome"];
    assert.equal(writes, 1);
    assert.equal(viewRadio().checked, true, "unknown outcome retains the local role draft");
    assert.equal(host.querySelector("[data-role-editor] fieldset")?.disabled, true);
    assert.equal(saveButton.disabled, true, "unknown writes cannot be replayed");
    assert.ok(host.textContent?.includes(identityMessages["management.pending"]));
    assert.equal(
      button(inspectLabel),
      undefined,
      "inspection is unavailable before outcome is unknown",
    );

    await React.act(async () => {
      rejectMutation(new AppError(AppErrorKind.NETWORK, "synthetic transport failure"));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    assert.ok(host.textContent?.includes(identityMessages["management.unknown"]));
    assert.ok(button(inspectLabel), "the only available write recovery is operation inspection");

    await React.act(async () => {
      button(inspectLabel).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(writes, 1, "a not-found lookup is not treated as rollback");
    assert.equal(lookups, 1);
    assert.ok(host.textContent?.includes(identityMessages["management.unknown"]));
    assert.equal(saveButton.disabled, true, "not-found does not authorize a write retry");
    assert.ok(button(inspectLabel), "unknown remains inspectable after a not-found result");

    await React.act(async () => {
      button(inspectLabel).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await React.act(async () => root.render(render(updatedRecord)));

    assert.equal(writes, 1, "confirmed operation lookup never replays the write");
    assert.equal(lookups, 2);
    assert.equal(viewRadio().checked, true, "the confirmed latest role is adopted");
    assert.equal(saveButton.disabled, true, "the confirmed draft is clean");
    assert.ok(!host.textContent?.includes(identityMessages["management.unknown"]));
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
