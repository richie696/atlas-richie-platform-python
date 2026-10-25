import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { StateStore } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted source registry checks a candidate before saving and reads it back", async () => {
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
  let workflow;
  let act;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { SourceRegistryPanel },
      { createSourceRegistrationWorkflow },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/system/ui/SourceRegistryPanel.tsx"),
      vite.ssrLoadModule("/src/features/system/application/sourceRegistrationWorkflow.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const [system, shell] = await Promise.all(
      ["system", "shell"].map(async (name) =>
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
      resources: { "en-US": { translation: { ...system, ...shell } } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const owner = Object.freeze({ ownerKey: "source-admin-session", allowed: true });
    const accessState = new StateStore(owner);
    let records = [];
    let checks = 0;
    let writes = 0;
    let operationSequence = 0;
    let checkInput;
    let submittedMutation;
    const submittedMutations = [];
    const port = {
      async readSources() {
        return { asOfMs: Date.UTC(2026, 9, 14, 12), items: records };
      },
      async checkSource(input) {
        checks += 1;
        checkInput = input;
        return {
          status: "reachable",
          capabilities: ["read"],
          checkedAtMs: Date.UTC(2026, 9, 14, 12),
          expiresAtMs: Date.UTC(2026, 9, 14, 12, 1),
        };
      },
      async mutateSource(mutation) {
        writes += 1;
        submittedMutation = mutation;
        submittedMutations.push(mutation);
        if (mutation.kind === "delete") {
          records = records.filter((record) => record.id !== mutation.sourceId);
          return {
            status: "completed",
            requestKey: mutation.requestKey,
            deletedSourceId: mutation.sourceId,
          };
        }
        const record = {
          id: "source-mounted-1",
          revision: "source-revision-1",
          name: mutation.name,
          endpoint: mutation.source.endpoint,
          provider: mutation.source.provider,
          namespace: mutation.source.namespace,
          authenticationMode: mutation.source.authentication.mode,
          credentialConfigured: false,
        };
        records = [record];
        return { status: "completed", requestKey: mutation.requestKey, record };
      },
      async readSourceOperation(requestKey) {
        return { status: "not-found", requestKey };
      },
    };
    workflow = createSourceRegistrationWorkflow(
      port,
      { read: accessState.getSnapshot, subscribe: accessState.subscribe },
      () => `source-mounted-${++operationSequence}`,
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
            React.createElement(SourceRegistryPanel, { workflow }),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    assert.equal(host.querySelector('[data-query-state="empty"]') !== null, true);
    const button = (label) => {
      const result = [...host.querySelectorAll("button")].find(
        (candidate) => candidate.textContent?.trim() === label,
      );
      assert.ok(result, `expected button: ${label}`);
      return result;
    };
    const dialogButton = (label) => {
      const dialog = host.querySelector("dialog");
      assert.ok(dialog, "expected open dialog");
      const result = [...dialog.querySelectorAll("button")].find(
        (candidate) => candidate.textContent?.trim() === label,
      );
      assert.ok(result, `expected dialog button: ${label}`);
      return result;
    };
    const openRegistration = button(system["system.source.add"]);
    assert.equal(
      openRegistration.disabled,
      false,
      "a loaded empty registry permits source creation",
    );
    await React.act(async () => {
      openRegistration.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    assert.ok(host.querySelector("dialog"), "source registration uses the shared dialog");

    const field = (labelText) => {
      const label = [...host.querySelectorAll("label")].find(
        (candidate) => candidate.textContent?.trim() === labelText,
      );
      assert.ok(label, `expected accessible field label: ${labelText}`);
      const control = browser.document.getElementById(label.htmlFor);
      assert.ok(control, `expected control associated with label: ${labelText}`);
      return control;
    };
    const setValue = (input, value) => {
      const setter = Object.getOwnPropertyDescriptor(
        browser.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(input, value);
      input.dispatchEvent(new browser.Event("input", { bubbles: true }));
    };
    await React.act(async () => {
      setValue(field(system["system.source.name"]), "Mounted Nacos");
      setValue(field(system["system.source.endpoint"]), "https://nacos.example.test:8848");
      setValue(field(system["system.source.namespace"]), "sentinel-staging");
    });

    await React.act(async () => button(system["system.source.check"]).click());
    assert.equal(checks, 1, "the candidate is checked once");
    assert.equal(writes, 0, "checking a candidate does not register or write rules");
    assert.deepEqual(checkInput, {
      sourceId: null,
      expectedRevision: null,
      source: {
        provider: "nacos",
        endpoint: "https://nacos.example.test:8848",
        namespace: "sentinel-staging",
        authentication: { mode: "none" },
      },
    });
    assert.match(host.textContent ?? "", new RegExp(system["system.source.reachable"]));

    await React.act(async () => {
      button(system["system.source.save"]).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(writes, 1, "explicit save sends exactly one command");
    assert.equal(submittedMutation.kind, "register");
    assert.deepEqual(submittedMutation.source.authentication, { mode: "none" });
    assert.equal(host.querySelector("dialog"), null, "confirmed save closes the dialog");
    assert.ok(host.querySelector('[data-source-id="source-mounted-1"]'));
    assert.match(host.textContent ?? "", /Mounted Nacos/);
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /password|token|reference/i);

    await React.act(async () => button(system["system.source.delete"]).click());
    assert.ok(host.querySelector("dialog"), "source deletion requires explicit confirmation");
    assert.match(host.textContent ?? "", /does not delete rules/i);
    await React.act(async () => {
      dialogButton(system["system.source.delete"]).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(writes, 2, "confirmed deletion sends exactly one command");
    assert.equal(submittedMutations[1].kind, "delete");
    assert.equal(submittedMutations[1].sourceId, "source-mounted-1");
    assert.deepEqual(records, []);
    assert.equal(host.querySelector("dialog"), null, "confirmed deletion closes the dialog");
    assert.equal(
      host.querySelector('[data-source-id="source-mounted-1"]'),
      null,
      "confirmed deletion refreshes the visible registry",
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
