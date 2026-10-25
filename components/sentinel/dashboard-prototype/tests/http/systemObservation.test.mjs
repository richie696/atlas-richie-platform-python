import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createSystemObservationHttp } from "../../src/features/system/api/systemObservationHttp";
import { createSourceRegistrationHttp } from "../../src/features/system/api/sourceRegistrationHttp";
import { createSystemMockHandlers } from "../../src/features/system/mock";
import { MOCK_SYSTEM_SCENARIO } from "../../src/app/api/mockSystemScenario";
import { MOCK_IDENTITY_SCENARIO } from "../../src/app/api/mockIdentityScenario";
import { readMockPrincipal, writeMockPrincipal } from "../../src/core/api/mock/mockRole";
import {
  auditPage,
  auditQuery,
  deploymentGuides,
  systemAsOfMs,
  systemConnections,
  systemProtocols,
  agentReportingObservationPage,
  incidentEventObservationPage,
} from "../fixtures/systemObservations";

const origin = "http://system-observation.test",
  signal = () => new AbortController().signal;
const instant = (value) => new Date(value).toISOString();
const connectionsWire = (value) => ({
  asOf: instant(value.asOfMs),
  items: value.items.map(({ checkedAtMs, expiresAtMs, ...item }) => ({
    ...item,
    checkedAt: checkedAtMs === null ? null : instant(checkedAtMs),
    expiresAt: expiresAtMs === null ? null : instant(expiresAtMs),
  })),
});
const protocolsWire = (value) => ({
  asOf: instant(value.asOfMs),
  items: value.items.map(({ observedAtMs, ...item }) => ({
    ...item,
    observedAt: observedAtMs === null ? null : instant(observedAtMs),
  })),
});
const agentReportingWire = (value) => ({
  asOf: instant(value.asOfMs),
  page: value.page,
  pageSize: value.pageSize,
  total: value.total,
  items: value.items.map(({ observedAtMs, ...item }) => ({
    ...item,
    observedAt: observedAtMs === null ? null : instant(observedAtMs),
  })),
});
const incidentEventWire = agentReportingWire;
const auditWire = (value) => ({
  query: {
    start: instant(value.query.startMs),
    end: instant(value.query.endMs),
    actorId: value.query.actorId,
    action: value.query.action,
    result: value.query.result,
    page: value.query.page,
    pageSize: value.query.pageSize,
  },
  asOf: instant(value.asOfMs),
  total: value.total,
  items: value.items.map(({ occurredAtMs, ...item }) => ({
    ...item,
    occurredAt: instant(occurredAtMs),
  })),
});
const reply = (request, body, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: { "x-request-id": request.headers.get("x-request-id") },
  });
async function run(handlers, action) {
  const server = setupServer(...handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "system-owner",
    onUnauthorized: () => {},
    requestId: () => `system-${++sequence}`,
  });
  try {
    await action(createSystemObservationHttp(transport), createSourceRegistrationHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("SYSTEM-CONNECTIONS: independent probes map UTC facts and expiry without exposing transport configuration", async () => {
  const expected = systemConnections,
    wire = connectionsWire(expected);
  await run(
    [http.get(`${origin}/api/v1/system/connections`, ({ request }) => reply(request, wire))],
    async (ports) => {
      assert.deepEqual(await ports.health.readConnections(signal()), expected);
      assert.equal(wire.items[0].checkedAt, instant(expected.items[0].checkedAtMs));
    },
  );
  const secret = structuredClone(wire);
  secret.items[0].endpoint = "https://user:password@private.example";
  await run(
    [http.get(`${origin}/api/v1/system/connections`, ({ request }) => reply(request, secret))],
    async (ports) => {
      await assert.rejects(
        ports.health.readConnections(signal()),
        (error) =>
          error.code === "console_response_invalid" && !JSON.stringify(error).includes("password"),
      );
    },
  );
  for (const id of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"]) {
    const invalid = structuredClone(wire);
    invalid.items[0].id = id;
    await run(
      [http.get(`${origin}/api/v1/system/connections`, ({ request }) => reply(request, invalid))],
      async (ports) => {
        await assert.rejects(
          ports.health.readConnections(signal()),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  }
});

test("SYSTEM-DEPLOYMENT-GUIDES: server catalog and advertised Collector endpoint are validated facts", async () => {
  await run(
    [
      http.get(`${origin}/api/v1/system/deployment-guides`, ({ request }) =>
        reply(request, deploymentGuides),
      ),
    ],
    async (ports) => {
      assert.deepEqual(await ports.deploymentGuides.readDeploymentGuides(signal()), deploymentGuides);
    },
  );

  const invalid = {
    ...deploymentGuides,
    runtimeCollector: { state: "configured", endpoint: "http://collector.example.test" },
  };
  await run(
    [
      http.get(`${origin}/api/v1/system/deployment-guides`, ({ request }) =>
        reply(request, invalid),
      ),
    ],
    async (ports) => {
      await assert.rejects(
        ports.deploymentGuides.readDeploymentGuides(signal()),
        (error) => error.code === "deployment_guide_read_invalid",
      );
    },
  );
});

test("SYSTEM-PROTOCOLS: supported and active negotiation facts are distinct; invalid duplicate boundaries reject", async () => {
  const expected = systemProtocols,
    wire = protocolsWire(expected);
  await run(
    [http.get(`${origin}/api/v1/system/protocols`, ({ request }) => reply(request, wire))],
    async (ports) => {
      assert.deepEqual(await ports.protocols.readProtocols(signal()), expected);
    },
  );
  const invalid = structuredClone(wire);
  invalid.items.push(structuredClone(invalid.items[0]));
  await run(
    [http.get(`${origin}/api/v1/system/protocols`, ({ request }) => reply(request, invalid))],
    async (ports) => {
      await assert.rejects(
        ports.protocols.readProtocols(signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
  for (const version of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"]) {
    const invalidIdentifier = structuredClone(wire);
    invalidIdentifier.items[0].supported = [version];
    await run(
      [
        http.get(`${origin}/api/v1/system/protocols`, ({ request }) =>
          reply(request, invalidIdentifier),
        ),
      ],
      async (ports) => {
        await assert.rejects(
          ports.protocols.readProtocols(signal()),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  }
});

test("SYSTEM-PROTOCOL-WORKERS: versioned read preserves each worker and unknown without leaking peer identity", async () => {
  const expected = agentReportingObservationPage,
    wire = agentReportingWire(expected);
  let query;
  await run(
    [
      http.get(`${origin}/api/v2/system/protocol-observations/agent-reporting`, ({ request }) => {
        query = new URL(request.url).searchParams;
        return reply(request, wire);
      }),
    ],
    async (ports) => {
      assert.deepEqual(
        await ports.protocols.readAgentReportingObservations(1, 20, signal()),
        expected,
      );
      assert.equal(query.get("page"), "1");
      assert.equal(query.get("pageSize"), "20");
    },
  );
  const invalid = structuredClone(wire);
  invalid.items[0].certificatePrincipal = "secret-principal";
  await run(
    [
      http.get(`${origin}/api/v2/system/protocol-observations/agent-reporting`, ({ request }) =>
        reply(request, invalid),
      ),
    ],
    async (ports) => {
      await assert.rejects(
        ports.protocols.readAgentReportingObservations(1, 20, signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});

test("SYSTEM-INCIDENT-PROTOCOL-WORKERS: incident negotiation is an independent authority and keeps unknown per worker", async () => {
  const expected = incidentEventObservationPage,
    wire = incidentEventWire(expected);
  let query;
  await run(
    [
      http.get(`${origin}/api/v2/system/protocol-observations/incident-events`, ({ request }) => {
        query = new URL(request.url).searchParams;
        return reply(request, wire);
      }),
    ],
    async (ports) => {
      assert.deepEqual(
        await ports.protocols.readIncidentEventObservations(1, 20, signal()),
        expected,
      );
      assert.equal(query.get("page"), "1");
      assert.equal(query.get("pageSize"), "20");
    },
  );
  const invalid = structuredClone(wire);
  invalid.items[0].boundary = "agent-reporting";
  await run(
    [
      http.get(`${origin}/api/v2/system/protocol-observations/incident-events`, ({ request }) =>
        reply(request, invalid),
      ),
    ],
    async (ports) => {
      await assert.rejects(
        ports.protocols.readIncidentEventObservations(1, 20, signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});

test("SYSTEM-AUDIT: bounded UTC query identity, stable page, and redacted record shape survive projection", async () => {
  const expected = auditPage(),
    wire = auditWire(expected);
  assert.equal(wire.items[0].requestId, expected.items[0].requestId);
  assert.equal("requestKey" in wire.items[0], false);
  let params;
  await run(
    [
      http.get(`${origin}/api/v1/system/audit`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return reply(request, wire);
      }),
    ],
    async (ports) => {
      assert.deepEqual(await ports.audit.readAudit(auditQuery, signal()), expected);
      assert.equal(params.get("start"), instant(auditQuery.startMs));
      assert.equal(params.get("end"), instant(auditQuery.endMs));
      assert.equal(params.get("page"), "1");
      assert.equal(params.get("pageSize"), "1");
      assert.equal(params.has("actorId"), false);
      assert.equal(params.has("action"), false);
    },
  );
  for (const alter of [
    (value) => (value.query.actorId = "foreign-actor"),
    (value) => (value.items[0].occurredAt = value.query.end),
    (value) => (value.items[0].password = "PRIVATE-PASSWORD"),
    (value) => {
      value.items[0].requestKey = value.items[0].requestId;
      delete value.items[0].requestId;
    },
    (value) => {
      value.items[0].bindingId = null;
      value.items[0].publicationId = "publication-without-binding";
    },
  ]) {
    const invalid = structuredClone(wire);
    alter(invalid);
    await run(
      [http.get(`${origin}/api/v1/system/audit`, ({ request }) => reply(request, invalid))],
      async (ports) => {
        await assert.rejects(
          ports.audit.readAudit(auditQuery, signal()),
          (error) =>
            error.code === "console_response_invalid" &&
            !JSON.stringify(error).includes("PRIVATE-PASSWORD"),
        );
      },
    );
  }
  for (const actorId of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"]) {
    const invalid = structuredClone(wire);
    invalid.query.actorId = actorId;
    await run(
      [http.get(`${origin}/api/v1/system/audit`, ({ request }) => reply(request, invalid))],
      async (ports) => {
        await assert.rejects(
          ports.audit.readAudit(auditQuery, signal()),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  }
});

test("SYSTEM-AUDIT: system-owned initialization and scheduled actions accept a missing account actor", async () => {
  const expected = auditPage(),
    wire = auditWire(expected);
  wire.items[0].action = "system-initialize";
  wire.items[0].actorId = null;
  await run(
    [http.get(`${origin}/api/v1/system/audit`, ({ request }) => reply(request, wire))],
    async (ports) => {
      const actual = await ports.audit.readAudit(auditQuery, signal());
      assert.equal(actual.items[0].action, "system-initialize");
      assert.equal(actual.items[0].actorId, null);
    },
  );

  for (const action of ["plan-activate", "plan-restore"]) {
    const scheduled = auditWire(expected);
    scheduled.items[0].action = action;
    scheduled.items[0].actorId = null;
    await run(
      [http.get(`${origin}/api/v1/system/audit`, ({ request }) => reply(request, scheduled))],
      async (ports) => {
        const actual = await ports.audit.readAudit(auditQuery, signal());
        assert.equal(actual.items[0].action, action);
        assert.equal(actual.items[0].actorId, null);
      },
    );
  }
});

test("SYSTEM-AUDIT: an account-owned action cannot claim a missing actor", async () => {
  const wire = auditWire(auditPage());
  wire.items[0].action = "account-create";
  wire.items[0].actorId = null;
  await run(
    [http.get(`${origin}/api/v1/system/audit`, ({ request }) => reply(request, wire))],
    async (ports) => {
      await assert.rejects(
        ports.audit.readAudit(auditQuery, signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});

test("SYSTEM-AUDIT-INPUT: oversized windows, reversed times and invalid pagination never dispatch", async () => {
  let dispatches = 0;
  await run(
    [
      http.all(`${origin}/*`, ({ request }) => {
        dispatches += 1;
        return reply(request, {});
      }),
    ],
    async (ports) => {
      const invalid = [
        { ...auditQuery, startMs: auditQuery.endMs },
        { ...auditQuery, startMs: systemAsOfMs - 32 * 24 * 60 * 60 * 1000 },
        { ...auditQuery, page: 0 },
        { ...auditQuery, pageSize: 101 },
        { ...auditQuery, actorId: "x".repeat(201) },
        ...["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"].map((actorId) => ({
          ...auditQuery,
          actorId,
        })),
      ];
      for (const query of invalid)
        await assert.rejects(
          ports.audit.readAudit(query, signal()),
          (error) => error.code === "console_request_invalid",
        );
      assert.equal(dispatches, 0);
    },
  );
});

test("SYSTEM-MOCK-SEED: source, administrator, environment and audit facts share one isolated scenario", async () => {
  const now = Date.parse("2026-10-08T00:00:00.000Z");
  const mock = createSystemMockHandlers(
    MOCK_SYSTEM_SCENARIO,
    MOCK_IDENTITY_SCENARIO.accounts.find((account) => account.builtIn).id,
    () => now,
  );
  const query = {
    startMs: now - 60 * 60 * 1000,
    endMs: now,
    actorId: "",
    action: null,
    result: null,
    page: 1,
    pageSize: 20,
  };
  const previousPrincipal = readMockPrincipal();
  writeMockPrincipal("admin");
  try {
    await run(mock.handlers, async (ports, sources) => {
      const connections = await ports.health.readConnections(signal());
      assert.equal(connections.items.length, 3);
      assert.equal(connections.items[0].provider, "nacos");
      assert.equal(connections.items[0].sourceId, MOCK_SYSTEM_SCENARIO.primarySource.id);
      assert.equal(connections.items[0].checkedAtMs, now - 20_000);
      assert.equal(connections.items[0].expiresAtMs, now + 40_000);
      const registry = await sources.readSources(signal());
      assert.equal(registry.items.length, 1);
      assert.equal(registry.items[0].id, connections.items[0].sourceId);
      assert.equal(connections.items[1].state, "unconfigured");
      const protocols = await ports.protocols.readProtocols(signal());
      assert.equal(protocols.items.length, 3);
      assert.equal(protocols.items[0].observedAtMs, now - 30_000);
      assert.equal(protocols.items[1].active, null);
      const audit = await ports.audit.readAudit(query, signal());
      assert.equal(audit.total, 2);
      assert.equal(audit.items[0].publicationId, MOCK_SYSTEM_SCENARIO.publicationId);
      assert.equal(
        audit.items[0].actorId,
        MOCK_IDENTITY_SCENARIO.accounts.find((account) => account.builtIn).id,
      );
      assert.equal(audit.items[0].environmentId, MOCK_SYSTEM_SCENARIO.environmentId);
      assert.equal(
        audit.items[1].targetId,
        MOCK_IDENTITY_SCENARIO.accounts.find((account) => account.builtIn).id,
      );
      assert.equal("password" in audit.items[0], false);
    });
  } finally {
    writeMockPrincipal(previousPrincipal);
  }
});
