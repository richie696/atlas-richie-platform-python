import { test } from "node:test";
import assert from "node:assert/strict";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createRuleOperation } from "../../src/features/rules/application/ruleOperation";
import { validRuleOperationObservation } from "../../src/features/rules/model/ruleOperationPolicy";
import {
  beginRuleSetEditing,
  prepareRuleSetCandidate,
} from "../../src/features/rules/editor/ruleSetEditing";
import { ruleSet } from "../fixtures/ruleSets";
const input = () => ({
  kind: "save_draft",
  draftId: null,
  expectedRevision: null,
  candidate: prepareRuleSetCandidate(beginRuleSetEditing(ruleSet)).candidate,
});
const receipt = (mutation) => ({
  requestKey: mutation.requestKey,
  bindingId: mutation.bindingId,
  status: "completed",
  result: {
    kind: "save_draft",
    draft: {
      id: "draft-one",
      bindingId: "binding-one",
      revision: "revision-one",
      kind: "flow",
      profile: ruleSet.binding.profile,
      baseVersionId: ruleSet.versionId,
      baseChecksum: ruleSet.checksum,
      sourceRevision: ruleSet.sourceRevision,
      updatedAtMs: 100,
      records: ruleSet.records,
    },
  },
});
function topology(overrides = {}, options = {}) {
  let next = 0,
    last;
  const counts = { writes: 0, lookups: 0 };
  const access = new StateStore({ ownerKey: "rule-test-session", allowed: true });
  const owner = createRuleOperation(
    "binding-one",
    {
      mutateRuleSet: async (mutation, signal) => {
        counts.writes++;
        last = mutation;
        return overrides.write ? overrides.write(mutation, signal) : receipt(mutation);
      },
      readRuleOperation: async (bindingId, key, signal) => {
        counts.lookups++;
        return overrides.lookup ? overrides.lookup(last, key, signal) : receipt(last);
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
    () => `request-${++next}`,
    options,
  );
  return { owner, access, counts, last: () => last };
}
test("RULE-OPERATION: correlated complete save returns server identities, no optimistic rule id or write body in pending state", async () => {
  let resolve;
  const { owner, counts } = topology({
    write: (mutation) =>
      new Promise((done) => {
        resolve = () => done(receipt(mutation));
      }),
  });
  const promise = owner.run(input());
  await Promise.resolve();
  assert.equal(owner.getSnapshot().command.status, "pending");
  assert.ok(!JSON.stringify(owner.getSnapshot()).includes("POST /orders"));
  await assert.rejects(owner.run(input()), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(counts.writes, 1);
  resolve();
  const result = await promise;
  assert.equal(result.draft.id, "draft-one");
  assert.equal(owner.getSnapshot().command.status, "success");
  owner.dispose();
});
test("RULE-OPERATION: unknown ACK requires original lookup; not-found/pending/wrong content cannot unlock or resend", async () => {
  let outcome = "not-found";
  const { owner, counts } = topology({
    write: async () => {
      throw new AppError(AppErrorKind.NETWORK, "PRIVATE-RAW-ERROR", { code: "PRIVATE-CODE" });
    },
    lookup: async (mutation) =>
      outcome === "wrong"
        ? {
            ...receipt(mutation),
            result: {
              ...receipt(mutation).result,
              draft: { ...receipt(mutation).result.draft, baseChecksum: "wrong" },
            },
          }
        : outcome === "completed"
          ? receipt(mutation)
          : { requestKey: mutation.requestKey, bindingId: mutation.bindingId, status: outcome },
  });
  await assert.rejects(owner.run(input()), (error) => !error.message.includes("PRIVATE"));
  assert.equal(owner.getSnapshot().command.status, "result-unknown");
  assert.ok(!JSON.stringify(owner.getSnapshot()).includes("PRIVATE"));
  for (const status of ["not-found", "pending"]) {
    outcome = status;
    await owner.inspect();
    assert.equal(owner.getSnapshot().command.status, "result-unknown");
    await assert.rejects(owner.run(input()));
  }
  outcome = "wrong";
  await assert.rejects(owner.inspect());
  assert.equal(owner.getSnapshot().command.status, "result-unknown");
  outcome = "completed";
  await owner.inspect();
  assert.equal(owner.getSnapshot().command.status, "success");
  assert.equal(counts.writes, 1);
  assert.equal(counts.lookups, 4);
  owner.dispose();
});
test("RULE-OPERATION: pending acceptance is unknown, while durable rejection is terminal even for unavailable source", async () => {
  const pending = topology({
    write: async (mutation) => ({
      status: "pending",
      requestKey: mutation.requestKey,
      bindingId: mutation.bindingId,
    }),
  });
  await assert.rejects(pending.owner.run(input()));
  assert.equal(pending.owner.getSnapshot().command.status, "result-unknown");
  await pending.owner.inspect();
  assert.equal(pending.owner.getSnapshot().command.status, "success");
  pending.owner.dispose();
  const rejected = topology({
    write: async (mutation) => ({
      status: "rejected",
      reason: "unavailable",
      requestKey: mutation.requestKey,
      bindingId: mutation.bindingId,
    }),
  });
  await assert.rejects(rejected.owner.run(input()));
  assert.equal(rejected.owner.getSnapshot().command.status, "error");
  await assert.rejects(rejected.owner.run(input()));
  assert.equal(rejected.counts.writes, 2);
  rejected.owner.dispose();
});
test("RULE-OPERATION: timeout aborts a hung Port and has no automatic retry; completed lookup restores a known outcome", async () => {
  let signal;
  const { owner, counts } = topology(
    {
      write: async (_, s) => {
        signal = s;
        return new Promise(() => {});
      },
    },
    { timeoutMs: 5 },
  );
  await assert.rejects(owner.run(input()));
  assert.equal(signal.aborted, true);
  assert.equal(owner.getSnapshot().command.status, "result-unknown");
  await assert.rejects(owner.run(input()));
  assert.equal(counts.writes, 1);
  await owner.inspect();
  assert.equal(owner.getSnapshot().command.status, "success");
  owner.dispose();
});
test("RULE-OPERATION: first revocation hides all completed facts; changed owner cannot inherit or refill old operations", async () => {
  const { owner, access } = topology();
  await owner.run(input());
  const observed = [];
  const unsubscribe = owner.subscribe(() => observed.push(owner.getSnapshot()));
  observed.length = 0;
  access.set({ ownerKey: "rule-test-session", allowed: false });
  assert.equal(observed[0].authorized, false);
  assert.deepEqual(observed[0].command, { status: "idle" });
  assert.equal(observed[0].operation, null);
  access.set({ ownerKey: "rule-test-session", allowed: true });
  assert.equal(owner.getSnapshot().command.status, "idle");
  access.set({ ownerKey: "new-session", allowed: true });
  await assert.rejects(owner.run(input()), (error) => error.status === 403);
  unsubscribe();
  owner.dispose();
});
test("RULE-OPERATION: ignored late write cannot expose facts after revocation; same session can only inspect the original operation", async () => {
  let release, signal;
  const { owner, access } = topology({
    write: (mutation, s) => {
      signal = s;
      return new Promise((done) => {
        release = () => done(receipt(mutation));
      });
    },
  });
  const promise = owner.run(input());
  await Promise.resolve();
  access.set({ ownerKey: "rule-test-session", allowed: false });
  assert.equal(signal.aborted, true);
  release();
  await assert.rejects(promise);
  assert.equal(owner.getSnapshot().authorized, false);
  assert.equal(owner.getSnapshot().operation, null);
  access.set({ ownerKey: "rule-test-session", allowed: true });
  assert.equal(owner.getSnapshot().command.status, "result-unknown");
  await assert.rejects(owner.run(input()));
  await owner.inspect();
  assert.equal(owner.getSnapshot().command.status, "success");
  owner.dispose();
});
test("RULE-OPERATION: synchronous success subscriber cannot overwrite request identity with a reentrant write", async () => {
  const { owner, counts } = topology();
  let attempted = false,
    second;
  const unsubscribe = owner.subscribe(() => {
    if (!attempted && owner.getSnapshot().command.status === "success") {
      attempted = true;
      second = owner.run(input());
      second.catch(() => {});
    }
  });
  await owner.run(input());
  await assert.rejects(second, (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(counts.writes, 1);
  assert.equal(owner.getSnapshot().operation.requestKey, "request-1");
  unsubscribe();
  owner.dispose();
});
test("RULE-OPERATION: wrong binding never dispatches; invalid receipt is unknown and inspection errors are redacted", async () => {
  const { owner, counts } = topology({
    write: async (mutation) => ({ ...receipt(mutation), bindingId: "wrong" }),
    lookup: async () => {
      throw new AppError(AppErrorKind.NETWORK, "PRIVATE-LOOKUP");
    },
  });
  await assert.rejects(
    owner.run({ ...input(), candidate: { ...input().candidate, bindingId: "wrong" } }),
  );
  assert.equal(counts.writes, 0);
  await assert.rejects(owner.run(input()));
  assert.equal(owner.getSnapshot().command.status, "result-unknown");
  await assert.rejects(owner.inspect(), (error) => !error.message.includes("PRIVATE"));
  assert.equal(owner.getSnapshot().command.status, "result-unknown");
  owner.dispose();
});
test("RULE-OPERATION-MATCH: kind, target, base, revision and full candidate facts are required", () => {
  const mutation = { ...input(), bindingId: "binding-one", requestKey: "request-one" },
    good = receipt(mutation);
  assert.equal(validRuleOperationObservation(good, mutation, false), true);
  for (const bad of [
    { ...good, requestKey: "another" },
    { ...good, result: { kind: "delete_draft", draftId: "draft-one" } },
    {
      ...good,
      result: {
        ...good.result,
        draft: { ...good.result.draft, records: [...ruleSet.records].reverse() },
      },
    },
    { ...good, result: { ...good.result, draft: { ...good.result.draft, records: [] } } },
  ])
    assert.equal(validRuleOperationObservation(bad, mutation, false), false);
  assert.equal(
    validRuleOperationObservation({ ...good, status: "not-found" }, mutation, false),
    false,
  );
  assert.equal(
    validRuleOperationObservation({ ...good, status: "not-found" }, mutation, true),
    true,
  );
});
