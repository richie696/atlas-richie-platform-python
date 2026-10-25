import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { MOCK_ROLE_STORAGE_KEY, writeMockPrincipal } from "../../src/core/api/mock/mockRole";
import { MOCK_IDENTITY_SCENARIO } from "../../src/app/api/mockIdentityScenario";
import { MOCK_RULE_SCENARIO } from "../../src/app/api/mockRuleScenario";
import { MOCK_SYSTEM_SCENARIO } from "../../src/app/api/mockSystemScenario";
import { createRuleSetHttp } from "../../src/features/rules/api/ruleSetHttp";
import { RULE_MUTATION } from "../../src/features/rules/model/ruleSetOperations";
import { createRuleSetMockHandlers } from "../../src/features/rules/mock";
import { createSourceRegistrationHttp } from "../../src/features/system/api/sourceRegistrationHttp";
import { createSourceRegistrationMockHandlers } from "../../src/features/system/fixtures/sourceRegistrationMockHandlers";
import { createConsoleAuthentication } from "../../src/app/api/consoleAuthentication";
import { createAccountManagementHttp } from "../../src/features/identity/api/accountManagementHttp";
import { createAccountManagementWorkflow } from "../../src/features/identity/application/accountManagementWorkflow";
import { http, HttpResponse } from "msw/http";

const origin = "http://viewer-write-denial.test";
const signal = () => new AbortController().signal;
const csrfFailure = (error) => error.code === "forbidden" && error.status === 403;

test("F7.2-VIEWER-WRITE-DENIAL: feature adapters reject viewer writes before fixture state changes", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const storage = new Map();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: (key) => storage.delete(key),
      },
    },
  });

  const ruleHandlers = createRuleSetMockHandlers(
    MOCK_RULE_SCENARIO,
    MOCK_IDENTITY_SCENARIO.accounts.find((account) => account.builtIn).id,
  );
  const sourceHandlers = createSourceRegistrationMockHandlers(
    [MOCK_SYSTEM_SCENARIO.primarySource],
    MOCK_SYSTEM_SCENARIO.sourceCheck,
  );
  const server = setupServer(...ruleHandlers.handlers, ...sourceHandlers.handlers);
  server.listen({ onUnhandledRequest: "error" });

  let requestSequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "viewer-write-denial-owner",
    onUnauthorized: () => {},
    requestId: () => `viewer-write-denial-${++requestSequence}`,
  });
  const rules = createRuleSetHttp(transport);
  const sources = createSourceRegistrationHttp(transport);

  try {
    writeMockPrincipal("admin");
    const baselineSources = await sources.readSources(signal());
    const baselineSnapshot = await rules.readSnapshot(
      MOCK_RULE_SCENARIO.deployment.eventVersion.bindingId,
      signal(),
    );
    const sourceRequestKey = "viewer-source-register-denied";
    const ruleRequestKey = "viewer-rule-command-denied";
    const sourceMutation = {
      kind: "register",
      requestKey: sourceRequestKey,
      name: "must-not-register",
      source: {
        provider: "consul",
        endpoint: "https://consul.example.com",
        datacenter: "dc-viewer-denial",
        authentication: { mode: "none" },
      },
    };
    const sourceCheck = {
      sourceId: null,
      expectedRevision: null,
      source: {
        provider: "nacos",
        endpoint: "https://nacos.example.com",
        namespace: "viewer-denial",
        authentication: { mode: "none" },
      },
    };
    const candidate = {
      bindingId: baselineSnapshot.binding.id,
      profile: baselineSnapshot.binding.profile,
      kind: baselineSnapshot.binding.kind,
      baseVersionId: baselineSnapshot.versionId,
      baseChecksum: baselineSnapshot.checksum,
      sourceRevision: baselineSnapshot.sourceRevision,
      rules: baselineSnapshot.records.map((record) => ({ recordId: record.id, rule: record.rule })),
    };
    const ruleMutation = {
      kind: RULE_MUTATION.SaveDraft,
      requestKey: ruleRequestKey,
      bindingId: baselineSnapshot.binding.id,
      draftId: null,
      expectedRevision: null,
      candidate,
    };

    writeMockPrincipal("view");
    await assert.rejects(rules.mutateRuleSet(ruleMutation, signal()), csrfFailure);
    await assert.rejects(sources.mutateSource(sourceMutation, signal()), csrfFailure);
    await assert.rejects(sources.checkSource(sourceCheck, signal()), csrfFailure);

    writeMockPrincipal("admin");
    assert.deepEqual((await sources.readSources(signal())).items, baselineSources.items);
    const afterSnapshot = await rules.readSnapshot(baselineSnapshot.binding.id, signal());
    const { asOfMs: _baselineReadAt, ...baselineSnapshotFacts } = baselineSnapshot;
    const { asOfMs: _afterReadAt, ...afterSnapshotFacts } = afterSnapshot;
    assert.deepEqual(afterSnapshotFacts, baselineSnapshotFacts);
    assert.equal(
      (await sources.readSourceOperation(sourceRequestKey, signal())).status,
      "not-found",
    );
    assert.equal(
      (await rules.readRuleOperation(baselineSnapshot.binding.id, ruleRequestKey, signal())).status,
      "not-found",
    );
  } finally {
    transport.dispose();
    server.close();
    ruleHandlers.reset();
    sourceHandlers.reset();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("F7.2-ROLE-REVOCATION: a 403 revalidates the principal and clears cached admin data", async () => {
  const csrf = "R".repeat(48);
  const admin = {
    accountId: "current-admin",
    username: "operator",
    roleId: "admin",
    capabilities: ["metrics:view", "rules:write"],
    sessionEpoch: "session-admin",
  };
  const viewer = {
    ...admin,
    roleId: "view",
    capabilities: ["metrics:view"],
    sessionEpoch: "session-viewer",
  };
  const protectedAccount = {
    id: "sensitive-account",
    username: "restricted-operator",
    roleId: "view",
    status: "active",
    builtIn: false,
    lastLoginAt: null,
    revision: "1",
    lastActiveAdmin: false,
  };
  let sessionReads = 0;
  let directoryReads = 0;
  let deniedCommands = 0;
  const server = setupServer(
    http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
      HttpResponse.json(
        { initialized: true },
        {
          headers: {
            "x-request-id": request.headers.get("x-request-id"),
            "x-sentinel-csrf": csrf,
          },
        },
      ),
    ),
    http.get(`${origin}/api/v1/auth/me`, ({ request }) => {
      sessionReads++;
      const identity = sessionReads === 1 ? admin : viewer;
      return HttpResponse.json(identity, {
        headers: {
          "x-request-id": request.headers.get("x-request-id"),
          "x-sentinel-csrf": csrf,
        },
      });
    }),
    http.get(`${origin}/api/v1/accounts`, ({ request }) => {
      directoryReads++;
      return HttpResponse.json(
        { items: [protectedAccount], page: 1, pageSize: 20, total: 1 },
        {
          headers: {
            "x-request-id": request.headers.get("x-request-id"),
            "x-sentinel-csrf": csrf,
          },
        },
      );
    }),
    http.post(`${origin}/api/v1/accounts/commands`, ({ request }) => {
      deniedCommands++;
      return HttpResponse.json(
        {
          error: {
            code: "forbidden",
            requestId: request.headers.get("x-request-id"),
          },
        },
        {
          status: 403,
          headers: {
            "x-request-id": request.headers.get("x-request-id"),
            "x-sentinel-csrf": csrf,
          },
        },
      );
    }),
  );
  server.listen({ onUnhandledRequest: "error" });
  let requestSequence = 0;
  const runtime = createConsoleAuthentication({
    baseUrl: origin,
    requestId: () => `role-revocation-${++requestSequence}`,
  });
  try {
    await runtime.authentication.restore();
    const current = runtime.authentication.getSnapshot().access;
    assert.equal(current.phase, "resolved");
    if (current.phase !== "resolved" || current.facts.kind !== "authenticated")
      throw new Error("Expected a confirmed administrator session");

    const accounts = createAccountManagementHttp(runtime.transport);
    const manager = createAccountManagementWorkflow(
      accounts,
      current.facts.identity,
      runtime.session,
      () => "role-revocation-command",
    );
    try {
      const page = await manager.list({ page: 1, pageSize: 20, search: "" });
      assert.deepEqual(page.items, [protectedAccount]);
      assert.equal(manager.getSnapshot().directory.status, "ready");

      await assert.rejects(
        manager.create({
          username: "new-operator",
          password: "F7.2-SYNTHETIC-ONLY-PASSWORD",
          roleId: "view",
        }),
        (error) => error.status === 403 && error.code === "forbidden",
      );

      const access = runtime.authentication.getSnapshot().access;
      assert.equal(access.phase, "resolved");
      if (access.phase !== "resolved" || access.facts.kind !== "authenticated")
        throw new Error("Expected the downgraded viewer session to remain authenticated");
      assert.equal(access.facts.identity.roleId, "view");
      assert.equal(manager.getSnapshot().authorized, false);
      assert.equal(manager.getSnapshot().directory.status, "idle");
      assert.equal(JSON.stringify(manager.getSnapshot()).includes("restricted-operator"), false);
      assert.equal(directoryReads, 1);
      assert.equal(deniedCommands, 1, "a forbidden command must not be replayed");
      await assert.rejects(
        manager.list({ page: 1, pageSize: 20, search: "" }),
        (error) => error.status === 403,
      );
      assert.equal(directoryReads, 1, "stale admin authority must not dispatch another read");
    } finally {
      manager.dispose();
    }
  } finally {
    runtime.dispose();
    server.close();
  }
});
