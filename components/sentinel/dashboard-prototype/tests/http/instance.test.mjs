import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createInstanceHttp } from "../../src/features/applications/api/instanceHttp";
import { createInstanceResources } from "../../src/features/applications/application/instanceResources";
import { catalogFor, catalogQuery, detailFor, instanceFor } from "../fixtures/instances";

const origin = "http://instance-http.test",
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
const bundleWire = (value) => ({
  query: { ...value.query, context: contextWire(value.query.context) },
  asOf: instant(value.asOfMs),
  summary: value.summary.map(readingWire),
  series: value.series.map((item) => ({
    ...metadata(item),
    samples: item.samples.map((sample) => ({ at: instant(sample.atMs), value: sample.value })),
  })),
  annotations: value.annotations.map(({ atMs, ...item }) => ({ ...item, at: instant(atMs) })),
});
const observedWire = (value) => ({
  instanceId: value.instanceId,
  appId: value.appId,
  environmentId: value.environmentId,
  hostId: value.hostId,
  containerId: value.containerId,
  processId: value.processId,
  processEpoch: value.processEpoch,
  health: value.health,
  lastReportAt: value.lastReportAtMs === null ? null : instant(value.lastReportAtMs),
  supportedScopes: value.supportedScopes,
  ruleReceipt: {
    state: value.ruleReceipt.state,
    desiredVersionId: value.ruleReceipt.desiredVersionId,
    appliedVersionId: value.ruleReceipt.appliedVersionId,
    processEpoch: value.ruleReceipt.processEpoch,
    receivedAt:
      value.ruleReceipt.receivedAtMs === null ? null : instant(value.ruleReceipt.receivedAtMs),
  },
  processMetrics: value.processMetrics.map(readingWire),
});
const catalogWire = (value) => ({
  query: { ...value.query, context: contextWire(value.query.context) },
  asOf: instant(value.asOfMs),
  coverage: value.coverage,
  totalInstances: value.totalInstances,
  attentionInstances: value.attentionInstances,
  filteredTotal: value.filteredTotal,
  items: value.items.map(observedWire),
});
const detailWire = (value) => ({
  query: { ...value.query, context: contextWire(value.query.context) },
  asOf: instant(value.asOfMs),
  instance: observedWire(value.instance),
  metrics: value.metrics === null ? null : bundleWire(value.metrics),
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
    owner: () => "instance-owner",
    onUnauthorized: () => {},
    requestId: () => `instance-${++sequence}`,
  });
  try {
    await action(createInstanceHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}
test("INSTANCE-CATALOG: actual filters/paging and server counters are preserved with exact epoch/UTC projections", async () => {
  const expected = catalogFor(),
    wire = catalogWire(expected);
  let params;
  await run(
    [
      http.get(`${origin}/api/v1/instances`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return reply(request, wire);
      }),
    ],
    async (port) => {
      assert.deepEqual(await port.readCatalog(catalogQuery, signal()), expected);
      assert.equal(params.get("page"), "1");
      assert.equal(params.get("pageSize"), "2");
      assert.equal(params.get("attentionOnly"), "false");
      assert.equal(params.get("from"), instant(expected.query.context.window.fromMs));
      assert.equal(params.has("instanceId"), false);
    },
  );
});
test("INSTANCE-DETAIL: path identity/processEpoch/scope/window match; unsupported collection layer has null metrics", async () => {
  const expected = detailFor(),
    wire = detailWire(expected);
  const projected = {
    ...expected,
    instance: { ...expected.instance, ruleReceipt: { ...expected.instance.ruleReceipt } },
    metrics: {
      ...expected.metrics,
      series: expected.metrics.series.map(({ value, sampledAtMs, ...series }) => series),
    },
  };
  let target;
  await run(
    [
      http.get(`${origin}/api/v1/instances/:id`, ({ request, params }) => {
        target = params.id;
        return reply(request, wire);
      }),
    ],
    async (port) => {
      assert.deepEqual(await port.readInstance(expected.query, signal()), projected);
      assert.equal(target, expected.query.context.instanceId);
    },
  );
  const unsupported = {
    ...expected,
    instance: { ...expected.instance, supportedScopes: ["process"] },
    metrics: null,
  };
  await run(
    [
      http.get(`${origin}/api/v1/instances/:id`, ({ request }) =>
        reply(request, detailWire(unsupported)),
      ),
    ],
    async (port) => {
      await assert.rejects(
        port.readInstance(expected.query, signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});
test("INSTANCE-RETIRED: backend 410 invalidates selected process through the existing detail owner contract", async () => {
  const expected = detailFor(),
    input = expected.query;
  let calls = 0;
  await run(
    [
      http.get(`${origin}/api/v1/instances/:id`, ({ request }) =>
        ++calls === 1
          ? reply(request, detailWire(expected))
          : reply(
              request,
              { error: { code: "target_retired", requestId: request.headers.get("x-request-id") } },
              410,
            ),
      ),
    ],
    async (port) => {
      const resource = createInstanceResources(port, {
        read: () => ({ allowed: true, ownerKey: "session-one" }),
        subscribe: () => () => {},
      });
      try {
        await resource.detail.load(input);
        await assert.rejects(
          resource.detail.load(input),
          (error) => error.status === 409 && error.code === "instance_incarnation_changed",
        );
        assert.equal(resource.detail.getSnapshot().status, "error");
        assert.equal(calls, 2);
      } finally {
        resource.dispose();
      }
    },
  );
});
test("INSTANCE-WIRE: foreign process receipts/metrics/secrets and repeated catalog identities fail closed", async () => {
  const input = detailFor().query,
    wire = detailWire(detailFor()),
    invalid = [];
  for (const alter of [
    (value) => {
      value.instance.processEpoch = "new-epoch";
    },
    (value) => {
      value.instance.ruleReceipt.processEpoch = "old-epoch";
    },
    (value) => {
      value.instance.ruleReceipt.state = "applied";
      value.instance.ruleReceipt.appliedVersionId = "other-version";
    },
    (value) => {
      value.instance.password = "PRIVATE";
    },
    (value) => {
      value.query.context.environmentId = "foreign";
    },
    (value) => {
      value.metrics.query.context.scope = "container";
    },
    (value) => {
      value.metrics.query.context.scope = "fleet";
    },
    (value) => {
      value.instance.supportedScopes = ["process", "process"];
    },
  ]) {
    const copy = structuredClone(wire);
    alter(copy);
    invalid.push(copy);
  }
  for (const value of invalid)
    await run(
      [http.get(`${origin}/api/v1/instances/:id`, ({ request }) => reply(request, value))],
      async (port) => {
        await assert.rejects(
          port.readInstance(input, signal()),
          (error) =>
            error.code === "console_response_invalid" && !JSON.stringify(error).includes("PRIVATE"),
        );
      },
    );
  const page = catalogFor();
  await run(
    [
      http.get(`${origin}/api/v1/instances`, ({ request }) =>
        reply(request, {
          ...catalogWire(page),
          items: [observedWire(instanceFor(1)), observedWire(instanceFor(1))],
          filteredTotal: 2,
        }),
      ),
    ],
    async (port) => {
      await assert.rejects(
        port.readCatalog(catalogQuery, signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});
