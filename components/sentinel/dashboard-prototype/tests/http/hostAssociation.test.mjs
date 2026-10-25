import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import { createHostAssociationHttp } from "../../src/features/hosts/api/hostAssociationHttp";
import { createHostAssociationMockHandlers } from "../../src/features/hosts/mock";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { CONSOLE_HEADER } from "../../src/core/api/protocol/common";
import { writeMockPrincipal } from "../../src/core/api/mock/mockRole";

test("HOST-ASSOCIATION-MOCK: HTTP mock supports read, CAS associate, receipt lookup, and remove", async () => {
  const csrf = "H".repeat(48);
  const identityEndpoint = {
    url: defineUrl("/api/v1/test-csrf", { method: HttpMethod.GET }),
    response: z.strictObject({ ready: z.literal(true) }),
    successStatus: 200,
    errors: ["service_unavailable"],
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: false,
  };
  const handlers = createHostAssociationMockHandlers(() => Date.parse("2026-10-18T00:00:00.000Z"));
  const server = setupServer(
    http.get("*/api/v1/test-csrf", ({ request }) =>
      HttpResponse.json(
        { ready: true },
        {
          headers: {
            [CONSOLE_HEADER.RequestId]: request.headers.get(CONSOLE_HEADER.RequestId) ?? "test",
            [CONSOLE_HEADER.Csrf]: csrf,
          },
        },
      ),
    ),
    ...handlers.handlers,
  );
  server.listen({ onUnhandledRequest: "error" });
  writeMockPrincipal("admin");
  const transport = createConsoleTransport({
    baseUrl: "http://host-association-mock.test",
    owner: () => "host-association-admin",
    onUnauthorized: () => {},
    requestId: (() => {
      let sequence = 0;
      return () => `host-association-${++sequence}`;
    })(),
  });

  try {
    await transport.send(identityEndpoint, { signal: new AbortController().signal });
    const client = createHostAssociationHttp(transport);
    const signal = new AbortController().signal;
    const initial = await client.read("e2e", { page: 1, pageSize: 10 }, signal);
    assert.equal(initial.total, 0);

    const associated = await client.associate(
      {
        requestKey: "associate-e2e-1",
        environmentId: "e2e",
        sourceId: "prom-e2e",
        hostId: "worker-node-1",
        appId: "orders",
        instanceId: "orders-1",
        expectedRevision: null,
      },
      signal,
    );
    assert.equal(associated.provenance, "operator_confirmed");
    assert.equal(associated.reporterActive, false);

    const directory = await client.read("e2e", { appId: "orders", page: 1, pageSize: 10 }, signal);
    assert.deepEqual(directory.associatedHostIds, ["worker-node-1"]);
    const operation = await client.readOperation("associate-e2e-1", signal);
    assert.equal(operation.status, "completed");

    assert.deepEqual(
      await client.remove(
        {
          requestKey: "remove-e2e-1",
          environmentId: "e2e",
          appId: "orders",
          instanceId: "orders-1",
          expectedRevision: associated.revision,
        },
        signal,
      ),
      { removed: true },
    );
    assert.equal((await client.read("e2e", { page: 1, pageSize: 10 }, signal)).total, 0);
  } finally {
    transport.dispose();
    server.close();
    writeMockPrincipal(null);
  }
});

test("HOST-ASSOCIATION-HTTP: binds source, observed host, worker and CAS revision", async () => {
  const calls = [];
  const transport = {
    send: async (endpoint, options) => {
      calls.push({ endpoint, options });
      return {
        sourceId: "prom-prod",
        environmentId: "prod",
        hostId: "node-01",
        appId: "orders",
        instanceId: "worker-1",
        processId: "pid-123",
        revision: "42e1f3e0-8aca-4389-9ddf-20d9b24e5a43",
        provenance: "operator_confirmed",
        currentEpoch: null,
        lastReceivedAt: null,
        reporterActive: true,
        createdAt: "2026-10-17T12:00:00.000Z",
      };
    },
  };
  const client = createHostAssociationHttp(transport);
  await client.associate(
    {
      requestKey: "associate-node-0001",
      environmentId: "prod",
      sourceId: "prom-prod",
      hostId: "node-01",
      appId: "orders",
      instanceId: "worker-1",
      expectedRevision: null,
    },
    new AbortController().signal,
  );
  assert.equal(calls[0].options.body.expectedRevision, null);
  assert.equal(calls[0].options.requestKey, "associate-node-0001");
  assert.equal(calls[0].endpoint.csrf, true);
});

test("HOST-ASSOCIATION-INPUT: malformed identifiers and missing CAS are rejected before dispatch", async () => {
  let dispatched = 0;
  const client = createHostAssociationHttp({
    send: async () => {
      dispatched++;
    },
  });
  await assert.rejects(
    client.associate(
      {
        environmentId: "prod",
        sourceId: "prom-prod",
        hostId: "node-01",
        appId: "orders",
        instanceId: "worker-1",
      },
      new AbortController().signal,
    ),
  );
  assert.equal(dispatched, 0);
});

test("HOST-ASSOCIATION-PAGE: reads a bounded source/app page and validates its summary", async () => {
  let call;
  const client = createHostAssociationHttp({
    send: async (endpoint, options) => {
      call = { endpoint, options };
      return {
        environmentId: "prod",
        asOf: "2026-10-17T12:00:00.000Z",
        page: 1,
        pageSize: 1,
        total: 1,
        associatedHostIds: ["node-01"],
        hostIdsComplete: true,
        items: [
          {
            sourceId: "prom-prod",
            environmentId: "prod",
            hostId: "node-01",
            appId: "orders",
            instanceId: "worker-2",
            processId: "pid-2",
            revision: "42e1f3e0-8aca-4389-9ddf-20d9b24e5a43",
            provenance: "operator_confirmed",
            currentEpoch: null,
            lastReceivedAt: null,
            reporterActive: true,
            createdAt: "2026-10-17T12:00:00.000Z",
          },
        ],
      };
    },
  });
  const result = await client.read(
    "prod",
    {
      sourceId: "prom-prod",
      appId: "orders",
      instanceId: "worker-2",
      page: 1,
      pageSize: 1,
    },
    new AbortController().signal,
  );
  assert.equal(result.total, 1);
  assert.deepEqual(call.options.query, {
    environmentId: "prod",
    sourceId: "prom-prod",
    appId: "orders",
    instanceId: "worker-2",
    page: 1,
    pageSize: 1,
  });
});
