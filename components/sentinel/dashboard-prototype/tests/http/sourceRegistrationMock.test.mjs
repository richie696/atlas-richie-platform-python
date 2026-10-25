import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createSourceRegistrationHttp } from "../../src/features/system/api/sourceRegistrationHttp";
import { createSourceRegistrationWorkflow } from "../../src/features/system/application/sourceRegistrationWorkflow";
import { createSourceRegistrationMockHandlers } from "../../src/features/system/fixtures/sourceRegistrationMockHandlers";
import { MOCK_SYSTEM_SCENARIO } from "../../src/app/api/mockSystemScenario";
import { MOCK_ROLE_STORAGE_KEY, writeMockPrincipal } from "../../src/core/api/mock/mockRole";

const origin = "http://source-registry-mock.test";
const signal = () => new AbortController().signal;
async function run(action, referencedSourceIds = []) {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  if (!previousWindow) {
    const values = new Map([[MOCK_ROLE_STORAGE_KEY, "admin"]]);
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: (key) => values.get(key) ?? null,
          setItem: (key, value) => values.set(key, value),
          removeItem: (key) => values.delete(key),
        },
      },
    });
  }
  const sourceMock = createSourceRegistrationMockHandlers(
    [MOCK_SYSTEM_SCENARIO.primarySource],
    MOCK_SYSTEM_SCENARIO.sourceCheck,
    Date.now,
    referencedSourceIds,
  );
  writeMockPrincipal("admin");
  const server = setupServer(...sourceMock.handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "source-registry-owner",
    onUnauthorized: () => {},
    requestId: () => `source-registry-${++sequence}`,
  });
  try {
    await action(createSourceRegistrationHttp(transport), sourceMock);
  } finally {
    transport.dispose();
    server.close();
    sourceMock.reset();
    if (previousWindow) writeMockPrincipal("admin");
    else delete globalThis.window;
  }
}

test("SOURCE-MOCK-DELETE: deletion is revision-bound, idempotent and removes only an unreferenced registration", async () => {
  await run(async (port) => {
    const record = (await port.readSources(signal())).items[0];
    const deletion = {
      kind: "delete",
      requestKey: "source-delete-one",
      sourceId: record.id,
      expectedRevision: record.revision,
    };
    const first = await port.mutateSource(deletion, signal());
    const replay = await port.mutateSource(deletion, signal());
    assert.deepEqual(first, {
      requestKey: deletion.requestKey,
      status: "completed",
      deletedSourceId: record.id,
    });
    assert.deepEqual(replay, first);
    assert.equal((await port.readSources(signal())).items.length, 0);
    assert.deepEqual(await port.readSourceOperation(deletion.requestKey, signal()), first);
    assert.doesNotMatch(JSON.stringify(first), /endpoint|credential|password|token/i);
  });
});

test("SOURCE-MOCK-DELETE-IN-USE: a referenced source is preserved and deletion is rejected", async () => {
  const id = MOCK_SYSTEM_SCENARIO.primarySource.id;
  await run(
    async (port) => {
      const workflow = createSourceRegistrationWorkflow(
        port,
        {
          read: () => ({ ownerKey: "admin-session", allowed: true }),
          subscribe: () => () => {},
        },
        () => "source-delete-in-use",
      );
      try {
        const registry = await workflow.registry.load(null);
        await assert.rejects(workflow.deleteSource(registry.items[0]), (error) => {
          assert.equal(error.code, "source_in_use");
          return true;
        });
        assert.equal(workflow.getSnapshot().command.status, "error");
        assert.equal((await port.readSources(signal())).items[0].id, id);
      } finally {
        workflow.dispose();
      }
    },
    [id],
  );
});

test("SOURCE-MOCK-REGISTRY: admin reads safe seeded source through HTTP and workflow", async () => {
  await run(async (port) => {
    const workflow = createSourceRegistrationWorkflow(
      port,
      {
        read: () => ({ ownerKey: "admin-session", allowed: true }),
        subscribe: () => () => {},
      },
      () => "source-read-test",
    );
    try {
      const result = await workflow.registry.load(null);
      assert.equal(result.items.length, 1);
      assert.equal(result.items[0].id, "nacos-primary");
      assert.equal(result.items[0].provider, "nacos");
      assert.doesNotMatch(JSON.stringify(result), /vault:\/\/|password|aclToken|username/i);
    } finally {
      workflow.dispose();
    }
  });
});

test("SOURCE-MOCK-RESET: reset restores only the factory-owned canonical seed", async () => {
  await run(async (port, mock) => {
    await port.readSources(signal());
    const result = await port.mutateSource(
      {
        kind: "register",
        requestKey: "source-reset-consul-1",
        name: "temporary",
        source: {
          provider: "consul",
          endpoint: "https://consul.example.com",
          datacenter: "dc-reset",
          authentication: { mode: "none" },
        },
      },
      signal(),
    );
    assert.equal(result.status, "completed");
    assert.equal((await port.readSources(signal())).items.length, 2);

    mock.reset();
    const registry = await port.readSources(signal());
    assert.equal(registry.items.length, 1);
    assert.equal(registry.items[0].id, MOCK_SYSTEM_SCENARIO.primarySource.id);
    assert.equal(
      await port
        .readSourceOperation("source-reset-consul-1", signal())
        .then((value) => value.status),
      "not-found",
    );
  });
});

test("SOURCE-MOCK-COMMAND: direct Consul secret is write-only, revisioned and idempotent", async () => {
  await run(async (port) => {
    await port.readSources(signal()); // Receive the transport's ephemeral CSRF nonce.
    const input = {
      kind: "register",
      requestKey: "source-create-consul-1",
      name: "secondary",
      source: {
        provider: "consul",
        endpoint: "https://consul.example.com",
        datacenter: "dc-west",
        authentication: { mode: "direct", aclToken: "PRIVATE-CONSUL-TOKEN" },
      },
    };
    const first = await port.mutateSource(input, signal());
    const replay = await port.mutateSource(input, signal());
    assert.deepEqual(replay, first);
    assert.equal(first.status, "completed");
    assert.equal(first.record.provider, "consul");
    assert.equal(first.record.authenticationMode, "direct");
    assert.equal(first.record.credentialConfigured, true);
    assert.doesNotMatch(JSON.stringify(first), /PRIVATE-CONSUL-TOKEN/);
    const registry = await port.readSources(signal());
    assert.equal(registry.items.length, 2);
    assert.doesNotMatch(JSON.stringify(registry), /PRIVATE-CONSUL-TOKEN/);
    const operation = await port.readSourceOperation(input.requestKey, signal());
    assert.deepEqual(operation, first);
    assert.doesNotMatch(JSON.stringify(operation), /PRIVATE-CONSUL-TOKEN/);
    await assert.rejects(
      port.mutateSource(
        {
          ...input,
          source: { ...input.source, authentication: { mode: "direct", aclToken: "OTHER-TOKEN" } },
        },
        signal(),
      ),
      (error) => error.code === "idempotency_conflict" && error.status === 409,
    );
    assert.equal((await port.readSources(signal())).items.length, 2);
  });
});

test("SOURCE-MOCK-REVISION: stale conditional update is rejected without changing the source", async () => {
  await run(async (port) => {
    const before = await port.readSources(signal());
    const source = before.items[0];
    const result = await port.mutateSource(
      {
        kind: "update",
        requestKey: "source-stale-update-1",
        sourceId: source.id,
        expectedRevision: "stale-revision",
        name: "renamed",
        source: {
          provider: "nacos",
          endpoint: source.endpoint,
          namespace: source.namespace,
          authentication: { mode: "keep" },
        },
      },
      signal(),
    );
    assert.deepEqual(result, {
      status: "rejected",
      requestKey: "source-stale-update-1",
      reason: "conflict",
    });
    assert.deepEqual((await port.readSources(signal())).items, before.items);
  });
});

test("SOURCE-MOCK-CHECK: check only returns a synthetic safe result and never changes registry", async () => {
  await run(async (port) => {
    const before = await port.readSources(signal());
    const input = {
      sourceId: null,
      expectedRevision: null,
      source: {
        provider: "nacos",
        endpoint: "https://nacos.example.com",
        namespace: "demo",
        authentication: { mode: "credential-reference", reference: "vault://PRIVATE-REF" },
      },
    };
    const result = await port.checkSource(input, signal());
    assert.equal(result.status, "reachable");
    assert.deepEqual(result.capabilities, MOCK_SYSTEM_SCENARIO.sourceCheck.capabilities);
    assert.doesNotMatch(JSON.stringify(result), /PRIVATE-REF/);
    assert.deepEqual((await port.readSources(signal())).items, before.items);
  });
});

test("SOURCE-MOCK-CHECK-FAILURE: the app scenario owns the synthetic unavailable endpoint", async () => {
  await run(async (port) => {
    await port.readSources(signal()); // Receive the transport's ephemeral CSRF nonce.
    const result = await port.checkSource(
      {
        sourceId: null,
        expectedRevision: null,
        source: {
          provider: "nacos",
          endpoint: `https://${MOCK_SYSTEM_SCENARIO.sourceCheck.unavailableHostname}`,
          namespace: "demo",
          authentication: { mode: "none" },
        },
      },
      signal(),
    );
    assert.equal(result.status, "unreachable");
    assert.equal(result.reason, "connection");
    assert.equal(
      result.expiresAtMs - result.checkedAtMs,
      MOCK_SYSTEM_SCENARIO.sourceCheck.validForMs,
    );
  });
});

test("SOURCE-MOCK-AUTHORIZATION: viewer cannot read the registered source registry", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
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
  try {
    await run(async (port) => {
      storage.set(MOCK_ROLE_STORAGE_KEY, "view");
      await assert.rejects(port.readSources(signal()), (error) => error.code === "forbidden");
    });
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else delete globalThis.window;
  }
});

test("SOURCE-MOCK-PROTOCOL: missing CSRF and mismatched idempotency keys never mutate state", async () => {
  await run(async (port) => {
    const before = await port.readSources(signal());
    const input = {
      kind: "register",
      requestKey: "source-protocol-negative-1",
      name: "must-not-register",
      source: {
        provider: "consul",
        endpoint: "https://consul.example.com",
        datacenter: "dc-negative",
        authentication: { mode: "none" },
      },
    };
    const request = async (extraHeaders, requestBody = input) =>
      fetch(`${origin}/api/v1/system/sources/commands`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-request-id": "source-protocol-negative-id",
          ...extraHeaders,
        },
        body: JSON.stringify(requestBody),
      });
    const missingCsrf = await request({ "idempotency-key": input.requestKey });
    assert.equal(missingCsrf.status, 403);
    assert.equal((await missingCsrf.json()).error.code, "csrf_failed");
    const missingKey = await request({ "x-sentinel-csrf": "M".repeat(48) });
    assert.equal(missingKey.status, 422);
    assert.equal((await missingKey.json()).error.code, "validation_failed");
    const invalidBody = await request(
      { "x-sentinel-csrf": "M".repeat(48), "idempotency-key": input.requestKey },
      { ...input, name: undefined },
    );
    assert.equal(invalidBody.status, 422);
    assert.equal((await invalidBody.json()).error.code, "validation_failed");
    const mismatchedKey = await request({
      "x-sentinel-csrf": "M".repeat(48),
      "idempotency-key": "different-request-key",
    });
    assert.equal(mismatchedKey.status, 409);
    assert.equal((await mismatchedKey.json()).error.code, "idempotency_conflict");
    assert.deepEqual((await port.readSources(signal())).items, before.items);
  });
});
