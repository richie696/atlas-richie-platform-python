import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { initReactI18next, I18nextProvider } from "react-i18next";
import { StateStore } from "@richie696/react-framework";
import { createServer } from "vite";

const identityOwner = Object.freeze({
  accountId: "operator",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "role-editor-conflict-session",
});

test("F4.29 mounted revision conflict locks stale edits until an authoritative read succeeds", async () => {
  const browser = new Window({ url: "http://localhost/role-editor-conflict" });
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
    const staleRecord = Object.freeze({
      id: "account-role-target",
      username: "target",
      roleId: "admin",
      status: "active",
      builtIn: false,
      lastActiveAdmin: false,
      lastLoginAt: null,
      revision: "8",
    });
    const latestRecord = Object.freeze({ ...staleRecord, roleId: "view", revision: "9" });
    const access = new StateStore({
      phase: "resolved",
      facts: { kind: "authenticated", identity: identityOwner },
    });
    let authoritativeRecord = staleRecord;
    let failNextRead = false;
    let writes = 0;
    workflow = createAccountManagementWorkflow(
      {
        listAccounts: async () => ({ items: [staleRecord], page: 1, pageSize: 20, total: 1 }),
        readAccount: async () => {
          if (failNextRead) {
            failNextRead = false;
            throw new Error("synthetic read failure");
          }
          return authoritativeRecord;
        },
        mutateAccount: async (mutation) => {
          writes += 1;
          assert.equal(mutation.kind, "role");
          assert.equal(mutation.roleId, "view");
          return { status: "rejected", requestKey: mutation.requestKey, reason: "conflict" };
        },
        readAccountOperation: async (requestKey) => ({ status: "not-found", requestKey }),
      },
      identityOwner,
      {
        read: access.getSnapshot,
        subscribe: access.subscribe,
        revalidateAccess: async () => undefined,
      },
      () => "role-save-revision-conflict",
    );
    await workflow.select(staleRecord.id);

    await vite
      .ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts")
      .then(({ loadAstryxLocaleCatalog }) => loadAstryxLocaleCatalog("en-US"));
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;
    const render = (record) =>
      React.createElement(
        I18nextProvider,
        { i18n },
        React.createElement(
          AstryxProvider,
          null,
          React.createElement(RoleEditor, {
            workflow,
            record,
            sessionEpoch: identityOwner.sessionEpoch,
          }),
        ),
      );
    await React.act(async () => {
      root.render(render(staleRecord));
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

    assert.equal(writes, 1, "a conflict must not create an implicit write retry");
    assert.equal(viewRadio().checked, true, "the attempted role remains visible as a local draft");
    assert.equal(
      host.querySelector("[data-role-editor] fieldset")?.disabled,
      true,
      "a stale revision cannot be edited or resubmitted",
    );
    assert.equal(saveButton.disabled, true, "the conflict requires an authoritative reread");
    assert.ok(host.textContent?.includes(identityMessages["management.conflict"]));

    const readLatestLabel = shellMessages["shell.feedback.readLatest"];
    const readLatest = button(readLatestLabel);
    assert.ok(readLatest, "the conflict exposes a read-only recovery action");
    failNextRead = true;
    await React.act(async () => {
      readLatest.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(viewRadio().checked, true, "a failed reread must preserve the user's draft");
    assert.ok(host.textContent?.includes(identityMessages["management.conflict"]));
    assert.ok(button(readLatestLabel), "a failed reread keeps recovery available");

    authoritativeRecord = latestRecord;
    await React.act(async () => {
      button(readLatestLabel).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await React.act(async () => root.render(render(latestRecord)));

    assert.equal(viewRadio().checked, true, "the editor adopts the authority's latest role");
    assert.equal(saveButton.disabled, true, "the refreshed authoritative draft is clean");
    assert.ok(!host.textContent?.includes(identityMessages["management.conflict"]));
    assert.equal(writes, 1, "read-latest recovery never repeats the role mutation");
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
