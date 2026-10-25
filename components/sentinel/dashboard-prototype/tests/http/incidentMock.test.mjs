import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createIncidentMockHandlers } from "../../src/features/faults/mock";
import { createIncidentHttp } from "../../src/features/faults/api/incidentHttp";
import { MOCK_INCIDENT_SCENARIO } from "../../src/app/api/mockIncidentScenario";

test("INCIDENT-MOCK-RECOVERY: scenario injects one timeline outage and a new handler factory replays it deterministically", async () => {
  const origin = "http://incident-recovery-mock.test";
  const fixedNow = Date.parse("2026-10-07T00:10:00.000Z");
  const createServerForScenario = () =>
    setupServer(...createIncidentMockHandlers(MOCK_INCIDENT_SCENARIO, () => fixedNow));
  let activeServer = createServerForScenario();
  activeServer.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-incident-session",
    onUnauthorized: () => {},
    requestId: (() => {
      let sequence = 0;
      return () => `incident-recovery-${++sequence}`;
    })(),
  });
  const port = createIncidentHttp(transport);
  const query = {
    context: {
      environmentId: "test-env",
      appId: MOCK_INCIDENT_SCENARIO.incidents.timelineFailure.applicationId,
      instanceId: null,
      resource: null,
      scope: "application",
      window: { fromMs: fixedNow - 15 * 60_000, toMs: fixedNow },
    },
    severity: null,
    category: null,
    cursor: null,
    pageSize: 20,
  };
  try {
    await assert.rejects(port.readTimeline(query, new AbortController().signal), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.code, "service_unavailable");
      assert.equal(error.requestId, "incident-recovery-1");
      return true;
    });

    const recovered = await port.readTimeline(query, new AbortController().signal);
    assert.equal(recovered.asOfMs, fixedNow);
    assert.equal(recovered.statistics.total, 12);

    activeServer.close();
    activeServer = createServerForScenario();
    activeServer.listen({ onUnhandledRequest: "error" });
    await assert.rejects(port.readTimeline(query, new AbortController().signal), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.code, "service_unavailable");
      return true;
    });
  } finally {
    transport.dispose();
    activeServer.close();
  }
});

test("INCIDENT-MOCK: Console HTTP reads timeline and exact selected evidence without raw logs", async () => {
  const origin = "http://incident-mock.test";
  const server = setupServer(...createIncidentMockHandlers(MOCK_INCIDENT_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-incident-session",
    onUnauthorized: () => {},
  });
  try {
    const port = createIncidentHttp(transport);
    const query = {
      context: {
        environmentId: "test-env",
        appId: "app-one",
        instanceId: null,
        resource: null,
        scope: "application",
        window: { fromMs: Date.now() - 15 * 60_000, toMs: Date.now() },
      },
      severity: null,
      category: null,
      cursor: null,
      pageSize: 20,
    };
    const page = await port.readTimeline(query, new AbortController().signal);
    assert.equal(page.statistics.total, 12);
    assert.equal(page.items[0].id, MOCK_INCIDENT_SCENARIO.incidents.templates[0].id);
    assert.ok(page.items[0].receivedAtMs >= page.items[0].occurredAtMs);
    const evidence = await port.readEvidence(
      {
        context: query.context,
        eventId: page.items[0].id,
        severity: null,
        category: null,
      },
      new AbortController().signal,
    );
    assert.equal(evidence.event.id, page.items[0].id);
    assert.equal(evidence.facts.length, 2);
    assert.equal(evidence.completeness, "complete");
    assert.equal(
      evidence.facts[1].fact.value,
      Math.max(
        0,
        evidence.event.caption.value - MOCK_INCIDENT_SCENARIO.incidents.resourcePressureValueDelta,
      ),
    );
    assert.equal("traceback" in evidence, false);
  } finally {
    transport.dispose();
    server.close();
  }
});

test("INCIDENT-MOCK: instance scope filters events and cursor pages preserve whole-scope counts", async () => {
  const origin = "http://incident-instance-mock.test";
  const server = setupServer(...createIncidentMockHandlers(MOCK_INCIDENT_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-incident-session",
    onUnauthorized: () => {},
  });
  try {
    const port = createIncidentHttp(transport);
    const context = {
      environmentId: "test-env",
      appId: null,
      instanceId: null,
      resource: null,
      scope: "fleet",
      window: { fromMs: Date.now() - 15 * 60_000, toMs: Date.now() },
    };
    const first = await port.readTimeline(
      { context, severity: null, category: null, cursor: null, pageSize: 20 },
      new AbortController().signal,
    );
    assert.equal(first.statistics.total, 36);
    assert.equal(first.items.length, 20);
    assert.ok(first.nextCursor);
    const second = await port.readTimeline(
      {
        context,
        severity: null,
        category: null,
        cursor: first.nextCursor,
        pageSize: 20,
      },
      new AbortController().signal,
    );
    assert.equal(second.items.length, 16);
    assert.equal(second.statistics.total, first.statistics.total);
    assert.equal(second.nextCursor, null);
    const events = [...first.items, ...second.items];
    assert.equal(new Set(events.map((item) => item.id)).size, 36);
    const applications = new Set(MOCK_INCIDENT_SCENARIO.applications.map((item) => item.id));
    const instances = new Map(MOCK_INCIDENT_SCENARIO.instances.map((item) => [item.id, item]));
    for (const event of events) {
      assert.ok(applications.has(event.appId));
      if (event.instanceId === null) {
        assert.equal(event.processEpoch, null);
      } else {
        const instance = instances.get(event.instanceId);
        assert.ok(instance, `event ${event.id} references an instance in the shared scenario`);
        assert.equal(instance.appId, event.appId);
        assert.equal(instance.processEpoch, event.processEpoch);
      }
    }

    const instanceContext = {
      ...context,
      appId: "app-one",
      instanceId: "instance-1",
      scope: "process",
    };
    const instancePage = await port.readTimeline(
      {
        context: instanceContext,
        severity: null,
        category: null,
        cursor: null,
        pageSize: 20,
      },
      new AbortController().signal,
    );
    assert.ok(instancePage.items.length > 0);
    assert.ok(instancePage.items.every((item) => item.instanceId === "instance-1"));
    assert.equal(instancePage.query.context.instanceId, "instance-1");
  } finally {
    transport.dispose();
    server.close();
  }
});

test("INCIDENT-MOCK: unknown environment returns an empty read model", async () => {
  const origin = "http://incident-unknown-environment.test";
  const server = setupServer(...createIncidentMockHandlers(MOCK_INCIDENT_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-incident-session",
    onUnauthorized: () => {},
  });
  try {
    const page = await createIncidentHttp(transport).readTimeline(
      {
        context: {
          environmentId: "unknown-env",
          appId: null,
          instanceId: null,
          resource: null,
          scope: "fleet",
          window: { fromMs: Date.now() - 15 * 60_000, toMs: Date.now() },
        },
        severity: null,
        category: null,
        cursor: null,
        pageSize: 20,
      },
      new AbortController().signal,
    );
    assert.equal(page.items.length, 0);
    assert.equal(page.statistics.total, 0);
    assert.equal(page.statistics.affectedApplications, 0);
  } finally {
    transport.dispose();
    server.close();
  }
});
