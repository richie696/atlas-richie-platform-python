import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { z } from "zod";
import { AppErrorKind, defineUrl, HttpMethod } from "@richie696/react-framework";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createConsoleServices } from "../../src/app/providers/consoleServices";
import { createObservationCatalogHttp } from "../../src/features/applications/api/catalogHttp";
import { createObservationCatalogResource } from "../../src/features/applications/application/catalogResource";
import { createCommandResource } from "../../src/shared/state/commandResource";
import { boundedResponse, withinJsonDepth } from "../../src/core/api/transport/boundedResponse";
import {
  CONSOLE_ERROR_STATUS,
  CONSOLE_WIRE_LIMIT,
  ConsoleErrorSchema,
  InventoryCoverageSchema,
  OpaqueIdentifierSchema,
  RequestKeySchema,
  UtcInstantSchema,
  instantToMilliseconds,
  millisecondsToInstant,
} from "../../src/core/api/protocol/common";
import "./identity.test.mjs";
import "./contract.test.mjs";
import "./account.test.mjs";
import "./accountIdentityMock.test.mjs";
import "./authenticationOwner.test.mjs";
import "./observation.test.mjs";
import "./fleetMock.test.mjs";
import "./instanceMock.test.mjs";
import "./realtimeMock.test.mjs";
import "./mockObservationConsistency.test.mjs";
import "./mockOperationCoverage.test.mjs";
import "./operationErrorMatrix.test.mjs";
import "./authorizationMatrix.test.mjs";
import "./instance.test.mjs";
import "./incident.test.mjs";
import "./incidentMock.test.mjs";
import "./systemObservation.test.mjs";
import "./catalog.test.mjs";
import "./ruleSet.test.mjs";
import "./ruleSetMock.test.mjs";
import "./sourceRegistration.test.mjs";
import "./sourceRegistrationMock.test.mjs";
import "./unmatchedConsoleApi.test.mjs";

const origin = "http://console-http.test",
  csrf = "A".repeat(48),
  otherCsrf = "B".repeat(48);
const payload = { value: 7 },
  schema = z.strictObject({ value: z.int().min(0).max(10) });
const endpoint = (path = "/api/v1/probe", overrides = {}) => ({
  url: defineUrl(path),
  response: schema,
  successStatus: 200,
  errors: ["unauthenticated", "forbidden", "conflict", "rate_limited", "service_unavailable"],
  command: false,
  idempotency: overrides.command ? "required" : "none",
  csrf: false,
  expireOnUnauthorized: true,
  ...overrides,
});
const call = (overrides = {}) => ({ signal: new AbortController().signal, ...overrides });
const response = (
  request,
  data = payload,
  { status = 200, token = csrf, correlation = request.headers.get("x-request-id") } = {},
) =>
  HttpResponse.json(data, {
    status,
    headers: { "x-request-id": correlation, ...(token ? { "x-sentinel-csrf": token } : {}) },
  });
const rejection = (request, code, status) =>
  response(
    request,
    { error: { code, requestId: request.headers.get("x-request-id") } },
    { status, token: null },
  );
async function withMock(handlers, run, overrides = {}) {
  const server = setupServer(...handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0,
    owner = "initial-owner",
    expires = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => owner,
    onUnauthorized: () => {
      expires++;
    },
    requestId: () => `request-${++sequence}`,
    ...overrides,
  });
  try {
    await run({
      transport,
      setOwner: (value) => {
        owner = value;
      },
      expires: () => expires,
      server,
    });
  } finally {
    transport.dispose();
    server.close();
  }
}
test("HTTP-WIRE: schemas are strict, bounded and exportable JSON; unknown inventory is not zero", () => {
  assert.equal(
    InventoryCoverageSchema.safeParse({ expected: null, inventorySource: null }).success,
    true,
  );
  for (const value of [
    { expected: 0, inventorySource: null },
    { expected: null, inventorySource: "fake" },
    { expected: 2, inventorySource: "valid", extra: 1 },
  ])
    assert.equal(InventoryCoverageSchema.safeParse(value).success, false);
  assert.equal(
    ConsoleErrorSchema.safeParse({
      error: { code: "forbidden", requestId: "request-1", message: "SECRET" },
    }).success,
    false,
  );
  assert.equal(RequestKeySchema.safeParse("secret\r\nheader").success, false);
  for (const identifier of ["\u001c", "\u0085", "\ufeff", "\u3000"])
    assert.equal(OpaqueIdentifierSchema.safeParse(identifier).success, false);
  assert.equal(OpaqueIdentifierSchema.safeParse("id\ufeff").success, true);
  assert.equal(OpaqueIdentifierSchema.safeParse("\ud800").success, false);
  assert.equal(OpaqueIdentifierSchema.safeParse("😀").success, true);
  assert.equal(UtcInstantSchema.safeParse("2026-10-07T00:00:00.000+09:00").success, false);
  assert.equal(UtcInstantSchema.safeParse("1970-01-01T00:00:00.000Z").success, true);
  assert.equal(UtcInstantSchema.safeParse("9999-12-31T23:59:59.999Z").success, true);
  assert.equal(UtcInstantSchema.safeParse("2026-02-30T10:00:45.456Z").success, false);
  assert.equal(UtcInstantSchema.safeParse("2100-02-29T10:00:45.456Z").success, false);
  assert.equal(UtcInstantSchema.safeParse("2000-02-29T10:00:45.456Z").success, true);
  assert.equal(instantToMilliseconds("2026-10-07T00:00:00.123Z"), 1791331200123);
  assert.equal(instantToMilliseconds("1970-01-01T00:00:00.000Z"), 0);
  assert.equal(instantToMilliseconds("9999-12-31T23:59:59.999Z"), 253402300799999);
  assert.equal(millisecondsToInstant(1791331200123), "2026-10-07T00:00:00.123Z");
  assert.equal(millisecondsToInstant(0), "1970-01-01T00:00:00.000Z");
  assert.equal(millisecondsToInstant(253402300799999), "9999-12-31T23:59:59.999Z");
  const json = z.toJSONSchema(ConsoleErrorSchema);
  assert.equal(json.additionalProperties, false);
  assert.equal(json.properties.error.additionalProperties, false);
});
test("APP-COMPOSITION: authentication and feature ports share one configured Console transport", async () => {
  const bootstrap = { initialized: false, setupAvailable: true, operatorAuthorized: false };
  await withMock(
    [http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) => response(request, bootstrap))],
    async ({ server }) => {
      const services = createConsoleServices({ mode: "mock", apiBaseUrl: origin });
      try {
        const access = await services.authentication.restore();
        assert.deepEqual(access, {
          kind: "uninitialized",
          setupAvailable: true,
          operatorAuthorized: false,
        });
        assert.equal(server.listHandlers().length, 1);
        assert.equal(typeof services.transport.send, "function");
        assert.equal(typeof services.authentication.login, "function");
      } finally {
        services.dispose();
      }
    },
  );
});
test("APPLICATION-CATALOG-EMPTY: MSW response crosses Console transport, HTTP mapper and resource classification", async () => {
  let requests = 0;
  await withMock(
    [
      http.get(`${origin}/api/v1/observation/catalog`, ({ request }) => {
        requests++;
        return response(request, {
          asOf: "2026-10-07T00:00:00.000Z",
          environments: [],
          applications: [],
        });
      }),
    ],
    async ({ transport }) => {
      const resource = createObservationCatalogResource(createObservationCatalogHttp(transport));
      try {
        const value = await resource.load(undefined);
        assert.equal(requests, 1);
        assert.deepEqual(value, { asOfMs: 1791331200000, environments: [], applications: [] });
        assert.equal(resource.getSnapshot().status, "empty");
        assert.deepEqual(resource.getSnapshot().data.applications, []);
      } finally {
        resource.dispose();
      }
    },
  );
});
test("HTTP-MSW: foundation URL encodes path identity/query; legacy localStorage cannot become authentication headers", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: { getItem: () => "PRIVATE-LEGACY-USER" },
  });
  let observed, outgoing;
  try {
    await withMock(
      [
        http.get(`${origin}/api/v1/probe/:id`, ({ request }) => {
          observed = request;
          return response(request);
        }),
      ],
      async ({ transport }) => {
        assert.deepEqual(
          await transport.send(
            endpoint("/api/v1/probe/{id}"),
            call({
              pathParams: ["资源/a?#"],
              query: { search: "中文 & x", page: 2, absent: null },
            }),
          ),
          payload,
        );
        const url = new URL(observed.url);
        assert.equal(url.pathname, "/api/v1/probe/%E8%B5%84%E6%BA%90%2Fa%3F%23");
        assert.equal(url.searchParams.get("search"), "中文 & x");
        assert.equal(url.searchParams.get("page"), "2");
        assert.equal(url.searchParams.has("absent"), false);
        for (const name of [
          "x-user-id",
          "x-device-id",
          "x-client-id",
          "x-client-timestamp",
          "x-gateway-protocol-version",
          "authorization",
        ])
          assert.equal(observed.headers.has(name), false, name);
        // Node interceptor normalizes its handler Request. Read actual foundation fetch input for Fetch policy evidence.
        assert.equal(outgoing.credentials, "include");
        assert.equal(outgoing.redirect, "error");
        assert.equal(outgoing.cache, "no-store");
        assert.equal(observed.headers.get("accept"), "application/json");
      },
      {
        fetch: (request) => {
          outgoing = request;
          return globalThis.fetch(request);
        },
      },
    );
  } finally {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else delete globalThis.localStorage;
  }
});
test("HTTP-CSRF: token stays private, comes from verified current response, and same command carries original idempotency key once", async () => {
  let writes = 0,
    observed;
  await withMock(
    [
      http.get(`${origin}/api/v1/probe`, ({ request }) => response(request)),
      http.post(`${origin}/api/v1/command`, async ({ request }) => {
        writes++;
        observed = request;
        assert.deepEqual(await request.json(), {
          requestKey: "command-one",
          password: "WRITE-ONLY-SECRET",
        });
        return response(request);
      }),
    ],
    async ({ transport }) => {
      const command = endpoint("/api/v1/command", {
        url: defineUrl("/api/v1/command", { method: HttpMethod.POST }),
        command: true,
        csrf: true,
      });
      await assert.rejects(
        transport.send(command, call({ requestKey: "command-one" })),
        (error) => error.kind === AppErrorKind.FORBIDDEN,
      );
      assert.equal(writes, 0);
      await transport.send(endpoint(), call());
      await transport.send(
        command,
        call({
          requestKey: "command-one",
          body: { requestKey: "command-one", password: "WRITE-ONLY-SECRET" },
        }),
      );
      assert.equal(observed.headers.get("x-sentinel-csrf"), csrf);
      assert.equal(observed.headers.get("idempotency-key"), "command-one");
      assert.equal(writes, 1);
      assert.equal(JSON.stringify(transport).includes(csrf), false);
      transport.clearCredentials();
      await assert.rejects(
        transport.send(command, call({ requestKey: "other-key" })),
        (error) => error.kind === AppErrorKind.FORBIDDEN,
      );
      assert.equal(writes, 1);
    },
  );
});
test("HTTP-ERROR: status/code/correlation are verified; password/provider message/body/cause never cross the boundary", async () => {
  for (const [code, status, kind] of [
    ["unauthenticated", 401, AppErrorKind.UNAUTHORIZED],
    ["forbidden", 403, AppErrorKind.FORBIDDEN],
    ["conflict", 409, AppErrorKind.PROTOCOL],
    ["rate_limited", 429, AppErrorKind.RATE_LIMITED],
    ["service_unavailable", 503, AppErrorKind.SERVER],
  ]) {
    await withMock(
      [http.get(`${origin}/api/v1/probe`, ({ request }) => rejection(request, code, status))],
      async ({ transport, expires }) => {
        await assert.rejects(transport.send(endpoint(), call()), (error) => {
          assert.equal(error.kind, kind);
          assert.equal(error.code, code);
          assert.equal(error.responseBody, undefined);
          assert.equal(error.cause, undefined);
          assert.doesNotMatch(error.message, /PRIVATE/);
          return true;
        });
        assert.equal(expires(), status === 401 ? 1 : 0);
      },
    );
  }
  await withMock(
    [
      http.get(`${origin}/api/v1/probe`, ({ request }) =>
        response(
          request,
          {
            error: {
              code: "forbidden",
              requestId: request.headers.get("x-request-id"),
              message: "PRIVATE-PASSWORD",
            },
          },
          { status: 403 },
        ),
      ),
    ],
    async ({ transport }) => {
      await assert.rejects(
        transport.send(endpoint(), call()),
        (error) =>
          error.code === "console_response_invalid" &&
          error.responseBody === undefined &&
          !JSON.stringify(error).includes("PRIVATE"),
      );
    },
  );
});
test("HTTP-ERROR-MATRIX: every declared Console error code is accepted only with its canonical status and is safely projected", async () => {
  const expectedKind = (status) =>
    status === 401
      ? AppErrorKind.UNAUTHORIZED
      : status === 403
        ? AppErrorKind.FORBIDDEN
        : status === 429
          ? AppErrorKind.RATE_LIMITED
          : status >= 500
            ? AppErrorKind.SERVER
            : AppErrorKind.PROTOCOL;
  const declaredErrors = Object.keys(CONSOLE_ERROR_STATUS);

  for (const [code, status] of Object.entries(CONSOLE_ERROR_STATUS)) {
    await withMock(
      [
        http.get(`${origin}/api/v1/probe`, ({ request }) =>
          HttpResponse.json(
            {
              error: {
                code,
                requestId: request.headers.get("x-request-id"),
                ...(code === "validation_failed"
                  ? { issues: [{ field: "quota", reason: "out_of_range" }] }
                  : {}),
                ...(code === "rate_limited" ? { retryAfterMs: 1250 } : {}),
              },
            },
            {
              status,
              headers: { "x-request-id": request.headers.get("x-request-id") },
            },
          ),
        ),
      ],
      async ({ transport, expires }) => {
        await assert.rejects(
          transport.send(endpoint("/api/v1/probe", { errors: declaredErrors }), call()),
          (error) => {
            assert.equal(error.kind, expectedKind(status), code);
            assert.equal(error.status, status, code);
            assert.equal(error.code, code, code);
            assert.equal(error.requestId, "request-1", code);
            assert.equal(error.responseBody, undefined, code);
            assert.equal(error.cause, undefined, code);
            assert.equal(error.message, "Console request rejected", code);
            assert.equal(error.retryAfterMs, code === "rate_limited" ? 1250 : undefined, code);
            return true;
          },
        );
        assert.equal(expires(), status === 401 ? 1 : 0, code);
      },
    );
  }
});
test("HTTP-UNKNOWN: malformed command ACK locks the actual command resource and never retries a potentially committed mutation", async () => {
  let writes = 0;
  await withMock(
    [
      http.post(`${origin}/api/v1/command`, ({ request }) => {
        writes++;
        return response(request, { value: 7, unexpected: "PRIVATE-ACK" });
      }),
    ],
    async ({ transport }) => {
      const command = endpoint("/api/v1/command", {
        url: defineUrl("/api/v1/command", { method: HttpMethod.POST }),
        command: true,
      });
      const resource = createCommandResource((body, signal) =>
        transport.send(command, { body, signal, requestKey: "original-key" }),
      );
      try {
        await assert.rejects(resource.run({ requestKey: "original-key" }));
        assert.equal(resource.getSnapshot().status, "result-unknown");
        await assert.rejects(resource.run({ requestKey: "new-key" }));
        assert.equal(writes, 1);
        assert.equal(resource.getSnapshot().error.code, "console_response_invalid");
      } finally {
        resource.dispose();
      }
    },
  );
});
test("HTTP-INGRESS: wrong content type, correlation, status, JSON and oversized bodies reject without echoing bytes or retry", async () => {
  const scenarios = [
    (request) =>
      new HttpResponse("PRIVATE-HTML", {
        headers: {
          "content-type": "text/html",
          "x-request-id": request.headers.get("x-request-id"),
        },
      }),
    (request) => response(request, payload, { correlation: "foreign-request" }),
    (request) => response(request, payload, { status: 201 }),
    (request) =>
      new HttpResponse("{PRIVATE-BROKEN", {
        headers: {
          "content-type": "application/json",
          "x-request-id": request.headers.get("x-request-id"),
        },
      }),
    (request) => response(request, { value: "x".repeat(CONSOLE_WIRE_LIMIT.BodyBytes) }),
  ];
  for (const handle of scenarios) {
    let reads = 0;
    await withMock(
      [
        http.get(`${origin}/api/v1/probe`, ({ request }) => {
          reads++;
          return handle(request);
        }),
      ],
      async ({ transport }) => {
        await assert.rejects(
          transport.send(endpoint(), call()),
          (error) =>
            error.code === "console_response_invalid" &&
            error.responseBody === undefined &&
            !error.message.includes("PRIVATE"),
        );
        assert.equal(reads, 1);
      },
    );
  }
});
test("HTTP-OWNER: delayed old 401 cannot expire the next owner or replace its CSRF token", async () => {
  let release, oldStarted;
  const started = new Promise((resolve) => {
    oldStarted = resolve;
  });
  let reads = 0,
    observed;
  await withMock(
    [
      http.get(`${origin}/api/v1/probe`, async ({ request }) => {
        reads++;
        if (reads === 1) {
          oldStarted();
          return new Promise((resolve) => {
            release = () => resolve(rejection(request, "unauthenticated", 401));
          });
        }
        return response(request, payload, { token: otherCsrf });
      }),
      http.post(`${origin}/api/v1/command`, ({ request }) => {
        observed = request;
        return response(request, payload, { token: otherCsrf });
      }),
    ],
    async ({ transport, setOwner, expires }) => {
      const old = transport.send(endpoint(), call());
      await started;
      setOwner("next-owner");
      await transport.send(endpoint(), call());
      release();
      await assert.rejects(old);
      assert.equal(expires(), 0);
      await transport.send(
        endpoint("/api/v1/command", {
          url: defineUrl("/api/v1/command", { method: HttpMethod.POST }),
          command: true,
          csrf: true,
        }),
        call({ requestKey: "next-key" }),
      );
      assert.equal(observed.headers.get("x-sentinel-csrf"), otherCsrf);
    },
  );
});
test("HTTP-CANCEL: ignored old response cannot produce data after caller cancellation or install credentials", async () => {
  let release, started;
  const start = new Promise((resolve) => {
    started = resolve;
  });
  await withMock(
    [],
    async ({ transport }) => {
      const controller = new AbortController(),
        pending = transport.send(endpoint(), call({ signal: controller.signal }));
      await start;
      controller.abort();
      release();
      await assert.rejects(pending, (error) => error.kind === AppErrorKind.CANCELLED);
      await assert.rejects(
        transport.send(
          endpoint("/api/v1/command", {
            url: defineUrl("/api/v1/command", { method: HttpMethod.POST }),
            command: true,
            csrf: true,
          }),
          call({ requestKey: "one" }),
        ),
        (error) => error.kind === AppErrorKind.FORBIDDEN,
      );
    },
    {
      fetch: (request) =>
        new Promise((resolve) => {
          started();
          release = () =>
            resolve(
              new Response(JSON.stringify(payload), {
                headers: {
                  "content-type": "application/json",
                  "x-request-id": request.headers.get("x-request-id"),
                  "x-sentinel-csrf": csrf,
                },
              }),
            );
        }),
    },
  );
});
test("HTTP-TIMEOUT: foundation timeout is bounded; unknown write does not become retryable rejection", async () => {
  let writes = 0,
    aborts = 0,
    requestSignal;
  await withMock(
    [],
    async ({ transport }) => {
      let watchdog;
      try {
        const bounded = await Promise.race([
          assert
            .rejects(
              transport.send(
                endpoint("/api/v1/command", {
                  url: defineUrl("/api/v1/command", { method: HttpMethod.POST }),
                  command: true,
                }),
                call({ requestKey: "original-key" }),
              ),
              (error) => error.kind === AppErrorKind.TIMEOUT,
            )
            .then(() => true),
          new Promise((resolve) => {
            watchdog = setTimeout(() => resolve(false), 1_000);
          }),
        ]);
        assert.equal(bounded, true, "Console deadline must settle a dispatched request");
        assert.equal(writes, 1);
        assert.equal(aborts, 1, "The timed-out request signal must abort exactly once");
        assert.equal(requestSignal?.aborted, true);
      } finally {
        if (watchdog) clearTimeout(watchdog);
      }
    },
    {
      timeoutMs: 25,
      fetch: (request) => {
        writes++;
        requestSignal = request.signal;
        request.signal.addEventListener("abort", () => aborts++, { once: true });
        return new Promise((resolve, reject) => {
          const abort = () => reject(new Error("PRIVATE-TIMEOUT"));
          if (request.signal.aborted) abort();
          else request.signal.addEventListener("abort", abort, { once: true });
        });
      },
    },
  );
});
test("HTTP-BOUNDS: stream exceeds limit before content length is known; JSON depth is checked independently", async () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(CONSOLE_WIRE_LIMIT.BodyBytes + 1));
      controller.close();
    },
  });
  await assert.rejects(
    boundedResponse(
      new Response(stream, { headers: { "content-type": "application/json" } }),
      new AbortController().signal,
    ),
  );
  let value = 0;
  for (let index = 0; index < CONSOLE_WIRE_LIMIT.JsonDepth + 1; index++) value = { next: value };
  assert.equal(withinJsonDepth(value), false);
  assert.equal(withinJsonDepth({ value: 7 }), true);
});
test("HTTP-204: accepts an empty response stream but rejects any response bytes", async () => {
  const emptyResponse = {
    status: 204,
    body: new ReadableStream({ start: (controller) => controller.close() }),
  };
  assert.equal(await boundedResponse(emptyResponse, new AbortController().signal), emptyResponse);

  const bodyResponse = {
    status: 204,
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("unexpected"));
        controller.close();
      },
    }),
  };
  await assert.rejects(
    boundedResponse(bodyResponse, new AbortController().signal),
    /Unexpected empty-response body/,
  );
});
test("HTTP-AUTH-FAILURE: malformed current 401 still clears current authorization; login rejection does not expire another identity", async () => {
  await withMock(
    [
      http.get(
        `${origin}/api/v1/probe`,
        ({ request }) =>
          new HttpResponse("PRIVATE-MALFORMED", {
            status: 401,
            headers: {
              "content-type": "text/plain",
              "x-request-id": request.headers.get("x-request-id"),
            },
          }),
      ),
    ],
    async ({ transport, expires }) => {
      await assert.rejects(transport.send(endpoint(), call()));
      assert.equal(expires(), 1);
    },
  );
  await withMock(
    [
      http.post(`${origin}/api/v1/auth/login`, ({ request }) =>
        rejection(request, "unauthenticated", 401),
      ),
    ],
    async ({ transport, expires }) => {
      await assert.rejects(
        transport.send(
          endpoint("/api/v1/auth/login", {
            url: defineUrl("/api/v1/auth/login", { method: HttpMethod.POST }),
            command: true,
            idempotency: "none",
            expireOnUnauthorized: false,
          }),
          call(),
        ),
      );
      assert.equal(expires(), 0);
    },
  );
});
test("HTTP-UTF8: mislabeled encoding and malformed UTF-8 never become silently repaired strings", async () => {
  const stringSchema = z.strictObject({ value: z.string() });
  for (const handle of [
    (request) =>
      new Response('{"value":"bad"}', {
        headers: {
          "content-type": "application/json;charset=iso-8859-1",
          "x-request-id": request.headers.get("x-request-id"),
        },
      }),
    (request) =>
      new Response(new Uint8Array([123, 34, 118, 97, 108, 117, 101, 34, 58, 34, 255, 34, 125]), {
        headers: {
          "content-type": "application/json",
          "x-request-id": request.headers.get("x-request-id"),
        },
      }),
  ]) {
    await withMock(
      [],
      async ({ transport }) => {
        await assert.rejects(
          transport.send(endpoint("/api/v1/probe", { response: stringSchema }), call()),
          (error) => error.code === "console_response_invalid",
        );
      },
      { fetch: async (request) => handle(request) },
    );
  }
});
test("HTTP-PATH: dot-segment identities and endpoint escape never dispatch outside the Console API", async () => {
  let reads = 0;
  await withMock(
    [],
    async ({ transport }) => {
      for (const [path, pathParams] of [
        ["/api/v1/probe/{id}", [".."]],
        ["/api/v1/../../outside", []],
      ])
        await assert.rejects(transport.send(endpoint(path), call({ pathParams })));
      assert.equal(reads, 0);
    },
    {
      fetch: async (request) => {
        reads++;
        return response(request);
      },
    },
  );
});
test("HTTP-DISPOSE: disposal aborts owned requests and a late response cannot populate another transport", async () => {
  let release, started, signal;
  const start = new Promise((resolve) => {
    started = resolve;
  });
  await withMock(
    [],
    async ({ transport }) => {
      const pending = transport.send(endpoint(), call());
      await start;
      transport.dispose();
      assert.equal(signal.aborted, true);
      release();
      await assert.rejects(pending, (error) => error.kind === AppErrorKind.CANCELLED);
      await assert.rejects(
        transport.send(endpoint(), call()),
        (error) => error.kind === AppErrorKind.CANCELLED,
      );
    },
    {
      fetch: (request) => {
        signal = request.signal;
        started();
        return new Promise((resolve) => {
          release = () => resolve(response(request));
        });
      },
    },
  );
});
test(
  "HTTP-LIVE-CONTROLLED: same foundation transport reaches an isolated loopback HTTP endpoint, not a synthetic Port",
  { timeout: 15_000 },
  async () => {
    let successRequest, failureRequest, resolveCancelReceived, resolveCancelClosed;
    const cancelReceived = new Promise((resolve) => (resolveCancelReceived = resolve));
    const cancelClosed = new Promise((resolve) => (resolveCancelClosed = resolve));
    const server = createServer((incoming, outgoing) => {
      const requestUrl = new URL(incoming.url ?? "/", "http://127.0.0.1");
      if (requestUrl.searchParams.get("case") === "cancel") {
        outgoing.once("close", resolveCancelClosed);
        resolveCancelReceived();
        return;
      }
      if (requestUrl.searchParams.get("case") === "unavailable") {
        failureRequest = incoming;
        outgoing.writeHead(503, {
          "content-type": "application/json",
          "x-request-id": incoming.headers["x-request-id"],
        });
        outgoing.end(
          JSON.stringify({
            error: {
              code: "service_unavailable",
              requestId: incoming.headers["x-request-id"],
            },
          }),
        );
        return;
      }
      successRequest = incoming;
      outgoing.writeHead(200, {
        "content-type": "application/json",
        "x-request-id": incoming.headers["x-request-id"],
      });
      outgoing.end(JSON.stringify(payload));
    });
    try {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          server.off("listening", onListening);
          server.off("error", onError);
          reject(new Error("Loopback HTTP listener did not become ready within 5 seconds"));
        }, 5_000);
        const onListening = () => {
          clearTimeout(timer);
          server.off("error", onError);
          resolve();
        };
        const onError = (error) => {
          clearTimeout(timer);
          server.off("listening", onListening);
          reject(error);
        };
        server.once("listening", onListening);
        server.once("error", onError);
        server.listen(0, "127.0.0.1");
      });
    } catch (error) {
      server.closeAllConnections();
      throw error;
    }
    const address = server.address(),
      transport = createConsoleTransport({
        baseUrl: `http://127.0.0.1:${address.port}`,
        owner: () => "real-http-owner",
        onUnauthorized: () => {},
      });
    try {
      assert.deepEqual(await transport.send(endpoint(), call({ query: { page: 2 } })), payload);
      assert.equal(successRequest.url, "/api/v1/probe?page=2");
      assert.ok(successRequest.headers["x-request-id"]);
      assert.equal(successRequest.headers.authorization, undefined);
      assert.equal(successRequest.headers["x-user-id"], undefined);

      await assert.rejects(
        transport.send(endpoint(), call({ query: { case: "unavailable" } })),
        (error) => {
          assert.equal(error.status, 503);
          assert.equal(error.code, "service_unavailable");
          assert.equal(error.requestId, failureRequest.headers["x-request-id"]);
          return true;
        },
      );

      const controller = new AbortController();
      const cancelled = transport.send(
        endpoint(),
        call({ query: { case: "cancel" }, signal: controller.signal }),
      );
      await cancelReceived;
      controller.abort();
      await assert.rejects(cancelled, (error) => error.kind === AppErrorKind.CANCELLED);
      assert.equal(
        await Promise.race([
          cancelClosed.then(() => true),
          new Promise((resolve) => setTimeout(() => resolve(false), 1_000)),
        ]),
        true,
        "aborting the live request closes the controlled server response",
      );
    } finally {
      transport.dispose();
      server.closeAllConnections();
      await new Promise((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
    }
  },
);
