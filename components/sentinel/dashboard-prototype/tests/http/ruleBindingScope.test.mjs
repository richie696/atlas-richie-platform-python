import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { AppErrorKind } from "@richie696/react-framework";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createRuleBindingScopeHttp } from "../../src/features/rules/api/ruleBindingScopeHttp";

const origin = "http://rule-binding-scope.test";

async function run(body, status, action) {
  const server = setupServer(
    http.get(`${origin}/api/v2/rules/binding-scopes`, () =>
      HttpResponse.json(body, {
        status,
        headers: { "x-request-id": "rule-scope-read-1" },
      }),
    ),
  );
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "rule-scope-test",
    onUnauthorized: () => {},
    requestId: () => "rule-scope-read-1",
  });
  try {
    await action(createRuleBindingScopeHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("RULE-SCOPE-HTTP: independent scope API maps persisted rule-binding facts", async () => {
  await run(
    {
      asOf: "2026-10-15T01:02:03.456Z",
      environments: [{ id: "prod", name: "prod" }],
      applications: [{ id: "checkout", environmentId: "prod", name: "checkout" }],
    },
    200,
    async (port) => {
      const catalog = await port.readRuleBindingScopes(new AbortController().signal);
      assert.equal(catalog.asOfMs, Date.parse("2026-10-15T01:02:03.456Z"));
      assert.deepEqual(catalog.environments, [{ id: "prod", name: "prod" }]);
      assert.deepEqual(catalog.applications, [
        { id: "checkout", environmentId: "prod", name: "checkout" },
      ]);
    },
  );
});

test("RULE-SCOPE-HTTP: an authoritative empty catalog remains a successful result", async () => {
  await run(
    { asOf: "2026-10-15T01:02:03.456Z", environments: [], applications: [] },
    200,
    async (port) => {
      const catalog = await port.readRuleBindingScopes(new AbortController().signal);
      assert.deepEqual(catalog.environments, []);
      assert.deepEqual(catalog.applications, []);
    },
  );
});

test("RULE-SCOPE-HTTP: an invalid response fails closed instead of becoming empty", async () => {
  await run(
    {
      asOf: "2026-10-15T01:02:03.456Z",
      environments: [],
      applications: [{ id: "orphan", environmentId: "missing", name: "orphan" }],
    },
    200,
    async (port) => {
      await assert.rejects(
        port.readRuleBindingScopes(new AbortController().signal),
        (error) => error.kind === AppErrorKind.PROTOCOL,
      );
    },
  );
});
