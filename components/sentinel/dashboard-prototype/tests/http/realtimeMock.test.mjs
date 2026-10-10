import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { AppErrorKind } from "@richie696/react-framework";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createRealtimeMockHandlers } from "../../src/features/realtime/mock";
import { MOCK_OBSERVATION_SCENARIO } from "../../src/app/api/mockObservationScenario";
const REALTIME_READ_SCENARIOS = MOCK_OBSERVATION_SCENARIO.readScenarios;
import { createMetricsHttp } from "../../src/features/realtime/api/metricsHttp";
import { createRealtimeMonitor } from "../../src/features/realtime/application/realtimeMonitor";
import { OPERATIONAL_METRICS } from "../../src/shared/model/observation";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const realtimeMockHandlers = () => createRealtimeMockHandlers(MOCK_OBSERVATION_SCENARIO);
async function until(check, timeoutMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (check()) return;
    await delay(5);
  }
  assert.fail("realtime monitor state deadline");
}

test("METRICS-QUERY: invalid metric selections are rejected before HTTP transport", async () => {
  let requests = 0;
  const port = createMetricsHttp({
    async send() {
      requests++;
      throw new Error("invalid query reached HTTP transport");
    },
  });
  const query = {
    context: {
      environmentId: "test-env",
      appId: "app-one",
      instanceId: null,
      resource: null,
      scope: "application",
      window: {
        fromMs: Date.parse("2026-10-07T00:00:00.000Z"),
        toMs: Date.parse("2026-10-07T00:01:00.000Z"),
      },
    },
    metrics: [],
    stepMs: 60_000,
  };
  for (const metrics of [
    [],
    ["http_qps", "http_qps"],
    ["unknown_metric"],
    ["http_qps,"],
  ]) {
    await assert.rejects(
      port.readMetrics({ ...query, metrics }, new AbortController().signal),
    );
  }
  assert.equal(requests, 0);
});

test("METRICS-MOCK: polling reads go through Console HTTP and preserve unavailable TPS semantics", async () => {
  const origin = "http://realtime-mock.test";
  const server = setupServer(...realtimeMockHandlers());
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-monitor-session",
    onUnauthorized: () => {},
  });
  try {
    const port = createMetricsHttp(transport);
    const query = {
      context: {
        environmentId: "test-env",
        appId: "app-one",
        instanceId: null,
        resource: null,
        scope: "application",
        window: {
          fromMs: Date.parse("2026-10-06T23:55:00Z"),
          toMs: Date.parse("2026-10-07T00:10:00Z"),
        },
      },
      metrics: OPERATIONAL_METRICS,
      stepMs: 60_000,
    };
    const result = await port.readMetrics(query, new AbortController().signal);
    assert.deepEqual(result.query, query);
    assert.equal(result.summary.find((reading) => reading.metric === "http_qps")?.value, 42);
    const qpsSamples = result.series
      .find(({ metric }) => metric === "http_qps")
      ?.samples.map(({ value }) => value);
    assert.equal(qpsSamples.length, 15);
    assert.equal(qpsSamples.at(-1), 42);
    assert.ok(new Set(qpsSamples).size > 1);
    const tps = result.summary.find((reading) => reading.metric === "tps");
    assert.equal(tps?.quality, "not_integrated");
    assert.equal(tps?.value, null);
    assert.deepEqual(result.annotations, [
      {
        id: "demo-publication-one",
        kind: "publication",
        atMs:
          query.context.window.fromMs +
          Math.floor((query.context.window.toMs - query.context.window.fromMs) / 2),
        versionId: "demo-version-two",
        publicationId: "demo-publication-one",
      },
    ]);

    const anotherApplication = await port.readMetrics(
      { ...query, context: { ...query.context, appId: "app-two" } },
      new AbortController().signal,
    );
    assert.equal(
      anotherApplication.summary.find((reading) => reading.metric === "http_qps")?.value,
      84,
    );
    assert.deepEqual(anotherApplication.annotations, []);

    const fleet = await port.readMetrics(
      { ...query, context: { ...query.context, appId: null, scope: "fleet" } },
      new AbortController().signal,
    );
    assert.equal(fleet.summary.find((reading) => reading.metric === "http_qps")?.value, 189);

    const unknownApplication = await port.readMetrics(
      { ...query, context: { ...query.context, appId: "missing-app" } },
      new AbortController().signal,
    );
    const missingQps = unknownApplication.summary.find((reading) => reading.metric === "http_qps");
    assert.equal(missingQps?.value, null);
    assert.equal(missingQps?.sampledAtMs, null);
    assert.equal(missingQps?.quality, "no_samples");
  } finally {
    transport.dispose();
    server.close();
  }
});

test("METRICS-RECOVERY: stale data is retained and the next HTTP poll recovers", async () => {
  const origin = "http://realtime-recovery-mock.test";
  const server = setupServer(...realtimeMockHandlers());
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-monitor-session",
    onUnauthorized: () => {},
  });
  const query = {
    context: {
      environmentId: "test-env",
      appId: REALTIME_READ_SCENARIOS.metricFailures.recovering.applicationId,
      instanceId: null,
      resource: null,
      scope: "application",
      window: {
        fromMs: Date.parse("2026-10-06T23:55:00Z"),
        toMs: Date.parse("2026-10-07T00:10:00Z"),
      },
    },
    metrics: OPERATIONAL_METRICS,
    stepMs: 60_000,
  };
  try {
    const applicationIds = new Set(MOCK_OBSERVATION_SCENARIO.applications.map(({ id }) => id));
    assert.ok(applicationIds.has(REALTIME_READ_SCENARIOS.metricFailures.recovering.applicationId));
    assert.ok(applicationIds.has(REALTIME_READ_SCENARIOS.metricFailures.retryable.applicationId));

    const port = createMetricsHttp(transport);
    const read = (appId) =>
      port.readMetrics(
        { ...query, context: { ...query.context, appId } },
        new AbortController().signal,
      );
    const recoveringApplicationId = REALTIME_READ_SCENARIOS.metricFailures.recovering.applicationId;
    const retryableApplicationId = REALTIME_READ_SCENARIOS.metricFailures.retryable.applicationId;
    const initial = await read(recoveringApplicationId);
    assert.equal(initial.query.context.appId, recoveringApplicationId);
    const beforeTransientFailure = await read(recoveringApplicationId);
    assert.equal(
      beforeTransientFailure.summary.find((reading) => reading.metric === "http_qps")?.value,
      84,
    );

    await assert.rejects(read(recoveringApplicationId), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.code, "service_unavailable");
      return true;
    });

    const recovered = await read(recoveringApplicationId);
    assert.equal(recovered.query.context.appId, recoveringApplicationId);
    assert.equal(recovered.asOfMs, query.context.window.toMs);
    assert.equal(recovered.summary.find((reading) => reading.metric === "http_qps")?.value, 84);
    assert.equal(
      recovered.summary.find((reading) => reading.metric === "http_qps")?.quality,
      "available",
    );

    await assert.rejects(read(retryableApplicationId), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.code, "service_unavailable");
      return true;
    });
    const retry = await read(retryableApplicationId);
    assert.equal(retry.query.context.appId, retryableApplicationId);
    assert.equal(retry.summary.find((reading) => reading.metric === "http_qps")?.value, 63);
    assert.equal(
      retry.summary.find((reading) => reading.metric === "http_qps")?.quality,
      "available",
    );
  } finally {
    transport.dispose();
    server.close();
  }
});

test("METRICS-NETWORK-RECOVERY: a directory application retains valid data through one offline read and recovers without hidden retry", async () => {
  const origin = "http://realtime-network-recovery.test";
  const server = setupServer(...realtimeMockHandlers());
  server.listen({ onUnhandledRequest: "error" });
  let requestSequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-monitor-session",
    onUnauthorized: () => {},
    requestId: () => `realtime-network-${++requestSequence}`,
  });
  const window = {
    fromMs: Date.parse("2026-10-06T23:55:00Z"),
    toMs: Date.parse("2026-10-07T00:10:00Z"),
  };
  const query = {
    context: {
      environmentId: "test-env",
      appId: REALTIME_READ_SCENARIOS.networkFailure.applicationId,
      instanceId: null,
      resource: null,
      scope: "application",
      window,
    },
    metrics: OPERATIONAL_METRICS,
    stepMs: 60_000,
  };

  try {
    const port = createMetricsHttp(transport);
    const applicationIds = new Set(MOCK_OBSERVATION_SCENARIO.applications.map(({ id }) => id));
    assert.ok(applicationIds.has(query.context.appId));
    await assert.rejects(port.readMetrics(query, new AbortController().signal), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.code, "service_unavailable");
      return true;
    });
    const initial = await port.readMetrics(query, new AbortController().signal);
    assert.equal(initial.query.context.appId, query.context.appId);
    assert.equal(initial.summary.find((reading) => reading.metric === "http_qps")?.value, 63);

    const stable = await port.readMetrics(query, new AbortController().signal);
    assert.equal(stable.query.context.appId, query.context.appId);
    assert.equal(stable.summary.find((reading) => reading.metric === "http_qps")?.value, 63);

    await assert.rejects(port.readMetrics(query, new AbortController().signal), (error) => {
      assert.equal(error.kind, AppErrorKind.NETWORK);
      assert.equal(error.status, undefined);
      assert.equal(error.code, undefined);
      assert.equal(error.requestId, undefined);
      assert.equal(error.message, "Console transport unavailable");
      return true;
    });
    assert.equal(requestSequence, 4, "the shared transport must not silently retry an offline read");

    const recovered = await port.readMetrics(query, new AbortController().signal);
    assert.equal(requestSequence, 5);
    assert.equal(recovered.query.context.appId, query.context.appId);
    assert.equal(recovered.asOfMs, window.toMs);
    assert.equal(recovered.summary.find((reading) => reading.metric === "http_qps")?.value, 63);
    assert.equal(
      recovered.summary.find((reading) => reading.metric === "http_qps")?.quality,
      "available",
    );
  } finally {
    transport.dispose();
    server.close();
  }
});

test("METRICS-MONITOR-RECOVERY: a successful HTTP poll replaces stale observation state", async () => {
  const origin = "http://realtime-monitor-recovery-mock.test";
  const server = setupServer(...realtimeMockHandlers());
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-monitor-session",
    onUnauthorized: () => {},
  });
  let now = Date.parse("2026-10-07T00:10:00Z");
  const monitor = createRealtimeMonitor(createMetricsHttp(transport), undefined, {
    intervalMs: 100,
    clock: () => now,
  });
  const selection = {
    context: {
      environmentId: "test-env",
      appId: REALTIME_READ_SCENARIOS.metricFailures.recovering.applicationId,
      instanceId: null,
      resource: null,
      scope: "application",
      window: {
        fromMs: Date.parse("2026-10-06T23:55:00Z"),
        toMs: now,
      },
    },
    metrics: OPERATIONAL_METRICS,
    stepMs: 60_000,
    windowMode: "rolling",
  };
  try {
    monitor.start(selection);
    await until(() => monitor.getSnapshot().observation.status === "partial");
    const initial = monitor.getSnapshot().observation.data;

    now += 5_000;
    await until(
      () =>
        monitor.getSnapshot().observation.status === "partial" &&
        monitor.getSnapshot().observation.data !== initial &&
        monitor.getSnapshot().observation.data.asOfMs === now,
    );
    const trusted = monitor.getSnapshot().observation.data;

    now += 5_000;
    await until(() => monitor.getSnapshot().observation.status === "stale");
    assert.equal(monitor.getSnapshot().observation.data, trusted);

    now += 5_000;
    await until(
      () =>
        monitor.getSnapshot().observation.status === "partial" &&
        monitor.getSnapshot().observation.data.asOfMs === now,
    );
    assert.notEqual(monitor.getSnapshot().observation.data, trusted);
    assert.equal(monitor.getSnapshot().observation.data.query.context.window.toMs, now);
    assert.equal(
      monitor
        .getSnapshot()
        .observation.data.summary.find((reading) => reading.metric === "http_qps")?.value,
      84,
    );
  } finally {
    monitor.dispose();
    transport.dispose();
    server.close();
  }
});
