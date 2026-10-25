import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { StateStore } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted AccountsPage creates an account and reloads the authoritative directory", async () => {
  const browser = new Window({ url: "http://localhost/#/accounts?page=1" });
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
      { AccountsPage },
      { createAccountManagementWorkflow },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/identity/ui/AccountsPage.tsx"),
      vite.ssrLoadModule("/src/features/identity/application/accountManagementWorkflow.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const [identity, shell] = await Promise.all(
      ["identity", "shell"].map(async (name) =>
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
      resources: { "en-US": { translation: { ...identity, ...shell } } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const owner = Object.freeze({
      accountId: "operator-admin",
      username: "operator",
      roleId: "admin",
      capabilities: ["metrics:view", "rules:write"],
      sessionEpoch: "accounts-page-mounted-session",
    });
    const session = new StateStore({
      phase: "resolved",
      facts: { kind: "authenticated", identity: owner },
    });
    let accounts = [];
    let submittedPassword;
    let mutationCalls = 0;
    let requestSequence = 0;
    const port = {
      async listAccounts(query) {
        return {
          items: accounts,
          page: query.page,
          pageSize: query.pageSize,
          total: accounts.length,
        };
      },
      async readAccount(accountId) {
        return accounts.find((account) => account.id === accountId) ?? null;
      },
      async mutateAccount(mutation) {
        mutationCalls += 1;
        assert.equal(mutation.kind, "create");
        assert.equal(mutation.input.roleId, "view");
        submittedPassword = mutation.input.password;
        const account = {
          id: "created-account-1",
          username: mutation.input.username,
          roleId: mutation.input.roleId,
          status: "active",
          builtIn: false,
          lastActiveAdmin: false,
          lastLoginAt: null,
          revision: "account-revision-1",
        };
        accounts = [account];
        return { status: "completed", requestKey: mutation.requestKey, account };
      },
      async readAccountOperation(requestKey) {
        return { status: "not-found", requestKey };
      },
    };
    workflow = createAccountManagementWorkflow(
      port,
      owner,
      {
        read: session.getSnapshot,
        subscribe: session.subscribe,
        revalidateAccess: async () => undefined,
      },
      () => `accounts-create-${++requestSequence}`,
    );

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
            React.createElement(AccountsPage, {
              workflow,
              query: { page: 1, pageSize: 20, search: "" },
              onQueryChange: () => {},
              onBindRole: () => {},
            }),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    assert.ok(host.querySelector("[data-account-management]"));
    assert.equal(host.querySelector('[data-query-state="empty"]') !== null, true);
    const createLabel = identity["accounts.action.create"];
    const openCreate = [...host.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === createLabel,
    );
    assert.ok(openCreate, "the formal account page exposes its create action");
    await React.act(async () => openCreate.click());

    const field = (labelText) => {
      const label = [...host.querySelectorAll("label")].find(
        (candidate) => candidate.textContent?.trim() === labelText,
      );
      assert.ok(label, `expected an accessible field label: ${labelText}`);
      const control = browser.document.getElementById(label.htmlFor);
      assert.ok(control, `expected the field to be associated with its label: ${labelText}`);
      return control;
    };
    const username = field(identity["accountDialog.field.username"]);
    const password = field(identity["accountDialog.field.password"]);
    assert.equal(password.type, "password");
    const setValue = (input, value) => {
      const setter = Object.getOwnPropertyDescriptor(
        browser.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(input, value);
      input.dispatchEvent(new browser.Event("input", { bubbles: true }));
    };
    const testPassword = "synthetic-only-account-password-42";
    await React.act(async () => {
      setValue(username, "mounted-viewer");
      setValue(password, testPassword);
    });
    const submit = [...host.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === identity["accountDialog.action.create"],
    );
    assert.ok(submit, "the modal uses the shared DialogFrame submit action");
    await React.act(async () => {
      submit.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    assert.equal(mutationCalls, 1);
    assert.equal(submittedPassword, testPassword, "the password reaches only the command Port");
    assert.equal(host.querySelector('[role="dialog"]'), null, "confirmed create closes the dialog");
    assert.ok(host.querySelector('[data-account-id="created-account-1"]'));
    assert.match(host.textContent ?? "", /mounted-viewer/);
    assert.doesNotMatch(host.textContent ?? "", new RegExp(testPassword));
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), new RegExp(testPassword));
    assert.equal(
      host.querySelector('input[type="password"]'),
      null,
      "the secret field is unmounted",
    );

    await React.act(async () => root.unmount());
    mounted = false;
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
