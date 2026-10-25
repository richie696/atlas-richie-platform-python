import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleAuthentication } from "../../src/app/api/consoleAuthentication";
import { createOwnPasswordHttp } from "../../src/features/identity/api/ownPasswordHttp";
import { createAccountManagementHttp } from "../../src/features/identity/api/accountManagementHttp";
import { PASSWORD_MAX_LENGTH } from "../../src/features/identity/model/passwordPolicy";

const origin = "http://auth-owner.test",
  anonymousCsrf = "E".repeat(48),
  sessionCsrf = "F".repeat(48),
  owner = {
    accountId: "admin-one",
    username: "admin",
    roleId: "admin",
    capabilities: ["metrics:view", "rules:write"],
    sessionEpoch: "server-epoch-one",
  };
const signal = () => new AbortController().signal;
const respond = (request, body, csrf, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: { "x-request-id": request.headers.get("x-request-id"), "x-sentinel-csrf": csrf },
  });
test("OWN-PASSWORD-INPUT: oversized password is rejected before transport dispatch", async () => {
  let calls = 0;
  const password = createOwnPasswordHttp({
    async send() {
      calls++;
      return { sessionDisposition: "reauthenticate" };
    },
  });
  await assert.rejects(
    password.changeOwnPassword(
      {
        currentPassword: "PRIVATE-CURRENT",
        newPassword: "x".repeat(PASSWORD_MAX_LENGTH + 1),
      },
      signal(),
    ),
  );
  assert.equal(calls, 0);
});
async function runOwned(extra, run) {
  let current = null,
    sequence = 0,
    writes = 0;
  const paths = [];
  const server = setupServer(
    ...extra,
    http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) => {
      paths.push("bootstrap");
      return respond(request, { initialized: true }, current ? sessionCsrf : anonymousCsrf);
    }),
    http.get(`${origin}/api/v1/auth/me`, ({ request }) => {
      paths.push("me");
      return respond(request, current, current ? sessionCsrf : anonymousCsrf);
    }),
    http.post(`${origin}/api/v1/auth/login`, ({ request }) => {
      paths.push("login");
      writes++;
      assert.equal(request.headers.get("x-sentinel-csrf"), anonymousCsrf);
      current = owner;
      return respond(request, owner, sessionCsrf);
    }),
    http.post(`${origin}/api/v1/auth/logout`, ({ request }) => {
      paths.push("logout");
      writes++;
      assert.equal(request.headers.get("x-sentinel-csrf"), sessionCsrf);
      current = null;
      return new HttpResponse(null, {
        status: 204,
        headers: { "x-request-id": request.headers.get("x-request-id") },
      });
    }),
  );
  server.listen({ onUnhandledRequest: "error" });
  const runtime = createConsoleAuthentication({
    baseUrl: origin,
    requestId: () => `auth-owner-${++sequence}`,
  });
  try {
    await run(runtime, { paths, writes: () => writes });
  } finally {
    runtime.dispose();
    server.close();
  }
}
test("AUTH-APP-OWNER: login/read-back changes server epoch without losing current CSRF; password and logout remain authorized", async () => {
  let passwordWrites = 0;
  await runOwned(
    [
      http.post(`${origin}/api/v1/auth/password`, async ({ request }) => {
        passwordWrites++;
        assert.equal(request.headers.get("x-sentinel-csrf"), sessionCsrf);
        assert.deepEqual(await request.json(), {
          currentPassword: "PRIVATE-CURRENT",
          newPassword: "PRIVATE-NEW-PASSWORD",
        });
        return respond(request, { sessionDisposition: "reauthenticate" }, sessionCsrf);
      }),
    ],
    async (runtime, evidence) => {
      assert.deepEqual(await runtime.authentication.restore(), { kind: "anonymous" });
      await runtime.authentication.login({ username: "admin", password: "PRIVATE-LOGIN-PASSWORD" });
      assert.equal(runtime.session.read().facts.identity.sessionEpoch, owner.sessionEpoch);
      await createOwnPasswordHttp(runtime.transport).changeOwnPassword(
        { currentPassword: "PRIVATE-CURRENT", newPassword: "PRIVATE-NEW-PASSWORD" },
        signal(),
      );
      assert.equal(passwordWrites, 1);
      await runtime.authentication.logout();
      assert.deepEqual(runtime.session.read(), { phase: "resolved", facts: { kind: "anonymous" } });
      assert.equal(evidence.writes(), 2);
      assert.deepEqual(evidence.paths, [
        "bootstrap",
        "me",
        "bootstrap",
        "login",
        "bootstrap",
        "me",
        "bootstrap",
        "logout",
        "bootstrap",
        "me",
      ]);
    },
  );
});
test("OWN-PASSWORD-ERROR: wrong current password is a correctable rejection and keeps the verified session", async () => {
  await runOwned(
    [
      http.post(`${origin}/api/v1/auth/password`, async ({ request }) => {
        const body = await request.json();
        if (body.currentPassword === "PRIVATE-WRONG-CURRENT")
          return respond(
            request,
            {
              error: {
                code: "current_password_invalid",
                requestId: request.headers.get("x-request-id"),
              },
            },
            sessionCsrf,
            400,
          );
        return respond(request, { sessionDisposition: "reauthenticate" }, sessionCsrf);
      }),
    ],
    async (runtime) => {
      await runtime.authentication.restore();
      await runtime.authentication.login({ username: "admin", password: "PRIVATE-LOGIN-PASSWORD" });

      await assert.rejects(
        createOwnPasswordHttp(runtime.transport).changeOwnPassword(
          {
            currentPassword: "PRIVATE-WRONG-CURRENT",
            newPassword: "PRIVATE-NEW-PASSWORD",
          },
          signal(),
        ),
        (error) => error.code === "current_password_invalid" && error.status === 400,
      );
      assert.equal(runtime.session.read().phase, "resolved");

      await createOwnPasswordHttp(runtime.transport).changeOwnPassword(
        {
          currentPassword: "PRIVATE-CURRENT",
          newPassword: "PRIVATE-NEW-PASSWORD",
        },
        signal(),
      );
      assert.equal(runtime.session.read().phase, "resolved");
    },
  );
});
test("AUTH-APP-OWNER: a late old authenticated 401 cannot expire restored login or poison its next command nonce", async () => {
  let release, started;
  const entered = new Promise((resolve) => {
    started = resolve;
  });
  await runOwned(
    [
      http.get(`${origin}/api/v1/accounts/:id`, async ({ request }) => {
        started();
        await new Promise((resolve) => {
          release = resolve;
        });
        return respond(
          request,
          { error: { code: "unauthenticated", requestId: request.headers.get("x-request-id") } },
          anonymousCsrf,
          401,
        );
      }),
      http.post(`${origin}/api/v1/auth/password`, ({ request }) => {
        assert.equal(request.headers.get("x-sentinel-csrf"), sessionCsrf);
        return respond(request, { sessionDisposition: "reauthenticate" }, sessionCsrf);
      }),
    ],
    async (runtime) => {
      await runtime.authentication.restore();
      await runtime.authentication.login({ username: "admin", password: "PRIVATE-LOGIN-PASSWORD" });
      const read = createAccountManagementHttp(runtime.transport).readAccount(
        "old-target",
        signal(),
      );
      const rejection = assert.rejects(read);
      await entered;
      runtime.authentication.expire();
      assert.equal(runtime.session.read().phase, "expired");
      await runtime.authentication.restore();
      assert.equal(runtime.session.read().facts.identity.sessionEpoch, owner.sessionEpoch);
      release();
      await rejection;
      assert.equal(runtime.session.read().phase, "resolved");
      await createOwnPasswordHttp(runtime.transport).changeOwnPassword(
        { currentPassword: "PRIVATE-CURRENT", newPassword: "PRIVATE-NEW-PASSWORD" },
        signal(),
      );
    },
  );
});
test("AUTH-APP-OWNER: denied intent does not rotate credentials of the current verified session; current malformed 401 still expires it", async () => {
  let rejected = false;
  await runOwned(
    [
      http.get(`${origin}/api/v1/accounts/:id`, ({ request }) => {
        rejected = true;
        return respond(request, { unsafeMessage: "PRIVATE" }, sessionCsrf, 401);
      }),
      http.post(`${origin}/api/v1/auth/password`, ({ request }) => {
        assert.equal(request.headers.get("x-sentinel-csrf"), sessionCsrf);
        return respond(request, { sessionDisposition: "reauthenticate" }, sessionCsrf);
      }),
    ],
    async (runtime) => {
      await runtime.authentication.restore();
      await runtime.authentication.login({ username: "admin", password: "PRIVATE-LOGIN-PASSWORD" });
      await assert.rejects(
        runtime.authentication.login({ username: "admin", password: "PRIVATE" }),
      );
      await createOwnPasswordHttp(runtime.transport).changeOwnPassword(
        { currentPassword: "PRIVATE-CURRENT", newPassword: "PRIVATE-NEW-PASSWORD" },
        signal(),
      );
      await assert.rejects(
        createAccountManagementHttp(runtime.transport).readAccount("current-target", signal()),
      );
      assert.equal(rejected, true);
      assert.equal(runtime.session.read().phase, "expired");
      await assert.rejects(
        createOwnPasswordHttp(runtime.transport).changeOwnPassword(
          { currentPassword: "PRIVATE-CURRENT", newPassword: "PRIVATE-NEW-PASSWORD" },
          signal(),
        ),
        (error) => error.code === "csrf_failed",
      );
      assert.equal(JSON.stringify(runtime.authentication.getSnapshot()).includes("PRIVATE"), false);
    },
  );
});
test("AUTH-APP-OWNER F4.23: session authority failure hides stale identity and confirmed 401 expires it", async () => {
  let current = null;
  let sessionMode = "valid";
  let sequence = 0;
  const server = setupServer(
    http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
      respond(request, { initialized: true }, current ? sessionCsrf : anonymousCsrf),
    ),
    http.get(`${origin}/api/v1/auth/me`, ({ request }) => {
      if (sessionMode === "unavailable")
        return respond(
          request,
          {
            error: { code: "service_unavailable", requestId: request.headers.get("x-request-id") },
          },
          current ? sessionCsrf : anonymousCsrf,
          503,
        );
      if (sessionMode === "expired") {
        current = null;
        return respond(
          request,
          { error: { code: "unauthenticated", requestId: request.headers.get("x-request-id") } },
          anonymousCsrf,
          401,
        );
      }
      return respond(request, current, current ? sessionCsrf : anonymousCsrf);
    }),
    http.post(`${origin}/api/v1/auth/login`, ({ request }) => {
      assert.equal(request.headers.get("x-sentinel-csrf"), anonymousCsrf);
      current = owner;
      return respond(request, owner, sessionCsrf);
    }),
  );
  server.listen({ onUnhandledRequest: "error" });
  const runtime = createConsoleAuthentication({
    baseUrl: origin,
    requestId: () => `auth-session-owner-${++sequence}`,
  });
  try {
    assert.deepEqual(await runtime.authentication.restore(), { kind: "anonymous" });
    await runtime.authentication.login({ username: "admin", password: "PRIVATE-LOGIN-PASSWORD" });
    assert.deepEqual(runtime.session.read(), {
      phase: "resolved",
      facts: { kind: "authenticated", identity: owner },
    });

    sessionMode = "unavailable";
    await assert.rejects(runtime.authentication.revalidateAccess());
    assert.equal(runtime.session.read().phase, "unavailable");
    assert.doesNotMatch(JSON.stringify(runtime.session.read()), /admin-one|PRIVATE-LOGIN-PASSWORD/);

    sessionMode = "expired";
    await assert.rejects(runtime.authentication.revalidateAccess());
    assert.equal(runtime.session.read().phase, "expired");
    assert.doesNotMatch(JSON.stringify(runtime.session.read()), /admin-one|PRIVATE-LOGIN-PASSWORD/);

    sessionMode = "valid";
    assert.deepEqual(await runtime.authentication.restore(), { kind: "anonymous" });
    assert.deepEqual(runtime.session.read(), { phase: "resolved", facts: { kind: "anonymous" } });
  } finally {
    runtime.dispose();
    server.close();
  }
});
