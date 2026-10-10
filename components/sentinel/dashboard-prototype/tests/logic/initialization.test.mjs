import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInitializationWorkflow } from "../../src/features/identity/application/initializationWorkflow";
import {
  initializationFeedbackKey,
  isSetupAuthorityClosed,
} from "../../src/features/identity/presentation/setupFeedback";

const input = Object.freeze({
  database: { kind: "sqlite" },
  admin: { username: "admin", password: "SYNTHETIC-INIT-SECRET" },
  source: {
    provider: "consul",
    endpoint: "http://consul.synthetic.internal",
    datacenter: "",
    authentication: { mode: "none" },
  },
});
const completed = (key) => ({
  status: "completed",
  requestKey: key,
  operationId: "synthetic-operation",
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function make(overrides = {}) {
  let initialized = false,
    calls = 0;
  const port = {
    readBootstrap: async () =>
      initialized ? { initialized: true } : { initialized: false, setupAvailable: true },
    checkDatabase: async () => ({ status: "reachable" }),
    checkSource: async () => ({ status: "reachable" }),
    initialize: async (request) => {
      calls++;
      initialized = true;
      return completed(request.requestKey);
    },
    readInitialization: async (key) => completed(key),
    ...overrides,
  };
  let keys = 0;
  const workflow = createInitializationWorkflow(port, () => `synthetic-request-${++keys}`);
  return {
    workflow,
    calls: () => calls,
    setInitialized: (value) => {
      initialized = value;
    },
  };
}

test("SETUP-BOOTSTRAP restore forwards an explicit force refresh to the read port", async () => {
  const receivedRefreshOptions = [];
  const { workflow } = make({
    readBootstrap: async (_signal, options) => {
      receivedRefreshOptions.push(options?.forceRefresh ?? false);
      return { initialized: false, setupAvailable: true };
    },
  });

  try {
    await workflow.restore();
    await workflow.restore(true);

    assert.deepEqual(receivedRefreshOptions, [false, true]);
  } finally {
    workflow.dispose();
  }
});

test("SETUP-LIFECYCLE recognizes authoritative closure without stealing this page's success", () => {
  const snapshot = {
    bootstrap: {
      status: "ready",
      key: "setup-window",
      data: { initialized: false, setupAvailable: true },
      receivedAt: 1,
    },
    databaseCheck: { status: "idle" },
    sourceCheck: { status: "idle" },
    initialization: { status: "idle" },
  };
  assert.equal(isSetupAuthorityClosed(snapshot), false);
  assert.equal(
    isSetupAuthorityClosed({
      ...snapshot,
      bootstrap: { ...snapshot.bootstrap, data: { initialized: true } },
    }),
    true,
  );
  assert.equal(
    isSetupAuthorityClosed({
      ...snapshot,
      bootstrap: {
        ...snapshot.bootstrap,
        data: { initialized: false, setupAvailable: false },
      },
    }),
    true,
  );
  assert.equal(
    isSetupAuthorityClosed({
      ...snapshot,
      bootstrap: { ...snapshot.bootstrap, data: { initialized: true } },
      initialization: { status: "ready", requestKey: "request", operationId: "operation" },
    }),
    false,
  );
  for (const status of ["submitting", "checking", "pending"]) {
    assert.equal(
      isSetupAuthorityClosed({
        ...snapshot,
        bootstrap: { ...snapshot.bootstrap, data: { initialized: true } },
        initialization: { status, requestKey: "request" },
      }),
      false,
      `${status} must not be mistaken for a completed external close`,
    );
  }
  assert.equal(
    isSetupAuthorityClosed({
      ...snapshot,
      initialization: { status: "rejected", requestKey: "request", reason: "setup-closed" },
    }),
    true,
  );
});

test("SETUP-COMMAND requires confirmed setup window, checks again before write and does not claim another initializer's success", async () => {
  const { workflow, calls, setInitialized } = make();
  await assert.rejects(
    workflow.initialize(input),
    (error) => error.kind === AppErrorKind.FORBIDDEN,
  );
  await workflow.restore();
  setInitialized(true);
  await assert.rejects(
    workflow.initialize(input),
    (error) => error.kind === AppErrorKind.FORBIDDEN,
  );
  assert.equal(calls(), 0);
  assert.equal(workflow.getSnapshot().initialization.status, "closed");
  workflow.dispose();
});
test("SETUP-COMMAND duplicate writes are blocked; completion requires correlated receipt AND authoritative bootstrap confirmation", async () => {
  const pending = deferred();
  let initialized = false,
    calls = 0,
    received;
  const { workflow } = make({
    readBootstrap: async () =>
      initialized ? { initialized: true } : { initialized: false, setupAvailable: true },
    initialize: async (request) => {
      calls++;
      received = request;
      return pending.promise;
    },
  });
  await workflow.restore();
  const running = workflow.initialize(input);
  await assert.rejects(
    workflow.initialize(input),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  assert.notEqual(workflow.getSnapshot().initialization.status, "ready");
  initialized = true;
  pending.resolve(completed("synthetic-request-1"));
  await running;
  assert.equal(calls, 1);
  assert.equal(workflow.getSnapshot().initialization.status, "ready");
  assert.equal(received.input, input);
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-INIT-SECRET/);
  workflow.dispose();
});
test("SETUP-COMMAND timeout stays unknown; explicit lookup resolves original request with no repeated write", async () => {
  const { workflow, calls, setInitialized } = make({
    initialize: async () => {
      throw new AppError(AppErrorKind.TIMEOUT, "unconfirmed");
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.initialize(input));
  assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
  await assert.rejects(
    workflow.initialize(input),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  await assert.rejects(workflow.restore(), (error) => error.kind === AppErrorKind.DUPLICATE);
  setInitialized(true);
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().initialization.status, "ready");
  assert.equal(calls(), 0);
  workflow.dispose();
});
test("SETUP-COMMAND not-found is not proof of rollback; pending remains inspectable and no automatic poll/replay", async () => {
  let observations = 0,
    writes = 0,
    result = "not-found";
  const { workflow } = make({
    initialize: async (request) => {
      writes++;
      return { status: "pending", requestKey: request.requestKey, operationId: "op" };
    },
    readInitialization: async (key) => {
      observations++;
      return result === "not-found"
        ? { status: "not-found", requestKey: key }
        : { status: "pending", requestKey: key, operationId: "op" };
    },
  });
  await workflow.restore();
  await workflow.initialize(input);
  assert.equal(workflow.getSnapshot().initialization.status, "pending");
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
  await assert.rejects(
    workflow.initialize(input),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  result = "pending";
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().initialization.status, "pending");
  assert.equal(writes, 1);
  assert.equal(observations, 2);
  workflow.dispose();
});
test("SETUP-COMMAND mismatched receipt never succeeds or grants resubmission, even if setup globally completed", async () => {
  const { workflow } = make({ initialize: async () => completed("another-request") });
  await workflow.restore();
  await assert.rejects(
    workflow.initialize(input),
    (error) => error.code === "initialization_receipt_mismatch",
  );
  assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
  workflow.dispose();
});
test("SETUP-COMMAND completed receipt with unavailable/incomplete confirmation remains unknown; failed inspection keeps original identity", async () => {
  let fail = false;
  const { workflow } = make({
    readBootstrap: async () => {
      if (fail) throw new AppError(AppErrorKind.NETWORK, "offline");
      return { initialized: false, setupAvailable: true };
    },
    initialize: async (request) => {
      fail = true;
      return completed(request.requestKey);
    },
    readInitialization: async () => {
      throw new AppError(AppErrorKind.NETWORK, "offline");
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.initialize(input));
  const key = workflow.getSnapshot().initialization.requestKey;
  await assert.rejects(workflow.inspect());
  assert.equal(workflow.getSnapshot().initialization.requestKey, key);
  assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
  workflow.dispose();
});
test("SETUP-COMMAND known validation/conflict failures permit only a deliberate new request, never replay on their own", async () => {
  let count = 0;
  const keys = [];
  const { workflow } = make({
    initialize: async (request) => {
      keys.push(request.requestKey);
      throw new AppError(AppErrorKind.PROTOCOL, "safe", { status: ++count === 1 ? 422 : 409 });
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.initialize(input));
  assert.equal(workflow.getSnapshot().initialization.status, "error");
  await assert.rejects(workflow.initialize(input));
  assert.equal(workflow.getSnapshot().initialization.status, "conflict");
  assert.deepEqual(keys, ["synthetic-request-1", "synthetic-request-2"]);
  workflow.dispose();
});
test("SETUP-COMMAND server validation receipt is a known rejection; only an explicit corrected submit creates a new request", async () => {
  let initialized = false;
  const received = [];
  const corrected = { ...input, admin: { ...input.admin, username: "operator" } };
  const { workflow } = make({
    readBootstrap: async () =>
      initialized ? { initialized: true } : { initialized: false, setupAvailable: true },
    initialize: async (request) => {
      received.push(request);
      if (received.length === 1)
        return {
          status: "rejected",
          requestKey: request.requestKey,
          operationId: "setup-rejected",
          reason: "validation",
        };
      initialized = true;
      return completed(request.requestKey);
    },
  });
  await workflow.restore();
  assert.deepEqual(await workflow.initialize(input), {
    status: "rejected",
    requestKey: "synthetic-request-1",
    reason: "validation",
  });
  assert.equal(workflow.getSnapshot().initialization.reason, "validation");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-INIT-SECRET/);
  assert.deepEqual(await workflow.initialize(corrected), {
    status: "ready",
    requestKey: "synthetic-request-2",
    operationId: "synthetic-operation",
  });
  assert.deepEqual(
    received.map((request) => request.requestKey),
    ["synthetic-request-1", "synthetic-request-2"],
  );
  assert.equal(received[1].input.admin.username, "operator");
  workflow.dispose();
});
test("SETUP-COMMAND setup-closed receipt is terminal even while cached bootstrap is stale-open", async () => {
  let writes = 0;
  let bootstrapReads = 0;
  const { workflow } = make({
    readBootstrap: async () => {
      bootstrapReads++;
      return { initialized: false, setupAvailable: true };
    },
    initialize: async (request) => {
      writes++;
      return {
        status: "rejected",
        requestKey: request.requestKey,
        operationId: "closed-setup",
        reason: "setup-closed",
      };
    },
  });

  try {
    await workflow.restore();
    assert.deepEqual(await workflow.initialize(input), { status: "closed" });
    assert.equal(workflow.getSnapshot().bootstrap.data.setupAvailable, true);
    assert.equal(workflow.getSnapshot().initialization.status, "closed");
    await assert.rejects(
      workflow.initialize(input),
      (error) => error.kind === AppErrorKind.FORBIDDEN,
    );
    await assert.rejects(
      workflow.checkDatabase(input.database),
      (error) => error.kind === AppErrorKind.FORBIDDEN,
    );
    await assert.rejects(
      workflow.checkSource(input.source),
      (error) => error.kind === AppErrorKind.FORBIDDEN,
    );

    // A read-only explicit refresh remains available to reconcile the stale bootstrap fact.
    await workflow.restore(true);
    assert.equal(bootstrapReads, 3);
    assert.equal(writes, 1);
  } finally {
    workflow.dispose();
  }
});
test("SETUP-PRESENTATION: server rejection reasons receive distinct safe recovery messages", () => {
  assert.equal(
    initializationFeedbackKey({ status: "rejected", requestKey: "request", reason: "validation" }),
    "setup.workflow.rejected.validation",
  );
  assert.equal(
    initializationFeedbackKey({
      status: "rejected",
      requestKey: "request",
      reason: "setup-closed",
    }),
    "setup.workflow.rejected.setupClosed",
  );
  assert.equal(
    initializationFeedbackKey({ status: "rejected", requestKey: "request", reason: "dependency" }),
    "setup.workflow.rejected.dependency",
  );
  assert.equal(
    initializationFeedbackKey({ status: "result-unknown", requestKey: "request" }),
    "setup.workflow.unknown",
  );
});
test("SETUP-CHECK revisions contain no secrets, changed input invalidates confirmation and late completion cannot restore it", async () => {
  const pending = deferred();
  let calls = 0;
  const { workflow } = make({
    checkDatabase: async () => (++calls === 1 ? pending.promise : { status: "reachable" }),
  });
  await workflow.restore();
  const checking = workflow.checkDatabase({ ...input.database, password: "SYNTHETIC-DB-CHECK" });
  const rejected = assert.rejects(checking);
  assert.equal(workflow.getSnapshot().databaseCheck.status, "loading");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-DB-CHECK/);
  workflow.invalidateChecks();
  await rejected;
  pending.resolve({ status: "reachable" });
  await Promise.resolve();
  assert.equal(workflow.getSnapshot().databaseCheck.status, "idle");
  await workflow.checkDatabase(input.database);
  assert.equal(workflow.getSnapshot().databaseCheck.status, "ready");
  workflow.dispose();
});
test("SETUP-CHECK exposes only stable failure reasons and a deliberate retry replaces failure with success", async () => {
  const databaseResults = [
    { status: "unreachable", reason: "authentication" },
    { status: "unreachable", reason: "connection" },
    { status: "reachable" },
  ];
  const sourceResults = [
    { status: "unreachable", reason: "unsupported" },
    { status: "unreachable", reason: "connection" },
    { status: "reachable" },
  ];
  const { workflow } = make({
    checkDatabase: async () => databaseResults.shift(),
    checkSource: async () => sourceResults.shift(),
  });
  await workflow.restore();
  assert.deepEqual(await workflow.checkDatabase(input.database), {
    status: "unreachable",
    reason: "authentication",
  });
  assert.deepEqual(workflow.getSnapshot().databaseCheck.data, {
    status: "unreachable",
    reason: "authentication",
  });
  assert.deepEqual(await workflow.checkDatabase(input.database), {
    status: "unreachable",
    reason: "connection",
  });
  assert.deepEqual(workflow.getSnapshot().databaseCheck.data, {
    status: "unreachable",
    reason: "connection",
  });
  assert.deepEqual(await workflow.checkSource(input.source), {
    status: "unreachable",
    reason: "unsupported",
  });
  assert.deepEqual(workflow.getSnapshot().sourceCheck.data, {
    status: "unreachable",
    reason: "unsupported",
  });
  assert.deepEqual(await workflow.checkSource(input.source), {
    status: "unreachable",
    reason: "connection",
  });
  assert.deepEqual(workflow.getSnapshot().sourceCheck.data, {
    status: "unreachable",
    reason: "connection",
  });
  assert.doesNotMatch(
    JSON.stringify(workflow.getSnapshot()),
    /SYNTHETIC-DB-CHECK|SYNTHETIC-INIT-SECRET/,
  );
  assert.deepEqual(await workflow.checkDatabase(input.database), { status: "reachable" });
  assert.deepEqual(workflow.getSnapshot().databaseCheck.data, { status: "reachable" });
  assert.deepEqual(await workflow.checkSource(input.source), { status: "reachable" });
  assert.deepEqual(workflow.getSnapshot().sourceCheck.data, { status: "reachable" });
  assert.deepEqual(databaseResults, []);
  assert.deepEqual(sourceResults, []);
  workflow.dispose();
});
test("SETUP-CHECK same-kind requests are single-flight while independent database/source checks may overlap", async () => {
  const database = deferred();
  const source = deferred();
  let databaseSignal;
  const { workflow } = make({
    checkDatabase: async (_input, signal) => {
      databaseSignal = signal;
      return database.promise;
    },
    checkSource: async () => source.promise,
  });
  await workflow.restore();
  const databaseRun = workflow.checkDatabase(input.database);
  await assert.rejects(
    workflow.checkDatabase(input.database),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  assert.equal(
    databaseSignal.aborted,
    false,
    "duplicate caller must not cancel the active request",
  );
  const sourceRun = workflow.checkSource(input.source);
  database.resolve({ status: "reachable" });
  source.resolve({ status: "reachable" });
  assert.deepEqual(await databaseRun, { status: "reachable" });
  assert.deepEqual(await sourceRun, { status: "reachable" });
  assert.equal(workflow.getSnapshot().databaseCheck.status, "ready");
  assert.equal(workflow.getSnapshot().sourceCheck.status, "ready");
  workflow.dispose();
});
test("SETUP-COMMAND cleanup after dispatch aborts observation, never treats cancellation as rollback; disposal releases all snapshots", async () => {
  const pending = deferred();
  let signal;
  const { workflow } = make({
    initialize: async (_request, received) => {
      signal = received;
      return pending.promise;
    },
  });
  await workflow.restore();
  const running = workflow.initialize(input);
  const rejected = assert.rejects(running);
  while (!signal) await Promise.resolve();
  workflow.cancel();
  await rejected;
  assert.ok(signal.aborted);
  assert.equal(workflow.getSnapshot().initialization.status, "result-unknown");
  pending.resolve(completed("synthetic-request-1"));
  await Promise.resolve();
  assert.notEqual(workflow.getSnapshot().initialization.status, "ready");
  workflow.dispose();
  workflow.dispose();
  assert.equal(workflow.getSnapshot().initialization.status, "idle");
  await assert.rejects(workflow.restore(), (error) => error.kind === AppErrorKind.CANCELLED);
});
