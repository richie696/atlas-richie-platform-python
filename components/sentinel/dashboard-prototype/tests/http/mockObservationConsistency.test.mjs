import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createAppConsoleMockAssembly } from "../../src/app/api/mockConsoleHandlers";
import { createFleetHttp } from "../../src/features/overview/api/fleetHttp";
import { createMetricsHttp } from "../../src/features/realtime/api/metricsHttp";
import { createInstanceHttp } from "../../src/features/applications/api/instanceHttp";
import { createIncidentHttp } from "../../src/features/faults/api/incidentHttp";
import {
  INSTANCE_LAYER,
  instanceSelection,
} from "../../src/features/applications/model/instanceObservation";
import { OPERATIONAL_METRICS } from "../../src/shared/model/observation";
import { catalogQuery } from "../fixtures/instances";
import { MOCK_OBSERVATION_SCENARIO } from "../../src/app/api/mockObservationScenario";
import { createMockScenarioClock } from "../../src/app/api/mockScenarioClock";

const MOCK_NOW_MS = Date.parse("2026-10-07T00:10:00.000Z");

const METRIC_ORIGIN = "http://mock-observation-consistency.test";
const timeWindow = MOCK_OBSERVATION_SCENARIO.window;
const metricValues = (bundle) =>
  Object.fromEntries(
    bundle.summary.map((reading) => [
      reading.metric,
      {
        value: reading.value,
        quality: reading.quality,
        denominator: reading.denominator,
        coverage: reading.coverage,
      },
    ]),
  );

async function readMetricsAfterTransientMockFailure(port, query, signal) {
  try {
    return await port.readMetrics(query, signal);
  } catch (error) {
    if (error.status !== 503 || error.code !== "service_unavailable") throw error;
    return port.readMetrics(query, signal);
  }
}

test("OBSERVATION-SEED-CONSISTENCY: fleet, application and process reads share one scenario", async () => {
  const assembly = createAppConsoleMockAssembly(MOCK_NOW_MS);
  const server = setupServer(...assembly.handlers);
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: METRIC_ORIGIN,
    owner: () => "synthetic-observation-session",
    onUnauthorized: () => {},
  });

  try {
    const fleetPort = createFleetHttp(transport);
    const metricsPort = createMetricsHttp(transport);
    const instancePort = createInstanceHttp(transport);
    const signal = () => new AbortController().signal;
    const fleetContext = {
      environmentId: MOCK_OBSERVATION_SCENARIO.environment.id,
      appId: null,
      instanceId: null,
      resource: null,
      scope: "fleet",
      window: timeWindow,
    };
    const fleetQuery = {
      context: fleetContext,
      page: 1,
      pageSize: 100,
      search: "",
      stepMs: 60_000,
    };
    const [fleet, realtimeFleet, instances] = await Promise.all([
      fleetPort.readFleet(fleetQuery, signal()),
      metricsPort.readMetrics(
        { context: fleetContext, metrics: OPERATIONAL_METRICS, stepMs: 60_000 },
        signal(),
      ),
      instancePort.readCatalog({ ...catalogQuery, pageSize: 100 }, signal()),
    ]);

    assert.deepEqual(metricValues(fleet.metrics), metricValues(realtimeFleet));
    assert.equal(fleet.coverage.expected, instances.totalInstances);
    assert.equal(fleet.coverage.reporting, instances.coverage.reporting);
    for (const instance of instances.items) {
      const seed = MOCK_OBSERVATION_SCENARIO.instances.find(({ id }) => id === instance.instanceId);
      assert.ok(seed, `instance ${instance.instanceId} must have one app-owned seed`);
      assert.equal(instance.containerId, seed.containerId);
      assert.equal(instance.processId, seed.processId);
      assert.deepEqual(instance.supportedScopes, seed.supportedScopes);
      assert.equal(instance.lastReportAtMs, timeWindow.fromMs + seed.lastReportOffsetMs);
    }

    const processQpsByApplication = new Map();
    for (const instance of instances.items) {
      const detail = await instancePort.readInstance(
        instanceSelection(instance, catalogQuery.context, INSTANCE_LAYER.Process),
        signal(),
      );
      const qps = detail.metrics?.summary.find(({ metric }) => metric === "http_qps")?.value;
      assert.notEqual(qps, null);
      processQpsByApplication.set(
        instance.appId,
        (processQpsByApplication.get(instance.appId) ?? 0) + qps,
      );
    }

    for (const application of fleet.applications.items) {
      const applicationContext = {
        ...fleetContext,
        appId: application.appId,
        scope: "application",
      };
      const realtimeApplication = await readMetricsAfterTransientMockFailure(
        metricsPort,
        { context: applicationContext, metrics: OPERATIONAL_METRICS, stepMs: 60_000 },
        signal(),
      );
      assert.deepEqual(
        metricValues({ summary: application.metrics }),
        metricValues(realtimeApplication),
      );
      assert.equal(
        application.metrics.find(({ metric }) => metric === "http_qps")?.value,
        processQpsByApplication.get(application.appId),
      );
    }

    assert.equal(
      fleet.metrics.summary.find(({ metric }) => metric === "http_qps")?.value,
      [...processQpsByApplication.values()].reduce((sum, value) => sum + value, 0),
    );

    const unknown = await metricsPort.readMetrics(
      {
        context: { ...fleetContext, appId: "unknown-application", scope: "application" },
        metrics: OPERATIONAL_METRICS,
        stepMs: 60_000,
      },
      signal(),
    );
    assert.equal(
      unknown.summary.find(({ metric }) => metric === "http_qps")?.quality,
      "no_samples",
    );
  } finally {
    transport.dispose();
    server.close();
  }
});

test("MOCK-CLOCK-HTTP: application, incident, and system snapshots share the app clock", async () => {
  const assembly = createAppConsoleMockAssembly(MOCK_NOW_MS);
  const server = setupServer(...assembly.handlers);
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: METRIC_ORIGIN,
    owner: () => "synthetic-observation-session",
    onUnauthorized: () => {},
  });

  try {
    const catalogResponse = await fetch(`${METRIC_ORIGIN}/api/v1/observation/catalog`);
    const catalog = await catalogResponse.json();
    assert.equal(catalogResponse.status, 200);
    assert.equal(Date.parse(catalog.asOf), MOCK_NOW_MS);
    assert.equal(catalog.environments[0].id, MOCK_OBSERVATION_SCENARIO.environment.id);
    assert.equal(catalog.environments[0].name, MOCK_OBSERVATION_SCENARIO.environment.name);

    const systemResponse = await fetch(`${METRIC_ORIGIN}/api/v1/system/connections`);
    const system = await systemResponse.json();
    assert.equal(systemResponse.status, 200);
    assert.equal(Date.parse(system.asOf), MOCK_NOW_MS);

    const incidents = await createIncidentHttp(transport).readTimeline(
      {
        context: {
          environmentId: MOCK_OBSERVATION_SCENARIO.environment.id,
          appId: null,
          instanceId: null,
          resource: null,
          scope: "fleet",
          window: timeWindow,
        },
        severity: null,
        category: null,
        cursor: null,
        pageSize: 20,
      },
      new AbortController().signal,
    );
    assert.equal(incidents.asOfMs, MOCK_NOW_MS);
  } finally {
    transport.dispose();
    server.close();
  }
});

test("MOCK-SCENARIO-REPLAY: rebuilding the app assembly repeats fixed time and isolated failure state", async () => {
  const origin = "http://mock-scenario-replay.test";
  const query = {
    context: {
      environmentId: MOCK_OBSERVATION_SCENARIO.environment.id,
      appId: MOCK_OBSERVATION_SCENARIO.readScenarios.metricFailures.retryable.applicationId,
      instanceId: null,
      resource: null,
      scope: "application",
      window: timeWindow,
    },
    metrics: OPERATIONAL_METRICS,
    stepMs: 60_000,
  };

  const runFailureAndRecovery = async () => {
    const assembly = createAppConsoleMockAssembly(MOCK_NOW_MS);
    const server = setupServer(...assembly.handlers);
    server.listen({ onUnhandledRequest: "error" });
    const transport = createConsoleTransport({
      baseUrl: origin,
      owner: () => "synthetic-observation-session",
      onUnauthorized: () => {},
      requestId: (() => {
        let sequence = 0;
        return () => `mock-replay-${++sequence}`;
      })(),
    });
    const port = createMetricsHttp(transport);
    try {
      await assert.rejects(port.readMetrics(query, new AbortController().signal), (error) => {
        assert.equal(error.status, 503);
        assert.equal(error.code, "service_unavailable");
        assert.equal(error.requestId, "mock-replay-1");
        return true;
      });
      return await port.readMetrics(query, new AbortController().signal);
    } finally {
      transport.dispose();
      server.close();
    }
  };

  const firstReplay = await runFailureAndRecovery();
  const secondReplay = await runFailureAndRecovery();
  assert.equal(firstReplay.asOfMs, MOCK_NOW_MS);
  assert.deepEqual(secondReplay, firstReplay);
});

test("MOCK-CLOCK-INPUT: fixed scenario clocks reject invalid epoch values", () => {
  const fixedClock = createMockScenarioClock(MOCK_NOW_MS);
  assert.equal(fixedClock(), MOCK_NOW_MS);
  assert.throws(() => createMockScenarioClock(Number.NaN), RangeError);
  assert.throws(() => createMockScenarioClock(-1), RangeError);
  assert.throws(() => createMockScenarioClock(Number.MAX_SAFE_INTEGER + 1), RangeError);
});
