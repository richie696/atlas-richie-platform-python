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
  sessionEpoch: "role-editor-mounted-session",
});

test("F4.30 mounted role editor preserves an attempted demotion after authoritative last-admin rejection", async () => {
  const browser = new Window({ url: "http://localhost/role-editor" });
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
      id: "account-becomes-last-admin",
      username: "operator-two",
      roleId: "admin",
      status: "active",
      builtIn: false,
      // The selected snapshot is stale: another administrator concurrently
      // became protected, so only the server can reject this demotion.
      lastActiveAdmin: false,
      lastLoginAt: null,
      revision: "8",
    });
    const access = new StateStore({
      phase: "resolved",
      facts: { kind: "authenticated", identity: identityOwner },
    });
    let writes = 0;
    workflow = createAccountManagementWorkflow(
      {
        listAccounts: async () => ({ items: [record], page: 1, pageSize: 20, total: 1 }),
        readAccount: async () => record,
        mutateAccount: async (mutation) => {
          writes += 1;
          assert.equal(mutation.kind, "role");
          assert.equal(mutation.roleId, "view");
          return {
            status: "rejected",
            requestKey: mutation.requestKey,
            reason: "last_admin",
          };
        },
        readAccountOperation: async (requestKey) => ({ status: "not-found", requestKey }),
      },
      identityOwner,
      {
        read: access.getSnapshot,
        subscribe: access.subscribe,
        revalidateAccess: async () => undefined,
      },
      () => "role-save-last-admin-rejection",
    );

    await vite
      .ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts")
      .then(({ loadAstryxLocaleCatalog }) => loadAstryxLocaleCatalog("en-US"));
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
            React.createElement(RoleEditor, {
              workflow,
              record,
              sessionEpoch: identityOwner.sessionEpoch,
            }),
          ),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    const viewRadio = host.querySelector('input[type="radio"][value="view"]');
    const saveButton = [...host.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === identityMessages["management.saveRole"],
    );
    assert.ok(viewRadio, "the actual RoleEditor mounted its Viewer radio");
    assert.ok(saveButton, "the actual RoleEditor mounted its Save role command");
    assert.equal(viewRadio.checked, false);
    assert.equal(saveButton.disabled, true, "clean role draft cannot be submitted");

    await React.act(async () => {
      viewRadio.click();
    });
    assert.equal(viewRadio.checked, true, "the attempted role is held as a local draft");
    assert.equal(saveButton.disabled, false, "dirty selection is explicitly saveable");

    await React.act(async () => {
      saveButton.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(writes, 1, "the rejected role command is sent once");
    assert.equal(viewRadio.checked, true, "server rejection must not erase the selected role");
    assert.equal(
      saveButton.disabled,
      true,
      "an authoritative last-admin rejection must be reread before another write",
    );
    assert.ok(
      [...host.querySelectorAll("button")].some(
        (button) => button.textContent?.trim() === shellMessages["shell.feedback.readLatest"],
      ),
      "the conflict exposes an explicit read-latest recovery action",
    );
    assert.ok(
      host.textContent?.includes(identityMessages["management.lastAdmin"]),
      "the authoritative last-admin rejection is shown with safe localized copy",
    );
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
