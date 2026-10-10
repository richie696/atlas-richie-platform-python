import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test } from "node:test";
import { setupServer } from "msw/node";
import {
  CONSOLE_ERROR_STATUS,
  CONSOLE_HEADER,
  ConsoleErrorSchema,
} from "../../src/core/api/protocol/common";
import { unmatchedConsoleApiHandler } from "../../src/core/api/runtime/consoleMockHandlers";

const origin = "http://unmatched-console-api.test";

test("MOCK-FAIL-CLOSED: an unimplemented Console operation returns a safe 503 without network passthrough", async () => {
  const server = setupServer(unmatchedConsoleApiHandler);
  server.listen({ onUnhandledRequest: "error" });
  try {
    const response = await fetch(`${origin}/api/v1/future-operation`, {
      method: "PATCH",
      headers: { [CONSOLE_HEADER.RequestId]: "unmatched-request-1" },
      body: "{}",
    });

    assert.equal(response.status, CONSOLE_ERROR_STATUS.dependency_unavailable);
    assert.equal(response.headers.get(CONSOLE_HEADER.RequestId), "unmatched-request-1");
    const body = await response.json();
    assert.equal(ConsoleErrorSchema.safeParse(body).success, true);
    assert.deepEqual(body, {
      error: { code: "dependency_unavailable", requestId: "unmatched-request-1" },
    });

    const apiRootResponse = await fetch(`${origin}/api/v1`, {
      headers: { [CONSOLE_HEADER.RequestId]: "unmatched-root-request" },
    });
    assert.equal(apiRootResponse.status, CONSOLE_ERROR_STATUS.dependency_unavailable);
    assert.equal(apiRootResponse.headers.get(CONSOLE_HEADER.RequestId), "unmatched-root-request");
  } finally {
    server.close();
  }
});

test("MOCK-FAIL-CLOSED: malformed correlation identifiers are not reflected", async () => {
  const server = setupServer(unmatchedConsoleApiHandler);
  server.listen({ onUnhandledRequest: "error" });
  try {
    const response = await fetch(`${origin}/api/v1/another-future-operation`, {
      headers: { [CONSOLE_HEADER.RequestId]: "not a valid request id" },
    });

    assert.equal(response.status, CONSOLE_ERROR_STATUS.dependency_unavailable);
    assert.equal(response.headers.get(CONSOLE_HEADER.RequestId), "mock-unmatched-request");
    const body = await response.json();
    assert.deepEqual(body, {
      error: { code: "dependency_unavailable", requestId: "mock-unmatched-request" },
    });
    assert.equal(JSON.stringify(body).includes("not a valid request id"), false);
  } finally {
    server.close();
  }
});

test("MOCK-FAIL-CLOSED: static assets remain outside the Console API fallback", async () => {
  const receivedPaths = [];
  const assetServer = createServer((request, response) => {
    receivedPaths.push(request.url);
    response.writeHead(200, { "content-type": "text/javascript" });
    response.end("asset");
  });
  await new Promise((resolve, reject) => {
    assetServer.once("error", reject);
    assetServer.listen(0, "127.0.0.1", resolve);
  });
  const address = assetServer.address();
  assert.ok(address && typeof address === "object");
  const assetOrigin = `http://127.0.0.1:${address.port}`;
  const mockServer = setupServer(unmatchedConsoleApiHandler);
  mockServer.listen({ onUnhandledRequest: "bypass" });
  try {
    const assetResponse = await fetch(`${assetOrigin}/assets/app.js`);

    assert.equal(assetResponse.status, 200);
    assert.equal(await assetResponse.text(), "asset");
    const apiResponse = await fetch(`${assetOrigin}/api/v1/future-operation`);
    assert.equal(apiResponse.status, CONSOLE_ERROR_STATUS.dependency_unavailable);
    assert.deepEqual(receivedPaths, ["/assets/app.js"]);
  } finally {
    mockServer.close();
    await new Promise((resolve, reject) => {
      assetServer.close((error) => (error ? reject(error) : resolve()));
    });
  }
});
