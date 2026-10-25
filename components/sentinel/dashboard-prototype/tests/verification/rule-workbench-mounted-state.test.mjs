import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T06.4 mounted rule workbench fails closed, retries, and starts a local rule draft", async () => {
  const browser = new Window({
    url: "http://localhost/#/rules?environment=production&binding=flow-1",
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
      { RuleSetWorkbenchPage },
      { createRuleDraftWorkflow },
      { createRuleOperation },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/rules/ui/RuleSetWorkbenchPage.tsx"),
      vite.ssrLoadModule("/src/features/rules/application/ruleDraftWorkflow.ts"),
      vite.ssrLoadModule("/src/features/rules/application/ruleOperation.ts"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

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

    const binding = {
      id: "flow-1",
      environmentId: "production",
      appId: "orders",
      kind: "flow",
      profile: "sentinel-v1",
      sourceId: "source-1",
      sourceLabel: "Nacos · production-rules",
      location: "namespace/group/flow-rules",
    };
    const access = {
      read: () => ({ ownerKey: "session-admin-1", allowed: true }),
      subscribe: () => () => {},
    };
    let snapshotReads = 0;
    let mutationCalls = 0;
    let draftReadCalls = 0;
    let validationCalls = 0;
    let operationLookups = 0;
    let latestMutation;
    let unknownReceipt;
    let persistedRuleRecords = [];
    let sourceSnapshot = {
      binding,
      versionId: null,
      checksum: "sha256:empty-baseline",
      sourceRevision: "revision-1",
      asOfMs: 1_797_000_000_000,
      records: [],
    };
    const port = {
      async readSnapshot(bindingId) {
        snapshotReads += 1;
        assert.equal(bindingId, binding.id);
        if (snapshotReads === 1)
          throw new AppError(AppErrorKind.NETWORK, "PRIVATE_RULE_SOURCE_DETAIL");
        return sourceSnapshot;
      },
      async readDraft() {
        draftReadCalls += 1;
        throw new Error("unexpected draft read");
      },
      async validateCandidate(candidate) {
        validationCalls += 1;
        return {
          bindingId: candidate.bindingId,
          profile: candidate.profile,
          baseChecksum: candidate.baseChecksum,
          candidateChecksum: "sha256:candidate-1",
          validationId: "validation-1",
          isPublishable: true,
          issues: [],
        };
      },
      async compareCandidate() {
        throw new Error("unexpected candidate diff");
      },
      async mutateRuleSet(mutation) {
        mutationCalls += 1;
        latestMutation = mutation;
        if (mutation.kind === "freeze_version") {
          return {
            bindingId: mutation.bindingId,
            requestKey: mutation.requestKey,
            status: "completed",
            result: {
              kind: "freeze_version",
              draftId: mutation.draftId,
              draftRevision: mutation.expectedRevision,
              version: {
                id: "immutable-version-1",
                bindingId: mutation.bindingId,
                kind: "flow",
                profile: "sentinel-v1",
                baseVersionId: null,
                checksum: mutation.candidateChecksum,
                name: mutation.name,
                note: mutation.note,
                createdAtMs: 1_797_000_000_002,
                createdById: "operator-admin",
                records: persistedRuleRecords,
              },
            },
          };
        }
        if (mutationCalls === 2)
          return {
            bindingId: mutation.bindingId,
            requestKey: mutation.requestKey,
            status: "rejected",
            reason: "conflict",
          };
        const candidate = mutation.candidate;
        persistedRuleRecords = candidate.rules.map((record, index) => ({
          id: record.recordId ?? `version-rule-${index + 1}`,
          rule: record.rule,
        }));
        const draft = {
          id: "draft-1",
          revision: `draft-revision-${mutationCalls === 3 ? 2 : 1}`,
          bindingId: mutation.bindingId,
          kind: candidate.kind,
          profile: candidate.profile,
          baseVersionId: candidate.baseVersionId,
          baseChecksum: candidate.baseChecksum,
          sourceRevision: candidate.sourceRevision,
          updatedAtMs: 1_797_000_000_001,
          records: candidate.rules.map((record, index) => ({
            id: record.recordId ?? `persisted-rule-${index + 1}`,
            rule: record.rule,
          })),
        };
        const receipt = {
          bindingId: mutation.bindingId,
          requestKey: mutation.requestKey,
          status: "completed",
          result: { kind: "save_draft", draft },
        };
        if (mutationCalls === 3) {
          unknownReceipt = receipt;
          throw new AppError(AppErrorKind.NETWORK, "PRIVATE_RULE_SAVE_ACK");
        }
        return receipt;
      },
      async readRuleOperation() {
        operationLookups += 1;
        assert.ok(unknownReceipt, "only an uncertain original mutation is inspected");
        return unknownReceipt;
      },
    };
    let requestSequence = 0;
    const operation = createRuleOperation(
      binding.id,
      port,
      access,
      () => `request-${++requestSequence}`,
    );
    workflow = createRuleDraftWorkflow(binding, port, access, access, operation);
    let formKeyRequests = 0;
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
            React.createElement(RuleSetWorkbenchPage, {
              workflow,
              binding,
              newFormKey: () => {
                formKeyRequests += 1;
                return "form-1";
              },
            }),
          ),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    assert.equal(host.querySelector('[data-query-state="error"]') !== null, true);
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_RULE_SOURCE_DETAIL/);
    assert.equal(snapshotReads, 1, "mount reads the selected binding's source snapshot");
    const begin = host.querySelector('[data-rule-action="begin"]');
    assert.ok(begin);
    assert.equal(begin.disabled, true, "editing cannot begin without a trusted source snapshot");
    assert.equal(host.querySelector("[data-rule-dirty]"), null);

    const retry = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry reading"),
    );
    assert.ok(retry, "the formal source state exposes a read-only retry");
    await React.act(async () =>
      retry.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(snapshotReads, 2, "retry re-reads the exact selected binding");
    assert.equal(draftReadCalls, 0, "a source failure does not guess or open a saved draft");
    assert.equal(mutationCalls, 0, "a source failure cannot emit rule mutations");
    assert.equal(host.querySelector('[data-query-state="error"]'), null);
    assert.equal(host.querySelector('[data-rule-action="begin"]')?.disabled, false);
    assert.equal(formKeyRequests, 0, "loading a source does not create a local draft implicitly");

    const beginAfterRecovery = host.querySelector('[data-rule-action="begin"]');
    await React.act(async () =>
      beginAfterRecovery.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.ok(host.querySelector("[data-rule-dirty]"), "the explicit action opens a clean draft");
    assert.equal(host.querySelector('[data-rule-action="add"]')?.disabled, false);
    assert.equal(mutationCalls, 0, "starting an editor is local and does not write to the server");

    await React.act(async () =>
      host
        .querySelector('[data-rule-action="add"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(formKeyRequests, 1, "adding a rule creates one stable editor identity");
    assert.ok(host.querySelector('[data-rule-record="form-1"]'));
    assert.ok(host.textContent.includes("New rule 1"));
    assert.equal(mutationCalls, 0, "adding a local rule does not publish or save it");

    await React.act(async () =>
      host
        .querySelector('[data-rule-action="validate"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(validationCalls, 0, "an incomplete local candidate never reaches the server port");
    assert.equal(mutationCalls, 0, "local validation failure cannot persist or publish a rule");
    assert.ok(host.querySelector('[role="alert"]'), "the page exposes a visible validation error");

    const added = workflow.getSnapshot().editing.records[0];
    await React.act(async () =>
      workflow.change(added.formKey, {
        ...added.rule,
        draft: { ...added.rule.draft, resource: "POST /api/orders", count: 25 },
      }),
    );
    await React.act(async () =>
      host
        .querySelector('[data-rule-action="validate"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(validationCalls, 1, "a valid candidate is validated only after explicit action");
    assert.ok(host.querySelector("[data-rule-validation]"));
    assert.match(host.querySelector("[data-rule-validation]")?.textContent ?? "", /validated/i);
    assert.equal(mutationCalls, 0, "candidate validation is read-only");

    await React.act(async () =>
      host
        .querySelector('[data-rule-action="save"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(mutationCalls, 1, "the explicit save action creates one durable mutation");
    assert.equal(latestMutation.kind, "save_draft");
    assert.equal(latestMutation.candidate.rules[0].rule.value.resource, "POST /api/orders");
    assert.equal(latestMutation.candidate.rules[0].rule.value.count, 25);
    assert.equal(workflow.getSnapshot().savedIdentity.id, "draft-1");
    assert.equal(workflow.getSnapshot().savedIdentity.revision, "draft-revision-1");
    assert.equal(
      workflow.getSnapshot().dirty,
      false,
      "the confirmed save adopts its server revision",
    );

    const persisted = workflow.getSnapshot().editing.records[0];
    await React.act(async () =>
      workflow.change(persisted.formKey, {
        ...persisted.rule,
        draft: { ...persisted.rule.draft, count: 30 },
      }),
    );
    await React.act(async () =>
      host
        .querySelector('[data-rule-action="save"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(mutationCalls, 2, "the next explicit save receives a durable conflict result");
    assert.equal(workflow.getSnapshot().operation.command.status, "conflict");
    assert.equal(workflow.getSnapshot().editing.records[0].rule.draft.count, 30);
    assert.equal(workflow.getSnapshot().savedIdentity.revision, "draft-revision-1");
    assert.equal(
      workflow.getSnapshot().dirty,
      true,
      "a conflict preserves the user's attempted edit",
    );
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_RULE_SOURCE_DETAIL/);

    const conflicted = workflow.getSnapshot().editing.records[0];
    await React.act(async () =>
      workflow.change(conflicted.formKey, {
        ...conflicted.rule,
        draft: { ...conflicted.rule.draft, count: 31 },
      }),
    );
    await React.act(async () =>
      host
        .querySelector('[data-rule-action="save"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(mutationCalls, 3, "the user explicitly submits a new request after conflict");
    assert.equal(workflow.getSnapshot().operation.command.status, "result-unknown");
    assert.equal(workflow.getSnapshot().editing.records[0].rule.draft.count, 31);
    assert.equal(host.querySelector('[data-rule-action="save"]')?.disabled, true);
    const inspect = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Check outcome"),
    );
    assert.ok(inspect, "the unknown outcome exposes inspection, not a retry action");
    await React.act(async () =>
      inspect.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(operationLookups, 1, "inspection reads the original request identity");
    assert.equal(mutationCalls, 3, "recovery never replays the uncertain write");
    assert.equal(workflow.getSnapshot().operation.command.status, "success");
    assert.equal(workflow.getSnapshot().savedIdentity.revision, "draft-revision-2");
    assert.equal(workflow.getSnapshot().editing.records[0].rule.draft.count, 31);
    assert.equal(
      workflow.getSnapshot().dirty,
      false,
      "confirmed inspection adopts the saved draft",
    );
    assert.doesNotMatch(host.textContent ?? "", /PRIVATE_RULE_SAVE_ACK/);

    await React.act(async () =>
      host
        .querySelector('[data-rule-action="validate"]')
        .dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(validationCalls, 2, "the recovered draft must be revalidated before freezing");
    const freezeAction = host.querySelector('[data-rule-action="freeze"]');
    assert.ok(freezeAction);
    assert.equal(freezeAction.disabled, false);
    await React.act(async () =>
      freezeAction.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    const freezeDialog = browser.document.querySelector("dialog");
    assert.ok(freezeDialog, "freeze opens the shared dialog only after a clean validated save");
    const dialogField = (labelText) => {
      const label = [...freezeDialog.querySelectorAll("label")].find(
        (candidate) => candidate.textContent?.trim() === labelText,
      );
      assert.ok(label, `expected the freeze field label: ${labelText}`);
      return browser.document.getElementById(label.htmlFor);
    };
    const versionName = dialogField("Version name");
    const versionNote = dialogField("Version notes");
    assert.ok(versionName);
    assert.ok(versionNote);
    await React.act(async () => {
      const setValue = (input, value) => {
        const setter = Object.getOwnPropertyDescriptor(
          browser.HTMLInputElement.prototype,
          "value",
        ).set;
        setter.call(input, value);
        input.dispatchEvent(new browser.Event("input", { bubbles: true }));
      };
      setValue(versionName, "Incident burst profile");
      setValue(versionNote, "Temporary capacity protection");
    });
    const confirmFreeze = [...freezeDialog.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Freeze immutable version"),
    );
    assert.ok(confirmFreeze);
    await React.act(async () =>
      confirmFreeze.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(mutationCalls, 4);
    assert.equal(latestMutation.kind, "freeze_version");
    assert.equal(latestMutation.draftId, "draft-1");
    assert.equal(latestMutation.expectedRevision, "draft-revision-2");
    assert.equal(latestMutation.validationId, "validation-1");
    assert.equal(latestMutation.name, "Incident burst profile");
    assert.equal(latestMutation.note, "Temporary capacity protection");
    assert.equal(workflow.getSnapshot().operation.command.result.version.id, "immutable-version-1");
    assert.equal(
      workflow.getSnapshot().source.data.versionId,
      null,
      "freezing a version does not claim the configuration center or runtime applied it",
    );
    assert.equal(
      browser.document.querySelector("dialog"),
      null,
      "a confirmed freeze closes the dialog",
    );
    assert.equal(
      workflow.getSnapshot().savedIdentity.revision,
      "draft-revision-2",
      "freezing an immutable version does not rewrite the mutable draft revision",
    );

    sourceSnapshot = {
      ...sourceSnapshot,
      versionId: "externally-updated-source-version",
      checksum: "sha256:external-source-update",
      sourceRevision: "revision-2",
      asOfMs: sourceSnapshot.asOfMs + 1,
    };
    const refreshSource = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Refresh authoritative snapshot"),
    );
    assert.ok(refreshSource);
    await React.act(async () => {
      refreshSource.dispatchEvent(new browser.MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(snapshotReads, 3);
    assert.equal(workflow.getSnapshot().source.data.versionId, "externally-updated-source-version");
    assert.equal(
      workflow.getSnapshot().editing.baseline.versionId,
      null,
      "refreshing source facts never silently changes the editor baseline",
    );
    assert.equal(
      workflow.getSnapshot().editing.records[0].rule.draft.count,
      31,
      "the saved draft remains intact after a newer source version is observed",
    );
    const adoptLatest = host.querySelector('[data-rule-action="restart"]');
    assert.ok(adoptLatest);
    await React.act(async () =>
      adoptLatest.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    const adoptionDialog = browser.document.querySelector("dialog");
    assert.ok(adoptionDialog, "adopting a refreshed source requires explicit confirmation");
    const confirmAdoption = [...adoptionDialog.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Confirm"),
    );
    assert.ok(confirmAdoption);
    await React.act(async () =>
      confirmAdoption.dispatchEvent(new browser.MouseEvent("click", { bubbles: true })),
    );
    assert.equal(browser.document.querySelector("dialog"), null);
    assert.equal(
      workflow.getSnapshot().editing.baseline.versionId,
      "externally-updated-source-version",
      "the latest baseline is adopted only after user confirmation",
    );
    assert.equal(workflow.getSnapshot().savedIdentity, null);
    assert.equal(workflow.getSnapshot().editing.records.length, 0);
    assert.equal(mutationCalls, 4, "refresh and baseline adoption never emit a mutation");

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
