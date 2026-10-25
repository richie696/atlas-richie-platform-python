import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  bootstrapFactFromAccess,
  bootstrapOperatorGateFromAccess,
  decideControlPlaneAccess,
  isAdministrator,
} from "../../src/features/identity/model/controlPlaneAccess";
import {
  accessStateFromResource,
  createAccessResource,
} from "../../src/features/identity/state/accessResource";
import { createSetupIdentityPorts } from "../../src/app/api/setupIdentityPorts";

const requirements = ["public", "setup", "session", "metrics", "admin"];
const identity = Object.freeze({
  accountId: "one",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "incarnation-one",
});
const query = Object.freeze({ sessionGeneration: "one" });
const port = (changes) => ({
  readBootstrap: async () => ({ initialized: true }),
  readSession: async () => identity,
  login: async () => identity,
  logout: async () => {},
  ...changes,
});
const resolved = (facts) => ({ phase: "resolved", facts });

test("F2 access gates all pages before bootstrap, forces setup only for confirmed open initialization", () => {
  for (const requirement of requirements) {
    for (const phase of ["unknown", "checking", "authenticating"])
      assert.equal(decideControlPlaneAccess(requirement, { phase }).kind, "wait");
    assert.equal(
      decideControlPlaneAccess(requirement, { phase: "unavailable" }).kind,
      "unavailable",
    );
    assert.equal(
      decideControlPlaneAccess(
        requirement,
        resolved({ kind: "uninitialized", setupAvailable: true, operatorAuthorized: false }),
      ).kind,
      "setup",
    );
    assert.equal(
      decideControlPlaneAccess(
        requirement,
        resolved({ kind: "uninitialized", setupAvailable: false, operatorAuthorized: false }),
      ).kind,
      "unavailable",
    );
  }
});
test("F2 completed setup is closed for admin, viewer and anonymous; login alone never grants private routes", () => {
  for (const facts of [{ kind: "authenticated", identity }, { kind: "anonymous" }])
    assert.equal(decideControlPlaneAccess("setup", resolved(facts)).kind, "login");
  assert.equal(decideControlPlaneAccess("public", resolved({ kind: "anonymous" })).kind, "allow");
  for (const requirement of ["session", "metrics", "admin"])
    assert.equal(
      decideControlPlaneAccess(requirement, resolved({ kind: "anonymous" })).kind,
      "login",
    );
  assert.equal(decideControlPlaneAccess("admin", { phase: "expired" }).kind, "login");
});
test("F2 admin and metrics requirements differ; view cannot administer even with a forged write capability", () => {
  assert.equal(isAdministrator(identity), true);
  assert.equal(
    decideControlPlaneAccess("admin", resolved({ kind: "authenticated", identity })).kind,
    "allow",
  );
  const viewer = { ...identity, roleId: "view" };
  assert.equal(isAdministrator(viewer), false);
  assert.deepEqual(
    decideControlPlaneAccess("admin", resolved({ kind: "authenticated", identity: viewer })),
    { kind: "denied", reason: "admin_required" },
  );
  assert.equal(
    decideControlPlaneAccess("metrics", resolved({ kind: "authenticated", identity: viewer })).kind,
    "allow",
  );
  assert.deepEqual(
    decideControlPlaneAccess(
      "metrics",
      resolved({ kind: "authenticated", identity: { ...identity, capabilities: [] } }),
    ),
    { kind: "denied", reason: "metrics_required" },
  );
});
test("F2 server bootstrap is sequenced before session; uninitialized deployments never fetch private identity", async () => {
  const calls = [];
  const resource = createAccessResource(
    port({
      readBootstrap: async () => {
        calls.push("bootstrap");
        return { initialized: false, setupAvailable: true, operatorAuthorized: false };
      },
      readSession: async () => {
        calls.push("session");
        return identity;
      },
    }),
  );
  await resource.load(query);
  assert.deepEqual(calls, ["bootstrap"]);
  assert.deepEqual(
    accessStateFromResource(resource.getSnapshot()),
    resolved({ kind: "uninitialized", setupAvailable: true, operatorAuthorized: false }),
  );
  resource.dispose();
});
test("F4.21 setup ports read refreshed authorization from the single auth owner", async () => {
  let restores = 0;
  let facts = { kind: "uninitialized", setupAvailable: true, operatorAuthorized: false };
  let currentAccess = resolved(facts);
  const authentication = {
    getSnapshot() {
      return { access: currentAccess };
    },
    async restore() {
      restores++;
      currentAccess = resolved(facts);
      return facts;
    },
  };
  const ports = createSetupIdentityPorts(
    authentication,
    {
      readGate: async () => assert.fail("setup gate must not read bootstrap independently"),
      authorize: async () => {},
    },
    {
      readBootstrap: async () =>
        assert.fail("initialization must not read bootstrap independently"),
      checkDatabase: async () => ({ status: "reachable" }),
      checkSource: async () => ({ status: "reachable" }),
      initialize: async () => assert.fail("not used"),
      readInitialization: async () => assert.fail("not used"),
    },
  );
  assert.deepEqual(await ports.authorization.readGate(new AbortController().signal), {
    kind: "open",
    authorized: false,
  });
  assert.deepEqual(await ports.initialization.readBootstrap(new AbortController().signal), {
    initialized: false,
    setupAvailable: true,
    operatorAuthorized: false,
  });
  assert.equal(restores, 0);
  facts = { kind: "uninitialized", setupAvailable: true, operatorAuthorized: true };
  assert.deepEqual(
    await ports.authorization.readGate(new AbortController().signal, { forceRefresh: true }),
    {
      kind: "open",
      authorized: true,
    },
  );
  assert.deepEqual(await ports.initialization.readBootstrap(new AbortController().signal), {
    initialized: false,
    setupAvailable: true,
    operatorAuthorized: true,
  });
  assert.equal(restores, 1, "initialization observes the authorization owner's refreshed fact");
  facts = { kind: "uninitialized", setupAvailable: true, operatorAuthorized: false };
  assert.deepEqual(
    await ports.authorization.readGate(new AbortController().signal, { forceRefresh: true }),
    {
      kind: "open",
      authorized: false,
    },
  );
  assert.deepEqual(
    await ports.initialization.readBootstrap(new AbortController().signal, {
      forceRefresh: true,
    }),
    { initialized: false, setupAvailable: true, operatorAuthorized: false },
  );
  assert.equal(restores, 3);
  assert.deepEqual(bootstrapFactFromAccess({ kind: "anonymous" }), { initialized: true });
  assert.deepEqual(
    bootstrapOperatorGateFromAccess({
      kind: "uninitialized",
      setupAvailable: false,
      operatorAuthorized: true,
    }),
    { kind: "closed" },
  );
});
test("F2 initialized response restores one server session; confirmed absence resolves anonymous", async () => {
  for (const session of [identity, null]) {
    const calls = [];
    const resource = createAccessResource(
      port({
        readBootstrap: async () => {
          calls.push("bootstrap");
          return { initialized: true };
        },
        readSession: async () => {
          calls.push("session");
          return session;
        },
      }),
    );
    await resource.load(query);
    assert.deepEqual(calls, ["bootstrap", "session"]);
    assert.deepEqual(
      resource.getSnapshot().data,
      session ? { kind: "authenticated", identity } : { kind: "anonymous" },
    );
    resource.dispose();
  }
});
test("F2 bootstrap and restoration failures do not reopen setup or manufacture anonymous/admin success", async () => {
  for (const stage of ["readBootstrap", "readSession"]) {
    const resource = createAccessResource(
      port({
        [stage]: async () => {
          throw new AppError(AppErrorKind.SERVER, "raw", { status: 503 });
        },
      }),
    );
    await assert.rejects(resource.load(query));
    assert.deepEqual(accessStateFromResource(resource.getSnapshot()), { phase: "unavailable" });
    resource.dispose();
  }
});
test("F2 authorization never reuses stale or refreshing session data as an allow decision", async () => {
  let fail = false;
  const resource = createAccessResource(
    port({
      readSession: async () => {
        if (fail) throw new AppError(AppErrorKind.NETWORK, "offline");
        return identity;
      },
    }),
  );
  await resource.load(query);
  fail = true;
  const refresh = resource.load(query);
  assert.equal(
    decideControlPlaneAccess("admin", accessStateFromResource(resource.getSnapshot())).kind,
    "wait",
  );
  await assert.rejects(refresh);
  assert.equal(resource.getSnapshot().status, "stale");
  assert.equal(
    decideControlPlaneAccess("admin", accessStateFromResource(resource.getSnapshot())).kind,
    "unavailable",
  );
  resource.dispose();
});
test("F2 an obsolete bootstrap response cannot start session restoration for a new owner", async () => {
  let release,
    calls = 0;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const resource = createAccessResource(
    port({
      readBootstrap: () => (++calls === 1 ? pending : Promise.resolve({ initialized: true })),
      readSession: async () => {
        calls++;
        return identity;
      },
    }),
  );
  const earlier = resource.load(query);
  const rejection = assert.rejects(earlier);
  await resource.load({ sessionGeneration: "two" });
  await rejection;
  release({ initialized: true });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(calls, 3);
  assert.match(resource.getSnapshot().key, /two/);
  resource.dispose();
});
