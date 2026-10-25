import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createIncidentHttp } from "../../src/features/faults/api/incidentHttp";
import { evidenceFor, eventsFor, incidentPageFor, incidentQuery } from "../fixtures/incidents";

const origin = "http://incident-http.test",
  signal = () => new AbortController().signal;
const instant = (value) => new Date(value).toISOString();
const contextWire = (value) => ({
  ...value,
  window: { from: instant(value.window.fromMs), to: instant(value.window.toMs) },
});
const eventWire = (value) => {
  const { occurredAtMs, receivedAtMs, ...event } = value;
  return { ...event, occurredAt: instant(occurredAtMs), receivedAt: instant(receivedAtMs) };
};
const pageWire = (value) => ({
  query: { ...value.query, context: contextWire(value.query.context) },
  asOf: instant(value.asOfMs),
  statistics: value.statistics,
  items: value.items.map(eventWire),
  filteredTotal: value.filteredTotal,
  nextCursor: value.nextCursor,
});
const evidenceWire = (value) => ({
  query: { ...value.query, context: contextWire(value.query.context) },
  asOf: instant(value.asOfMs),
  event: eventWire(value.event),
  facts: value.facts.map(({ atMs, ...fact }) => ({ ...fact, at: instant(atMs) })),
  completeness: value.completeness,
  suggestedViews: value.suggestedViews,
  relatedRule: value.relatedRule,
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
    owner: () => "incident-owner",
    onUnauthorized: () => {},
    requestId: () => `incident-${++sequence}`,
  });
  try {
    await action(createIncidentHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("INCIDENT-TIMELINE: filters, cursor, UTC instants and delayed collector receipt survive projection", async () => {
  const expected = incidentPageFor(),
    wire = pageWire(expected);
  let parameters;
  await run(
    [
      http.get(`${origin}/api/v1/incidents`, ({ request }) => {
        parameters = new URL(request.url).searchParams;
        return reply(request, wire);
      }),
    ],
    async (port) => {
      assert.deepEqual(await port.readTimeline(incidentQuery, signal()), expected);
      assert.equal(parameters.get("environmentId"), "test-env");
      assert.equal(parameters.get("from"), instant(incidentQuery.context.window.fromMs));
      assert.equal(parameters.get("to"), instant(incidentQuery.context.window.toMs));
      assert.equal(parameters.get("pageSize"), "2");
      assert.equal(parameters.has("appId"), false);
      assert.equal(parameters.has("resource"), false);
      assert.ok(Date.parse(wire.items[0].receivedAt) > Date.parse(wire.query.context.window.to));
    },
  );
});

test("INCIDENT-EVIDENCE: exact event path, active filters and bounded UTC facts are preserved", async () => {
  const input = {
    context: incidentQuery.context,
    eventId: "event-a",
    severity: null,
    category: null,
  };
  const expected = evidenceFor(input),
    wire = evidenceWire(expected);
  let target;
  await run(
    [
      http.get(`${origin}/api/v1/incidents/:incidentId/evidence`, ({ request, params }) => {
        target = params.incidentId;
        assert.equal(new URL(request.url).searchParams.get("environmentId"), "test-env");
        return reply(request, wire);
      }),
    ],
    async (port) => {
      assert.deepEqual(await port.readEvidence(input, signal()), expected);
      assert.equal(target, input.eventId);
      assert.equal(wire.facts[0].at, wire.event.occurredAt);
    },
  );
});

test("INCIDENT-WIRE: foreign context, wrong event, malformed UTC, inferred captions and unsafe fields fail closed", async () => {
  const page = pageWire(incidentPageFor()),
    detailQuery = {
      context: incidentQuery.context,
      eventId: "event-b",
      severity: null,
      category: null,
    },
    detail = evidenceWire(evidenceFor(detailQuery));
  const invalidPages = [];
  for (const alter of [
    (value) => (value.items[0].environmentId = "foreign"),
    (value) => (value.items[0].occurredAt = value.query.context.window.to),
    (value) => (value.items[0].receivedAt = "2026-10-07T00:12:00+00:00"),
    (value) =>
      (value.items[0].caption = {
        code: "resource_pressure",
        metric: "cpu_ratio",
        value: 2,
        threshold: 0.8,
      }),
    (value) => (value.items[0].traceback = "PRIVATE-STACK"),
    (value) => (value.statistics.total = 99),
  ]) {
    const copy = structuredClone(page);
    alter(copy);
    invalidPages.push(copy);
  }
  for (const value of invalidPages)
    await run(
      [http.get(`${origin}/api/v1/incidents`, ({ request }) => reply(request, value))],
      async (port) => {
        await assert.rejects(
          port.readTimeline(incidentQuery, signal()),
          (error) =>
            error.code === "console_response_invalid" &&
            !JSON.stringify(error).includes("PRIVATE-STACK"),
        );
      },
    );

  const invalidEvidence = [];
  for (const alter of [
    (value) => (value.event.id = "event-a"),
    (value) => (value.query.context.appId = "foreign-app"),
    (value) => (value.facts[0].at = "not-a-time"),
    (value) => value.facts.push(structuredClone(value.facts[0])),
    (value) => (value.completeness = "unavailable"),
    (value) => (value.relatedRule = null),
    (value) => (value.relatedRule.appId = "foreign-app"),
    (value) => (value.relatedRule.publicationId = "foreign-publication"),
    (value) => (value.error = "PRIVATE-ERROR"),
  ]) {
    const copy = structuredClone(detail);
    alter(copy);
    invalidEvidence.push(copy);
  }
  for (const value of invalidEvidence)
    await run(
      [
        http.get(`${origin}/api/v1/incidents/:incidentId/evidence`, ({ request }) =>
          reply(request, value),
        ),
      ],
      async (port) => {
        await assert.rejects(
          port.readEvidence(detailQuery, signal()),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
});

test("INCIDENT-INPUT: invalid scopes, filters, page sizes and event identifiers never dispatch", async () => {
  let dispatches = 0;
  await run(
    [
      http.all(`${origin}/*`, ({ request }) => {
        dispatches += 1;
        return reply(request, {});
      }),
    ],
    async (port) => {
      for (const query of [
        { ...incidentQuery, pageSize: 0 },
        { ...incidentQuery, pageSize: 101 },
        { ...incidentQuery, context: { ...incidentQuery.context, resource: "/orders" } },
        { ...incidentQuery, cursor: "x".repeat(513) },
        { ...incidentQuery, cursor: "\u001c" },
        { ...incidentQuery, cursor: "\u0085" },
        { ...incidentQuery, cursor: "\ufeff" },
        { ...incidentQuery, cursor: "\ud800" },
      ])
        await assert.rejects(
          port.readTimeline(query, signal()),
          (error) => error.code === "console_request_invalid",
        );
      await assert.rejects(
        port.readEvidence(
          { context: incidentQuery.context, eventId: " ", severity: null, category: null },
          signal(),
        ),
        (error) => error.code === "console_request_invalid",
      );
      assert.equal(dispatches, 0);
    },
  );
});
