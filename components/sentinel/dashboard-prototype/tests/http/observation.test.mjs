import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import {
  createMetricsHttp,
  MetricParametersSchema,
} from "../../src/features/realtime/api/metricsHttp";
import { createFleetHttp } from "../../src/features/overview/api/fleetHttp";
import { FleetQuerySchema, FleetParametersSchema } from "../../src/features/overview/api/fleetWire";
import { observationContextParameters } from "../../src/shared/api/observationMapper";
import { createFleetResource } from "../../src/features/overview/application/fleetResource";
import {
  MetricBundleSchema,
  ObservationCoverageSchema,
} from "../../src/shared/api/observationWire";
import { METRIC_BASIS, METRIC_ID } from "../../src/shared/model/observation";
import { bundleFor, snapshotFor, query as fleetQuery } from "../fixtures/observations";
import { MOCK_SYSTEM_SCENARIO } from "../../src/app/api/mockSystemScenario";
import { MOCK_APPLICATION_SCENARIO } from "../../src/app/api/mockApplicationScenario";

const origin = "http://observation-http.test",
  signal = () => new AbortController().signal;
const instant = (value) => new Date(value).toISOString();
const contextWire = (value) => ({
  ...value,
  window: { from: instant(value.window.fromMs), to: instant(value.window.toMs) },
});
const metadata = (value) => ({
  source: value.source,
  denominator: value.denominator,
  coverage: value.coverage,
  quality: value.quality,
  metric: value.metric,
  unit: value.unit,
});
const readingWire = (value) => ({
  ...metadata(value),
  value: value.value,
  sampledAt: value.sampledAtMs === null ? null : instant(value.sampledAtMs),
});
// Independent explicit outbound test fixtures: never infer date conversion from a key suffix or reuse the production decoder.
function bundleWire(domain = bundleFor()) {
  return {
    query: { ...domain.query, context: contextWire(domain.query.context) },
    asOf: instant(domain.asOfMs),
    summary: domain.summary.map(readingWire),
    series: domain.series.map((value) => ({
      ...metadata(value),
      samples: value.samples.map((sample) => ({ at: instant(sample.atMs), value: sample.value })),
    })),
    annotations: domain.annotations.map(({ atMs, ...annotation }) => ({
      ...annotation,
      at: instant(atMs),
    })),
  };
}
function fleetWire(domain = snapshotFor()) {
  return {
    query: { ...domain.query, context: contextWire(domain.query.context) },
    asOf: instant(domain.asOfMs),
    coverage: domain.coverage,
    totalApplications: domain.totalApplications,
    attentionApplications: domain.attentionApplications,
    attentionTargets: domain.attentionTargets,
    applications: {
      ...domain.applications,
      items: domain.applications.items.map((value) => ({
        ...value,
        metrics: value.metrics.map(readingWire),
      })),
    },
    metrics: bundleWire(domain.metrics),
    connections: domain.connections.map(({ checkedAtMs, ...connection }) => ({
      ...connection,
      checkedAt: checkedAtMs === null ? null : instant(checkedAtMs),
    })),
  };
}
const reply = (request, body, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: { "x-request-id": request.headers.get("x-request-id") },
  });
async function runRead(handler, run) {
  const server = setupServer(handler);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "observation-owner",
    onUnauthorized: () => {},
    requestId: () => `observation-${++sequence}`,
  });
  try {
    await run(transport);
  } finally {
    transport.dispose();
    server.close();
  }
}
test("METRICS-HTTP: UTC wire instants project to exact internal milliseconds; durations, units and missing TPS remain explicit", async () => {
  const wire = bundleWire(),
    query = bundleFor().query;
  let parameters;
  await runRead(
    http.get(`${origin}/api/v1/metrics/query`, ({ request }) => {
      parameters = new URL(request.url).searchParams;
      return reply(request, wire);
    }),
    async (transport) => {
      const value = await createMetricsHttp(transport).readMetrics(query, signal());
      assert.deepEqual(value.query, query);
      assert.equal(value.asOfMs, Date.parse(wire.asOf));
      assert.deepEqual(value.summary, bundleFor().summary);
      assert.deepEqual(
        value.series.map((series) => series.samples),
        bundleFor().series.map((series) => series.samples),
      );
      assert.deepEqual(value.annotations, bundleFor().annotations);
      assert.equal(value.query.stepMs, 60000);
      assert.equal(value.summary.find((item) => item.metric === "tps").value, null);
      assert.equal(parameters.get("from"), "2026-10-06T23:55:00.000Z");
      assert.equal(parameters.get("to"), "2026-10-07T00:10:00.000Z");
      assert.equal(parameters.get("metrics"), query.metrics.join(","));
      assert.equal(parameters.has("appId"), false);
      assert.equal(parameters.has("instanceId"), false);
      assert.equal(parameters.has("resource"), false);
    },
  );
});
test("METRICS-WIRE: strict nested shape, unit/window identity, unknown coverage and unsupported instrument semantics fail closed", async () => {
  const malformed = [];
  const change = (fn) => {
    const wire = bundleWire();
    fn(wire);
    malformed.push(wire);
  };
  change((wire) => {
    wire.query.context.appId = "foreign";
  });
  change((wire) => {
    wire.summary[0].unit = "transactions_per_second";
  });
  change((wire) => {
    wire.summary[0].denominator = METRIC_BASIS.ElapsedSeconds;
  });
  change((wire) => {
    wire.series[0].source = "different-reporter";
  });
  change((wire) => {
    wire.summary.pop();
  });
  change((wire) => {
    wire.series[0].samples[0].at = wire.query.context.window.to;
  });
  change((wire) => {
    wire.summary[3].value = 1.1;
  });
  change((wire) => {
    wire.summary[0].coverage = { expected: null, inventorySource: null, reporting: 3 };
    wire.summary[0].quality = "available";
  });
  change((wire) => {
    wire.summary[1].value = 42;
  });
  change((wire) => {
    wire.summary[0].traceback = "PRIVATE-STACK";
  });
  change((wire) => {
    wire.query.context.window.from = "2026-10-06T23:55:00.000+00:00";
  });
  change((wire) => {
    wire.summary[0].coverage.inventorySource = null;
  });
  change((wire) => {
    wire.series[0].samples.reverse();
  });
  for (const wire of malformed)
    await runRead(
      http.get(`${origin}/api/v1/metrics/query`, ({ request }) => reply(request, wire)),
      async (transport) => {
        await assert.rejects(
          createMetricsHttp(transport).readMetrics(bundleFor().query, signal()),
          (error) =>
            error.code === "console_response_invalid" && !JSON.stringify(error).includes("PRIVATE"),
        );
      },
    );
  assert.equal(MetricBundleSchema.safeParse(bundleWire()).success, true);
  assert.equal(
    ObservationCoverageSchema.safeParse({ expected: null, inventorySource: null, reporting: 3 })
      .success,
    true,
  );
  assert.equal(
    ObservationCoverageSchema.safeParse({
      expected: null,
      inventorySource: "guessed",
      reporting: 3,
    }).success,
    false,
  );
});
test("FLEET-HTTP: whole-scope totals/coverage remain independent of returned page; dependency timestamps do not become metric sample times", async () => {
  const domain = snapshotFor(),
    wire = fleetWire(domain);
  const queryResult = FleetQuerySchema.safeParse({
    ...fleetQuery,
    context: contextWire(fleetQuery.context),
  });
  assert.equal(queryResult.success, true, JSON.stringify(queryResult.error?.issues));
  const { environmentId, appId, scope, from, to } = observationContextParameters(
    fleetQuery.context,
  );
  const parametersResult = FleetParametersSchema.safeParse({
    environmentId,
    appId,
    scope,
    from,
    to,
    page: fleetQuery.page,
    pageSize: fleetQuery.pageSize,
    search: fleetQuery.search,
    stepMs: fleetQuery.stepMs,
  });
  assert.equal(parametersResult.success, true, JSON.stringify(parametersResult.error?.issues));
  await runRead(
    http.get(`${origin}/api/v1/fleet/overview`, ({ request }) => reply(request, wire)),
    async (transport) => {
      const value = await createFleetHttp(transport).readFleet(fleetQuery, signal());
      assert.equal(value.totalApplications, 3);
      assert.equal(value.applications.items.length, 2);
      assert.equal(value.applications.total, 3);
      assert.deepEqual(value.connections, domain.connections);
      assert.deepEqual(value.query, fleetQuery);
      assert.equal(value.metrics.asOfMs, value.asOfMs);
      assert.equal(value.connections[0].id, MOCK_SYSTEM_SCENARIO.primarySource.id);
      assert.equal(value.connections[0].provider, MOCK_SYSTEM_SCENARIO.primarySource.provider);
      assert.equal(value.connections[0].state, MOCK_SYSTEM_SCENARIO.connections[0].state);
      assert.equal(value.connections[0].latencyMs, MOCK_SYSTEM_SCENARIO.connections[0].latencyMs);
      assert.deepEqual(value.applications.items[0].metrics, domain.applications.items[0].metrics);
    },
  );
});
test("FLEET-MOCK-SEED: rule loading coverage matches the configured app and its instance inventory", () => {
  const snapshot = snapshotFor({ ...fleetQuery, pageSize: 10 });
  const applications = new Map(
    snapshot.applications.items.map((application) => [application.appId, application]),
  );

  assert.deepEqual(
    [...applications].map(([appId, application]) => [
      appId,
      application.ruleCoverage.expected,
      application.ruleCoverage.reporting,
      application.instanceCoverage.expected,
    ]),
    [
      ["app-one", 2, 1, 2],
      ["app-two", 1, 0, 1],
      ["app-three", 1, 0, 1],
    ],
  );
  assert.deepEqual(
    MOCK_APPLICATION_SCENARIO.applications.map((application) => application.ruleCoverage),
    snapshot.applications.items.map((application) => application.ruleCoverage),
  );
});
test("FLEET-HTTP: unknown authoritative inventory stays partial rather than synthesizing reporting as total", async () => {
  const wire = fleetWire();
  wire.coverage = { expected: null, inventorySource: null, reporting: 3 };
  const access = {
    read: () => ({ allowed: true, ownerKey: "session-one" }),
    subscribe: () => () => {},
  };
  await runRead(
    http.get(`${origin}/api/v1/fleet/overview`, ({ request }) => reply(request, wire)),
    async (transport) => {
      const resource = createFleetResource(createFleetHttp(transport), access);
      try {
        await resource.load(fleetQuery);
        assert.equal(resource.getSnapshot().status, "partial");
        assert.equal(resource.getSnapshot().data.coverage.expected, null);
        assert.equal(resource.getSnapshot().data.coverage.reporting, 3);
      } finally {
        resource.dispose();
      }
    },
  );
});
test("FLEET-STALE: real HTTP refresh rejection retains only its original query/read time; changed key cannot borrow old page", async () => {
  let reads = 0;
  const access = {
    read: () => ({ allowed: true, ownerKey: "session-one" }),
    subscribe: () => () => {},
  };
  await runRead(
    http.get(`${origin}/api/v1/fleet/overview`, ({ request }) =>
      ++reads === 1
        ? reply(request, fleetWire())
        : reply(
            request,
            {
              error: {
                code: "service_unavailable",
                requestId: request.headers.get("x-request-id"),
              },
            },
            503,
          ),
    ),
    async (transport) => {
      const resource = createFleetResource(createFleetHttp(transport), access);
      try {
        await resource.load(fleetQuery);
        const previous = resource.getSnapshot().data;
        await assert.rejects(resource.load(fleetQuery));
        assert.equal(resource.getSnapshot().status, "stale");
        assert.equal(resource.getSnapshot().data, previous);
        await assert.rejects(resource.load({ ...fleetQuery, page: 2 }));
        assert.equal(resource.getSnapshot().status, "error");
        assert.equal("data" in resource.getSnapshot(), false);
      } finally {
        resource.dispose();
      }
    },
  );
});
test("OBSERVATION-INPUT: invalid steps, duplicate instruments and instance/resource fleet scopes never dispatch", async () => {
  let dispatched = 0;
  await runRead(
    http.all(`${origin}/*`, ({ request }) => {
      dispatched++;
      return reply(request, {});
    }),
    async (transport) => {
      const metrics = createMetricsHttp(transport),
        fleet = createFleetHttp(transport),
        query = bundleFor().query;
      for (const input of [
        { ...query, stepMs: 0 },
        { ...query, stepMs: 1 },
        { ...query, metrics: ["http_qps", "http_qps"] },
        {
          ...query,
          context: {
            ...query.context,
            window: { fromMs: query.context.window.toMs, toMs: query.context.window.fromMs },
          },
        },
      ])
        await assert.rejects(
          metrics.readMetrics(input, signal()),
          (error) => error.code === "console_request_invalid",
        );
      for (const input of [
        { ...fleetQuery, context: { ...fleetQuery.context, resource: "/foreign" } },
        { ...fleetQuery, pageSize: 101 },
        { ...fleetQuery, search: "x".repeat(201) },
        { ...fleetQuery, search: "🌋".repeat(101) },
        { ...fleetQuery, search: "invalid-\ud800" },
      ])
        await assert.rejects(
          fleet.readFleet(input, signal()),
          (error) => error.code === "console_request_invalid",
        );
      assert.equal(dispatched, 0);
    },
  );
});

test("METRICS-QUERY-WIRE: the comma-separated selection accepts only registered metric IDs", () => {
  const schema = MetricParametersSchema.shape.metrics;
  assert.equal(schema.safeParse(Object.values(METRIC_ID).join(",")).success, true);
  for (const invalid of ["http_qps,unknown_metric", "http_qps,", ",http_qps"])
    assert.equal(schema.safeParse(invalid).success, false, invalid);
});
