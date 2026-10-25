import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createObservationCatalogHttp } from "../../src/features/applications/api/catalogHttp";

const origin = "http://catalog-http.test",
  signal = () => new AbortController().signal,
  asOf = "2026-10-07T12:00:00.000Z";
const catalog = {
  asOf,
  environments: [
    { id: "prod", name: "Production" },
    { id: "staging", name: "Staging" },
  ],
  applications: [
    { id: "orders", environmentId: "prod", name: "Orders" },
    { id: "orders", environmentId: "staging", name: "Orders preview" },
  ],
};
const reply = (request, body) =>
  HttpResponse.json(body, { headers: { "x-request-id": request.headers.get("x-request-id") } });
async function run(body, action) {
  const server = setupServer(
    http.get(`${origin}/api/v1/observation/catalog`, ({ request }) => reply(request, body)),
  );
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "catalog-owner",
    onUnauthorized: () => {},
    requestId: () => "catalog-request",
  });
  try {
    await action(createObservationCatalogHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("CATALOG-HTTP: authorized environment/application facts map one exact UTC instant; same app ID can exist in distinct environments", async () => {
  await run(catalog, async (port) => {
    assert.deepEqual(await port.readObservationCatalog(signal()), {
      asOfMs: Date.parse(asOf),
      environments: catalog.environments,
      applications: catalog.applications,
    });
  });
});

test("CATALOG-WIRE: foreign environment, duplicate scoped identity, unsafe fields and duplicate environment reject", async () => {
  const malformed = [
    { ...catalog, applications: [{ id: "foreign", environmentId: "missing", name: "Foreign" }] },
    { ...catalog, applications: [catalog.applications[0], catalog.applications[0]] },
    { ...catalog, environments: [catalog.environments[0], catalog.environments[0]] },
    { ...catalog, environments: [{ ...catalog.environments[0], name: " \u001c " }] },
    { ...catalog, applications: [{ ...catalog.applications[0], name: " \u0085 " }] },
    { ...catalog, credentials: "PRIVATE-SECRET" },
    { ...catalog, asOf: "2026-10-07T12:00:00+00:00" },
  ];
  for (const value of malformed)
    await run(value, async (port) => {
      await assert.rejects(
        port.readObservationCatalog(signal()),
        (error) =>
          error.code === "console_response_invalid" &&
          !JSON.stringify(error).includes("PRIVATE-SECRET"),
      );
    });
});
