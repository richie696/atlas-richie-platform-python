import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { initReactI18next, I18nextProvider } from "react-i18next";
import { StateStore } from "@richie696/react-framework";
import { createServer } from "vite";

const admin = Object.freeze({
  accountId: "operator",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "role-mounted-admin-session",
});
const viewer = Object.freeze({
  ...admin,
  roleId: "view",
  capabilities: ["metrics:view"],
  sessionEpoch: "role-mounted-view-session",
});
const protectedRecord = Object.freeze({
  id: "last-administrator",
  username: "last-admin",
  roleId: "admin",
  status: "active",
  builtIn: false,
  lastActiveAdmin: true,
  lastLoginAt: null,
  revision: "12",
});

async function createMount() {
  const browser = new Window({ url: "http://localhost/role-management" });
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
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      React,
      { createRoot },
      { AstryxProvider },
      { createAccountManagementWorkflow },
      { RoleEditor },
      { RoleManagementPage },
    ] = await Promise.all([
      import("react"),
      import("react-dom/client"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      vite.ssrLoadModule("/src/features/identity/application/accountManagementWorkflow.ts"),
      vite.ssrLoadModule("/src/features/identity/ui/components/RoleEditor.tsx"),
      vite.ssrLoadModule("/src/features/identity/ui/RoleManagementPage.tsx"),
    ]);
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
    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    const root = createRoot(host);
    return {
      React,
      root,
      host,
      browser,
      vite,
      i18n,
      identityMessages,
      AstryxProvider,
      createAccountManagementWorkflow,
      RoleEditor,
      RoleManagementPage,
      async cleanup() {
        await React.act(async () => root.unmount());
        await vite.close();
        browser.happyDOM.abort();
        browser.close();
        for (const [name, descriptor] of priorGlobals) {
          if (descriptor) Object.defineProperty(globalThis, name, descriptor);
          else delete globalThis[name];
        }
      },
    };
  } catch (error) {
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
    throw error;
  }
}

function mountedTree(React, I18nextProvider, i18n, AstryxProvider, child) {
  return React.createElement(
    I18nextProvider,
    { i18n },
    React.createElement(AstryxProvider, null, child),
  );
}

test("F4.30 mounted last administrator role editor is locked and sends no write", async () => {
  const mount = await createMount();
  const access = new StateStore({
    phase: "resolved",
    facts: { kind: "authenticated", identity: admin },
  });
  let writes = 0;
  const workflow = mount.createAccountManagementWorkflow(
    {
      listAccounts: async () => ({ items: [protectedRecord], page: 1, pageSize: 20, total: 1 }),
      readAccount: async () => protectedRecord,
      mutateAccount: async () => {
        writes++;
        assert.fail("locked last-administrator role editor must never dispatch a mutation");
      },
      readAccountOperation: async (requestKey) => ({ status: "not-found", requestKey }),
    },
    admin,
    {
      read: access.getSnapshot,
      subscribe: access.subscribe,
      revalidateAccess: async () => undefined,
    },
    () => "last-admin-role-write",
  );
  try {
    await mount.React.act(async () => {
      mount.root.render(
        mountedTree(
          mount.React,
          I18nextProvider,
          mount.i18n,
          mount.AstryxProvider,
          mount.React.createElement(mount.RoleEditor, {
            workflow,
            record: protectedRecord,
            sessionEpoch: admin.sessionEpoch,
          }),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    const viewRadio = mount.host.querySelector('input[type="radio"][value="view"]');
    const saveButton = [...mount.host.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === mount.identityMessages["management.saveRole"],
    );
    assert.ok(viewRadio, "the mounted editor exposes the role choice");
    assert.ok(saveButton, "the mounted editor exposes its save command");
    assert.equal(
      viewRadio.closest("fieldset")?.disabled,
      true,
      "last-active-admin role options are locked by their containing fieldset",
    );
    assert.equal(saveButton.disabled, true, "the role cannot be submitted");
    await mount.React.act(async () => {
      viewRadio.click();
      saveButton.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(writes, 0, "attempting disabled controls produces no mutation");
    assert.ok(
      mount.host.textContent?.includes(mount.identityMessages["roles.restriction.lastAdmin"]),
      "the lock is explained in the mounted UI",
    );
  } finally {
    await mount.cleanup();
    workflow.dispose();
  }
});

test("F4.30 mounted viewer direct account-target route renders denial and never reads or writes", async () => {
  const mount = await createMount();
  const access = new StateStore({
    phase: "resolved",
    facts: { kind: "authenticated", identity: viewer },
  });
  const calls = [];
  const workflow = mount.createAccountManagementWorkflow(
    {
      listAccounts: async () => {
        calls.push("list");
        return { items: [], page: 1, pageSize: 20, total: 0 };
      },
      readAccount: async () => {
        calls.push("read");
        return protectedRecord;
      },
      mutateAccount: async () => {
        calls.push("write");
        return assert.fail("viewer direct route must not reach a mutation port");
      },
      readAccountOperation: async (requestKey) => ({ status: "not-found", requestKey }),
    },
    viewer,
    {
      read: access.getSnapshot,
      subscribe: access.subscribe,
      revalidateAccess: async () => undefined,
    },
    () => "viewer-direct-role-write",
  );
  try {
    await mount.React.act(async () => {
      mount.root.render(
        mountedTree(
          mount.React,
          I18nextProvider,
          mount.i18n,
          mount.AstryxProvider,
          mount.React.createElement(mount.RoleManagementPage, {
            workflow,
            accountId: protectedRecord.id,
            sessionEpoch: viewer.sessionEpoch,
            onAccountSelection: () => assert.fail("denied route must not navigate to accounts"),
          }),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.ok(
      mount.host.textContent?.includes(mount.identityMessages["management.denied"]),
      "a view session opening the direct account-target page sees the localized denial state",
    );
    assert.equal(mount.host.querySelector("[data-role-editor]"), null);
    assert.deepEqual(calls, [], "client denial prevents directory, detail and mutation requests");
  } finally {
    await mount.cleanup();
    workflow.dispose();
  }
});

test("F4.30 mounted administrator role downgrade revokes the editor and clears the direct target", async () => {
  const mount = await createMount();
  const access = new StateStore({
    phase: "resolved",
    facts: { kind: "authenticated", identity: admin },
  });
  const calls = [];
  const workflow = mount.createAccountManagementWorkflow(
    {
      listAccounts: async () => {
        calls.push("list");
        return { items: [protectedRecord], page: 1, pageSize: 20, total: 1 };
      },
      readAccount: async () => {
        calls.push("read");
        return protectedRecord;
      },
      mutateAccount: async () => {
        calls.push("write");
        return assert.fail("role downgrade must revoke writes before another command");
      },
      readAccountOperation: async (requestKey) => ({ status: "not-found", requestKey }),
    },
    admin,
    {
      read: access.getSnapshot,
      subscribe: access.subscribe,
      revalidateAccess: async () => undefined,
    },
    () => "role-downgrade-write",
  );
  try {
    await mount.React.act(async () => {
      mount.root.render(
        mountedTree(
          mount.React,
          I18nextProvider,
          mount.i18n,
          mount.AstryxProvider,
          mount.React.createElement(mount.RoleManagementPage, {
            workflow,
            accountId: protectedRecord.id,
            sessionEpoch: admin.sessionEpoch,
            onAccountSelection: () => assert.fail("role downgrade must not switch targets"),
          }),
        ),
      );
      for (let tick = 0; tick < 5; tick++) await Promise.resolve();
    });
    assert.ok(mount.host.querySelector("[data-role-editor]"), "admin initially sees the editor");
    assert.deepEqual(calls, ["list", "read"]);

    await mount.React.act(async () => {
      access.set({
        phase: "resolved",
        facts: { kind: "authenticated", identity: viewer },
      });
      await Promise.resolve();
    });
    assert.ok(
      mount.host.textContent?.includes(mount.identityMessages["management.denied"]),
      "a role owner change replaces the management editor with the denial state",
    );
    assert.equal(mount.host.querySelector("[data-role-editor]"), null);
    assert.deepEqual(calls, ["list", "read"], "revocation triggers no additional reads or writes");
  } finally {
    await mount.cleanup();
    workflow.dispose();
  }
});
