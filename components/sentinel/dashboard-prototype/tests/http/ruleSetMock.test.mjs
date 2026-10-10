import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createRuleSetHttp } from "../../src/features/rules/api/ruleSetHttp";
import { createSourceRegistrationHttp } from "../../src/features/system/api/sourceRegistrationHttp";
import { RULE_MUTATION } from "../../src/features/rules/model/ruleSetOperations";
import { MOCK_ROLE_STORAGE_KEY } from "../../src/core/api/mock/mockRole";
import { MOCK_RULE_SCENARIO } from "../../src/app/api/mockRuleScenario";
import { MOCK_SYSTEM_SCENARIO } from "../../src/app/api/mockSystemScenario";
import { MOCK_IDENTITY_SCENARIO } from "../../src/app/api/mockIdentityScenario";
import { RULE_KIND } from "../../src/features/rules/mock";
import { createRuleSetMockHandlers } from "../../src/features/rules/mock";
import { createAppConsoleMockAssembly } from "../../src/app/api/mockConsoleHandlers";
import { StateStore } from "@richie696/react-framework";
import { createRuleDraftWorkflow } from "../../src/features/rules/application/ruleDraftWorkflow";
import { createRuleOperation } from "../../src/features/rules/application/ruleOperation";

const origin = "http://rules-demo.test";
const mockAdminId = MOCK_IDENTITY_SCENARIO.accounts.find((account) => account.builtIn).id;
const fixedNow = Date.parse("2026-10-08T12:00:00Z");

test("RULE-BINDING-REGISTRATION-MOCK: registered source creation is stateful and rereadable", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
      },
    },
  });
  const mockAssembly = createAppConsoleMockAssembly(fixedNow);
  const server = setupServer(...mockAssembly.handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "rules-registration-demo-session",
    onUnauthorized: () => {},
    requestId: () => `rules-registration-demo-${++sequence}`,
  });
  try {
    const sourcePort = createSourceRegistrationHttp(transport);
    await sourcePort.readSources(new AbortController().signal);
    const registeredSource = await sourcePort.mutateSource(
      {
        kind: "register",
        requestKey: "register-source-for-binding",
        name: "Secondary Nacos",
        source: {
          provider: "nacos",
          endpoint: "https://nacos-secondary.example.com",
          namespace: "secondary",
          authentication: { mode: "none" },
        },
      },
      new AbortController().signal,
    );
    assert.equal(registeredSource.status, "completed");
    const port = createRuleSetHttp(transport);
    const signal = new AbortController().signal;
    await port.readBindings(
      {
        environmentId: MOCK_RULE_SCENARIO.environment.id,
        appId: null,
        kind: null,
        search: "",
        page: 1,
        pageSize: 20,
      },
      signal,
    );
    const command = {
      requestKey: "register-binding-once",
      bindingId: "binding-registration-demo",
      environmentId: MOCK_RULE_SCENARIO.environment.id,
      appId: MOCK_SYSTEM_SCENARIO.applicationId,
      kind: RULE_KIND.Flow,
      profile: "sentinel-python-v1",
      sourceId: registeredSource.record.id,
      sourceRevision: registeredSource.record.revision,
      target: {
        provider: "nacos",
        namespace: "orders",
        group: "DEFAULT_GROUP",
        dataId: "orders-flow-rules",
      },
    };

    const created = await port.registerBinding(command, signal);
    assert.equal(created.id, command.bindingId);
    assert.equal(created.sourceLabel, registeredSource.record.name);
    assert.equal(created.location, "nacos://orders/DEFAULT_GROUP/orders-flow-rules");
    assert.deepEqual(await port.registerBinding(command, signal), created);

    const directory = await port.readBindings(
      {
        environmentId: command.environmentId,
        appId: command.appId,
        kind: command.kind,
        search: "",
        page: 1,
        pageSize: 20,
      },
      signal,
    );
    assert.ok(directory.items.some((binding) => binding.id === command.bindingId));
    const snapshot = await port.readSnapshot(command.bindingId, signal);
    assert.equal(snapshot.binding.id, command.bindingId);
    assert.equal(snapshot.versionId, null);
    assert.deepEqual(snapshot.records, []);
    assert.equal(snapshot.sourceRevision, command.sourceRevision);
    const target = await port.readPublicationTarget(command.bindingId, signal);
    assert.equal(target.target.provider, "nacos");
    assert.equal(target.target.dataId, command.target.dataId);

    await assert.rejects(
      port.registerBinding(
        { ...command, target: { ...command.target, dataId: "different-rules" } },
        signal,
      ),
      (error) => error?.status === 409,
    );
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("RULE-MOCK: explicit demo handlers support the same directory, snapshot, and durable draft HTTP path", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
      },
    },
  });
  const ruleMock = createRuleSetMockHandlers(MOCK_RULE_SCENARIO, mockAdminId, () => fixedNow);
  const server = setupServer(...ruleMock.handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "rules-demo-session",
    onUnauthorized: () => {},
    requestId: () => `rules-demo-${++sequence}`,
  });
  try {
    const port = createRuleSetHttp(transport);
    const signal = new AbortController().signal;
    const query = {
      environmentId: "test-env",
      appId: null,
      kind: null,
      search: "",
      page: 1,
      pageSize: 20,
    };
    const directory = await port.readBindings(query, signal);
    assert.equal(directory.total, MOCK_RULE_SCENARIO.bindings.length);
    assert.equal(
      directory.items.some(
        (binding) => binding.id === MOCK_RULE_SCENARIO.deployment.eventVersion.bindingId,
      ),
      true,
    );
    assert.ok(
      directory.items.every(
        (binding) => binding.sourceId === MOCK_SYSTEM_SCENARIO.primarySource.id,
      ),
      "all bindings refer to the registered primary configuration source",
    );
    assert.ok(
      directory.items.every(
        (binding) => binding.sourceLabel === MOCK_SYSTEM_SCENARIO.primarySource.name,
      ),
      "all bindings project the canonical registered source name",
    );
    const applicationDirectory = await port.readBindings(
      { ...query, appId: MOCK_RULE_SCENARIO.bindings[0].appId },
      signal,
    );
    assert.equal(applicationDirectory.total, MOCK_RULE_SCENARIO.bindings.length);
    assert.ok(
      applicationDirectory.items.every(
        (binding) => binding.appId === MOCK_RULE_SCENARIO.bindings[0].appId,
      ),
    );
    const unknownEnvironment = await port.readBindings(
      { ...query, environmentId: "unknown-env" },
      signal,
    );
    assert.equal(unknownEnvironment.total, 0);

    const snapshot = await port.readSnapshot(
      MOCK_RULE_SCENARIO.deployment.eventVersion.bindingId,
      signal,
    );
    assert.equal(snapshot.records[0].rule.kind, "flow");
    assert.equal(snapshot.binding.sourceId, MOCK_SYSTEM_SCENARIO.primarySource.id);
    const targetBindingId = snapshot.binding.id;
    assert.deepEqual(await port.readPublicationTarget(targetBindingId, signal), {
      bindingId: targetBindingId,
      target: null,
    });
    const targetMutation = {
      kind: RULE_MUTATION.ConfigureTarget,
      bindingId: targetBindingId,
      requestKey: "configure-target-once",
      expectedSourceRevision: snapshot.sourceRevision,
      expectedTargetRevision: null,
      target: {
        provider: "nacos",
        sourceId: snapshot.binding.sourceId,
        namespace: "prod",
        group: "SENTINEL_GROUP",
        dataId: "orders-flow-rules",
      },
    };
    const configuredTarget = await port.mutateRuleSet(targetMutation, signal);
    assert.equal(configuredTarget.status, "completed");
    assert.equal(configuredTarget.result.kind, RULE_MUTATION.ConfigureTarget);
    assert.equal(configuredTarget.result.target.target.namespace, "prod");
    const readTarget = await port.readPublicationTarget(targetBindingId, signal);
    assert.equal(readTarget.targetRevision, configuredTarget.result.target.targetRevision);
    const staleTarget = await port.mutateRuleSet(
      {
        ...targetMutation,
        requestKey: "configure-target-stale",
        target: { ...targetMutation.target, dataId: "changed" },
      },
      signal,
    );
    assert.equal(staleTarget.status, "rejected");
    assert.equal(staleTarget.reason, "conflict");
    const candidate = {
      bindingId: snapshot.binding.id,
      profile: snapshot.binding.profile,
      kind: snapshot.binding.kind,
      baseVersionId: snapshot.versionId,
      baseChecksum: snapshot.checksum,
      sourceRevision: snapshot.sourceRevision,
      rules: snapshot.records.map((record) => ({ recordId: record.id, rule: record.rule })),
    };
    const changedCandidate = {
      ...candidate,
      rules: candidate.rules.map((item, index) =>
        index === 0
          ? { ...item, rule: { ...item.rule, value: { ...item.rule.value, count: 2100 } } }
          : item,
      ),
    };
    const saved = await port.mutateRuleSet(
      {
        kind: RULE_MUTATION.SaveDraft,
        requestKey: "request-save-one",
        bindingId: snapshot.binding.id,
        draftId: null,
        expectedRevision: null,
        candidate: changedCandidate,
      },
      signal,
    );
    assert.equal(saved.status, "completed");
    assert.equal(saved.result.kind, RULE_MUTATION.SaveDraft);
    assert.equal(saved.result.draft.records[0].rule.value.count, 2100);
    const inspected = await port.readRuleOperation(snapshot.binding.id, "request-save-one", signal);
    assert.equal(inspected.status, "completed");
    assert.equal(inspected.result.draft.records[0].rule.value.count, 2100);
    const drafts = await port.readDrafts(snapshot.binding.id, signal);
    assert.equal(drafts.items.length, 1);
    assert.equal(drafts.items[0].id, saved.result.draft.id);
    const frozen = await port.mutateRuleSet(
      {
        kind: RULE_MUTATION.FreezeVersion,
        requestKey: "request-freeze-one",
        bindingId: snapshot.binding.id,
        draftId: drafts.items[0].id,
        expectedRevision: drafts.items[0].revision,
        validationId: "validation-demo",
        candidateChecksum: "checksum-demo",
        name: "Test version",
        note: "Synthetic test only",
      },
      signal,
    );
    assert.equal(frozen.status, "completed");
    assert.equal(frozen.result.kind, RULE_MUTATION.FreezeVersion);
    assert.equal(frozen.result.version.createdById, mockAdminId);
    const published = await port.mutateRuleSet(
      {
        kind: RULE_MUTATION.Publish,
        requestKey: "request-publish-new-version",
        bindingId: snapshot.binding.id,
        versionId: frozen.result.version.id,
        versionChecksum: frozen.result.version.checksum,
        expectedVersionId: snapshot.versionId,
        expectedChecksum: snapshot.checksum,
        expectedSourceRevision: snapshot.sourceRevision,
        reason: "Synthetic publication receipt test",
      },
      signal,
    );
    assert.equal(published.status, "completed");
    assert.equal(published.result.kind, RULE_MUTATION.Publish);
    assert.equal(published.result.publication.configurationWrite.state, "succeeded");
    const receipts = await port.readReceipts(
      {
        bindingId: snapshot.binding.id,
        publicationId: published.result.publication.id,
        page: 1,
        pageSize: 20,
      },
      signal,
    );
    const targetInstances = MOCK_RULE_SCENARIO.instances.filter(
      (instance) => instance.appId === snapshot.binding.appId,
    );
    assert.equal(receipts.expected, targetInstances.length);
    assert.equal(receipts.inventorySource, MOCK_RULE_SCENARIO.inventorySource);
    assert.equal(receipts.total, targetInstances.length);
    assert.equal(receipts.applied, 0);
    assert.equal(receipts.pending, targetInstances.length);
    assert.deepEqual(
      receipts.items.map((item) => [item.instanceId, item.processEpoch, item.state]),
      targetInstances.map((instance) => [instance.id, instance.processEpoch, "pending"]),
    );
    assert.ok(
      receipts.items.every(
        (item) =>
          item.targetVersionId === frozen.result.version.id &&
          item.loadedProcessEpoch === null &&
          item.loadedVersionId === null &&
          item.loadedChecksum === null &&
          item.appliedAtMs === null &&
          item.lastReportAtMs === null,
      ),
      "publishing does not invent instance application evidence",
    );

    const accessState = new StateStore({ ownerKey: "rules-demo-session", allowed: true });
    const access = { read: accessState.getSnapshot, subscribe: accessState.subscribe };
    const operation = createRuleOperation(
      snapshot.binding.id,
      port,
      access,
      () => "workflow-save-request",
    );
    const workflow = createRuleDraftWorkflow(snapshot.binding, port, access, access, operation);
    try {
      await workflow.refreshSource();
      workflow.begin();
      const first = workflow.getSnapshot().editing.records[0];
      workflow.change(first.formKey, {
        ...first.rule,
        draft: { ...first.rule.draft, count: 2300 },
      });
      const workflowResult = await workflow.save();
      assert.equal(workflowResult.kind, RULE_MUTATION.SaveDraft);
      assert.equal(workflowResult.draft.records[0].rule.value.count, 2300);
      assert.equal(workflow.getSnapshot().dirty, false);
      assert.equal(workflow.getSnapshot().savedIdentity.revision, workflowResult.draft.revision);
    } finally {
      workflow.dispose();
      operation.dispose();
      accessState.complete();
    }
  } finally {
    transport.dispose();
    server.close();
    ruleMock.reset();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("RULE-MOCK-DEPLOYMENT: seeded immutable versions, partial receipts, schedule conflicts, cancellation and reset use HTTP contracts", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
      },
    },
  });
  const ruleMock = createRuleSetMockHandlers(MOCK_RULE_SCENARIO, mockAdminId, () => fixedNow);
  const server = setupServer(...ruleMock.handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "rules-demo-session",
    onUnauthorized: () => {},
    requestId: () => `rules-deployment-${++sequence}`,
  });
  try {
    const port = createRuleSetHttp(transport);
    const signal = new AbortController().signal;
    const bindingId = MOCK_RULE_SCENARIO.deployment.eventVersion.bindingId;
    const versions = await port.readVersions(bindingId, signal);
    assert.deepEqual(
      versions.items.map((version) => version.id),
      [
        MOCK_RULE_SCENARIO.deployment.baselineVersion.id,
        MOCK_RULE_SCENARIO.deployment.eventVersion.id,
      ],
    );
    assert.ok(versions.items.every((version) => version.createdById === mockAdminId));
    const eventVersion = versions.items.find((version) => version.id === "version-event-flow");
    assert.ok(eventVersion);
    assert.equal(eventVersion.records[0].rule.value.count, 1500);
    assert.equal(
      (await port.readVersions("binding-app-one-degrade", signal)).items[0].id,
      "version-one",
    );

    const publicationId = MOCK_RULE_SCENARIO.deployment.eventPublication.id;
    const publication = await port.readPublication(bindingId, publicationId, signal);
    assert.equal(publication.targetVersionId, eventVersion.id);
    const receipts = await port.readReceipts(
      { bindingId, publicationId, page: 1, pageSize: 20 },
      signal,
    );
    const expectedInstances = MOCK_RULE_SCENARIO.instances.filter(
      (instance) => instance.appId === MOCK_SYSTEM_SCENARIO.applicationId,
    );
    assert.equal(receipts.expected, expectedInstances.length);
    assert.equal(receipts.inventorySource, MOCK_RULE_SCENARIO.inventorySource);
    assert.equal(receipts.applied, 1);
    assert.equal(receipts.pending, 1);
    assert.equal(receipts.restartRequired, 0);
    assert.deepEqual(
      receipts.items.map((item) => item.state),
      ["applied", "pending"],
    );
    assert.deepEqual(
      receipts.items.map((item) => [item.instanceId, item.processEpoch]),
      expectedInstances.map((instance) => [instance.id, instance.processEpoch]),
    );
    assert.equal(
      receipts.items.find((item) => item.state === "applied").instanceId,
      MOCK_RULE_SCENARIO.deployment.receipt.appliedInstanceId,
    );

    const plans = await port.readPlans(bindingId, signal);
    assert.equal(plans.items.length, 1);
    const plan = plans.items[0];
    assert.equal(
      plan.activateAtMs,
      fixedNow + MOCK_RULE_SCENARIO.deployment.initialPlan.activateAfterMs,
    );
    assert.equal(
      plan.deactivateAtMs - plan.activateAtMs,
      MOCK_RULE_SCENARIO.deployment.initialPlan.durationMs,
    );
    const schedule = {
      bindingId,
      versionId: plan.versionId,
      restoreVersionId: plan.restoreVersionId,
      activateAtMs: plan.activateAtMs,
      deactivateAtMs: plan.deactivateAtMs,
      timeZone: plan.timeZone,
    };
    const overlappingPlan = await port.mutateRuleSet(
      {
        kind: RULE_MUTATION.CreatePlan,
        bindingId,
        requestKey: "overlapping-plan-request",
        schedule,
      },
      signal,
    );
    assert.equal(overlappingPlan.status, "rejected");
    assert.equal(overlappingPlan.reason, "conflict");
    assert.equal((await port.readPlans(bindingId, signal)).items.length, 1);

    const cancelled = await port.mutateRuleSet(
      {
        kind: RULE_MUTATION.CancelPlan,
        bindingId,
        requestKey: "cancel-seeded-plan-request",
        planId: plan.id,
        expectedRevision: plan.revision,
        reason: "Reset the synthetic demo schedule",
      },
      signal,
    );
    assert.equal(cancelled.status, "completed");
    assert.equal(cancelled.result.plan.state, "cancelled");
    const created = await port.mutateRuleSet(
      {
        kind: RULE_MUTATION.CreatePlan,
        bindingId,
        requestKey: "replacement-plan-request",
        schedule,
      },
      signal,
    );
    assert.equal(created.status, "completed");
    assert.equal(created.result.plan.restoreVersionId, "version-one");

    ruleMock.reset();
    const resetPlans = await port.readPlans(bindingId, signal);
    assert.deepEqual(
      resetPlans.items.map((item) => item.id),
      [MOCK_RULE_SCENARIO.deployment.initialPlan.id],
    );
    assert.equal(
      resetPlans.items[0].activateAtMs,
      fixedNow + MOCK_RULE_SCENARIO.deployment.initialPlan.activateAfterMs,
    );
    assert.equal(
      resetPlans.items[0].deactivateAtMs - resetPlans.items[0].activateAtMs,
      MOCK_RULE_SCENARIO.deployment.initialPlan.durationMs,
    );
    assert.equal(
      (await port.readReceipts({ bindingId, publicationId, page: 1, pageSize: 20 }, signal))
        .pending,
      1,
    );
  } finally {
    transport.dispose();
    server.close();
    ruleMock.reset();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
