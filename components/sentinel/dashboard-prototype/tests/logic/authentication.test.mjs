import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  loginFeedback,
  loginRetryDelayMs,
} from "../../src/features/identity/presentation/loginFeedback.ts";
import { CONSOLE_WIRE_LIMIT } from "../../src/core/api/protocol/common.ts";
import { createAuthenticationWorkflow } from "../../src/features/identity/application/authenticationWorkflow";
import { observeAuthenticationForeground } from "../../src/features/identity/state/foregroundRevalidation";

const identity = Object.freeze({
  accountId: "one",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "epoch-one",
});
const credentials = Object.freeze({
  username: " operator ",
  password: "SYNTHETIC-SECRET-NEVER-STORED",
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function make(changes = {}) {
  return createAuthenticationWorkflow({
    readBootstrap: async () => ({ initialized: true }),
    readSession: async () => null,
    login: async () => identity,
    logout: async () => {},
    ...changes,
  });
}

test("F2 authentication requires confirmed initialized anonymous state, validates blanks before dispatch", async () => {
  let calls = 0;
  const workflow = make({
    login: async () => {
      calls++;
      return identity;
    },
  });
  await assert.rejects(
    workflow.login(credentials),
    (error) => error.kind === AppErrorKind.FORBIDDEN,
  );
  await workflow.restore();
  await assert.rejects(
    workflow.login({ ...credentials, username: "   " }),
    (error) => error.code === "credentials_required",
  );
  await assert.rejects(
    workflow.login({ ...credentials, password: "" }),
    (error) => error.code === "credentials_required",
  );
  assert.equal(calls, 0);
  workflow.dispose();
});
test("F2 login prevents duplicate submission, keeps secrets out of snapshots and confirms returned identity separately", async () => {
  const response = deferred(),
    confirmation = deferred();
  let reads = 0,
    calls = 0,
    captured;
  const workflow = make({
    readSession: async () => (++reads === 1 ? null : confirmation.promise),
    login: async (input) => {
      calls++;
      captured = input;
      return response.promise;
    },
  });
  await workflow.restore();
  const running = workflow.login(credentials);
  assert.equal(workflow.getSnapshot().access.phase, "authenticating");
  await assert.rejects(
    workflow.login(credentials),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  response.resolve(identity);
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  // Server POST confirmation alone does not open the private page before GET /session confirms it.
  assert.notEqual(workflow.getSnapshot().access.phase, "resolved");
  confirmation.resolve(identity);
  await running;
  assert.equal(calls, 1);
  assert.equal(captured.username, "operator");
  assert.equal(workflow.getSnapshot().login.status, "success");
  assert.equal(workflow.getSnapshot().access.facts.identity.accountId, "one");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-SECRET/);
  workflow.dispose();
});
test("F2 known bad credentials remain anonymous and allow a deliberate corrected attempt, never infer admin", async () => {
  let calls = 0;
  const workflow = make({
    login: async () => {
      calls++;
      throw new AppError(AppErrorKind.UNAUTHORIZED, "safe");
    },
  });
  await workflow.restore();
  for (let index = 0; index < 2; index++) await assert.rejects(workflow.login(credentials));
  assert.equal(calls, 2);
  assert.equal(workflow.getSnapshot().login.status, "error");
  assert.equal(workflow.getSnapshot().access.facts.kind, "anonymous");
  workflow.dispose();
});
test("F4.22 editing credentials clears only a known rejection and keeps the anonymous session facts", async () => {
  let calls = 0;
  const workflow = make({
    login: async () => {
      calls++;
      throw new AppError(AppErrorKind.UNAUTHORIZED, "safe");
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.login(credentials));
  assert.equal(workflow.getSnapshot().login.status, "error");
  workflow.clearLoginFailure();
  assert.equal(workflow.getSnapshot().login.status, "idle");
  assert.deepEqual(workflow.getSnapshot().access.facts, { kind: "anonymous" });
  await assert.rejects(workflow.login({ ...credentials, password: "corrected-secret" }));
  assert.equal(calls, 2);
  workflow.dispose();
});
test("F4.22 editing credentials cannot dismiss or replay a login with an unknown outcome", async () => {
  let calls = 0;
  const workflow = make({
    login: async () => {
      calls++;
      throw new AppError(AppErrorKind.TIMEOUT, "unknown");
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.login(credentials));
  workflow.clearLoginFailure();
  assert.equal(workflow.getSnapshot().login.status, "result-unknown");
  await assert.rejects(
    workflow.login({ ...credentials, password: "corrected-secret" }),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  assert.equal(calls, 1);
  workflow.dispose();
});
test("F4.22 dispatched network failure stays unknown until explicit session inspection", async () => {
  let calls = 0;
  const workflow = make({
    login: async () => {
      calls++;
      throw new AppError(AppErrorKind.NETWORK, "private transport details");
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.login(credentials));
  assert.equal(workflow.getSnapshot().login.status, "result-unknown");
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  workflow.clearLoginFailure();
  await assert.rejects(
    workflow.login({ ...credentials, password: "corrected-secret" }),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  assert.equal(calls, 1);
  assert.deepEqual(await workflow.inspectSession(), { kind: "anonymous" });
  assert.equal(workflow.getSnapshot().login.status, "idle");
  workflow.dispose();
});
test("F4.22 login cooldown accepts only bounded retry metadata from the rate-limit contract", () => {
  const valid = new AppError(AppErrorKind.SERVER, "safe", {
    status: 429,
    code: "rate_limited",
    retryAfterMs: 1_250,
  });
  assert.equal(loginRetryDelayMs(valid), 1_250);
  assert.equal(
    loginRetryDelayMs(
      new AppError(AppErrorKind.SERVER, "safe", {
        status: 429,
        code: "rate_limited",
        retryAfterMs: CONSOLE_WIRE_LIMIT.RetryAfterMs + 1,
      }),
    ),
    CONSOLE_WIRE_LIMIT.RetryAfterMs,
  );
  for (const retryAfterMs of [undefined, 0, -1, Number.NaN])
    assert.equal(
      loginRetryDelayMs(
        new AppError(AppErrorKind.SERVER, "safe", {
          status: 429,
          code: "rate_limited",
          retryAfterMs,
        }),
      ),
      null,
    );
  assert.equal(
    loginRetryDelayMs(
      new AppError(AppErrorKind.SERVER, "safe", {
        status: 503,
        code: "rate_limited",
        retryAfterMs: 1_250,
      }),
    ),
    null,
  );
});
test("F4.22 server cooldown feedback survives edited credentials returning login to idle", () => {
  const feedback = loginFeedback(
    {
      access: { phase: "resolved", facts: { kind: "anonymous" } },
      login: { status: "idle" },
      logout: { status: "idle" },
    },
    2,
  );
  assert.equal(feedback.key, "login.remote.rateLimitedFor");
  assert.deepEqual(feedback.values, { count: 2 });
  assert.equal(feedback.tone, "error");
});
test("F2 unknown login result is not replayed; explicit session investigation must succeed before another command", async () => {
  let calls = 0,
    failRead = false;
  const workflow = make({
    readSession: async () => {
      if (failRead) throw new AppError(AppErrorKind.NETWORK, "offline");
      return null;
    },
    login: async () => {
      calls++;
      throw new AppError(AppErrorKind.TIMEOUT, "unknown");
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.login(credentials));
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  assert.equal(workflow.getSnapshot().login.status, "result-unknown");
  await assert.rejects(workflow.restore(), (error) => error.kind === AppErrorKind.DUPLICATE);
  await assert.rejects(
    workflow.login(credentials),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  failRead = true;
  await assert.rejects(workflow.inspectSession());
  assert.equal(workflow.getSnapshot().login.status, "result-unknown");
  failRead = false;
  await workflow.inspectSession();
  assert.equal(workflow.getSnapshot().login.status, "idle");
  assert.equal(workflow.getSnapshot().access.facts.kind, "anonymous");
  assert.equal(calls, 1);
  workflow.dispose();
});
test("F2 login response/session mismatch never grants another account, even for one publication", async () => {
  let reads = 0;
  const states = [];
  const workflow = make({
    readSession: async () => (++reads === 1 ? null : { ...identity, accountId: "different" }),
  });
  const unsubscribe = workflow.subscribe(() => states.push(workflow.getSnapshot()));
  await workflow.restore();
  await assert.rejects(
    workflow.login(credentials),
    (error) => error.code === "session_confirmation_mismatch",
  );
  assert.ok(
    states.every(
      (value) => value.access.phase !== "resolved" || value.access.facts.kind !== "authenticated",
    ),
  );
  assert.equal(workflow.getSnapshot().login.status, "success"); // POST is known; confirmation failure is separate.
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  unsubscribe();
  workflow.dispose();
});
test("F2 successful login followed by unavailable confirmation is not an automatic second POST", async () => {
  let calls = 0,
    reads = 0;
  const workflow = make({
    readSession: async () => {
      if (++reads > 1) throw new AppError(AppErrorKind.NETWORK, "offline");
      return null;
    },
    login: async () => {
      calls++;
      return identity;
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.login(credentials));
  assert.equal(workflow.getSnapshot().login.status, "success");
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  assert.equal(calls, 1);
  workflow.dispose();
});
test("F2 logout drops private identity immediately, disallows concurrent auth and confirms server invalidation", async () => {
  const pending = deferred();
  let authenticated = true,
    calls = 0;
  const workflow = make({
    readSession: async () => (authenticated ? identity : null),
    logout: async () => {
      calls++;
      await pending.promise;
      authenticated = false;
    },
  });
  await workflow.restore();
  const running = workflow.logout();
  assert.notEqual(workflow.getSnapshot().access.phase, "resolved");
  await assert.rejects(
    workflow.login(credentials),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  pending.resolve();
  await running;
  assert.equal(workflow.getSnapshot().logout.status, "success");
  assert.equal(workflow.getSnapshot().access.facts.kind, "anonymous");
  assert.equal(calls, 1);
  workflow.dispose();
});
test("F2 logout transport failure remains unknown, cannot restore old trusted privileges or replay", async () => {
  let calls = 0;
  const workflow = make({
    readSession: async () => identity,
    logout: async () => {
      calls++;
      throw new AppError(AppErrorKind.SERVER, "unknown", { status: 503 });
    },
  });
  await workflow.restore();
  await assert.rejects(workflow.logout());
  assert.equal(workflow.getSnapshot().logout.status, "result-unknown");
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  await assert.rejects(workflow.logout(), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(calls, 1);
  workflow.dispose();
});
test("F2 confirmed logout response is distinct from failed session invalidation; the UI receives a recoverable unavailable state", async () => {
  const workflow = make({ readSession: async () => identity });
  await workflow.restore();
  await assert.rejects(workflow.logout(), (error) => error.code === "logout_confirmation_mismatch");
  assert.equal(workflow.getSnapshot().logout.status, "success");
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  workflow.dispose();
});
test("F2 explicit outcome investigation is single-flight and expiry cannot resurrect its late identity", async () => {
  const pending = deferred();
  let hold = false;
  const workflow = make({ readSession: async () => (hold ? pending.promise : null) });
  await workflow.restore();
  hold = true;
  const checking = workflow.inspectSession();
  const rejected = assert.rejects(checking);
  assert.equal(workflow.getSnapshot().access.phase, "checking");
  await assert.rejects(workflow.inspectSession(), (error) => error.kind === AppErrorKind.DUPLICATE);
  workflow.expire();
  await rejected;
  pending.resolve(identity);
  await Promise.resolve();
  assert.equal(workflow.getSnapshot().access.phase, "expired");
  workflow.dispose();
});
test("F2 foreground revalidation refreshes authoritative bootstrap/session and does not resolve unknown writes", async () => {
  let initialized = false,
    authenticated = false,
    bootstrapReads = 0;
  const workflow = make({
    readBootstrap: async () => {
      bootstrapReads++;
      return { initialized, setupAvailable: !initialized, operatorAuthorized: !initialized };
    },
    readSession: async () => (authenticated ? identity : null),
    login: async () => {
      throw new AppError(AppErrorKind.TIMEOUT, "unknown");
    },
  });
  await workflow.restore();
  initialized = true;
  assert.deepEqual(await workflow.revalidateAccess(), { kind: "anonymous" });
  assert.equal(bootstrapReads, 2);
  assert.deepEqual(workflow.getSnapshot().access, {
    phase: "resolved",
    facts: { kind: "anonymous" },
  });

  authenticated = true;
  await workflow.revalidateAccess();
  assert.equal(workflow.getSnapshot().access.facts.kind, "authenticated");
  authenticated = false;
  await workflow.revalidateAccess();
  assert.equal(workflow.getSnapshot().access.facts.kind, "anonymous");

  await assert.rejects(workflow.login(credentials), (error) => error.kind === AppErrorKind.TIMEOUT);
  assert.equal(await workflow.revalidateAccess(), undefined);
  // Expired privilege and an unresolved write are not auto-recovered.
  workflow.expire();
  assert.equal(await workflow.revalidateAccess(), undefined);
  assert.equal(workflow.getSnapshot().access.phase, "expired");
  workflow.dispose();
});
test("F4.20 a pending bootstrap read preserves only the last confirmed setup facts until the read resolves", async () => {
  const pending = deferred();
  let hold = false;
  const workflow = make({
    readBootstrap: async () =>
      hold
        ? pending.promise
        : { initialized: false, setupAvailable: true, operatorAuthorized: true },
  });
  const setupFacts = {
    kind: "uninitialized",
    setupAvailable: true,
    operatorAuthorized: true,
  };

  assert.deepEqual(await workflow.restore(), setupFacts);
  hold = true;
  const revalidation = workflow.restore();
  assert.deepEqual(workflow.getSnapshot().access, {
    phase: "checking",
    previousFacts: setupFacts,
  });

  pending.resolve({ initialized: true });
  assert.deepEqual(await revalidation, { kind: "anonymous" });
  assert.deepEqual(workflow.getSnapshot().access, {
    phase: "resolved",
    facts: { kind: "anonymous" },
  });
  workflow.dispose();
});
test("F4.20 a failed bootstrap revalidation clears the preserved setup facts", async () => {
  let fail = false;
  const workflow = make({
    readBootstrap: async () => {
      if (fail) throw new AppError(AppErrorKind.NETWORK, "private network details");
      return { initialized: false, setupAvailable: true, operatorAuthorized: true };
    },
  });
  await workflow.restore();
  fail = true;
  await assert.rejects(workflow.restore());
  assert.equal(workflow.getSnapshot().access.phase, "unavailable");
  fail = false;
  const retry = workflow.restore();
  assert.deepEqual(workflow.getSnapshot().access, { phase: "checking" });
  await retry;
  workflow.dispose();
});
test("F4.20 checking snapshots never expose a previously authenticated identity", async () => {
  const pending = deferred();
  let hold = false;
  const workflow = make({
    readBootstrap: async () => ({ initialized: true }),
    readSession: async () => (hold ? pending.promise : identity),
  });
  await workflow.restore();
  hold = true;
  const revalidation = workflow.revalidateAccess();
  assert.deepEqual(workflow.getSnapshot().access, { phase: "checking" });
  pending.resolve(identity);
  await revalidation;
  workflow.dispose();
});
test("F2 foreground observer revalidates only when visible and detaches both listeners", async () => {
  const listeners = new Map();
  const target = {
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type);
    },
  };
  let reads = 0,
    visibilityState = "hidden";
  const documentTarget = Object.create(target);
  Object.defineProperty(documentTarget, "visibilityState", { get: () => visibilityState });
  const workflow = make({
    readBootstrap: async () => {
      reads++;
      return { initialized: true };
    },
  });
  await workflow.restore();
  const stop = observeAuthenticationForeground(workflow, target, documentTarget);
  listeners.get("focus")();
  listeners.get("visibilitychange")();
  assert.equal(reads, 1);
  visibilityState = "visible";
  listeners.get("visibilitychange")();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(reads, 2);
  stop();
  assert.equal(listeners.size, 0);
  workflow.dispose();
});
test("F4.21 a setup tab returning to the foreground accepts the initialized server fact", async () => {
  const listeners = new Map();
  const target = {
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type);
    },
  };
  let initialized = false,
    visibilityState = "visible",
    bootstrapReads = 0,
    sessionReads = 0;
  const documentTarget = Object.create(target);
  Object.defineProperty(documentTarget, "visibilityState", { get: () => visibilityState });
  const workflow = make({
    readBootstrap: async () => {
      bootstrapReads++;
      return initialized
        ? { initialized: true }
        : { initialized: false, setupAvailable: true, operatorAuthorized: true };
    },
    readSession: async () => {
      sessionReads++;
      return null;
    },
  });
  assert.deepEqual(await workflow.restore(), {
    kind: "uninitialized",
    setupAvailable: true,
    operatorAuthorized: true,
  });
  const stop = observeAuthenticationForeground(workflow, target, documentTarget);
  initialized = true;
  visibilityState = "hidden";
  listeners.get("focus")();
  listeners.get("visibilitychange")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(bootstrapReads, 1);

  visibilityState = "visible";
  listeners.get("focus")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(bootstrapReads, 2);
  assert.equal(sessionReads, 1);
  assert.deepEqual(workflow.getSnapshot().access, {
    phase: "resolved",
    facts: { kind: "anonymous" },
  });

  stop();
  assert.equal(listeners.size, 0);
  workflow.dispose();
});
test("F2 explicit bootstrap receipt read supersedes a background focus refresh", async () => {
  const pending = deferred();
  let initialized = false,
    holdForeground = false,
    bootstrapReads = 0;
  const workflow = make({
    readBootstrap: async () => {
      bootstrapReads++;
      if (holdForeground && bootstrapReads === 2) return pending.promise;
      return { initialized, setupAvailable: !initialized, operatorAuthorized: !initialized };
    },
  });
  await workflow.restore();
  holdForeground = true;
  const foreground = workflow.revalidateAccess();
  const foregroundRejected = assert.rejects(
    foreground,
    (error) => error.kind === AppErrorKind.CANCELLED,
  );
  initialized = true;
  const confirmed = await workflow.restore();
  assert.deepEqual(confirmed, { kind: "anonymous" });
  pending.resolve({ initialized: false, setupAvailable: true, operatorAuthorized: true });
  await foregroundRejected;
  assert.equal(workflow.getSnapshot().access.facts.kind, "anonymous");
  assert.equal(bootstrapReads, 3);
  workflow.dispose();
});
test("F2 expire/cancel ignore late login and disposal releases subscriptions with no credential/result retention", async () => {
  const pending = deferred();
  let signals = [];
  const workflow = make({
    login: async (_credentials, signal) => {
      signals.push(signal);
      return pending.promise;
    },
  });
  await workflow.restore();
  const running = workflow.login(credentials);
  const rejected = assert.rejects(running);
  await Promise.resolve();
  workflow.expire();
  await rejected;
  assert.ok(signals[0].aborted);
  pending.resolve(identity);
  await Promise.resolve();
  assert.equal(workflow.getSnapshot().access.phase, "expired");
  workflow.dispose();
  workflow.dispose();
  assert.deepEqual(workflow.getSnapshot(), {
    access: { phase: "expired" },
    login: { status: "idle" },
    logout: { status: "idle" },
  });
  await assert.rejects(workflow.restore(), (error) => error.kind === AppErrorKind.CANCELLED);
});
test("F2 authentication snapshot identity stays stable for no-op cancellation and unsubscribe is idempotent", () => {
  const workflow = make();
  const before = workflow.getSnapshot();
  let calls = 0;
  const unsubscribe = workflow.subscribe(() => calls++);
  const initial = calls;
  workflow.cancel();
  workflow.cancel();
  assert.strictEqual(workflow.getSnapshot(), before);
  assert.equal(calls, initial);
  unsubscribe();
  unsubscribe();
  workflow.dispose();
});
