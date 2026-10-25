import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { AppErrorKind } from "@richie696/react-framework";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createRuleObservationHttp } from "../../src/features/rules/api/ruleObservationHttp";

const origin = "http://rule-observation.test";
const bindingStates = {
  query: { environmentId: "prod", appId: "orders", kind: null, page: 1, pageSize: 20 },
  asOf: "2026-10-16T08:00:00.000Z",
  coverage: "complete",
  total: 1,
  hasMore: false,
  items: [
    {
      binding: {
        id: "orders-flow",
        environmentId: "prod",
        appId: "orders",
        kind: "flow",
        profile: "sentinel-python-v1",
        sourceId: "nacos",
        sourceLabel: "Nacos",
        location: "public/DEFAULT_GROUP/flow",
      },
      state: "configured_empty",
      ruleCount: 0,
      sourceRevision: "revision-1",
      lastAttemptAt: "2026-10-16T07:59:55.000Z",
      freshness: "current",
      hasLastKnownGood: true,
    },
  ],
};
const loadObservations = {
  query: {
    environmentId: "prod",
    appId: "orders",
    bindingId: "orders-flow",
    instanceId: null,
    page: 1,
    pageSize: 20,
  },
  asOf: "2026-10-16T08:00:00.000Z",
  coverage: "complete",
  targets: {
    source: "active_reporter_enrollment",
    expected: 1,
    observed: 0,
    stale: 0,
    notObserved: 1,
  },
  total: 1,
  hasMore: false,
  items: [
    {
      bindingId: "orders-flow",
      instanceId: "orders-0",
      processId: "worker-0",
      processEpoch: null,
      profileId: null,
      loadState: "not_observed",
      eventKind: null,
      activeSnapshot: null,
      attempt: null,
      observedAt: null,
      receivedAt: null,
      freshness: "unknown",
    },
  ],
};
const loadHistory = {
  query: {
    environmentId: "prod",
    appId: "orders",
    bindingId: "orders-flow",
    instanceId: null,
    page: 1,
    pageSize: 20,
  },
  asOf: "2026-10-17T08:00:00.000Z",
  coverage: "complete",
  total: 1,
  hasMore: false,
  items: [
    {
      observationId: "observation-1",
      epochStatus: "superseded",
      observation: {
        bindingId: "orders-flow",
        instanceId: "orders-0",
        processId: "worker-0",
        processEpoch: "72000000-0000-4000-8000-000000000001",
        profileId: "sentinel-java-v1",
        loadState: "applied",
        eventKind: "snapshot_applied",
        activeSnapshot: {
          sourceRevision: "r1",
          canonicalRulesSha256: "a".repeat(64),
          membershipComplete: false,
          members: [],
        },
        attempt: null,
        observedAt: "2026-10-16T08:00:00.000Z",
        receivedAt: "2026-10-16T08:00:01.000Z",
        freshness: "stale",
      },
    },
  ],
};

async function run(body, action) {
  const server = setupServer(
    http.get(`${origin}/api/v2/rules/catalog/binding-states`, () =>
      HttpResponse.json(body.bindingStates ?? bindingStates, {
        headers: { "x-request-id": "rule-observation-1" },
      }),
    ),
    http.get(`${origin}/api/v2/rules/load-observations`, () =>
      HttpResponse.json(body.loadObservations ?? loadObservations, {
        headers: { "x-request-id": "rule-observation-1" },
      }),
    ),
    http.get(`${origin}/api/v2/rules/load-observation-history`, ({ request }) =>
      HttpResponse.json(body.loadHistory ?? loadHistory, {
        headers: { "x-request-id": "rule-observation-1" },
      }),
    ),
  );
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "rule-observation-test",
    onUnauthorized: () => {},
    requestId: () => "rule-observation-1",
  });
  try {
    await action(createRuleObservationHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("RULE-OBSERVATION-HTTP: provider-empty and runtime-not-observed facts remain distinct", async () => {
  await run({}, async (port) => {
    const signal = new AbortController().signal;
    const states = await port.readBindingStates(
      { environmentId: "prod", appId: "orders", kind: null, page: 1, pageSize: 20 },
      signal,
    );
    const loads = await port.readRuleLoadObservations(
      {
        environmentId: "prod",
        appId: "orders",
        bindingId: "orders-flow",
        instanceId: null,
        page: 1,
        pageSize: 20,
      },
      signal,
    );
    assert.equal(states.items[0].state, "configured_empty");
    assert.equal(states.items[0].ruleCount, 0);
    assert.equal(loads.targets.expected, 1);
    assert.equal(loads.items[0].loadState, "not_observed");
    assert.equal(loads.items[0].freshness, "unknown");
  });
});

test("RULE-OBSERVATION-HTTP: historical epochs use an exact binding query and remain separate", async () => {
  await run({}, async (port) => {
    const history = await port.readRuleLoadObservationHistory(
      {
        environmentId: "prod",
        appId: "orders",
        bindingId: "orders-flow",
        instanceId: null,
        page: 1,
        pageSize: 20,
      },
      new AbortController().signal,
    );
    assert.equal(history.items[0].epochStatus, "superseded");
    assert.equal(history.items[0].observation.processEpoch, "72000000-0000-4000-8000-000000000001");
    assert.equal(history.items[0].observation.activeSnapshot?.canonicalRulesSha256, "a".repeat(64));
  });
});

test("RULE-OBSERVATION-HTTP: a response for another query is rejected", async () => {
  await run(
    {
      bindingStates: {
        ...bindingStates,
        query: { ...bindingStates.query, environmentId: "other" },
      },
    },
    async (port) => {
      await assert.rejects(
        port.readBindingStates(
          { environmentId: "prod", appId: "orders", kind: null, page: 1, pageSize: 20 },
          new AbortController().signal,
        ),
        (error) => error.kind === AppErrorKind.PROTOCOL,
      );
    },
  );
});
