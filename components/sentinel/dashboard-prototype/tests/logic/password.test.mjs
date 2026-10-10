import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  validatePasswordChange,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
} from "../../src/features/identity/model/passwordPolicy";
import { prepareOwnPasswordChange } from "../../src/features/identity/model/ownPasswordChange";
import { createOwnPasswordWorkflow } from "../../src/features/identity/application/ownPasswordWorkflow";

const owner = Object.freeze({
  accountId: "self",
  username: "viewer",
  roleId: "view",
  capabilities: ["metrics:view"],
  sessionEpoch: "session-one",
});
const draft = Object.freeze({
  current: " SYNTHETIC-CURRENT ",
  next: " SYNTHETIC-NEXT-PASSWORD ",
  confirm: " SYNTHETIC-NEXT-PASSWORD ",
});
function deferred() {
  let resolve;
  const promise = new Promise((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
function make(change = async () => ({ sessionDisposition: "reauthenticate" })) {
  let access = { phase: "resolved", facts: { kind: "authenticated", identity: owner } };
  const listeners = new Set();
  const session = {
    read: () => access,
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
  const workflow = createOwnPasswordWorkflow({ changeOwnPassword: change }, owner, session);
  return {
    workflow,
    listeners,
    setAccess: (next) => {
      access = next;
      [...listeners].forEach((fn) => fn());
    },
  };
}
test("PASSWORD-VALIDATE current is required, minimum/confirmation are local and exact passwords are never trimmed", () => {
  assert.equal(
    validatePasswordChange({ ...draft, current: "" })[0].key,
    "password.currentRequired",
  );
  assert.equal(
    validatePasswordChange({ ...draft, next: "x".repeat(PASSWORD_MIN_LENGTH - 1) })[0].key,
    "password.tooShort",
  );
  assert.deepEqual(
    validatePasswordChange({ ...draft, next: "x".repeat(PASSWORD_MAX_LENGTH + 1) })[0],
    { key: "password.tooLong", params: { max: PASSWORD_MAX_LENGTH } },
  );
  assert.deepEqual(
    validatePasswordChange({ ...draft, current: "x".repeat(PASSWORD_MAX_LENGTH + 1) })[0],
    { key: "password.tooLong", params: { max: PASSWORD_MAX_LENGTH } },
  );
  assert.deepEqual(
    validatePasswordChange({
      ...draft,
      next: "😀".repeat(PASSWORD_MAX_LENGTH / 2),
      confirm: "😀".repeat(PASSWORD_MAX_LENGTH / 2),
    }),
    [],
  );
  assert.equal(
    validatePasswordChange({ ...draft, confirm: "not-equal" })[0].key,
    "password.mismatch",
  );
  const prepared = prepareOwnPasswordChange(draft);
  assert.equal(prepared.status, "valid");
  assert.deepEqual(prepared.input, { currentPassword: draft.current, newPassword: draft.next });
  assert.equal(Object.hasOwn(prepared.input, "confirm"), false);
  assert.equal(Object.hasOwn(prepared.input, "accountId"), false);
});
test("PASSWORD-OWNER a viewer may change only their own password; expired/unresolved/different sessions cannot dispatch", async () => {
  let calls = 0;
  const { workflow, setAccess } = make(async () => {
    calls++;
    return { sessionDisposition: "reauthenticate" };
  });
  await workflow.submit(draft);
  assert.equal(calls, 1);
  for (const access of [
    { phase: "unknown" },
    { phase: "expired" },
    { phase: "resolved", facts: { kind: "anonymous" } },
    {
      phase: "resolved",
      facts: { kind: "authenticated", identity: { ...owner, accountId: "other" } },
    },
    {
      phase: "resolved",
      facts: { kind: "authenticated", identity: { ...owner, sessionEpoch: "another-session" } },
    },
  ]) {
    setAccess(access);
    await assert.rejects(workflow.submit(draft), (error) => error.kind === AppErrorKind.FORBIDDEN);
  }
  assert.equal(calls, 1);
  workflow.dispose();
});
test("PASSWORD-OUTCOME invalid fields never dispatch, pending is single-flight, secrets never enter snapshots", async () => {
  const pending = deferred();
  let calls = 0,
    input;
  const { workflow } = make(async (received) => {
    calls++;
    input = received;
    return pending.promise;
  });
  await assert.rejects(
    workflow.submit({ ...draft, current: "" }),
    (error) => error.code === "password_form_invalid",
  );
  await assert.rejects(
    workflow.submit({ ...draft, next: "x".repeat(PASSWORD_MAX_LENGTH + 1) }),
    (error) => error.code === "password_form_invalid",
  );
  assert.equal(calls, 0);
  const running = workflow.submit(draft);
  await Promise.resolve();
  await assert.rejects(workflow.submit(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(workflow.getSnapshot().status, "pending");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC/);
  pending.resolve({ sessionDisposition: "reauthenticate" });
  const result = await running;
  assert.equal(result.sessionDisposition, "reauthenticate");
  assert.deepEqual(input, { currentPassword: draft.current, newPassword: draft.next });
  assert.equal(calls, 1);
  workflow.dispose();
});
test("PASSWORD-OUTCOME known current-password/weak-password/rate-limit errors permit deliberate correction, never auto replay", async () => {
  let calls = 0;
  const { workflow } = make(async () => {
    throw new AppError(AppErrorKind.PROTOCOL, "safe", { status: [400, 422, 429][calls++] });
  });
  for (let i = 0; i < 3; i++) {
    await assert.rejects(workflow.submit(draft));
    assert.equal(workflow.getSnapshot().status, "error");
  }
  assert.equal(calls, 3);
  workflow.dispose();
});
test("PASSWORD-OUTCOME timeout/5xx/cancellation after dispatch are unknown, cannot be reset into repeated password mutation", async () => {
  for (const error of [
    new AppError(AppErrorKind.TIMEOUT, "safe"),
    new AppError(AppErrorKind.SERVER, "safe", { status: 503 }),
  ]) {
    let calls = 0;
    const { workflow } = make(async () => {
      calls++;
      throw error;
    });
    await assert.rejects(workflow.submit(draft));
    assert.equal(workflow.getSnapshot().status, "result-unknown");
    await assert.rejects(workflow.submit(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
    assert.equal(calls, 1);
    workflow.dispose();
  }
});
test("PASSWORD-SESSION owner changes abort observation and a late result cannot be published as success for the new user", async () => {
  const pending = deferred();
  let signal;
  const { workflow, setAccess } = make(async (_input, received) => {
    signal = received;
    return pending.promise;
  });
  const running = workflow.submit(draft);
  const rejected = assert.rejects(running);
  await Promise.resolve();
  setAccess({
    phase: "resolved",
    facts: { kind: "authenticated", identity: { ...owner, accountId: "other" } },
  });
  await rejected;
  assert.ok(signal.aborted);
  pending.resolve({ sessionDisposition: "reauthenticate" });
  await Promise.resolve();
  assert.notEqual(workflow.getSnapshot().status, "success");
  workflow.dispose();
});
test("PASSWORD-SESSION disposal clears result/error and detaches the session observer idempotently", async () => {
  const { workflow, listeners } = make();
  await workflow.submit(draft);
  assert.equal(listeners.size, 1);
  workflow.dispose();
  workflow.dispose();
  assert.equal(listeners.size, 0);
  assert.equal(workflow.getSnapshot().status, "idle");
  await assert.rejects(workflow.submit(draft), (error) => error.kind === AppErrorKind.CANCELLED);
});
test("PASSWORD-OUTCOME malformed write receipts are unknown, not a safe rejection permitting repeated mutation", async () => {
  for (const receipt of [
    null,
    undefined,
    {},
    { sessionDisposition: "retained" },
    { sessionDisposition: "unsupported" },
  ]) {
    let calls = 0;
    const { workflow } = make(async () => {
      calls++;
      return receipt;
    });
    await assert.rejects(workflow.submit(draft));
    assert.equal(workflow.getSnapshot().status, "result-unknown");
    await assert.rejects(workflow.submit(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
    assert.equal(calls, 1);
    workflow.dispose();
  }
});
