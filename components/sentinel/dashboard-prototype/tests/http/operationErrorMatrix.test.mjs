import assert from "node:assert/strict";
import { test } from "node:test";
import { http } from "msw/http";
import { setupServer } from "msw/node";
import { AppErrorKind } from "@richie696/react-framework";
import { CONSOLE_OPERATIONS } from "../../src/app/api/consoleContract";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { CONSOLE_ERROR_STATUS, CONSOLE_HEADER } from "../../src/core/api/protocol/common";
import { IDENTITY_ENDPOINTS } from "../../src/features/identity/api/identityEndpoints";

const origin = "http://operation-error-matrix.test";
const errorKindForStatus = (status) =>
  status === 401
    ? AppErrorKind.UNAUTHORIZED
    : status === 403
      ? AppErrorKind.FORBIDDEN
      : status === 429
        ? AppErrorKind.RATE_LIMITED
        : status >= 500
          ? AppErrorKind.SERVER
          : AppErrorKind.PROTOCOL;

test("HTTP-OPERATION-ERROR-MATRIX: every operation accepts only its declared safe HTTP errors", async () => {
  let activeError = null;
  let requestSequence = 0;
  let unauthorizedTransitions = 0;
  let errorCases = 0;
  const testedOperations = new Set();
  const server = setupServer(
    http.all(/\/api\/v\d+(?:\/.*)?$/, ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (activeError === null) {
        return Response.json(
          { initialized: false, setupAvailable: true, operatorAuthorized: false },
          {
            status: 200,
            headers: {
              [CONSOLE_HEADER.RequestId]: requestId,
              [CONSOLE_HEADER.Csrf]: "A".repeat(48),
            },
          },
        );
      }
      return Response.json(
        {
          error: {
            code: activeError.code,
            requestId,
            ...(activeError.code === "rate_limited" ? { retryAfterMs: 1_000 } : {}),
          },
        },
        {
          status: CONSOLE_ERROR_STATUS[activeError.code],
          headers: { [CONSOLE_HEADER.RequestId]: requestId },
        },
      );
    }),
  );
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "operation-error-owner",
    onUnauthorized: () => unauthorizedTransitions++,
    requestId: () => `operation-error-${++requestSequence}`,
  });

  try {
    const bootstrapOperation = CONSOLE_OPERATIONS.find(
      ({ endpoint }) => endpoint.url.path === IDENTITY_ENDPOINTS.Bootstrap.url.path,
    );
    assert.ok(bootstrapOperation, "the runtime registry includes bootstrap authorization setup");

    for (const operation of CONSOLE_OPERATIONS) {
      testedOperations.add(operation.operationId);
      for (const code of operation.endpoint.errors) {
        activeError = null;
        await transport.send(bootstrapOperation.endpoint, {
          signal: new AbortController().signal,
        });
        const status = CONSOLE_ERROR_STATUS[code];
        const beforeUnauthorized = unauthorizedTransitions;
        activeError = { code, ...(code === "rate_limited" ? { retryAfterMs: 1_000 } : {}) };
        const expectedRequestId = `operation-error-${requestSequence + 1}`;
        errorCases++;
        await assert.rejects(
          transport.send(operation.endpoint, {
            signal: new AbortController().signal,
            pathParams: operation.pathParameters.map((_, index) => `matrix-target-${index + 1}`),
            ...(operation.endpoint.idempotency === "required"
              ? { requestKey: `operation-key-${errorCases}` }
              : {}),
          }),
          (error) => {
            assert.equal(error.kind, errorKindForStatus(status), operation.operationId);
            assert.equal(error.status, status, operation.operationId);
            assert.equal(error.code, code, operation.operationId);
            assert.equal(error.requestId, expectedRequestId, operation.operationId);
            assert.equal(error.responseBody, undefined, operation.operationId);
            assert.equal(error.cause, undefined, operation.operationId);
            assert.equal(error.message, "Console request rejected", operation.operationId);
            return true;
          },
        );
        assert.equal(
          unauthorizedTransitions - beforeUnauthorized,
          code === "unauthenticated" && operation.endpoint.expireOnUnauthorized ? 1 : 0,
          operation.operationId,
        );
      }
    }

    assert.equal(testedOperations.size, CONSOLE_OPERATIONS.length);
    assert.ok(errorCases > 0);
  } finally {
    transport.dispose();
    server.close();
  }
});
