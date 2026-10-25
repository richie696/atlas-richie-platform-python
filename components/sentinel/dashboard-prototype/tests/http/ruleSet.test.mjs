import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createIdentityHttp } from "../../src/features/identity/api/identityAccessHttp";
import { createRuleSetHttp } from "../../src/features/rules/api/ruleSetHttp";
import {
  ActivationPlanSchema,
  PublicationReceiptPageSchema,
  PublicationReceiptSchema,
  RuleMutationSchema,
  RuleBindingSchema,
  RuleBindingRegistrationRequestSchema,
  RulePublicationTargetSnapshotSchema,
  RuleValueSchema,
  RuleSetCandidateSchema,
  RuleSetVersionSchema,
  RuleValidationReportSchema,
} from "../../src/features/rules/api/ruleSetWire";
import {
  RULE_EXAMPLE_CANDIDATE,
  RULE_EXAMPLE_VERSION,
} from "../../src/features/rules/api/ruleContractExamples";
import { ruleSet } from "../fixtures/ruleSets";

const origin = "http://rules-http.test";
const instant = (value) => new Date(value).toISOString();
const response = (request, body, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: {
      "x-request-id": request.headers.get("x-request-id"),
      "x-sentinel-csrf": "R".repeat(48),
    },
  });
async function run(handlers, action) {
  const server = setupServer(...handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "rule-owner",
    onUnauthorized: () => {},
    requestId: () => `rule-${++sequence}`,
  });
  try {
    await action(createRuleSetHttp(transport), createIdentityHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("RULE-WIRE: version names and lifecycle reasons reject cross-runtime blank text", () => {
  for (const blank of [" ", "\u0085", "\u001c", "\ufeff"]) {
    assert.equal(
      RuleMutationSchema.safeParse({
        kind: "freeze_version",
        draftId: "draft-1",
        expectedRevision: "revision-1",
        validationId: "validation-1",
        candidateChecksum: "sha256:candidate",
        name: blank,
        note: "",
      }).success,
      false,
    );
    assert.equal(
      RuleMutationSchema.safeParse({
        kind: "publish",
        versionId: "version-1",
        versionChecksum: "sha256:version",
        expectedVersionId: null,
        expectedChecksum: "sha256:baseline",
        expectedSourceRevision: null,
        reason: blank,
      }).success,
      false,
    );
    assert.equal(
      RuleMutationSchema.safeParse({
        kind: "cancel_plan",
        planId: "plan-1",
        expectedRevision: "revision-1",
        reason: blank,
      }).success,
      false,
    );
    assert.equal(
      RuleMutationSchema.safeParse({
        kind: "create_plan",
        schedule: {
          bindingId: "binding-1",
          versionId: "version-1",
          restoreVersionId: "version-2",
          activateAt: "2026-10-10T10:00:00.000Z",
          deactivateAt: "2026-10-10T11:00:00.000Z",
          timeZone: blank,
        },
      }).success,
      false,
    );
    assert.equal(
      RuleSetVersionSchema.safeParse({ ...RULE_EXAMPLE_VERSION, name: blank }).success,
      false,
    );
    assert.equal(
      ActivationPlanSchema.safeParse({
        id: "plan-1",
        revision: "revision-1",
        bindingId: "binding-1",
        versionId: "version-1",
        restoreVersionId: "version-2",
        activateAt: "2026-10-10T10:00:00.000Z",
        deactivateAt: "2026-10-10T11:00:00.000Z",
        timeZone: blank,
        state: "pending",
        activationPublicationId: null,
        restorePublicationId: null,
      }).success,
      false,
    );
  }
});

test("RULE-CANDIDATE-WIRE: required rule text rejects cross-runtime blank content", () => {
  for (const blank of [" ", "\u0085", "\u001c", "\ufeff"]) {
    const candidate = structuredClone(RULE_EXAMPLE_CANDIDATE);
    candidate.rules[0].rule.value.resource = blank;
    assert.equal(RuleSetCandidateSchema.safeParse(candidate).success, false);

    const parameterCandidate = structuredClone(RULE_EXAMPLE_CANDIDATE);
    parameterCandidate.kind = "param";
    parameterCandidate.rules = [
      {
        recordId: null,
        rule: {
          kind: "param",
          value: {
            resource: "lookup",
            grade: 1,
            count: 5,
            durationInSec: 1,
            paramIdx: 0,
            paramFlowItemList: [{ classType: "str", object: blank, count: 1 }],
          },
        },
      },
    ];
    assert.equal(RuleSetCandidateSchema.safeParse(parameterCandidate).success, false);
  }
});

test("RULE-VALUE-WIRE: integer fields reject fractions and unsafe integer magnitudes", () => {
  const flow = structuredClone(RULE_EXAMPLE_CANDIDATE.rules[0].rule);
  const warmup = structuredClone(flow);
  warmup.value.warmUpPeriodSec = 1.5;
  const unsafeQueueTime = structuredClone(flow);
  unsafeQueueTime.value.maxQueueingTimeMs = Number.MAX_SAFE_INTEGER + 1;

  const degrade = {
    kind: "degrade",
    value: {
      resource: "POST /api/orders",
      grade: 0,
      count: 0.5,
      timeWindow: 1.5,
      minRequestAmount: 5,
      statIntervalMs: 1000,
    },
  };
  const system = {
    kind: "system",
    value: {
      highestSystemLoad: 1,
      avgRt: -1,
      maxThread: 1.5,
      qps: -1,
      highestCpuUsage: -1,
    },
  };
  const param = {
    kind: "param",
    value: {
      resource: "lookup",
      grade: 1,
      count: 5,
      durationInSec: 1.5,
      paramIdx: 0,
      paramFlowItemList: [],
    },
  };

  for (const rule of [warmup, unsafeQueueTime, degrade, system, param]) {
    assert.equal(RuleValueSchema.safeParse(rule).success, false, JSON.stringify(rule));
  }
});

test("RULE-BINDING-WIRE: binding identities and display text reject cross-runtime blanks", () => {
  const binding = {
    id: "binding-1",
    environmentId: "prod",
    appId: "checkout",
    kind: "flow",
    profile: "sentinel-flow-v1",
    sourceId: "nacos-main",
    sourceLabel: "Primary Nacos",
    location: "sentinel/prod/flow-rules",
  };
  assert.equal(RuleBindingSchema.safeParse(binding).success, true);
  for (const blank of [" ", "\u0085", "\u001c", "\ufeff"]) {
    for (const field of ["id", "environmentId", "appId", "profile", "sourceId"]) {
      assert.equal(RuleBindingSchema.safeParse({ ...binding, [field]: blank }).success, false);
    }
    for (const field of ["sourceLabel", "location"]) {
      assert.equal(RuleBindingSchema.safeParse({ ...binding, [field]: blank }).success, false);
    }
  }
});

test("RULE-BINDING-REGISTRATION-WIRE: exact Nacos and Consul targets match Python bounds", () => {
  const command = {
    requestKey: "register-binding-1",
    bindingId: "checkout-prod-flow",
    environmentId: "prod",
    appId: "checkout",
    kind: "flow",
    profile: "sentinel-flow-v1",
    sourceId: "nacos-main",
    sourceRevision: "revision-1",
    target: {
      provider: "nacos",
      namespace: "n".repeat(512),
      group: "DEFAULT_GROUP",
      dataId: "flow-rules.json",
    },
  };
  assert.equal(RuleBindingRegistrationRequestSchema.safeParse(command).success, true);
  assert.equal(
    RuleBindingRegistrationRequestSchema.safeParse({
      ...command,
      target: { ...command.target, namespace: "n".repeat(513) },
    }).success,
    false,
  );
  assert.equal(
    RuleBindingRegistrationRequestSchema.safeParse({
      ...command,
      target: { provider: "consul", datacenter: null, key: "rules/flow.json" },
    }).success,
    true,
  );
  assert.equal(
    RuleBindingRegistrationRequestSchema.safeParse({
      ...command,
      target: { provider: "consul", datacenter: null, key: "rules/../flow.json" },
    }).success,
    false,
  );
  assert.equal(
    RuleBindingRegistrationRequestSchema.safeParse({
      ...command,
      target: { provider: "nacos", namespace: "prod", group: "DEFAULT_GROUP", dataId: "" },
    }).success,
    false,
  );
  assert.equal(
    RuleBindingRegistrationRequestSchema.safeParse({
      ...command,
      target: { ...command.target, unexpected: "credential" },
    }).success,
    false,
  );
});

test("RULE-TARGET-WIRE: provider target values use the Python 512-unit bounded-text contract", () => {
  const mutation = (target) => ({
    kind: "configure_target",
    expectedSourceRevision: "source-revision-1",
    expectedTargetRevision: null,
    target,
  });
  const nacos = {
    provider: "nacos",
    sourceId: "source-1",
    namespace: "n".repeat(201),
    group: "DEFAULT_GROUP",
    dataId: "rules.json",
  };
  assert.equal(RuleMutationSchema.safeParse(mutation(nacos)).success, true);
  assert.equal(
    RuleMutationSchema.safeParse(mutation({ ...nacos, namespace: "🚀".repeat(256) })).success,
    true,
  );
  assert.equal(
    RuleMutationSchema.safeParse(mutation({ ...nacos, namespace: "🚀".repeat(257) })).success,
    false,
  );
  for (const invalid of ["\ufeff", "safe\u0001value", "x".repeat(513)]) {
    assert.equal(
      RuleMutationSchema.safeParse(mutation({ ...nacos, dataId: invalid })).success,
      false,
    );
  }
  assert.equal(
    RuleMutationSchema.safeParse(mutation({ ...nacos, sourceId: "source\u0001id" })).success,
    false,
  );
  assert.equal(
    RulePublicationTargetSnapshotSchema.safeParse({
      bindingId: "binding-1",
      target: null,
    }).success,
    true,
  );
  assert.equal(
    RulePublicationTargetSnapshotSchema.safeParse({
      bindingId: "binding\u0001id",
      target: null,
    }).success,
    false,
  );
  assert.equal(
    RuleMutationSchema.safeParse(
      mutation({ provider: "consul", sourceId: "source-1", key: "k".repeat(201) }),
    ).success,
    true,
  );
});

test("RULE-VALIDATION-WIRE: validation receipt enforces Python issue and publishability invariants", () => {
  const report = {
    bindingId: "binding-1",
    profile: "sentinel-flow-v1",
    baseChecksum: "sha256:base",
    candidateChecksum: "sha256:candidate",
    validationId: "validation-1",
    isPublishable: false,
    issues: [{ code: "validation", recordIndex: 999, path: "rules[999].count" }],
  };
  assert.equal(RuleValidationReportSchema.safeParse(report).success, true);
  assert.equal(
    RuleValidationReportSchema.safeParse({
      ...report,
      issues: [{ ...report.issues[0], recordIndex: 1000 }],
    }).success,
    false,
  );
  assert.equal(
    RuleValidationReportSchema.safeParse({
      ...report,
      issues: [{ ...report.issues[0], path: "provider error: password=secret" }],
    }).success,
    false,
  );
  assert.equal(
    RuleValidationReportSchema.safeParse({ ...report, isPublishable: true }).success,
    false,
  );
  assert.equal(
    RuleValidationReportSchema.safeParse({ ...report, isPublishable: true, issues: [] }).success,
    true,
  );
});

test("RULE-RECEIPT-PAGE-WIRE: page counters and rows satisfy Python population invariants", () => {
  const first = {
    instanceId: "instance-one",
    processEpoch: "epoch-one",
    loadedProcessEpoch: "epoch-one",
    targetVersionId: "version-one",
    loadedVersionId: "version-one",
    loadedChecksum: "checksum-one",
    appliedAt: "2026-10-10T00:00:00.000Z",
    lastReportAt: "2026-10-10T00:00:00.000Z",
    state: "applied",
  };
  const second = {
    ...first,
    instanceId: "instance-two",
    state: "pending",
  };
  const valid = {
    publicationId: "publication-one",
    bindingId: "binding-one",
    page: 1,
    pageSize: 2,
    asOf: "2026-10-10T00:00:00.000Z",
    total: 3,
    expected: null,
    inventorySource: null,
    applied: 1,
    pending: 1,
    failed: 0,
    unknown: 0,
    restartRequired: 1,
    items: [first, second],
  };
  assert.equal(PublicationReceiptPageSchema.safeParse(valid).success, true);

  const invalidPages = [
    { ...valid, expected: 2, inventorySource: "inventory-one" },
    { ...valid, total: 4 },
    { ...valid, pageSize: 1 },
    { ...valid, page: 2 },
    { ...valid, items: [first, { ...second, instanceId: first.instanceId }] },
    { ...valid, items: [first, { ...second, state: "applied" }] },
  ];
  for (const page of invalidPages) {
    assert.equal(PublicationReceiptPageSchema.safeParse(page).success, false);
  }
});

test("RULE-RECEIPT-WIRE: unknown and applied rows satisfy Python incarnation invariants", () => {
  const applied = {
    instanceId: "instance-one",
    processEpoch: "epoch-one",
    loadedProcessEpoch: "epoch-one",
    targetVersionId: "version-one",
    loadedVersionId: "version-one",
    loadedChecksum: "checksum-one",
    appliedAt: "2026-10-10T00:00:00.000Z",
    lastReportAt: "2026-10-10T00:00:00.000Z",
    state: "applied",
  };
  const unknown = {
    ...applied,
    processEpoch: null,
    loadedProcessEpoch: null,
    loadedVersionId: null,
    loadedChecksum: null,
    appliedAt: null,
    lastReportAt: null,
    state: "unknown",
  };

  assert.equal(PublicationReceiptSchema.safeParse(applied).success, true);
  assert.equal(PublicationReceiptSchema.safeParse(unknown).success, true);
  for (const invalid of [
    { ...unknown, state: "pending" },
    { ...unknown, loadedVersionId: "version-one" },
    { ...applied, loadedProcessEpoch: "stale-epoch" },
    { ...applied, loadedVersionId: "other-version" },
    { ...applied, loadedChecksum: null },
    { ...applied, appliedAt: null },
    { ...applied, lastReportAt: null },
  ]) {
    assert.equal(PublicationReceiptSchema.safeParse(invalid).success, false);
  }
});

test("RULE-BINDINGS: explicit query, strict page echo and redacted binding facts map through HTTP", async () => {
  const query = {
    environmentId: "test-env",
    appId: null,
    kind: null,
    search: "",
    page: 1,
    pageSize: 25,
  };
  let search;
  await run(
    [
      http.get(`${origin}/api/v1/rulesets`, ({ request }) => {
        search = new URL(request.url).searchParams;
        return response(request, { query, total: 1, items: [ruleSet.binding] });
      }),
    ],
    async (port) => {
      assert.deepEqual(await port.readBindings(query, new AbortController().signal), {
        query,
        total: 1,
        items: [ruleSet.binding],
      });
      assert.equal(search.get("environmentId"), "test-env");
      assert.equal(search.get("page"), "1");
      assert.equal(search.get("pageSize"), "25");
      assert.equal(search.has("appId"), false);
      assert.equal(search.has("search"), false);
    },
  );
});

test("RULE-CATALOG HTTP: provider rules and freshness facts map from the Console wire contract", async () => {
  const query = {
    environmentId: "test-env",
    appId: null,
    kind: null,
    search: "",
    page: 1,
    pageSize: 25,
  };
  const timestamp = "2026-10-16T08:00:00.000Z";
  const item = {
    binding: ruleSet.binding,
    record: ruleSet.records[0],
    snapshot: {
      checksum: ruleSet.checksum,
      sourceRevision: ruleSet.sourceRevision,
      versionId: ruleSet.versionId,
      asOf: timestamp,
    },
    read: { freshness: "current", lastAttemptAt: timestamp },
  };
  const payload = {
    query,
    asOf: timestamp,
    coverage: "complete",
    bindings: { total: 1, current: 1, stale: 0, notRead: 0 },
    total: 1,
    hasMore: false,
    items: [item],
    issues: [],
  };
  let receivedUrl;
  await run(
    [
      http.get(`${origin}/api/v2/rules/catalog`, ({ request }) => {
        receivedUrl = new URL(request.url);
        return response(request, payload);
      }),
    ],
    async (port) => {
      const page = await port.readRuleCatalog(query, new AbortController().signal);
      assert.equal(receivedUrl.pathname, "/api/v2/rules/catalog");
      assert.equal(receivedUrl.searchParams.get("environmentId"), "test-env");
      assert.equal(receivedUrl.searchParams.get("page"), "1");
      assert.equal(receivedUrl.searchParams.get("pageSize"), "25");
      assert.equal(receivedUrl.searchParams.has("appId"), false);
      assert.equal(receivedUrl.searchParams.has("kind"), false);
      assert.equal(page.coverage, "complete");
      assert.equal(page.total, 1);
      assert.equal(page.items[0].record.id, "rule-one");
      assert.deepEqual(page.items[0].record.rule, ruleSet.records[0].rule);
      assert.equal(page.items[0].snapshot.checksum, ruleSet.checksum);
      assert.equal(page.items[0].read.freshness, "current");
    },
  );
});

test("RULE-CATALOG HTTP: refresh receipt is validated and mapped into the feature model", async () => {
  const timestamp = "2026-10-16T08:00:00.000Z";
  const payload = {
    scope: { environmentId: "test-env", appId: null },
    asOf: timestamp,
    coverage: "complete",
    bindings: { total: 2, attempted: 2, current: 2, stale: 0, notRead: 0 },
  };
  let requestBody;
  await run(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        response(request, { initialized: true }),
      ),
      http.post(`${origin}/api/v2/rules/catalog/refresh`, async ({ request }) => {
        requestBody = await request.json();
        return response(request, payload);
      }),
    ],
    async (port, identity) => {
      await identity.readBootstrap(new AbortController().signal);
      const result = await port.refreshRuleCatalog("test-env", null, new AbortController().signal);
      assert.deepEqual(requestBody, { environmentId: "test-env", appId: null });
      assert.deepEqual(result, payload);
    },
  );
});

test("RULE-CATALOG HTTP: mismatched query echo and unknown wire fields fail closed", async () => {
  const query = {
    environmentId: "test-env",
    appId: null,
    kind: null,
    search: "",
    page: 1,
    pageSize: 25,
  };
  const timestamp = "2026-10-16T08:00:00.000Z";
  const payload = {
    query: { ...query, environmentId: "other-env" },
    asOf: timestamp,
    coverage: "complete",
    bindings: { total: 0, current: 0, stale: 0, notRead: 0 },
    total: 0,
    hasMore: false,
    items: [],
    issues: [],
    unexpected: true,
  };
  await run(
    [http.get(`${origin}/api/v2/rules/catalog`, ({ request }) => response(request, payload))],
    async (port) => {
      await assert.rejects(port.readRuleCatalog(query, new AbortController().signal));
    },
  );
});

test("RULE-BINDING-REGISTER: sends an idempotent strict command and rejects a mismatched response", async () => {
  const command = {
    requestKey: "binding-create-1",
    bindingId: "checkout-prod-flow",
    environmentId: "prod",
    appId: "checkout",
    kind: "flow",
    profile: "sentinel-flow-v1",
    sourceId: "nacos-main",
    sourceRevision: "source-revision-1",
    target: {
      provider: "nacos",
      namespace: "prod-namespace",
      group: "DEFAULT_GROUP",
      dataId: "flow-rules.json",
    },
  };
  const registered = {
    id: command.bindingId,
    environmentId: command.environmentId,
    appId: command.appId,
    kind: command.kind,
    profile: command.profile,
    sourceId: command.sourceId,
    sourceLabel: "Operations Nacos",
    location: "nacos://prod-namespace/DEFAULT_GROUP/flow-rules.json",
  };
  let sentRequest;
  await run(
    [
      http.get(`${origin}/api/v1/rulesets`, ({ request }) =>
        response(request, {
          query: {
            environmentId: "prod",
            appId: null,
            kind: null,
            search: "",
            page: 1,
            pageSize: 1,
          },
          total: 0,
          items: [],
        }),
      ),
      http.post(`${origin}/api/v1/rulesets`, async ({ request }) => {
        sentRequest = {
          body: await request.json(),
          idempotencyKey: request.headers.get("idempotency-key"),
          csrf: request.headers.get("x-sentinel-csrf"),
        };
        return response(request, registered, 201);
      }),
    ],
    async (port) => {
      await port.readBindings(
        {
          environmentId: "prod",
          appId: null,
          kind: null,
          search: "",
          page: 1,
          pageSize: 1,
        },
        new AbortController().signal,
      );
      assert.deepEqual(
        await port.registerBinding(command, new AbortController().signal),
        registered,
      );
      assert.deepEqual(sentRequest.body, command);
      assert.equal(sentRequest.idempotencyKey, command.requestKey);
      assert.equal(sentRequest.csrf, "R".repeat(48));
    },
  );
  await run(
    [
      http.get(`${origin}/api/v1/rulesets`, ({ request }) =>
        response(request, {
          query: {
            environmentId: "prod",
            appId: null,
            kind: null,
            search: "",
            page: 1,
            pageSize: 1,
          },
          total: 0,
          items: [],
        }),
      ),
      http.post(`${origin}/api/v1/rulesets`, ({ request }) =>
        response(request, { ...registered, sourceId: "other-source" }, 201),
      ),
    ],
    async (port) => {
      await port.readBindings(
        {
          environmentId: "prod",
          appId: null,
          kind: null,
          search: "",
          page: 1,
          pageSize: 1,
        },
        new AbortController().signal,
      );
      await assert.rejects(
        port.registerBinding(command, new AbortController().signal),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});

test("RULE-SNAPSHOT: UTC and full rule facts map; identity mismatch and unknown fields fail closed", async () => {
  const wire = {
    binding: ruleSet.binding,
    versionId: ruleSet.versionId,
    checksum: ruleSet.checksum,
    sourceRevision: ruleSet.sourceRevision,
    asOf: instant(ruleSet.asOfMs),
    records: ruleSet.records,
  };
  await run(
    [
      http.get(`${origin}/api/v1/rulesets/:bindingId/snapshot`, ({ request }) =>
        response(request, wire),
      ),
    ],
    async (port) => {
      assert.deepEqual(
        await port.readSnapshot(ruleSet.binding.id, new AbortController().signal),
        ruleSet,
      );
      await assert.rejects(
        port.readSnapshot("another-binding", new AbortController().signal),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
  const invalid = { ...wire, records: [wire.records[0], wire.records[0]], password: "PRIVATE" };
  await run(
    [
      http.get(`${origin}/api/v1/rulesets/:bindingId/snapshot`, ({ request }) =>
        response(request, invalid),
      ),
    ],
    async (port) => {
      await assert.rejects(
        port.readSnapshot(ruleSet.binding.id, new AbortController().signal),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});

test("RULE-CANDIDATE: full-set validation binds the exact checksum/profile and rejects duplicate or non-finite input before dispatch", async () => {
  const candidate = {
    bindingId: ruleSet.binding.id,
    profile: ruleSet.binding.profile,
    kind: ruleSet.binding.kind,
    baseVersionId: ruleSet.versionId,
    baseChecksum: ruleSet.checksum,
    sourceRevision: ruleSet.sourceRevision,
    rules: ruleSet.records.map((record) => ({ recordId: record.id, rule: record.rule })),
  };
  let calls = 0;
  await run(
    [
      http.get(`${origin}/api/v1/rulesets`, ({ request }) =>
        response(request, {
          query: {
            environmentId: "test-env",
            appId: null,
            kind: null,
            search: "",
            page: 1,
            pageSize: 10,
          },
          total: 1,
          items: [ruleSet.binding],
        }),
      ),
      http.post(`${origin}/api/v1/rulesets/:bindingId/validate`, async ({ request, params }) => {
        calls += 1;
        assert.equal(params.bindingId, candidate.bindingId);
        assert.equal(request.headers.get("x-sentinel-csrf"), "R".repeat(48));
        assert.deepEqual(await request.json(), candidate);
        return response(request, {
          bindingId: candidate.bindingId,
          profile: candidate.profile,
          baseChecksum: candidate.baseChecksum,
          candidateChecksum: "server-candidate-checksum",
          validationId: "validation-ticket-one",
          isPublishable: true,
          issues: [],
        });
      }),
    ],
    async (port) => {
      await port.readBindings(
        { environmentId: "test-env", appId: null, kind: null, search: "", page: 1, pageSize: 10 },
        new AbortController().signal,
      );
      assert.equal(
        (await port.validateCandidate(candidate, new AbortController().signal)).isPublishable,
        true,
      );
      await assert.rejects(
        port.validateCandidate(
          { ...candidate, rules: [candidate.rules[0], candidate.rules[0]] },
          new AbortController().signal,
        ),
        (error) => error.code === "console_request_invalid",
      );
      assert.equal(calls, 1);
    },
  );
});

test("RULE-COLLECTIONS: drafts, versions, publications and plans retain binding ownership and UTC revisions", async () => {
  const bindingId = ruleSet.binding.id;
  const draft = {
    id: "draft-one",
    bindingId,
    revision: "draft-r2",
    kind: ruleSet.binding.kind,
    profile: ruleSet.binding.profile,
    baseVersionId: ruleSet.versionId,
    baseChecksum: ruleSet.checksum,
    sourceRevision: ruleSet.sourceRevision,
    updatedAt: instant(ruleSet.asOfMs),
    records: ruleSet.records,
  };
  const version = {
    id: "version-one",
    bindingId,
    kind: ruleSet.binding.kind,
    profile: ruleSet.binding.profile,
    baseVersionId: null,
    checksum: ruleSet.checksum,
    name: "Daily",
    note: "",
    createdAt: instant(ruleSet.asOfMs),
    createdById: "operator-one",
    records: ruleSet.records,
  };
  const publication = {
    id: "publication-one",
    bindingId,
    targetVersionId: version.id,
    targetChecksum: version.checksum,
    baseVersionId: null,
    createdAt: instant(ruleSet.asOfMs),
    validation: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
    configurationWrite: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
    readBack: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
  };
  const plan = {
    id: "plan-one",
    revision: "plan-r1",
    bindingId,
    versionId: version.id,
    restoreVersionId: "version-restore",
    activateAt: instant(ruleSet.asOfMs + 60_000),
    deactivateAt: instant(ruleSet.asOfMs + 120_000),
    timeZone: "Asia/Shanghai",
    state: "pending",
    activationPublicationId: null,
    restorePublicationId: null,
  };
  const list = (items) => ({ bindingId, asOf: instant(ruleSet.asOfMs), items });
  await run(
    [
      http.get(`${origin}/api/v1/rulesets/:bindingId/drafts`, ({ request }) =>
        response(request, list([draft])),
      ),
      http.get(`${origin}/api/v1/rulesets/:bindingId/versions`, ({ request }) =>
        response(request, list([version])),
      ),
      http.get(`${origin}/api/v1/rulesets/:bindingId/publications`, ({ request }) =>
        response(request, list([publication])),
      ),
      http.get(`${origin}/api/v1/rulesets/:bindingId/plans`, ({ request }) =>
        response(request, list([plan])),
      ),
    ],
    async (port) => {
      const drafts = await port.readDrafts(bindingId, new AbortController().signal);
      assert.deepEqual(drafts, {
        bindingId,
        asOfMs: ruleSet.asOfMs,
        items: [
          {
            id: draft.id,
            bindingId: draft.bindingId,
            revision: draft.revision,
            kind: draft.kind,
            profile: draft.profile,
            baseVersionId: draft.baseVersionId,
            baseChecksum: draft.baseChecksum,
            sourceRevision: draft.sourceRevision,
            updatedAtMs: ruleSet.asOfMs,
            records: draft.records,
          },
        ],
      });
      assert.equal(Object.hasOwn(drafts.items[0], "updatedAt"), false);

      const versions = await port.readVersions(bindingId, new AbortController().signal);
      assert.equal(versions.items[0].createdAtMs, ruleSet.asOfMs);
      assert.equal(Object.hasOwn(versions.items[0], "createdAt"), false);

      const publications = await port.readPublications(bindingId, new AbortController().signal);
      assert.equal(publications.items[0].createdAtMs, ruleSet.asOfMs);
      assert.equal(Object.hasOwn(publications.items[0], "createdAt"), false);
      assert.equal(Object.hasOwn(publications.items[0].validation, "observedAt"), false);

      const plans = await port.readPlans(bindingId, new AbortController().signal);
      assert.equal(plans.items[0].activateAtMs, ruleSet.asOfMs + 60_000);
      assert.equal(plans.items[0].state, "pending");
      assert.equal(Object.hasOwn(plans.items[0], "activateAt"), false);
      assert.equal(Object.hasOwn(plans.items[0], "deactivateAt"), false);
    },
  );
});

test("RULE-RECEIPTS: publication identity, denominator and incarnation-bound applied evidence are all required", async () => {
  const bindingId = ruleSet.binding.id;
  const publicationId = "publication-one";
  const publication = {
    id: publicationId,
    bindingId,
    targetVersionId: "version-one",
    targetChecksum: "checksum-one",
    baseVersionId: null,
    createdAt: instant(ruleSet.asOfMs),
    validation: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
    configurationWrite: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
    readBack: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
  };
  let order = 0;
  await run(
    [
      http.get(
        `${origin}/api/v1/rulesets/:bindingId/publications/:publicationId`,
        ({ request }) => {
          order += 1;
          return response(request, publication);
        },
      ),
      http.get(
        `${origin}/api/v1/rulesets/:bindingId/publications/:publicationId/receipts`,
        ({ request }) => {
          order += 1;
          const params = new URL(request.url).searchParams;
          assert.equal(params.get("page"), "1");
          assert.equal(params.get("pageSize"), "25");
          return response(request, {
            publicationId,
            bindingId,
            page: 1,
            pageSize: 25,
            asOf: instant(ruleSet.asOfMs),
            total: 1,
            expected: 1,
            inventorySource: "agent-reporting-v1",
            applied: 1,
            pending: 0,
            failed: 0,
            unknown: 0,
            restartRequired: 0,
            items: [
              {
                instanceId: "instance-one",
                processEpoch: "epoch-one",
                loadedProcessEpoch: "epoch-one",
                targetVersionId: publication.targetVersionId,
                loadedVersionId: publication.targetVersionId,
                loadedChecksum: publication.targetChecksum,
                appliedAt: instant(ruleSet.asOfMs),
                lastReportAt: instant(ruleSet.asOfMs),
                state: "applied",
              },
            ],
          });
        },
      ),
    ],
    async (port) => {
      const page = await port.readReceipts(
        { bindingId, publicationId, page: 1, pageSize: 25 },
        new AbortController().signal,
      );
      assert.equal(page.items[0].state, "applied");
      assert.equal(page.items[0].processEpoch, "epoch-one");
      assert.equal(page.asOfMs, ruleSet.asOfMs);
      assert.equal(Object.hasOwn(page, "asOf"), false);
      assert.equal(Object.hasOwn(page.items[0], "appliedAt"), false);
      assert.equal(Object.hasOwn(page.items[0], "lastReportAt"), false);
      assert.equal(order, 2);
    },
  );
});

test("RULE-RECEIPTS-CONTEXT: rows must belong to the requested page and immutable publication", async () => {
  const bindingId = ruleSet.binding.id;
  const publicationId = "publication-context";
  const publication = {
    id: publicationId,
    bindingId,
    targetVersionId: "version-one",
    targetChecksum: "checksum-one",
    baseVersionId: null,
    createdAt: instant(ruleSet.asOfMs),
    validation: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
    configurationWrite: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
    readBack: { state: "succeeded", observedAt: instant(ruleSet.asOfMs), reason: null },
  };
  const receipt = {
    instanceId: "instance-one",
    processEpoch: "epoch-one",
    loadedProcessEpoch: "epoch-one",
    targetVersionId: publication.targetVersionId,
    loadedVersionId: publication.targetVersionId,
    loadedChecksum: publication.targetChecksum,
    appliedAt: instant(ruleSet.asOfMs),
    lastReportAt: instant(ruleSet.asOfMs),
    state: "applied",
  };
  let page = {
    publicationId,
    bindingId,
    page: 1,
    pageSize: 25,
    asOf: instant(ruleSet.asOfMs),
    total: 1,
    expected: 1,
    inventorySource: "agent-reporting-v1",
    applied: 1,
    pending: 0,
    failed: 0,
    unknown: 0,
    restartRequired: 0,
    items: [receipt],
  };
  await run(
    [
      http.get(`${origin}/api/v1/rulesets/:bindingId/publications/:publicationId`, ({ request }) =>
        response(request, publication),
      ),
      http.get(
        `${origin}/api/v1/rulesets/:bindingId/publications/:publicationId/receipts`,
        ({ request }) => response(request, page),
      ),
    ],
    async (port) => {
      const invalidPages = [
        { ...page, publicationId: "another-publication" },
        { ...page, bindingId: "another-binding" },
        { ...page, page: 2, pageSize: 1, total: 2, expected: 2, applied: 2 },
        { ...page, pageSize: 20 },
        { ...page, items: [{ ...receipt, targetVersionId: "another-version" }] },
        { ...page, items: [{ ...receipt, loadedChecksum: "another-checksum" }] },
        { ...page, items: [{ ...receipt, loadedProcessEpoch: "another-epoch" }] },
      ];
      for (const candidate of invalidPages) {
        page = candidate;
        await assert.rejects(
          port.readReceipts(
            { bindingId, publicationId, page: 1, pageSize: 25 },
            new AbortController().signal,
          ),
        );
      }
    },
  );
});

test("RULE-COMMAND: request key is idempotency header; pending and not-found remain non-replay facts", async () => {
  let writes = 0;
  await run(
    [
      http.get(`${origin}/api/v1/rulesets`, ({ request }) =>
        response(request, {
          query: {
            environmentId: "test-env",
            appId: null,
            kind: null,
            search: "",
            page: 1,
            pageSize: 10,
          },
          total: 1,
          items: [ruleSet.binding],
        }),
      ),
      http.post(`${origin}/api/v1/rulesets/:bindingId/commands`, async ({ request, params }) => {
        const body = await request.json();
        writes += 1;
        assert.equal(params.bindingId, ruleSet.binding.id);
        assert.equal(request.headers.get("idempotency-key"), body.requestKey);
        assert.equal(body.requestKey, "rule-delete-001");
        assert.equal(body.mutation.kind, "delete_draft");
        assert.equal(body.bindingId, undefined);
        return response(
          request,
          {
            bindingId: ruleSet.binding.id,
            requestKey: body.requestKey,
            status: "pending",
          },
          202,
        );
      }),
      http.get(
        `${origin}/api/v1/rulesets/:bindingId/operations/:requestKey`,
        ({ request, params }) =>
          response(request, {
            bindingId: params.bindingId,
            requestKey: params.requestKey,
            status: "not-found",
          }),
      ),
    ],
    async (port) => {
      await port.readBindings(
        { environmentId: "test-env", appId: null, kind: null, search: "", page: 1, pageSize: 10 },
        new AbortController().signal,
      );
      const mutation = {
        kind: "delete_draft",
        bindingId: ruleSet.binding.id,
        requestKey: "rule-delete-001",
        draftId: "draft-one",
        expectedRevision: "revision-one",
      };
      assert.equal(
        (await port.mutateRuleSet(mutation, new AbortController().signal)).status,
        "pending",
      );
      assert.equal(
        (
          await port.readRuleOperation(
            mutation.bindingId,
            mutation.requestKey,
            new AbortController().signal,
          )
        ).status,
        "not-found",
      );
      assert.equal(writes, 1);
    },
  );
});
