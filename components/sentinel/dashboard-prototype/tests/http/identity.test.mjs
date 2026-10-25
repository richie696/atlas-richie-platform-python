import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { z } from "zod";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import {
  createIdentityHttp,
  createInitializationHttp,
  createBootstrapAuthorizationHttp,
} from "../../src/features/identity/api/identityHttp";
import { createAuthenticationWorkflow } from "../../src/features/identity/application/authenticationWorkflow";
import { createInitializationWorkflow } from "../../src/features/identity/application/initializationWorkflow";
import { createBootstrapAuthorizationWorkflow } from "../../src/features/identity/application/bootstrapAuthorizationWorkflow";
import { createIdentityMockHandlers } from "../../src/features/identity/mock";
import { createAppConsoleMockAssembly } from "../../src/app/api/mockConsoleHandlers";
import { createConsoleAuthentication } from "../../src/app/api/consoleAuthentication";
import {
  MOCK_IDENTITY_SCENARIO,
  MOCK_BOOTSTRAP_PROFILE,
  createMockIdentityScenario,
} from "../../src/app/api/mockIdentityScenario";
import {
  SessionIdentitySchema,
  SetupSubmissionSchema,
  LoginInputSchema,
} from "../../src/features/identity/api/identityWire";
import { ConfigurationSourceInputSchema } from "../../src/shared/api/configurationSourceWire";
const origin = "http://identity-http.test",
  csrf = "C".repeat(48),
  account = {
    accountId: "account-one",
    username: "operator",
    roleId: "admin",
    capabilities: ["metrics:view", "rules:write"],
    sessionEpoch: "opaque-session-one",
  };
const json = (request, body, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: { "x-request-id": request.headers.get("x-request-id"), "x-sentinel-csrf": csrf },
  });
async function withTransport(handlers, run) {
  const server = setupServer(...handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "identity-http-owner",
    onUnauthorized: () => {},
    requestId: () => `identity-${++sequence}`,
  });
  try {
    await run(transport);
  } finally {
    transport.dispose();
    server.close();
  }
}
test("IDENTITY-WIRE: login usernames use ECMAScript whitespace semantics", () => {
  for (const username of ["operator\u0085", "operator\u001c"]) {
    assert.equal(
      LoginInputSchema.safeParse({ username, password: "synthetic-password" }).success,
      true,
    );
  }
  for (const username of ["\u00a0", "\ufeff"]) {
    assert.equal(
      LoginInputSchema.safeParse({ username, password: "synthetic-password" }).success,
      false,
    );
  }
});
test("IDENTITY-MOCK: initialized bootstrap uses the strict production wire and restores the confirmed mock session", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "true"],
    ["sentinel.mock.role", "admin"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  try {
    await withTransport(createIdentityMockHandlers(MOCK_IDENTITY_SCENARIO), async (transport) => {
      const workflow = createAuthenticationWorkflow(createIdentityHttp(transport));
      try {
        assert.deepEqual(await workflow.restore(), {
          kind: "authenticated",
          identity: {
            accountId: "account-admin",
            username: "admin",
            roleId: "admin",
            capabilities: ["metrics:view", "rules:write"],
            sessionEpoch: "mock-session-admin",
          },
        });
        values.set("sentinel.mock.initialized", "false");
        assert.deepEqual(await workflow.restore(), {
          kind: "uninitialized",
          setupAvailable: true,
          operatorAuthorized: false,
        });
      } finally {
        workflow.dispose();
      }
    });
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("IDENTITY-APP-MOCK: admin and viewer repeated login/logout cycles clear the app mock session", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "true"],
    ["sentinel.mock.role", "anonymous"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  const server = setupServer(...createAppConsoleMockAssembly().handlers);
  server.listen({ onUnhandledRequest: "error" });
  const runtime = createConsoleAuthentication({
    baseUrl: origin,
    requestId: (() => {
      let sequence = 0;
      return () => `identity-app-${++sequence}`;
    })(),
  });
  try {
    for (const roleId of ["admin", "view"]) {
      values.set("sentinel.mock.role", roleId);
      const restored = await runtime.authentication.restore();
      assert.equal(restored.kind, "authenticated");
      assert.equal(restored.identity.roleId, roleId);

      await runtime.authentication.logout();

      assert.deepEqual(runtime.session.read(), { phase: "resolved", facts: { kind: "anonymous" } });
      assert.equal(values.get("sentinel.mock.role"), "anonymous");

      const credentials = {
        username: roleId === "admin" ? "admin" : "viewer",
        password: "synthetic-password",
      };
      const loggedIn = await runtime.authentication.login(credentials);
      assert.equal(loggedIn.roleId, roleId);
      assert.equal(values.get("sentinel.mock.role"), roleId);
      await runtime.authentication.logout();

      assert.deepEqual(runtime.session.read(), { phase: "resolved", facts: { kind: "anonymous" } });
      assert.equal(values.get("sentinel.mock.role"), "anonymous");
    }
  } finally {
    runtime.dispose();
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("IDENTITY-APP-MOCK: a definitive unauthenticated logout rejection is not converted into an unknown write", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "true"],
    ["sentinel.mock.role", "admin"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  const server = setupServer(...createAppConsoleMockAssembly().handlers);
  server.listen({ onUnhandledRequest: "error" });
  const runtime = createConsoleAuthentication({ baseUrl: origin });
  try {
    assert.equal((await runtime.authentication.restore()).kind, "authenticated");
    server.use(
      http.post(`${origin}/api/v1/auth/logout`, ({ request }) => {
        values.set("sentinel.mock.role", "anonymous");
        return HttpResponse.json(
          {
            error: {
              code: "unauthenticated",
              requestId: request.headers.get("x-request-id"),
            },
          },
          {
            status: 401,
            headers: { "x-request-id": request.headers.get("x-request-id") },
          },
        );
      }),
    );

    await assert.rejects(
      runtime.authentication.logout(),
      (error) => error.code === "unauthenticated" && error.status === 401,
    );
    assert.equal(runtime.authentication.getSnapshot().logout.status, "error");
    assert.equal(runtime.session.read().phase, "unavailable");
    assert.deepEqual(await runtime.authentication.inspectSession(), { kind: "anonymous" });
  } finally {
    runtime.dispose();
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("IDENTITY-HTTP: bootstrap invalid_request remains a typed HTTP 400", async () => {
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        json(
          request,
          { error: { code: "invalid_request", requestId: request.headers.get("x-request-id") } },
          400,
        ),
      ),
    ],
    async (transport) => {
      const identity = createIdentityHttp(transport);
      await assert.rejects(identity.readBootstrap(new AbortController().signal), (error) => {
        assert.equal(error.code, "invalid_request");
        assert.equal(error.status, 400);
        return true;
      });
    },
  );
});

test("IDENTITY-MOCK: first-run profile starts locked and grants setup access only after HTTP authorization", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  try {
    const scenario = createMockIdentityScenario(MOCK_BOOTSTRAP_PROFILE.FirstRun);
    await withTransport(createIdentityMockHandlers(scenario), async (transport) => {
      const initialization = createInitializationWorkflow(createInitializationHttp(transport));
      const authorization = createBootstrapAuthorizationWorkflow(
        createBootstrapAuthorizationHttp(transport),
      );
      try {
        assert.deepEqual(await initialization.restore(), {
          initialized: false,
          setupAvailable: true,
          operatorAuthorized: false,
        });
        assert.deepEqual(await authorization.restore(), { kind: "open", authorized: false });
        await authorization.authorize("SYNTHETIC-ONE-TIME-CODE-0123456789ABC");
        assert.deepEqual(await authorization.restore(), { kind: "open", authorized: true });
        assert.equal(values.get("sentinel.mock.operator-authorized"), "true");
        assert.equal(values.has("sentinel.mock.role"), false);
      } finally {
        initialization.dispose();
        authorization.dispose();
      }
    });
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
test("BOOTSTRAP-AUTH single-use authorization blocks duplicate writes and reads until authoritative confirmation", async () => {
  let releaseConfirmation;
  let signalConfirmationStarted;
  const confirmationStarted = new Promise((resolve) => {
    signalConfirmationStarted = resolve;
  });
  const confirmation = new Promise((resolve) => {
    releaseConfirmation = resolve;
  });
  let authorizationWrites = 0;
  const workflow = createBootstrapAuthorizationWorkflow({
    async readGate(_signal, { forceRefresh }) {
      if (!forceRefresh) return { kind: "open", authorized: false };
      signalConfirmationStarted();
      return confirmation;
    },
    async authorize() {
      authorizationWrites++;
    },
  });

  try {
    await workflow.restore();
    const initialAuthorization = workflow.authorize("SYNTHETIC-ONE-TIME-CODE-0123456789ABC");
    await confirmationStarted;

    await assert.rejects(
      workflow.authorize("SYNTHETIC-SECOND-CODE"),
      (error) => error.kind === "duplicate",
    );
    assert.throws(
      () => workflow.restore(true),
      (error) => error.kind === "duplicate",
    );
    await assert.rejects(workflow.inspect(), (error) => error.kind === "duplicate");
    assert.equal(
      authorizationWrites,
      1,
      "the one-time write must not be repeated while reading back",
    );
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-ONE-TIME-CODE/);

    releaseConfirmation({ kind: "open", authorized: true });
    await initialAuthorization;
    assert.deepEqual(workflow.getSnapshot().gate.data, { kind: "open", authorized: true });
  } finally {
    workflow.dispose();
  }
});
test("BOOTSTRAP-AUTH a successful one-time write stays unknown until an inspection confirms the gate", async () => {
  let forcedReads = 0;
  let authorizationWrites = 0;
  const workflow = createBootstrapAuthorizationWorkflow({
    async readGate(_signal, { forceRefresh }) {
      if (!forceRefresh) return { kind: "open", authorized: false };
      forcedReads++;
      if (forcedReads === 1) throw new Error("synthetic read-back failure");
      if (forcedReads === 2) throw new Error("synthetic inspection failure");
      if (forcedReads === 3) return { kind: "open", authorized: false };
      return { kind: "open", authorized: true };
    },
    async authorize() {
      authorizationWrites++;
    },
  });

  try {
    await workflow.restore();
    await assert.rejects(workflow.authorize("SYNTHETIC-ONE-TIME-CODE-0123456789ABC"));
    assert.equal(workflow.getSnapshot().command.status, "result-unknown");
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-ONE-TIME-CODE/);
    await assert.rejects(
      workflow.authorize("SYNTHETIC-SECOND-CODE"),
      (error) => error.kind === "duplicate",
    );
    assert.equal(authorizationWrites, 1, "a successful one-time write must never be replayed");

    await assert.rejects(workflow.inspect());
    assert.equal(workflow.getSnapshot().command.status, "result-unknown");
    await assert.rejects(
      workflow.authorize("SYNTHETIC-THIRD-CODE"),
      (error) => error.kind === "duplicate",
    );
    assert.equal(authorizationWrites, 1, "a failed inspection must not unlock authorization");

    await workflow.inspect();
    assert.deepEqual(workflow.getSnapshot().gate.data, { kind: "open", authorized: false });
    assert.equal(workflow.getSnapshot().command.status, "result-unknown");
    await assert.rejects(
      workflow.authorize("SYNTHETIC-FOURTH-CODE"),
      (error) => error.kind === "duplicate",
    );
    assert.equal(authorizationWrites, 1);

    await workflow.inspect();
    assert.deepEqual(workflow.getSnapshot().gate.data, { kind: "open", authorized: true });
    assert.equal(workflow.getSnapshot().command.status, "idle");
    assert.equal(authorizationWrites, 1);
  } finally {
    workflow.dispose();
  }
});
test("BOOTSTRAP-AUTH an unknown authorization write cannot be replayed before gate inspection", async () => {
  let authorized = false;
  let authorizationWrites = 0;
  const workflow = createBootstrapAuthorizationWorkflow({
    async readGate(_signal, { forceRefresh }) {
      if (!forceRefresh) return { kind: "open", authorized: false };
      return { kind: "open", authorized };
    },
    async authorize() {
      authorizationWrites++;
      throw new AppError(AppErrorKind.NETWORK, "synthetic response loss");
    },
  });

  try {
    await workflow.restore();
    await assert.rejects(
      workflow.authorize("SYNTHETIC-ONE-TIME-CODE-0123456789ABC"),
      (error) => error.kind === AppErrorKind.NETWORK,
    );
    assert.equal(workflow.getSnapshot().command.status, "result-unknown");
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-ONE-TIME-CODE/);
    await assert.rejects(
      workflow.authorize("SYNTHETIC-SECOND-CODE"),
      (error) => error.kind === AppErrorKind.DUPLICATE,
    );
    assert.equal(authorizationWrites, 1, "an unknown one-time write must not be replayed");

    await workflow.inspect();
    assert.equal(workflow.getSnapshot().command.status, "result-unknown");
    await assert.rejects(
      workflow.authorize("SYNTHETIC-THIRD-CODE"),
      (error) => error.kind === AppErrorKind.DUPLICATE,
    );
    assert.equal(authorizationWrites, 1, "an unauthorized inspection does not clear uncertainty");

    authorized = true;
    await workflow.inspect();
    assert.deepEqual(workflow.getSnapshot().gate.data, { kind: "open", authorized: true });
    assert.equal(workflow.getSnapshot().command.status, "idle");
    assert.equal(authorizationWrites, 1);
  } finally {
    workflow.dispose();
  }
});
test("IDENTITY-MOCK: completing first-run initialization closes setup but does not create a login session", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "false"],
    ["sentinel.mock.operator-authorized", "true"],
    ["sentinel.mock.role", "anonymous"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  const input = {
    database: {
      kind: "postgresql",
      host: "postgres.synthetic.internal",
      port: 5432,
      database: "sentinel",
      username: "sentinel",
      password: "SYNTHETIC-DB-PASSWORD",
    },
    admin: { username: "synthetic-admin", password: "SYNTHETIC-ADMIN-PASSWORD" },
    source: {
      provider: "nacos",
      endpoint: "https://nacos.synthetic.internal",
      namespace: "synthetic",
      authentication: { mode: "none" },
    },
  };
  try {
    await withTransport(createIdentityMockHandlers(MOCK_IDENTITY_SCENARIO), async (transport) => {
      const initialization = createInitializationWorkflow(
        createInitializationHttp(transport),
        () => "synthetic-setup-no-auto-login",
      );
      const authentication = createAuthenticationWorkflow(createIdentityHttp(transport));
      try {
        assert.equal((await initialization.restore()).initialized, false);
        assert.equal((await initialization.initialize(input)).status, "ready");
        assert.equal(values.get("sentinel.mock.initialized"), "true");
        assert.equal(values.get("sentinel.mock.role"), "anonymous");
        assert.deepEqual(await authentication.restore(), { kind: "anonymous" });
      } finally {
        initialization.dispose();
        authentication.dispose();
      }
    });
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("IDENTITY-MOCK: initialization header/body idempotency mismatch is a 409 without closing setup", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "false"],
    ["sentinel.mock.operator-authorized", "true"],
    ["sentinel.mock.role", "anonymous"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  const server = setupServer(...createIdentityMockHandlers(MOCK_IDENTITY_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  try {
    const body = JSON.stringify({
      requestKey: "setup-original-key",
      input: {
        database: { kind: "sqlite" },
        admin: { username: "synthetic-admin", password: "SYNTHETIC-ADMIN-PASSWORD" },
        source: {
          provider: "nacos",
          endpoint: "https://nacos.synthetic.internal",
          namespace: "synthetic",
          authentication: { mode: "none" },
        },
      },
    });
    const send = (headers) =>
      fetch(`${origin}/api/v1/system/bootstrap/initialize`, {
        method: "POST",
        headers: { "content-type": "application/json", ...headers },
        body,
      });
    const missingKey = await send({
      "x-request-id": "bootstrap-idempotency-missing",
      "x-sentinel-csrf": csrf,
    });
    assert.equal(missingKey.status, 400);
    assert.deepEqual(await missingKey.json(), {
      error: { code: "invalid_request", requestId: "bootstrap-idempotency-missing" },
    });
    const response = await send({
      "x-request-id": "bootstrap-idempotency-mismatch",
      "x-sentinel-csrf": csrf,
      "idempotency-key": "different-setup-key",
    });
    assert.equal(response.status, 409);
    assert.deepEqual(await response.json(), {
      error: { code: "idempotency_conflict", requestId: "bootstrap-idempotency-mismatch" },
    });
    assert.equal(values.get("sentinel.mock.initialized"), "false");
    assert.equal(values.get("sentinel.mock.operator-authorized"), "true");
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
test("IDENTITY-MOCK: connection checks expose one transient 503, recover on the next request, and never retain credentials", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "false"],
    ["sentinel.mock.operator-authorized", "true"],
    ["sentinel.mock.setup.database-check-failure", "fail-once"],
    ["sentinel.mock.setup.source-check-failure", "fail-once"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  const database = {
    kind: "postgresql",
    host: "db.synthetic.internal",
    port: 5432,
    database: "sentinel",
    username: "synthetic-user",
    password: "SYNTHETIC-DB-CHECK-SECRET",
  };
  const source = {
    provider: "consul",
    endpoint: "https://consul.synthetic.internal",
    datacenter: "synthetic-dc",
    authentication: { mode: "direct", aclToken: "SYNTHETIC-CONSUL-CHECK-SECRET" },
  };
  try {
    await withTransport(createIdentityMockHandlers(MOCK_IDENTITY_SCENARIO), async (transport) => {
      const workflow = createInitializationWorkflow(
        createInitializationHttp(transport),
        () => "synthetic-setup-request",
      );
      try {
        assert.equal((await workflow.restore()).initialized, false);
        for (const [check, secret, snapshotKey] of [
          [() => workflow.checkDatabase(database), "SYNTHETIC-DB-CHECK-SECRET", "databaseCheck"],
          [() => workflow.checkSource(source), "SYNTHETIC-CONSUL-CHECK-SECRET", "sourceCheck"],
        ]) {
          const failed = check();
          assert.equal(workflow.getSnapshot()[snapshotKey].status, "loading");
          assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), new RegExp(secret));
          await assert.rejects(failed, (error) => error.status === 503);
          assert.equal(workflow.getSnapshot()[snapshotKey].status, "error");
          assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), new RegExp(secret));
          assert.deepEqual(await check(), { status: "reachable" });
          assert.equal(workflow.getSnapshot()[snapshotKey].status, "ready");
          assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), new RegExp(secret));
        }
        assert.equal((await workflow.restore()).initialized, false);
      } finally {
        workflow.dispose();
      }
      assert.equal(values.has("sentinel.mock.setup.database-check-failure"), false);
      assert.equal(values.has("sentinel.mock.setup.source-check-failure"), false);
      assert.doesNotMatch(JSON.stringify([...values]), /SYNTHETIC-(DB|CONSUL)-CHECK-SECRET/);
    });
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
test("IDENTITY-MOCK: only documented demo identities with the synthetic password receive their fixed role", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "true"],
    ["sentinel.mock.role", "anonymous"],
  ]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  try {
    await withTransport(createIdentityMockHandlers(MOCK_IDENTITY_SCENARIO), async (transport) => {
      for (const [credentials, expectedRole] of [
        [{ username: "admin", password: "synthetic-password" }, "admin"],
        [{ username: "viewer", password: "synthetic-password" }, "view"],
        [{ username: "unknown-operator", password: "synthetic-password" }, null],
        [{ username: "__proto__", password: "synthetic-password" }, null],
        [{ username: "admin", password: "incorrect-password" }, null],
      ]) {
        values.set("sentinel.mock.role", "anonymous");
        const workflow = createAuthenticationWorkflow(createIdentityHttp(transport));
        try {
          assert.deepEqual(await workflow.restore(), { kind: "anonymous" });
          if (expectedRole) {
            const loggedIn = await workflow.login(credentials);
            assert.equal(loggedIn.roleId, expectedRole);
            assert.equal(
              loggedIn.accountId,
              expectedRole === "admin" ? "account-admin" : "account-view",
            );
            assert.equal(loggedIn.username, expectedRole === "admin" ? "admin" : "viewer");
            assert.equal(values.get("sentinel.mock.role"), expectedRole);
            assert.equal((await workflow.restore()).identity.accountId, loggedIn.accountId);
          } else {
            await assert.rejects(workflow.login(credentials), (error) => {
              assert.equal(error.status, 401);
              assert.equal(error.code, "unauthenticated");
              return true;
            });
            assert.equal(values.get("sentinel.mock.role"), "anonymous");
          }
        } finally {
          workflow.dispose();
        }
      }
      assert.equal([...values.values()].includes("synthetic-password"), false);
    });
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
test("IDENTITY-HTTP: actual authentication workflow restores anonymous, logs in/read-backs, then logs out/read-backs through HTTP", async () => {
  let authenticated = false,
    writes = 0,
    me = 0;
  const paths = [];
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) => {
        paths.push("bootstrap");
        return json(request, { initialized: true });
      }),
      http.get(`${origin}/api/v1/auth/me`, ({ request }) => {
        me++;
        paths.push("me");
        return json(request, authenticated ? account : null);
      }),
      http.post(`${origin}/api/v1/auth/login`, async ({ request }) => {
        paths.push("login");
        writes++;
        assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
        assert.equal(request.headers.has("idempotency-key"), false);
        assert.deepEqual(await request.json(), {
          username: "operator",
          password: "PRIVATE-LOGIN-PASSWORD",
        });
        authenticated = true;
        return json(request, account);
      }),
      http.post(`${origin}/api/v1/auth/logout`, ({ request }) => {
        paths.push("logout");
        writes++;
        assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
        authenticated = false;
        return new HttpResponse(null, {
          status: 204,
          headers: { "x-request-id": request.headers.get("x-request-id") },
        });
      }),
    ],
    async (transport) => {
      const workflow = createAuthenticationWorkflow(createIdentityHttp(transport));
      try {
        assert.deepEqual(await workflow.restore(), { kind: "anonymous" });
        assert.deepEqual(
          await workflow.login({ username: " operator ", password: "PRIVATE-LOGIN-PASSWORD" }),
          account,
        );
        assert.equal(workflow.getSnapshot().access.facts.kind, "authenticated");
        assert.equal(me, 2);
        await workflow.logout();
        assert.equal(workflow.getSnapshot().access.facts.kind, "anonymous");
        assert.equal(writes, 2);
        assert.equal(me, 3);
        assert.deepEqual(paths, [
          "bootstrap",
          "me",
          "login",
          "bootstrap",
          "me",
          "logout",
          "bootstrap",
          "me",
        ]);
        assert.equal(
          JSON.stringify(workflow.getSnapshot()).includes("PRIVATE-LOGIN-PASSWORD"),
          false,
        );
      } finally {
        workflow.dispose();
      }
    },
  );
});
test("IDENTITY-HTTP F4.22: credential rejection stays anonymous and a decoded 429 cooldown blocks dispatch", async () => {
  let loginCalls = 0;
  let now = 1_000;
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        json(request, { initialized: true }),
      ),
      http.get(`${origin}/api/v1/auth/me`, ({ request }) => json(request, null)),
      http.post(`${origin}/api/v1/auth/login`, ({ request }) => {
        loginCalls++;
        const status = loginCalls === 2 ? 429 : 401;
        const code = status === 429 ? "rate_limited" : "unauthenticated";
        return HttpResponse.json(
          {
            error: {
              code,
              requestId: request.headers.get("x-request-id"),
              ...(status === 429 ? { retryAfterMs: 1_500 } : {}),
            },
          },
          {
            status,
            headers: { "x-request-id": request.headers.get("x-request-id") },
          },
        );
      }),
    ],
    async (transport) => {
      const workflow = createAuthenticationWorkflow(createIdentityHttp(transport), undefined, {
        clock: () => now,
      });
      try {
        assert.deepEqual(await workflow.restore(), { kind: "anonymous" });

        await assert.rejects(
          workflow.login({ username: "operator", password: "PRIVATE-LOGIN-PASSWORD" }),
          (error) => error.status === 401 && error.code === "unauthenticated",
        );
        assert.equal(workflow.getSnapshot().login.status, "error");
        assert.deepEqual(workflow.getSnapshot().access.facts, { kind: "anonymous" });
        workflow.clearLoginFailure();

        await assert.rejects(
          workflow.login({ username: "operator", password: "PRIVATE-LOGIN-PASSWORD" }),
          (error) =>
            error.status === 429 && error.code === "rate_limited" && error.retryAfterMs === 1_500,
        );
        assert.equal(workflow.getLoginRetryAfterMs(), 1_500);
        assert.deepEqual(workflow.getSnapshot().access.facts, { kind: "anonymous" });
        assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-LOGIN-PASSWORD/);

        now += 1_499;
        await assert.rejects(
          workflow.login({ username: "operator", password: "CORRECTED-SECRET" }),
          (error) => error.code === "rate_limited" && error.retryAfterMs === 1,
        );
        assert.equal(loginCalls, 2, "the workflow must enforce the decoded deadline before HTTP");

        now += 1;
        await assert.rejects(
          workflow.login({ username: "operator", password: "CORRECTED-SECRET" }),
          (error) => error.status === 401 && error.code === "unauthenticated",
        );
        assert.equal(loginCalls, 3);
        assert.deepEqual(workflow.getSnapshot().access.facts, { kind: "anonymous" });
      } finally {
        workflow.dispose();
      }
    },
  );
});
test("IDENTITY-HTTP: secret-bearing malformed login ACK stays unknown; inspection confirms session without a second login", async () => {
  let authenticated = false,
    writes = 0;
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        json(request, { initialized: true }),
      ),
      http.get(`${origin}/api/v1/auth/me`, ({ request }) =>
        json(request, authenticated ? account : null),
      ),
      http.post(`${origin}/api/v1/auth/login`, ({ request }) => {
        writes++;
        authenticated = true;
        return json(request, { ...account, password: "PRIVATE-RESPONSE-SECRET" });
      }),
    ],
    async (transport) => {
      const workflow = createAuthenticationWorkflow(createIdentityHttp(transport));
      try {
        await workflow.restore();
        await assert.rejects(
          workflow.login({ username: "operator", password: "PRIVATE-LOGIN-PASSWORD" }),
        );
        assert.equal(workflow.getSnapshot().login.status, "result-unknown");
        await assert.rejects(
          workflow.login({ username: "operator", password: "PRIVATE-LOGIN-PASSWORD" }),
        );
        assert.equal(writes, 1);
        assert.equal(
          JSON.stringify(workflow.getSnapshot()).includes("PRIVATE-RESPONSE-SECRET"),
          false,
        );
        assert.equal((await workflow.inspectSession()).kind, "authenticated");
        assert.equal(writes, 1);
      } finally {
        workflow.dispose();
      }
    },
  );
});
test("IDENTITY-WIRE: view cannot acquire write capability; duplicate permissions and read credentials fail closed", async () => {
  for (const value of [
    { ...account, roleId: "view" },
    { ...account, capabilities: ["metrics:view", "metrics:view"] },
    { ...account, cookie: "PRIVATE" },
  ])
    await withTransport(
      [http.get(`${origin}/api/v1/auth/me`, ({ request }) => json(request, value))],
      async (transport) => {
        await assert.rejects(
          createIdentityHttp(transport).readSession(new AbortController().signal),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
  const schema = z.toJSONSchema(SessionIdentitySchema);
  assert.equal(schema.additionalProperties, false);
  assert.equal("password" in schema.properties, false);
  assert.equal("cookie" in schema.properties, false);
});
test("BOOTSTRAP-HTTP: operator grant remains distinct, source/database checks do not initialize, original command key is preserved", async () => {
  let authorized = false,
    initialized = false,
    checks = 0,
    writes = 0,
    received;
  const input = {
    database: {
      kind: "mysql",
      host: "mysql.internal",
      port: 3306,
      database: "sentinel",
      username: "sentinel",
      password: "PRIVATE-DB",
    },
    admin: { username: "admin", password: "PRIVATE-ADMIN-PASSWORD" },
    source: {
      provider: "consul",
      endpoint: "http://consul.internal:8500",
      datacenter: "dc-one",
      authentication: { mode: "direct", aclToken: "PRIVATE-CONSUL" },
    },
  };
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        json(
          request,
          initialized
            ? { initialized: true }
            : { initialized: false, setupAvailable: true, operatorAuthorized: authorized },
        ),
      ),
      http.post(`${origin}/api/v1/system/bootstrap/authorize`, async ({ request }) => {
        assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
        assert.deepEqual(await request.json(), {
          operatorCode: "PRIVATE-OPERATOR-CODE-0123456789ABC",
        });
        authorized = true;
        return json(request, { authorized: true });
      }),
      http.post(`${origin}/api/v1/system/bootstrap/authorize-local`, async ({ request }) => {
        assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
        assert.deepEqual(await request.json(), {});
        authorized = true;
        return json(request, { authorized: true });
      }),
      ...["database-check", "source-check"].map((name) =>
        http.post(`${origin}/api/v1/system/bootstrap/${name}`, async ({ request }) => {
          assert.equal(authorized, true);
          assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
          checks++;
          await request.json();
          return json(request, { status: "reachable" });
        }),
      ),
      http.post(`${origin}/api/v1/system/bootstrap/initialize`, async ({ request }) => {
        assert.equal(authorized, true);
        writes++;
        assert.equal(request.headers.get("idempotency-key"), "setup-original");
        received = await request.json();
        initialized = true;
        return json(request, {
          status: "completed",
          requestKey: "setup-original",
          operationId: "setup-one",
        });
      }),
      http.get(`${origin}/api/v1/system/bootstrap/operations/:key`, ({ request, params }) =>
        json(request, { status: "completed", requestKey: params.key, operationId: "setup-one" }),
      ),
    ],
    async (transport) => {
      const operator = createBootstrapAuthorizationHttp(transport),
        setup = createInitializationHttp(transport),
        signal = new AbortController().signal;
      assert.deepEqual(await operator.readGate(signal), { kind: "open", authorized: false });
      await operator.authorizeLocal(signal);
      assert.deepEqual(await operator.readGate(signal), { kind: "open", authorized: true });
      assert.deepEqual(await setup.checkDatabase(input.database, signal), { status: "reachable" });
      assert.deepEqual(await setup.checkSource(input.source, signal), { status: "reachable" });
      assert.equal(writes, 0);
      assert.equal(checks, 2);
      assert.deepEqual(await setup.initialize({ requestKey: "setup-original", input }, signal), {
        status: "completed",
        requestKey: "setup-original",
        operationId: "setup-one",
      });
      assert.deepEqual(received, { requestKey: "setup-original", input });
      assert.deepEqual(await operator.readGate(signal), { kind: "closed" });
      assert.equal((await setup.readInitialization("setup-original", signal)).status, "completed");
      assert.equal(writes, 1);
    },
  );
});
test("BOOTSTRAP-AUTH-WIRE: operator code matches deployment syntax before transport dispatch", async () => {
  let dispatched = 0;
  await withTransport(
    [
      http.post(`${origin}/api/v1/system/bootstrap/authorize`, ({ request }) => {
        dispatched++;
        return json(request, { authorized: true });
      }),
    ],
    async (transport) => {
      const operator = createBootstrapAuthorizationHttp(transport);
      for (const code of [
        "x".repeat(31),
        `${"x".repeat(32)}🌋`,
        ` ${"x".repeat(32)}`,
        `${"x".repeat(32)}\ufeff`,
        "x".repeat(1025),
      ]) {
        await assert.rejects(
          operator.authorize(code, new AbortController().signal),
          (error) => error.code === "console_request_invalid",
        );
      }
    },
  );
  assert.equal(dispatched, 0);
});
test("BOOTSTRAP-AUTH-WIRE: local setup authorization sends no operator code", async () => {
  let received;
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        json(request, {
          initialized: false,
          setupAvailable: true,
          operatorAuthorized: false,
        }),
      ),
      http.post(`${origin}/api/v1/system/bootstrap/authorize-local`, async ({ request }) => {
        received = await request.json();
        return json(request, { authorized: true });
      }),
    ],
    async (transport) => {
      const operator = createBootstrapAuthorizationHttp(transport);
      await operator.readGate(new AbortController().signal);
      await operator.authorizeLocal(new AbortController().signal);
    },
  );
  assert.deepEqual(received, {});
});
test("BOOTSTRAP-DATABASE-WIRE: database check rejects non-scalar and over-bound fields before dispatch", async () => {
  let dispatched = 0;
  await withTransport(
    [
      http.post(`${origin}/api/v1/system/bootstrap/database-check`, ({ request }) => {
        dispatched++;
        return json(request, { status: "reachable" });
      }),
    ],
    async (transport) => {
      const setup = createInitializationHttp(transport);
      const valid = {
        kind: "postgresql",
        host: "db.internal.example",
        port: 5432,
        database: "sentinel_console",
        username: "bootstrap_user",
        password: "synthetic-password",
      };
      const invalidInputs = [
        { ...valid, host: "🌋".repeat(127) },
        { ...valid, host: "db.internal\u001c" },
        { ...valid, host: "db.internal\ud800" },
        { ...valid, database: "🌋".repeat(101) },
        { ...valid, username: "\u0085" },
        { ...valid, username: "🌋".repeat(101) },
        { ...valid, password: "🌋".repeat(513) },
      ];
      for (const input of invalidInputs) {
        await assert.rejects(
          setup.checkDatabase(input, new AbortController().signal),
          (error) => error.code === "console_request_invalid",
        );
      }
    },
  );
  assert.equal(dispatched, 0);
});
test("BOOTSTRAP-CHECK: stable provider failure reasons survive strict database/source response parsing", async () => {
  const database = {
      kind: "mysql",
      host: "mysql.synthetic.internal",
      port: 3306,
      database: "sentinel",
      username: "sentinel",
      password: "SYNTHETIC-DB-CHECK",
    },
    source = {
      provider: "consul",
      endpoint: "http://consul.synthetic.internal:8500",
      datacenter: "dc-one",
      authentication: { mode: "direct", aclToken: "SYNTHETIC-CONSUL-CHECK" },
    };
  await withTransport(
    [
      http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
        json(request, { initialized: false, setupAvailable: true, operatorAuthorized: false }),
      ),
      http.post(`${origin}/api/v1/system/bootstrap/authorize`, ({ request }) =>
        json(request, { authorized: true }),
      ),
      http.post(`${origin}/api/v1/system/bootstrap/database-check`, ({ request }) =>
        json(request, { status: "unreachable", reason: "authentication" }),
      ),
      http.post(`${origin}/api/v1/system/bootstrap/source-check`, ({ request }) =>
        json(request, { status: "unreachable", reason: "unsupported" }),
      ),
    ],
    async (transport) => {
      const operator = createBootstrapAuthorizationHttp(transport),
        setup = createInitializationHttp(transport),
        signal = new AbortController().signal;
      assert.deepEqual(await operator.readGate(signal), { kind: "open", authorized: false });
      await operator.authorize("SYNTHETIC-ONE-TIME-CODE-0123456789ABC", signal);
      assert.deepEqual(await setup.checkDatabase(database, signal), {
        status: "unreachable",
        reason: "authentication",
      });
      assert.deepEqual(await setup.checkSource(source, signal), {
        status: "unreachable",
        reason: "unsupported",
      });
    },
  );
});
test("IDENTITY-INPUT: bounded strict inputs reject inactive secrets and destination userinfo before any network dispatch", async () => {
  let dispatched = 0;
  await withTransport(
    [
      http.all(`${origin}/*`, ({ request }) => {
        dispatched++;
        return json(request, {});
      }),
    ],
    async (transport) => {
      const identity = createIdentityHttp(transport),
        setup = createInitializationHttp(transport),
        signal = new AbortController().signal;
      await assert.rejects(
        identity.login({ username: "operator", password: "PRIVATE", roleId: "admin" }, signal),
        (error) =>
          error.code === "console_request_invalid" && !JSON.stringify(error).includes("PRIVATE"),
      );
      for (const input of [
        {
          provider: "consul",
          endpoint: "http://user:PRIVATE@consul.internal",
          datacenter: "dc",
          authentication: { mode: "none" },
        },
        {
          provider: "consul",
          endpoint: "http://consul.internal",
          datacenter: "dc",
          authentication: { mode: "none", aclToken: "PRIVATE" },
        },
        {
          provider: "nacos",
          endpoint: "http://nacos.internal",
          namespace: "public",
          datacenter: "dc",
          authentication: { mode: "direct", username: "user", password: "PRIVATE" },
        },
      ])
        await assert.rejects(
          setup.checkSource(input, signal),
          (error) => error.code === "console_request_invalid",
        );
      assert.equal(dispatched, 0);
    },
  );
  assert.equal(z.toJSONSchema(LoginInputSchema).properties.password.writeOnly, true);
  assert.equal(z.toJSONSchema(SetupSubmissionSchema).additionalProperties, false);
  assert.equal(
    ConfigurationSourceInputSchema.safeParse({
      provider: "consul",
      endpoint: "http://consul.internal",
      datacenter: "dc",
      authentication: { mode: "none" },
    }).success,
    true,
  );
});
test("BOOTSTRAP-ACK: not-found or foreign request acknowledgement remains unknown; original lookup never replays initialization", async () => {
  const input = {
    database: {
      kind: "postgresql",
      host: "postgres.internal",
      port: 5432,
      database: "sentinel",
      username: "sentinel",
      password: "PRIVATE-DB",
    },
    admin: { username: "admin", password: "PRIVATE-ADMIN-PASSWORD" },
    source: {
      provider: "nacos",
      endpoint: "http://nacos.internal:8848",
      namespace: "public",
      authentication: { mode: "none" },
    },
  };
  for (const receipt of [
    { status: "not-found", requestKey: "setup-original" },
    { status: "completed", requestKey: "foreign-key", operationId: "setup-one" },
  ]) {
    let writes = 0,
      lookups = 0;
    await withTransport(
      [
        http.get(`${origin}/api/v1/system/bootstrap`, ({ request }) =>
          json(request, { initialized: false, setupAvailable: true, operatorAuthorized: true }),
        ),
        http.post(`${origin}/api/v1/system/bootstrap/initialize`, ({ request }) => {
          writes++;
          return json(request, receipt);
        }),
        http.get(`${origin}/api/v1/system/bootstrap/operations/:key`, ({ request, params }) => {
          lookups++;
          return json(request, { status: "not-found", requestKey: params.key });
        }),
      ],
      async (transport) => {
        const workflow = createInitializationWorkflow(
          createInitializationHttp(transport),
          () => "setup-original",
        );
        try {
          await workflow.restore();
          await assert.rejects(workflow.initialize(input));
          assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
          await assert.rejects(workflow.initialize(input));
          assert.equal(writes, 1);
          assert.equal((await workflow.inspect()).status, "result-unknown");
          assert.equal(lookups, 1);
          assert.equal(writes, 1);
          assert.equal(JSON.stringify(workflow.getSnapshot()).includes("PRIVATE"), false);
        } finally {
          workflow.dispose();
        }
      },
    );
  }
});
