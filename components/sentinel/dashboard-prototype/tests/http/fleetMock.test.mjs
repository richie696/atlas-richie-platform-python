import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createFleetMockHandlers } from "../../src/features/overview/mock";
import { createApplicationsMockHandlers } from "../../src/features/applications/mock";
import { MOCK_APPLICATION_SCENARIO } from "../../src/app/api/mockApplicationScenario";
import { MOCK_OBSERVATION_SCENARIO } from "../../src/app/api/mockObservationScenario";
import { createFleetHttp } from "../../src/features/overview/api/fleetHttp";
import { createObservationCatalogHttp } from "../../src/features/applications/api/catalogHttp";
import { FleetSnapshotSchema } from "../../src/features/overview/api/fleetWire";
const FLEET_READ_SCENARIOS = MOCK_OBSERVATION_SCENARIO.readScenarios;

const origin = "http://dashboard-mock.test";
const applicationHandlers = () => createApplicationsMockHandlers(MOCK_APPLICATION_SCENARIO);
const fleetHandlers = () => createFleetMockHandlers(MOCK_APPLICATION_SCENARIO);

test("FLEET-MOCK: MSW exposes catalog and query-driven overview through the real HTTP adapters", async () => {
  const server = setupServer(...applicationHandlers(), ...fleetHandlers());
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-mock-session",
    onUnauthorized: () => {},
    requestId: () => `mock-request-${++sequence}`,
  });
  try {
    const catalog = await createObservationCatalogHttp(transport).readObservationCatalog(
      new AbortController().signal,
    );
    assert.deepEqual(
      catalog.environments.map(({ id }) => id),
      ["test-env"],
    );
    assert.deepEqual(
      catalog.applications.map(({ id }) => id),
      ["app-one", "app-two", "app-three"],
    );

    const fromMs = Date.parse("2026-10-06T23:55:00.000Z");
    const toMs = Date.parse("2026-10-07T00:10:00.000Z");
    const parameters = new URLSearchParams({
      environmentId: "test-env",
      scope: "fleet",
      from: new Date(fromMs).toISOString(),
      to: new Date(toMs).toISOString(),
      page: "2",
      pageSize: "2",
      search: "",
      stepMs: "60000",
    });
    const wireResponse = await fetch(`${origin}/api/v1/fleet/overview?${parameters}`, {
      headers: { "x-request-id": "mock-shape-probe" },
    });
    const wire = await wireResponse.json();
    const parsedWire = FleetSnapshotSchema.safeParse(wire);
    assert.equal(
      parsedWire.success,
      true,
      JSON.stringify(parsedWire.success ? null : parsedWire.error.issues),
    );
    const value = await createFleetHttp(transport).readFleet(
      {
        context: {
          environmentId: "test-env",
          appId: null,
          instanceId: null,
          resource: null,
          scope: "fleet",
          window: { fromMs, toMs },
        },
        page: 2,
        pageSize: 2,
        search: "",
        stepMs: 60_000,
      },
      new AbortController().signal,
    );
    assert.equal(value.totalApplications, 3);
    assert.deepEqual(
      value.applications.items.map(({ appId }) => appId),
      ["app-three"],
    );
    assert.equal(value.applications.total, 3);
    assert.equal(
      value.applications.items[0].metrics.find(({ metric }) => metric === "http_qps")?.value,
      63,
    );
    assert.equal(value.metrics.summary.find(({ metric }) => metric === "http_qps")?.value, 189);
    assert.equal(
      value.metrics.summary.find(({ metric }) => metric === "tps")?.quality,
      "not_integrated",
    );

    const filtered = await createFleetHttp(transport).readFleet(
      {
        context: value.query.context,
        page: 1,
        pageSize: 2,
        search: "no-such-application",
        stepMs: 60_000,
      },
      new AbortController().signal,
    );
    assert.equal(filtered.totalApplications, 3);
    assert.equal(filtered.attentionApplications, 1);
    assert.equal(filtered.applications.total, 0);
    assert.deepEqual(filtered.applications.items, []);

    const selectedApplication = await createFleetHttp(transport).readFleet(
      {
        context: {
          ...value.query.context,
          appId: "app-three",
          scope: "application",
        },
        page: 1,
        pageSize: 2,
        search: "",
        stepMs: 60_000,
      },
      new AbortController().signal,
    );
    assert.equal(
      selectedApplication.metrics.summary.find(({ metric }) => metric === "http_qps")?.value,
      63,
    );
    assert.deepEqual(
      selectedApplication.applications.items[0].metrics,
      selectedApplication.metrics.summary,
    );
    assert.equal(selectedApplication.metrics.query.context.appId, "app-three");
    assert.equal(selectedApplication.metrics.query.context.scope, "application");
    const qpsSamples = selectedApplication.metrics.series
      .find(({ metric }) => metric === "http_qps")
      ?.samples.map(({ value }) => value);
    assert.equal(qpsSamples.length, 15);
    assert.equal(qpsSamples.at(-1), 63);
    assert.ok(new Set(qpsSamples).size > 1);
  } finally {
    transport.dispose();
    server.close();
  }
});

test("FLEET-MOCK-READ-STATES: demo HTTP scenarios exercise 403 denial and one explicit retry recovery", async () => {
  const server = setupServer(...applicationHandlers(), ...fleetHandlers());
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-mock-session",
    onUnauthorized: () => {},
  });
  const fromMs = Date.parse("2026-10-06T23:55:00.000Z");
  const toMs = Date.parse("2026-10-07T00:10:00.000Z");
  const read = (appId) =>
    createFleetHttp(transport).readFleet(
      {
        context: {
          environmentId: "test-env",
          appId,
          instanceId: null,
          resource: null,
          scope: "application",
          window: { fromMs, toMs },
        },
        page: 1,
        pageSize: 20,
        search: "",
        stepMs: 60_000,
      },
      new AbortController().signal,
    );
  try {
    await assert.rejects(read(FLEET_READ_SCENARIOS.forbiddenApplicationId), (error) => {
      assert.equal(error.status, 403);
      assert.equal(error.code, "forbidden");
      return true;
    });
    const recoveringApplicationId = FLEET_READ_SCENARIOS.fleetFailure.applicationId;
    await assert.rejects(read(recoveringApplicationId), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.code, "service_unavailable");
      return true;
    });
    const recovered = await read(recoveringApplicationId);
    assert.equal(recovered.totalApplications, 0);
    assert.deepEqual(recovered.applications.items, []);
  } finally {
    transport.dispose();
    server.close();
  }
});
