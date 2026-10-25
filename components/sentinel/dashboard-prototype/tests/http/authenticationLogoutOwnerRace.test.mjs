import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleAuthentication } from "../../src/app/api/consoleAuthentication";
import { createAccountManagementHttp } from "../../src/features/identity/api/accountManagementHttp";

const origin = "http://auth-logout-owner-race.test";
const anonymousCsrf = "G".repeat(48);
const sessionCsrf = "H".repeat(48);
const firstOwner = Object.freeze({
  accountId: "operator-first",
  username: "operator-first",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "epoch-first",
});

test("AUTH-LOGOUT-OWNER-RACE: pre-logout protected 401 cannot expire the confirmed anonymous owner", async () => {
  let current = null;
  let sequence = 0;
  let releaseStaleResponse;
  let signalStaleRequest;
  const staleRequestStarted = new Promise((resolve) => {
    signalStaleRequest = resolve;
  });
  const staleResponseGate = new Promise((resolve) => {
    releaseStaleResponse = resolve;
  });
  const requestIds = new Map();
  const paths = [];
  const server = setupServer(
    http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) => {
      const id = request.headers.get("x-request-id");
      paths.push("bootstrap");
      requestIds.set("bootstrap", [...(requestIds.get("bootstrap") ?? []), id]);
      return HttpResponse.json(
        { initialized: true },
        {
          headers: {
            "x-request-id": id,
            "x-sentinel-csrf": current ? sessionCsrf : anonymousCsrf,
          },
        },
      );
    }),
    http.get(`${origin}/api/v1/auth/me`, ({ request }) => {
      const id = request.headers.get("x-request-id");
      paths.push("me");
      requestIds.set("me", [...(requestIds.get("me") ?? []), id]);
      return HttpResponse.json(current, {
        headers: {
          "x-request-id": id,
          "x-sentinel-csrf": current ? sessionCsrf : anonymousCsrf,
        },
      });
    }),
    http.post(`${origin}/api/v1/auth/login`, ({ request }) => {
      const id = request.headers.get("x-request-id");
      paths.push("login");
      assert.equal(request.headers.get("x-sentinel-csrf"), anonymousCsrf);
      current = firstOwner;
      return HttpResponse.json(firstOwner, {
        headers: { "x-request-id": id, "x-sentinel-csrf": sessionCsrf },
      });
    }),
    http.get(`${origin}/api/v1/accounts/:accountId`, async ({ request }) => {
      const id = request.headers.get("x-request-id");
      paths.push("account-read");
      requestIds.set("account-read", id);
      signalStaleRequest();
      await staleResponseGate;
      return HttpResponse.json(
        { error: { code: "unauthenticated", requestId: id } },
        {
          status: 401,
          headers: { "x-request-id": id, "x-sentinel-csrf": anonymousCsrf },
        },
      );
    }),
    http.post(`${origin}/api/v1/auth/logout`, ({ request }) => {
      const id = request.headers.get("x-request-id");
      paths.push("logout");
      requestIds.set("logout", id);
      assert.equal(request.headers.get("x-sentinel-csrf"), sessionCsrf);
      current = null;
      return new HttpResponse(null, { status: 204, headers: { "x-request-id": id } });
    }),
  );
  server.listen({ onUnhandledRequest: "error" });
  const runtime = createConsoleAuthentication({
    baseUrl: origin,
    requestId: () => `logout-owner-${++sequence}`,
  });

  try {
    assert.deepEqual(await runtime.authentication.restore(), { kind: "anonymous" });
    await runtime.authentication.login({ username: firstOwner.username, password: "synthetic" });
    assert.equal(runtime.session.read().facts.identity.sessionEpoch, firstOwner.sessionEpoch);

    const accounts = createAccountManagementHttp(runtime.transport);
    const staleRead = accounts.readAccount("account-target", new AbortController().signal);
    const staleReadRejected = assert.rejects(
      staleRead,
      (error) => error.code === "unauthenticated" && error.requestId === "logout-owner-7",
    );
    await staleRequestStarted;

    await runtime.authentication.logout();
    assert.deepEqual(runtime.session.read(), {
      phase: "resolved",
      facts: { kind: "anonymous" },
    });
    assert.equal(runtime.authentication.getSnapshot().logout.status, "success");

    releaseStaleResponse();
    await staleReadRejected;

    assert.equal(requestIds.get("account-read"), "logout-owner-7");
    assert.equal(requestIds.get("logout"), "logout-owner-9");
    assert.notEqual(requestIds.get("account-read"), requestIds.get("logout"));
    assert.deepEqual(runtime.session.read(), {
      phase: "resolved",
      facts: { kind: "anonymous" },
    });
    assert.equal(runtime.authentication.getSnapshot().logout.status, "success");
    assert.deepEqual(paths.slice(-5), ["account-read", "bootstrap", "logout", "bootstrap", "me"]);
  } finally {
    releaseStaleResponse();
    runtime.dispose();
    server.close();
  }
});
