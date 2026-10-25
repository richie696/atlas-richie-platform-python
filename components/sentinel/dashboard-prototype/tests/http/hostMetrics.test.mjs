import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { CONSOLE_HEADER } from "../../src/core/api/protocol/common";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createHostMetricsHttp } from "../../src/features/realtime/api/hostMetricsHttp";

const origin = "http://host-metrics-http.test";
const signal = () => new AbortController().signal;
const from = "2026-10-17T00:00:00.000Z";
const to = "2026-10-17T00:05:00.000Z";
const reply = (request, body) =>
  HttpResponse.json(body, {
    headers: { [CONSOLE_HEADER.RequestId]: request.headers.get(CONSOLE_HEADER.RequestId) },
  });
const kinds = [
  ["host_cpu_busy_ratio", "ratio"],
  ["host_memory_used_bytes", "bytes"],
  ["host_memory_used_ratio", "ratio"],
  ["host_load_1m", "tasks"],
];
function hostMetricsWire() {
  return {
    sourceId: "prometheus-prod",
    environmentId: "prod",
    query: { from, to, stepMs: 60_000 },
    asOf: to,
    quality: "available",
    reason: null,
    hosts: [
      {
        hostId: "[host=node-1]",
        identity: [{ name: "host", value: "node-1" }],
        metrics: kinds.map(([metric, unit]) => ({
          metric,
          unit,
          quality: "available",
          reason: null,
          samples: [
            { at: from, value: 0.25 },
            { at: "2026-10-17T00:01:00.000Z", value: 0.5 },
          ],
        })),
      },
    ],
  };
}
async function run(handler, callback) {
  const server = setupServer(handler);
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "host-metrics-owner",
    onUnauthorized: () => {},
    requestId: () => "host-metrics-request",
  });
  try {
    await callback(transport);
  } finally {
    transport.dispose();
    server.close();
  }
}

test("HOST-METRICS-HTTP: sends a bounded UTC query and decodes only the selected source window", async () => {
  let requested;
  await run(
    http.get(`${origin}/api/v2/monitoring/sources/:sourceId/host-metrics`, ({ request }) => {
      requested = new URL(request.url);
      return reply(request, hostMetricsWire());
    }),
    async (transport) => {
      const result = await createHostMetricsHttp(transport).read(
        "prometheus-prod",
        { from, to, stepMs: 60_000 },
        signal(),
      );
      assert.equal(result.hosts[0].metrics.length, 4);
      assert.equal(requested.pathname, "/api/v2/monitoring/sources/prometheus-prod/host-metrics");
      assert.equal(requested.searchParams.get("from"), from);
      assert.equal(requested.searchParams.get("to"), to);
      assert.equal(requested.searchParams.get("stepMs"), "60000");
      assert.equal(requested.searchParams.has("query"), false);
    },
  );
});

test("HOST-METRICS-SEMANTICS: foreign source/window, duplicate identity, duplicate metric and out-of-range samples fail closed", async () => {
  const invalid = [];
  for (const mutate of [
    (wire) => (wire.sourceId = "other-source"),
    (wire) => (wire.query.to = "2026-10-17T00:06:00.000Z"),
    (wire) => wire.hosts.push(structuredClone(wire.hosts[0])),
    (wire) => (wire.hosts[0].metrics[1].metric = wire.hosts[0].metrics[0].metric),
    (wire) => (wire.hosts[0].metrics[0].samples[1].at = to),
  ]) {
    const wire = hostMetricsWire();
    mutate(wire);
    invalid.push(wire);
  }
  for (const wire of invalid)
    await run(
      http.get(`${origin}/api/v2/monitoring/sources/:sourceId/host-metrics`, ({ request }) =>
        reply(request, wire),
      ),
      async (transport) => {
        await assert.rejects(
          createHostMetricsHttp(transport).read(
            "prometheus-prod",
            { from, to, stepMs: 60_000 },
            signal(),
          ),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
});

test("HOST-METRICS-INPUT: zero/reversed windows and over-1000-point intervals do not dispatch", async () => {
  let dispatched = 0;
  await run(
    http.all(`${origin}/*`, ({ request }) => {
      dispatched++;
      return reply(request, hostMetricsWire());
    }),
    async (transport) => {
      const client = createHostMetricsHttp(transport);
      for (const query of [
        { from, to: from, stepMs: 60_000 },
        { from: to, to: from, stepMs: 60_000 },
        { from, to: "2026-10-18T00:00:00.000Z", stepMs: 60_000 },
      ])
        await assert.rejects(
          client.read("prometheus-prod", query, signal()),
          (error) => error.code === "console_request_invalid" || error instanceof TypeError,
        );
      assert.equal(dispatched, 0);
    },
  );
});
