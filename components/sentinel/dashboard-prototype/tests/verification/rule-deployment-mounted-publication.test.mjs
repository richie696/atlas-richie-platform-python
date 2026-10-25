import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { StateStore } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted deployment publishes an immutable version and reads back provider facts", async () => {
  const browser = new Window({
    url: "http://localhost/#/rules?environment=test&binding=binding-one",
  });
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
  let operation;
  let source;
  let React;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { RuleDeploymentPanel },
      { createRuleDeploymentWorkflow },
      { createRuleOperation },
      { AstryxProvider },
      { ruleSet },
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/rules/ui/RuleDeploymentPanel.tsx"),
      vite.ssrLoadModule("/src/features/rules/application/ruleDeploymentWorkflow.ts"),
      vite.ssrLoadModule("/src/features/rules/application/ruleOperation.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      vite.ssrLoadModule("/tests/fixtures/ruleSets.ts"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    React = await import("react");

    const catalogs = await Promise.all(
      ["rules", "shell", "observation", "applications", "realtime"].map(async (name) =>
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

    const accessStore = new StateStore({ ownerKey: "deployment-admin", allowed: true });
    const access = { read: accessStore.getSnapshot, subscribe: accessStore.subscribe };
    source = new StateStore({
      status: "ready",
      key: ruleSet.binding.id,
      receivedAt: ruleSet.asOfMs,
      data: ruleSet,
    });
    const collection = (items) => ({
      bindingId: ruleSet.binding.id,
      asOfMs: ruleSet.asOfMs,
      items,
    });
    const daily = {
      id: "daily-version",
      bindingId: ruleSet.binding.id,
      kind: ruleSet.binding.kind,
      profile: ruleSet.binding.profile,
      baseVersionId: null,
      checksum: ruleSet.checksum,
      name: "Daily protection",
      note: "Normal operating policy",
      createdAtMs: ruleSet.asOfMs,
      createdById: "operator-admin",
      records: ruleSet.records,
    };
    const incident = {
      ...daily,
      id: "incident-version",
      baseVersionId: daily.id,
      checksum: "server-checksum-incident",
      name: "Incident protection",
      note: "Temporary peak event policy",
    };
    const awaiting = { state: "awaiting", observedAtMs: null, reason: null };
    const succeeded = { state: "succeeded", observedAtMs: ruleSet.asOfMs + 2, reason: null };
    let publication = null;
    let writeCount = 0;
    let readBackCount = 0;
    let receiptReads = 0;
    let lastMutation;
    operation = createRuleOperation(
      ruleSet.binding.id,
      {
        async mutateRuleSet(mutation) {
          writeCount += 1;
          lastMutation = mutation;
          assert.equal(mutation.kind, "publish");
          publication = {
            id: "publication-1",
            bindingId: mutation.bindingId,
            targetVersionId: mutation.versionId,
            targetChecksum: mutation.versionChecksum,
            baseVersionId: mutation.expectedVersionId,
            createdAtMs: ruleSet.asOfMs + 1,
            validation: succeeded,
            configurationWrite: awaiting,
            readBack: awaiting,
          };
          return {
            bindingId: mutation.bindingId,
            requestKey: mutation.requestKey,
            status: "completed",
            result: { kind: "publish", publication },
          };
        },
        async readRuleOperation() {
          assert.fail("a confirmed publication must not be inspected as an unknown result");
        },
      },
      access,
      () => "deployment-request-1",
    );
    workflow = createRuleDeploymentWorkflow(
      ruleSet.binding,
      {
        async readVersions() {
          return collection([daily, incident]);
        },
        async readVersion(_bindingId, versionId) {
          return [daily, incident].find((version) => version.id === versionId);
        },
        async readPublications() {
          return collection(publication ? [publication] : []);
        },
        async readPublication(_bindingId, publicationId) {
          readBackCount += 1;
          assert.equal(publicationId, "publication-1");
          publication = {
            ...publication,
            configurationWrite: succeeded,
            readBack: succeeded,
          };
          return publication;
        },
        async readReceipts() {
          receiptReads += 1;
          return {
            publicationId: "publication-1",
            bindingId: ruleSet.binding.id,
            page: 1,
            pageSize: 20,
            asOfMs: ruleSet.asOfMs + 2,
            total: 0,
            expected: 0,
            inventorySource: "test-inventory",
            applied: 0,
            pending: 0,
            failed: 0,
            unknown: 0,
            restartRequired: 0,
            items: [],
          };
        },
        async readPlans() {
          return collection([]);
        },
        async readPublicationTarget() {
          return {
            bindingId: ruleSet.binding.id,
            targetRevision: "target-r1",
            sourceRevision: ruleSet.sourceRevision,
            target: {
              provider: "nacos",
              sourceId: ruleSet.binding.sourceId,
              namespace: "production",
              group: "SENTINEL_GROUP",
              dataId: "flow-rules",
            },
          };
        },
      },
      access,
      access,
      operation,
      { getSnapshot: source.getSnapshot, subscribe: source.subscribe },
      () => ruleSet.asOfMs + 10,
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
            React.createElement(RuleDeploymentPanel, {
              bindingId: ruleSet.binding.id,
              workflow,
            }),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const versionChoice = host.querySelector('[data-deployment-version="incident-version"]');
    assert.ok(versionChoice, "the mounted deployment page reads the immutable version catalog");
    await React.act(async () =>
      versionChoice.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.ok(host.querySelector("[data-version-detail]"));
    const publishButton = host.querySelector("[data-deployment-publish]");
    assert.ok(publishButton);
    assert.equal(
      publishButton.disabled,
      false,
      "fresh source and selected immutable version enable publish",
    );
    await React.act(async () =>
      publishButton.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    const dialog = browser.document.querySelector("dialog");
    assert.ok(dialog, "publication requires the shared confirmation dialog");
    const reasonLabel = [...dialog.querySelectorAll("label")].find(
      (candidate) => candidate.textContent?.trim() === "Operation reason",
    );
    assert.ok(reasonLabel);
    const reasonInput = browser.document.getElementById(reasonLabel.htmlFor);
    assert.ok(reasonInput);
    await React.act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        browser.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(reasonInput, "Temporary peak event policy");
      reasonInput.dispatchEvent(new browser.Event("input", { bubbles: true }));
    });
    const confirm = dialog.querySelector("[data-deployment-submit-publish]");
    assert.ok(confirm);
    await React.act(async () =>
      confirm.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );

    assert.equal(writeCount, 1, "one explicit confirmation dispatches one publication command");
    assert.equal(lastMutation.versionId, incident.id);
    assert.equal(lastMutation.versionChecksum, incident.checksum);
    assert.equal(lastMutation.expectedVersionId, ruleSet.versionId);
    assert.equal(lastMutation.expectedChecksum, ruleSet.checksum);
    assert.equal(lastMutation.expectedSourceRevision, ruleSet.sourceRevision);
    assert.equal(lastMutation.reason, "Temporary peak event policy");
    assert.equal(browser.document.querySelector("dialog"), null);
    assert.equal(source.getSnapshot().data.versionId, ruleSet.versionId);
    assert.equal(
      host.querySelector("[data-publication-detail]"),
      null,
      "command acceptance alone does not invent provider write/read-back state",
    );

    const refresh = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Refresh publication facts"),
    );
    assert.ok(refresh);
    await React.act(async () =>
      refresh.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    await React.act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(readBackCount, 1, "the user-triggered refresh reads durable publication facts");
    const detail = host.querySelector("[data-publication-detail]");
    assert.ok(detail);
    assert.match(detail.textContent ?? "", /Confirmed success/);
    assert.equal(receiptReads, 0, "publication read-back does not imply instance applied receipts");
    assert.equal(
      source.getSnapshot().data.versionId,
      ruleSet.versionId,
      "provider read-back remains distinct from a source/runtime receipt projection",
    );

    await React.act(async () => root.unmount());
    mounted = false;
    host.remove();
  } finally {
    if (root && mounted) await React.act(async () => root.unmount());
    workflow?.dispose();
    operation?.dispose();
    source?.complete();
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
