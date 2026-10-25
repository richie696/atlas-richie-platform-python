import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createMonitoringSourceHttp } from "../../src/features/system/api/monitoringSourceHttp";
import { createMonitoringSourceMockHandlers } from "../../src/features/system/fixtures/monitoringSourceMockHandlers";
import { MOCK_ROLE_STORAGE_KEY, writeMockPrincipal } from "../../src/core/api/mock/mockRole";

const origin = "http://monitoring-source-mock.test";
const signal = () => new AbortController().signal;
const candidate = (overrides = {}) => ({
  sourceId: "prometheus-test",
  revision: "candidate-1",
  displayName: "Test Prometheus",
  environmentId: "test",
  endpoint: "https://prometheus.example.test/api/v1/query",
  provider: "prometheus-compatible",
  profile: "node-exporter-v1",
  authenticationMode: "none",
  credentialConfigured: false,
  enabled: true,
  identityLabels: ["instance"],
  selectorLabels: [{ name: "job", value: "node-exporter" }],
  scrapeIntervalSeconds: 15,
  staleAfterSeconds: 90,
  ...overrides,
});

async function run(action) {
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
  const mock = createMonitoringSourceMockHandlers();
  writeMockPrincipal("admin");
  const server = setupServer(...mock.handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "monitoring-source-test-session",
    onUnauthorized: () => {},
    requestId: () => `monitoring-source-${++sequence}`,
  });
  try {
    await action(createMonitoringSourceHttp(transport), mock);
  } finally {
    transport.dispose();
    server.close();
    mock.reset();
    if (previousWindow) writeMockPrincipal("admin");
    else delete globalThis.window;
  }
}

test("MONITORING-SOURCE-MOCK-DELETE: in-use source deletion returns the stable rejection reason", async () => {
  await run(async (port, mock) => {
    await port.readSources(signal());
    const source = candidate();
    const created = await port.mutate(
      {
        kind: "create",
        requestKey: "monitoring-source-in-use-create",
        source,
        credentials: null,
        credentialUpdate: "clear",
        checkId: null,
        skipCheck: true,
      },
      signal(),
    );
    assert.equal(created.status, "completed");
    mock.markSourceInUse(source.sourceId);

    const rejected = await port.mutate(
      {
        kind: "delete",
        requestKey: "monitoring-source-in-use-delete",
        sourceId: source.sourceId,
        expectedRevision: created.sourceRevision,
      },
      signal(),
    );

    assert.equal(rejected.status, "rejected");
    assert.equal(rejected.reason, "source_in_use");
    assert.equal((await port.readSources(signal())).items.length, 1);
  });
});

test("MONITORING-SOURCE-MOCK-COMMAND: check, create, safe readback and idempotent replay", async () => {
  await run(async (port) => {
    const before = await port.readSources(signal()); // Receives the transport's ephemeral CSRF nonce.
    assert.equal(before.items.length, 0);

    const source = candidate({
      authenticationMode: "direct-bearer",
      credentialConfigured: true,
    });
    const checked = await port.checkCandidate(
      source,
      { bearerToken: "PRIVATE-PROM-TOKEN" },
      signal(),
    );
    assert.equal(checked.result.connection, "reachable");
    assert.equal(checked.sourceId, source.sourceId);
    assert.doesNotMatch(JSON.stringify(checked), /PRIVATE-PROM-TOKEN|prometheus\.example\.test/);

    const command = {
      kind: "create",
      requestKey: "monitoring-source-create-1",
      source,
      credentials: { bearerToken: "PRIVATE-PROM-TOKEN" },
      credentialUpdate: "replace",
      checkId: checked.checkId,
      skipCheck: false,
    };
    const first = await port.mutate(command, signal());
    const replay = await port.mutate(command, signal());
    assert.deepEqual(replay, first);
    assert.equal(first.status, "completed");
    assert.equal(first.verified, true);
    assert.doesNotMatch(JSON.stringify(first), /PRIVATE-PROM-TOKEN|prometheus\.example\.test/);

    const operation = await port.readOperation(command.requestKey, signal());
    assert.deepEqual(operation, first);
    const directory = await port.readSources(signal());
    assert.equal(directory.items.length, 1);
    assert.equal(directory.items[0].authenticationMode, "direct-bearer");
    assert.equal(directory.items[0].credentialConfigured, true);
    assert.doesNotMatch(JSON.stringify(directory), /PRIVATE-PROM-TOKEN|prometheus\.example\.test/);

    const detail = await port.readSource(source.sourceId, signal());
    assert.equal(detail.endpointOrigin, "https://prometheus.example.test");
    assert.equal(detail.identityLabels[0], "instance");
    assert.doesNotMatch(JSON.stringify(detail), /PRIVATE-PROM-TOKEN|\/api\/v1\/query/);
  });
});

test("MONITORING-SOURCE-MOCK-ENABLE: minimal revision-CAS command preserves secret metadata", async () => {
  await run(async (port) => {
    await port.readSources(signal());
    const source = candidate({
      authenticationMode: "credential-reference",
      credentialConfigured: true,
    });
    const created = await port.mutate(
      {
        kind: "create",
        requestKey: "monitoring-source-create-reference",
        source,
        credentials: { reference: "vault://private-ref" },
        credentialUpdate: "replace",
        checkId: null,
        skipCheck: true,
      },
      signal(),
    );
    assert.equal(created.status, "completed");

    const disabled = await port.mutate(
      {
        kind: "set-enabled",
        requestKey: "monitoring-source-disable-1",
        sourceId: source.sourceId,
        expectedRevision: created.sourceRevision,
        enabled: false,
      },
      signal(),
    );
    assert.equal(disabled.status, "completed");
    assert.equal(disabled.enabled, false);
    const detail = await port.readSource(source.sourceId, signal());
    assert.equal(detail.enabled, false);
    assert.equal(detail.credentialConfigured, true);
    assert.doesNotMatch(JSON.stringify(detail), /vault:\/\/private-ref/);
  });
});
