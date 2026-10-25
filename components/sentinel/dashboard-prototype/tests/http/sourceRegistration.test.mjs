import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createSourceRegistrationHttp } from "../../src/features/system/api/sourceRegistrationHttp";
import { ConfigurationEndpointSchema } from "../../src/shared/api/configurationSourceWire";
import { SourceCheckInputSchema } from "../../src/features/system/api/sourceRegistrationWire";

const origin = "http://source-http.test";
const now = Date.parse("2026-10-07T03:00:00.000Z");
const at = (offset = 0) => new Date(now + offset).toISOString();
const record = {
  id: "source-nacos-one",
  revision: "source-rev-2",
  name: "primary",
  provider: "nacos",
  endpoint: "https://nacos.example.com",
  namespace: "sentinel",
  authenticationMode: "credential-reference",
  credentialConfigured: true,
};
const reply = (request, body, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: {
      "x-request-id": request.headers.get("x-request-id"),
      "x-sentinel-csrf": "S".repeat(48),
    },
  });
async function run(handlers, action) {
  const server = setupServer(...handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "source-owner",
    onUnauthorized: () => {},
    requestId: () => `source-${++sequence}`,
  });
  try {
    await action(createSourceRegistrationHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("SOURCE-REGISTRY: maps UTC and safe source metadata; rejects credential leakage and duplicate identity", async () => {
  await run(
    [
      http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
        reply(request, { asOf: at(), items: [record] }),
      ),
    ],
    async (port) => {
      assert.deepEqual(await port.readSources(new AbortController().signal), {
        asOfMs: now,
        items: [record],
      });
    },
  );
  await run(
    [
      http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
        reply(request, { asOf: at(), items: [{ ...record, password: "must-not-return" }] }),
      ),
    ],
    async (port) => {
      await assert.rejects(
        port.readSources(new AbortController().signal),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
  await run(
    [
      http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
        reply(request, {
          asOf: at(),
          items: [{ ...record, credentialReference: "vault://must-not-return" }],
        }),
      ),
    ],
    async (port) => {
      await assert.rejects(
        port.readSources(new AbortController().signal),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
  for (const name of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"]) {
    await run(
      [
        http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
          reply(request, { asOf: at(), items: [{ ...record, name }] }),
        ),
      ],
      async (port) => {
        await assert.rejects(
          port.readSources(new AbortController().signal),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  }
  for (const endpoint of [
    "http://:80",
    "https://nacos.example.com:99999",
    "https://nacos.example.com:abc",
    "http://256.256.256.256",
    "http://1.2.3.999",
    "https://exa%mple.com",
    "http://[v1.invalid]",
    "https://example..com",
    "https://.",
    "https://%41.nacos.example.com",
  ]) {
    await run(
      [
        http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
          reply(request, { asOf: at(), items: [{ ...record, endpoint }] }),
        ),
      ],
      async (port) => {
        await assert.rejects(
          port.readSources(new AbortController().signal),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  }
});

test("SOURCE-CHECK: POST is a CSRF-protected read-only probe, with no idempotency key or credential echo", async () => {
  const input = {
    sourceId: record.id,
    expectedRevision: record.revision,
    source: {
      provider: "nacos",
      endpoint: record.endpoint,
      namespace: record.namespace,
      authentication: { mode: "credential-reference", reference: "vault://ops/nacos" },
    },
  };
  await run(
    [
      http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
        reply(request, { asOf: at(), items: [] }),
      ),
      http.post(`${origin}/api/v1/system/sources/check`, async ({ request }) => {
        assert.equal(request.headers.get("x-sentinel-csrf"), "S".repeat(48));
        assert.equal(request.headers.get("idempotency-key"), null);
        assert.deepEqual(await request.json(), input);
        return reply(request, {
          status: "reachable",
          checkedAt: at(),
          expiresAt: at(30_000),
          capabilities: ["read", "conditional-write", "watch"],
        });
      }),
    ],
    async (port) => {
      await port.readSources(new AbortController().signal);
      assert.deepEqual(await port.checkSource(input, new AbortController().signal), {
        status: "reachable",
        checkedAtMs: now,
        expiresAtMs: now + 30_000,
        capabilities: ["read", "conditional-write", "watch"],
      });
    },
  );
});

test("SOURCE-CHECK: rate-limited replies require a bounded retry delay", async () => {
  const input = {
    sourceId: null,
    expectedRevision: null,
    source: {
      provider: "nacos",
      endpoint: "https://nacos.example.com",
      namespace: "sentinel",
      authentication: { mode: "none" },
    },
  };
  for (const body of [
    { error: { code: "rate_limited", requestId: "source-1" } },
    { error: { code: "rate_limited", requestId: "source-1", retryAfterMs: 300_001 } },
  ]) {
    await run(
      [
        http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
          reply(request, { asOf: at(), items: [] }),
        ),
        http.post(`${origin}/api/v1/system/sources/check`, ({ request }) =>
          reply(
            request,
            { error: { ...body.error, requestId: request.headers.get("x-request-id") } },
            429,
          ),
        ),
      ],
      async (port) => {
        await port.readSources(new AbortController().signal);
        await assert.rejects(
          port.checkSource(input, new AbortController().signal),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  }
  await run(
    [
      http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
        reply(request, { asOf: at(), items: [] }),
      ),
      http.post(`${origin}/api/v1/system/sources/check`, ({ request }) =>
        reply(
          request,
          {
            error: {
              code: "rate_limited",
              requestId: request.headers.get("x-request-id"),
              retryAfterMs: 250,
            },
          },
          429,
        ),
      ),
    ],
    async (port) => {
      await port.readSources(new AbortController().signal);
      await assert.rejects(
        port.checkSource(input, new AbortController().signal),
        (error) => error.code === "rate_limited" && error.retryAfterMs === 250,
      );
    },
  );
});

test("SOURCE-CHECK-WIRE: UTF-16 bounds and nonblank credential identifiers reject before dispatch", async () => {
  let dispatches = 0;
  const validEndpoint = "https://例子.测试/nacos";
  assert.equal(ConfigurationEndpointSchema.parse(validEndpoint), validEndpoint);
  assert.equal(
    ConfigurationEndpointSchema.parse("http://[::ffff:192.0.2.1]"),
    "http://[::ffff:192.0.2.1]",
  );
  const base = () => ({
    sourceId: null,
    expectedRevision: null,
    source: {
      provider: "nacos",
      endpoint: "https://nacos.example.com",
      namespace: "sentinel",
      authentication: { mode: "none" },
    },
  });
  const invalid = [];
  const endpoint = base();
  endpoint.source.endpoint = `https://nacos.example.com/${"😀".repeat(1020)}`;
  invalid.push(endpoint);
  for (const invalidEndpoint of [
    " https://nacos.example.com",
    "https://nacos.example.com ",
    "https://nacos.example.com /nacos",
    "https://nacos.example.com\ufeff",
    "https://nacos.example.com\u0085",
    "https://nacos.example.com/\u001c",
    "http://:80",
    "https://nacos.example.com:99999",
    "https://nacos.example.com:abc",
    "http://256.256.256.256",
    "http://1.2.3.999",
    "https://exa%mple.com",
    "http://[v1.invalid]",
    "https://%41.nacos.example.com",
  ]) {
    const malformed = base();
    malformed.source.endpoint = invalidEndpoint;
    invalid.push(malformed);
  }
  const namespace = base();
  namespace.source.namespace = "😀".repeat(101);
  invalid.push(namespace);
  const datacenter = base();
  datacenter.source.provider = "consul";
  delete datacenter.source.namespace;
  datacenter.source.datacenter = "😀".repeat(101);
  invalid.push(datacenter);
  const reference = base();
  reference.source.authentication = {
    mode: "credential-reference",
    reference: "😀".repeat(257),
  };
  invalid.push(reference);
  const blankReference = base();
  blankReference.source.authentication = { mode: "credential-reference", reference: "\ufeff" };
  invalid.push(blankReference);
  const username = base();
  username.source.authentication = {
    mode: "direct",
    username: "😀".repeat(101),
    password: "synthetic-password",
  };
  invalid.push(username);
  const blankUsername = base();
  blankUsername.source.authentication = {
    mode: "direct",
    username: "\u001c",
    password: "synthetic-password",
  };
  invalid.push(blankUsername);
  const password = base();
  password.source.authentication = {
    mode: "direct",
    username: "operator",
    password: "😀".repeat(513),
  };
  invalid.push(password);
  const aclToken = base();
  aclToken.source.provider = "consul";
  delete aclToken.source.namespace;
  aclToken.source.datacenter = "dc1";
  aclToken.source.authentication = { mode: "direct", aclToken: "😀".repeat(513) };
  invalid.push(aclToken);

  await run(
    [
      http.post(`${origin}/api/v1/system/sources/check`, ({ request }) => {
        dispatches += 1;
        return reply(request, {});
      }),
    ],
    async (port) => {
      for (const input of invalid) {
        await assert.rejects(
          port.checkSource(input, new AbortController().signal),
          (error) => error.code === "console_request_invalid",
          `invalid endpoint should be rejected locally: ${input.source.endpoint}`,
        );
      }
      assert.equal(dispatches, 0);
    },
  );
});

test("SOURCE-CHECK-WIRE: source identity and expected revision are both present or both absent", async () => {
  const source = {
    provider: "nacos",
    endpoint: "https://nacos.example.com",
    namespace: "sentinel",
    authentication: { mode: "none" },
  };
  const validUnregistered = { sourceId: null, expectedRevision: null, source };
  const validRegistered = { sourceId: record.id, expectedRevision: record.revision, source };
  const invalid = [
    { sourceId: null, expectedRevision: record.revision, source },
    { sourceId: record.id, expectedRevision: null, source },
  ];
  assert.equal(SourceCheckInputSchema.safeParse(validUnregistered).success, true);
  assert.equal(SourceCheckInputSchema.safeParse(validRegistered).success, true);
  for (const input of invalid)
    assert.equal(SourceCheckInputSchema.safeParse(input).success, false);

  let dispatches = 0;
  await run(
    [
      http.post(`${origin}/api/v1/system/sources/check`, ({ request }) => {
        dispatches += 1;
        return reply(request, {});
      }),
    ],
    async (port) => {
      for (const input of invalid)
        await assert.rejects(
          port.checkSource(input, new AbortController().signal),
          (error) => error.code === "console_request_invalid",
        );
      assert.equal(dispatches, 0);
    },
  );
});

test("SOURCE-COMMAND: direct secret is write-only and keyed acknowledgement is correlated", async () => {
  const input = {
    kind: "register",
    requestKey: "source-op-create-1",
    name: "primary",
    source: {
      provider: "consul",
      endpoint: "https://consul.example.com",
      datacenter: "dc1",
      authentication: { mode: "direct", aclToken: "write-only-secret" },
    },
  };
  let writes = 0;
  await run(
    [
      http.get(`${origin}/api/v1/system/sources`, ({ request }) =>
        reply(request, { asOf: at(), items: [] }),
      ),
      http.post(`${origin}/api/v1/system/sources/commands`, async ({ request }) => {
        writes += 1;
        assert.equal(request.headers.get("idempotency-key"), input.requestKey);
        assert.equal(request.headers.get("x-sentinel-csrf"), "S".repeat(48));
        assert.deepEqual(await request.json(), input);
        return reply(
          request,
          {
            status: "completed",
            requestKey: input.requestKey,
            record: {
              id: "source-consul-one",
              revision: "source-rev-1",
              name: input.name,
              provider: "consul",
              endpoint: input.source.endpoint,
              datacenter: "dc1",
              authenticationMode: "direct",
              credentialConfigured: true,
            },
          },
          202,
        );
      }),
    ],
    async (port) => {
      await port.readSources(new AbortController().signal);
      assert.deepEqual(await port.mutateSource(input, new AbortController().signal), {
        status: "completed",
        requestKey: input.requestKey,
        record: {
          id: "source-consul-one",
          revision: "source-rev-1",
          name: input.name,
          provider: "consul",
          endpoint: input.source.endpoint,
          datacenter: "dc1",
          authenticationMode: "direct",
          credentialConfigured: true,
        },
      });
      assert.equal(writes, 1);
      await assert.rejects(
        port.mutateSource({ ...input, requestKey: "bad key" }, new AbortController().signal),
        (error) => error.code === "console_request_invalid",
      );
      for (const name of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"]) {
        await assert.rejects(
          port.mutateSource({ ...input, name }, new AbortController().signal),
          (error) => error.code === "console_request_invalid",
        );
      }
      assert.equal(writes, 1);
    },
  );
});

test("SOURCE-OPERATION: preserves pending/not-found uncertainty and never authorizes replay", async () => {
  const key = "source-op-unknown";
  await run(
    [
      http.get(`${origin}/api/v1/system/sources/operations/:requestKey`, ({ request, params }) => {
        assert.equal(params.requestKey, key);
        return reply(request, { status: "not_found", requestKey: key });
      }),
    ],
    async (port) => {
      assert.deepEqual(await port.readSourceOperation(key, new AbortController().signal), {
        status: "not-found",
        requestKey: key,
      });
    },
  );
});
