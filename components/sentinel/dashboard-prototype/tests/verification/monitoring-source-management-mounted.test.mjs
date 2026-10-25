import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { StateStore } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T05.3 mounted monitoring-source flow checks before save and never reads credentials back", async () => {
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
      { MonitoringSourceRegistryPanel },
      { createMonitoringSourceWorkflow },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/system/ui/MonitoringSourceRegistryPanel.tsx"),
      vite.ssrLoadModule("/src/features/system/application/monitoringSourceWorkflow.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const catalogs = await Promise.all(
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
      resources: { "en-US": { translation: Object.assign({}, ...catalogs) } },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const accessState = new StateStore({ ownerKey: "monitoring-admin-session", allowed: true });
    let records = [];
    let sequence = 0;
    let checkInput;
    let mutationInput;
    const mutations = [];
    const port = {
      async readSources() {
        return { asOf: "2026-10-17T00:00:00Z", items: records };
      },
      async readSource(sourceId) {
        const record = records.find((candidate) => candidate.id === sourceId);
        assert.ok(record);
        return record;
      },
      async checkCandidate(source, credentials) {
        checkInput = { source, credentials };
        return {
          checkId: "monitoring-check-1",
          sourceId: source.sourceId,
          sourceRevision: source.revision,
          candidateFingerprint: "sha256:candidate",
          checkedAt: "2026-10-17T00:00:00Z",
          expiresAt: "2026-10-17T00:10:00Z",
          result: {
            connection: "reachable",
            queryApi: "available",
            profile: "supported",
            identity: { observed: 1, unique: 1, missing: 0, conflicting: 0 },
            failure: null,
          },
        };
      },
      async mutate(input) {
        mutationInput = input;
        mutations.push(input);
        if (input.kind === "set-enabled") {
          const current = records.find((candidate) => candidate.id === input.sourceId);
          assert.ok(current);
          records = [
            {
              ...current,
              revision: "monitoring-revision-disabled",
              enabled: input.enabled,
            },
          ];
          return {
            status: "completed",
            requestKey: input.requestKey,
            sourceId: input.sourceId,
            sourceRevision: records[0].revision,
            enabled: input.enabled,
          };
        }
        if (input.kind === "delete") {
          records = [];
          return {
            status: "completed",
            requestKey: input.requestKey,
            sourceId: input.sourceId,
          };
        }
        const record = {
          id: input.source.sourceId,
          revision: input.kind === "create" ? "monitoring-revision-2" : "monitoring-revision-saved",
          displayName: input.source.displayName,
          environmentId: input.source.environmentId,
          provider: input.source.provider,
          profile: input.source.profile,
          enabled: input.source.enabled,
          authenticationMode: input.source.authenticationMode,
          credentialConfigured: input.credentials !== null,
          endpointOrigin: "https://prometheus.example.test",
          identityLabels: input.source.identityLabels,
          selectorLabels: input.source.selectorLabels,
          scrapeIntervalSeconds: input.source.scrapeIntervalSeconds,
          staleAfterSeconds: input.source.staleAfterSeconds,
        };
        records = [record];
        return {
          status: "completed",
          requestKey: input.requestKey,
          sourceId: record.id,
          sourceRevision: record.revision,
          verified: true,
        };
      },
      async readOperation(requestKey) {
        return { status: "not_found", requestKey };
      },
    };
    workflow = createMonitoringSourceWorkflow(
      port,
      { read: accessState.getSnapshot, subscribe: accessState.subscribe },
      () => `monitoring-request-${++sequence}`,
    );

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    mounted = true;
    const render = async (canManage) =>
      act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              AstryxProvider,
              null,
              React.createElement(MonitoringSourceRegistryPanel, {
                workflow,
                canManage,
                demoMode: false,
              }),
            ),
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    await render(true);

    const button = (label, scope = host) => {
      const result = [...scope.querySelectorAll("button")].find(
        (candidate) => candidate.textContent?.trim() === label,
      );
      assert.ok(result, `expected button: ${label}`);
      return result;
    };
    const field = (labelText) => {
      const label = [...host.querySelectorAll("label")].find(
        (candidate) => candidate.textContent?.trim() === labelText,
      );
      assert.ok(label, `expected field label: ${labelText}`);
      const control = browser.document.getElementById(label.htmlFor);
      assert.ok(control, `expected labeled control for ${labelText}`);
      return control;
    };
    const setInput = (input, value) => {
      const setter = Object.getOwnPropertyDescriptor(
        browser.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(input, value);
      input.dispatchEvent(new browser.Event("input", { bubbles: true }));
    };
    const selectOption = async (label, optionLabel) => {
      const select = field(label);
      await act(async () => select.click());
      const option = [...host.querySelectorAll('[role="option"]')].find(
        (candidate) => candidate.textContent?.trim() === optionLabel,
      );
      assert.ok(option, `expected option: ${optionLabel}`);
      await act(async () => option.click());
    };

    await act(async () => button("Add source").click());
    const dialog = host.querySelector("dialog");
    assert.ok(dialog, "source editor is shown in the shared dialog frame");
    await act(async () => {
      setInput(field("Name"), "Production Prometheus");
      setInput(field("Environment ID"), "production");
      setInput(field("Prometheus service URL"), "https://prometheus.example.test");
    });
    await selectOption("Authentication", "Username and password");
    const password = "not-for-readback-credential";
    await act(async () => {
      setInput(field("Username"), "monitor-reader");
      setInput(field("Password"), password);
    });

    await act(async () => button("Test connection", dialog).click());
    assert.equal(mutations.length, 0, "provider check is separate from saving the source");
    assert.deepEqual(checkInput.credentials, { username: "monitor-reader", password });
    assert.equal(checkInput.source.endpoint, "https://prometheus.example.test");
    assert.match(host.textContent ?? "", /reachable · available · supported/);

    await act(async () => {
      button("Save registration", dialog).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(mutations.length, 1, "explicit save sends exactly one command");
    assert.equal(mutationInput.kind, "create");
    assert.deepEqual(mutationInput.credentials, { username: "monitor-reader", password });
    assert.equal(mutationInput.checkId, "monitoring-check-1");
    assert.equal(mutationInput.skipCheck, false);
    assert.equal(host.querySelector("dialog"), null, "confirmed save closes the dialog");
    assert.ok(host.querySelector("[data-monitoring-source-id]"));
    assert.match(host.textContent ?? "", /Production Prometheus/);
    assert.doesNotMatch(host.textContent ?? "", new RegExp(password));
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), new RegExp(password));
    assert.doesNotMatch(JSON.stringify(records), new RegExp(password));

    await act(async () => {
      button("Disable").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(mutations[1].kind, "set-enabled");
    assert.equal(mutations[1].enabled, false);
    assert.equal(records[0].enabled, false);

    await act(async () => button("Edit").click());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const editDialog = host.querySelector("dialog");
    assert.ok(editDialog, "editing opens the existing source in the shared dialog");
    assert.equal(field("Prometheus service URL").value, "https://prometheus.example.test");
    assert.equal(
      [...host.querySelectorAll("label")].some(
        (candidate) => candidate.textContent?.trim() === "Password",
      ),
      false,
      "the stored credential is never read back into a field",
    );
    await act(async () => {
      button("Save registration", editDialog).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(mutations[2].kind, "update");
    assert.equal(mutations[2].credentialUpdate, "keep");
    assert.equal(mutations[2].credentials, null);
    assert.equal(
      mutations[2].skipCheck,
      true,
      "unchanged credentials use the explicit skip-check path",
    );
    assert.equal(mutations[2].expectedRevision, "monitoring-revision-disabled");

    await act(async () => button("Delete").click());
    const deleteDialog = host.querySelector("dialog");
    assert.ok(deleteDialog, "deletion requires a confirmation dialog");
    assert.match(host.textContent ?? "", /delete/i);
    await act(async () => {
      button("Delete", deleteDialog).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(mutations[3].kind, "delete");
    assert.deepEqual(records, []);

    await render(false);
    assert.equal(
      [...host.querySelectorAll("button")].some(
        (candidate) => candidate.textContent?.trim() === "Add source",
      ),
      false,
      "view-only users cannot see source mutation controls",
    );
    assert.equal(mutations.length, 4, "rendering the view role does not issue a mutation");

    await act(async () => root.unmount());
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
