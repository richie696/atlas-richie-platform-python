import { test } from "node:test";
import assert from "node:assert/strict";
import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import {
  sourceRegistrationDraft,
  prepareSourceMutation,
  changeSourceRegistration,
  sourceOutcomeExpectation,
  validSourceObservation,
  validSourceRegistry,
} from "../../src/features/system/model/sourceRegistration";
import { isRuleSourceEndpoint } from "../../src/shared/model/configurationSource";
import { createSourceRegistrationWorkflow } from "../../src/features/system/application/sourceRegistrationWorkflow";
const record = {
  id: "source-one",
  revision: "source-revision-one",
  name: "Internal config",
  provider: "nacos",
  endpoint: "https://config.test",
  namespace: "namespace-one",
  authenticationMode: "direct",
  credentialConfigured: true,
};
const now = Date.parse("2026-10-07T12:00:00Z");
test("SOURCE-ENDPOINT: source form and wire URL syntax reject malformed hosts and whitespace but retain IPv4, IPv6 and IDN", () => {
  for (const value of [
    " http://nacos.example.com",
    "http://nacos.example.com ",
    "http://nacos.example.com /x",
    "https://nacos.example.com\ufeff",
    "https://nacos.example.com\u0085",
    "https://nacos.example.com/\u001c",
    "http://256.256.256.256",
    "http://1.2.3.999",
    "https://%41.nacos.example.com",
    "http://[v1.invalid]",
    "https://example..com",
    "https://.",
  ])
    assert.equal(isRuleSourceEndpoint(value), false, value);
  for (const value of [
    "http://192.0.2.10:8080",
    "https://[2001:db8::10]:8443",
    "http://[::ffff:192.0.2.1]",
    "https://例子.测试/nacos",
  ])
    assert.equal(isRuleSourceEndpoint(value), true, value);
});
function topology(overrides = {}, workflowOptions = {}) {
  const access = new StateStore({ ownerKey: "source-owner", allowed: true });
  let writes = 0,
    checks = 0,
    lookups = 0,
    key = 0,
    latest;
  const ports = {
    readSources: async () => ({ asOfMs: now, items: [record] }),
    checkSource: async () => {
      checks++;
      return {
        status: "reachable",
        capabilities: ["read"],
        checkedAtMs: now,
        expiresAtMs: now + 10000,
      };
    },
    mutateSource: async (mutation) => {
      writes++;
      latest = {
        requestKey: mutation.requestKey,
        status: "completed",
        record: { ...record, name: mutation.name, revision: "new-revision" },
      };
      return latest;
    },
    readSourceOperation: async () => {
      lookups++;
      return latest;
    },
    ...overrides,
  };
  const workflow = createSourceRegistrationWorkflow(
    ports,
    { read: access.getSnapshot, subscribe: access.subscribe },
    () => `source-request-${++key}`,
    { timeoutMs: 100, ...workflowOptions },
  );
  return { workflow, access, writes: () => writes, checks: () => checks, lookups: () => lookups };
}
test("SOURCE-FORM: keep preserves opaque credentials without reference/password copy; direct/none branches omit all inactive fields", () => {
  const draft = sourceRegistrationDraft(record),
    input = prepareSourceMutation(draft, record);
  assert.equal(input.expectedRevision, record.revision);
  assert.deepEqual(input.source.authentication, { mode: "keep" });
  assert.deepEqual(draft.connection.credentials, {
    reference: "",
    username: "",
    password: "",
    consulToken: "",
  });
  assert.equal(
    prepareSourceMutation(
      { ...draft, connection: { ...draft.connection, provider: "consul" } },
      record,
    ),
    null,
  );
  const replacement = {
    ...draft,
    credentialAction: "replace",
    connection: {
      ...draft.connection,
      authentication: "direct",
      credentials: {
        reference: "SECRET-REFERENCE",
        username: " test ",
        password: " SECRET-PASSWORD ",
        consulToken: "SECRET-TOKEN",
      },
    },
  };
  const replaced = prepareSourceMutation(replacement, record);
  assert.deepEqual(replaced.source.authentication, {
    mode: "direct",
    username: "test",
    password: " SECRET-PASSWORD ",
  });
  assert.ok(!JSON.stringify(replaced).includes("SECRET-TOKEN"));
  assert.deepEqual(
    prepareSourceMutation(
      { ...replacement, connection: { ...replacement.connection, authentication: "none" } },
      record,
    ).source.authentication,
    { mode: "none" },
  );
  const expected = sourceOutcomeExpectation({ ...replaced, requestKey: "source-request" }, record);
  assert.doesNotMatch(JSON.stringify(expected), /SECRET/);
});
test("SOURCE-FORM: provider/policy transitions clear secret and location meaning; invalid registry/receipt cannot masquerade as confirmed source", () => {
  const draft = {
    ...sourceRegistrationDraft(record),
    connection: {
      ...sourceRegistrationDraft(record).connection,
      credentials: {
        reference: "PRIVATE-REF",
        username: "PRIVATE-USER",
        password: "PRIVATE-PASS",
        consulToken: "PRIVATE-TOKEN",
      },
    },
  };
  const changed = changeSourceRegistration(draft, {
    ...draft,
    connection: { ...draft.connection, provider: "consul" },
  });
  assert.equal(changed.credentialAction, "replace");
  assert.equal(changed.connection.credentials.password, "");
  assert.equal(changed.connection.location, "");
  assert.equal(changed.connection.endpoint, "");
  assert.equal(validSourceRegistry({ asOfMs: now, items: [record, record] }), false);
  const expected = sourceOutcomeExpectation(
    { ...prepareSourceMutation(sourceRegistrationDraft(record), record), requestKey: "original" },
    record,
  );
  assert.equal(
    validSourceObservation({ status: "completed", requestKey: "original", record }, expected),
    true,
  );
  for (const value of [
    { status: "completed", requestKey: "other", record },
    { status: "completed", requestKey: "original", record: { ...record, id: "other" } },
    {
      status: "completed",
      requestKey: "original",
      record: { ...record, endpoint: "https://password:secret@config.test" },
    },
  ])
    assert.equal(validSourceObservation(value, expected), false);
});
test("SOURCE-CHECK: checks never mutate registration; generation reset aborts an ignored response and hides old secrets/errors", async () => {
  let release, signal;
  const { workflow } = topology({
    checkSource: async (_input, s) => {
      signal = s;
      return new Promise((resolve) => (release = resolve));
    },
  });
  await workflow.registry.load(null);
  const pending = workflow.checkSource(sourceRegistrationDraft(record), record);
  workflow.invalidateCheck();
  assert.equal(signal.aborted, true);
  release({
    status: "reachable",
    capabilities: ["read"],
    checkedAtMs: now,
    expiresAtMs: now + 10000,
  });
  await assert.rejects(pending);
  assert.equal(workflow.getSnapshot().check.status, "idle");
  assert.equal(workflow.getSnapshot().command.status, "idle");
  workflow.dispose();
});
test("SOURCE-CHECK-SUBMIT: submitting a source cancels a pending probe and ignores its late result", async () => {
  let releaseCheck;
  let checkSignal;
  const { workflow, writes } = topology({
    checkSource: async (_input, signal) => {
      checkSignal = signal;
      return new Promise((resolve) => (releaseCheck = resolve));
    },
  });
  await workflow.registry.load(null);

  const checking = workflow.checkSource(sourceRegistrationDraft(record), record);
  await Promise.resolve();
  assert.ok(checkSignal);
  const created = await workflow.submit(sourceRegistrationDraft(record), record);
  assert.equal(created.id, record.id);
  assert.equal(checkSignal.aborted, true);
  await assert.rejects(checking, (error) => error.kind === AppErrorKind.CANCELLED);
  assert.equal(workflow.getSnapshot().check.status, "idle");
  assert.equal(workflow.getSnapshot().command.status, "success");

  releaseCheck({
    status: "unreachable",
    reason: "connectivity",
    checkedAtMs: now,
    expiresAtMs: now + 10000,
  });
  await new Promise(setImmediate);
  assert.equal(workflow.getSnapshot().check.status, "idle");
  assert.equal(workflow.getSnapshot().command.status, "success");
  assert.equal(writes(), 1);
  workflow.dispose();
});
test("SOURCE-CHECK: a newer request owns the visible result when an older provider ignores cancellation", async () => {
  const pending = [];
  let writes = 0;
  const { workflow } = topology({
    checkSource: async (_input, signal) =>
      new Promise((resolve) => pending.push({ resolve, signal })),
    mutateSource: async (mutation) => {
      writes++;
      return { requestKey: mutation.requestKey, status: "completed", record };
    },
  });
  await workflow.registry.load(null);
  const draft = sourceRegistrationDraft(record),
    first = workflow.checkSource(draft, record),
    second = workflow.checkSource(draft, record);
  assert.equal(pending.length, 2);
  assert.equal(pending[0].signal.aborted, true);
  pending[0].resolve({
    status: "reachable",
    capabilities: ["read"],
    checkedAtMs: now,
    expiresAtMs: now + 10000,
  });
  await assert.rejects(first);
  const latest = {
    status: "unreachable",
    reason: "unsupported",
    checkedAtMs: now + 1,
    expiresAtMs: now + 10001,
  };
  pending[1].resolve(latest);
  assert.deepEqual(await second, latest);
  assert.equal(workflow.getSnapshot().check.status, "partial");
  assert.deepEqual(workflow.getSnapshot().check.data, latest);
  assert.equal(writes, 0);
  workflow.dispose();
});
test("SOURCE-CHECK: redaction preserves bounded retry hints without exposing provider errors", async () => {
  const privateMessage = "PRIVATE-PROVIDER-DETAIL";
  const { workflow } = topology({
    checkSource: async () => {
      throw new AppError(AppErrorKind.RATE_LIMITED, privateMessage, {
        status: 429,
        retryAfterMs: 1500,
        responseBody: { token: "PRIVATE-TOKEN" },
      });
    },
  });
  await workflow.registry.load(null);
  await assert.rejects(workflow.checkSource(sourceRegistrationDraft(record), record));
  const snapshot = workflow.getSnapshot();
  assert.equal(snapshot.check.status, "error");
  assert.equal(snapshot.check.error.status, 429);
  assert.equal(snapshot.check.error.retryAfterMs, 1500);
  assert.equal(snapshot.check.error.message, "Source operation failed");
  assert.equal(snapshot.check.error.responseBody, undefined);
  assert.doesNotMatch(JSON.stringify(snapshot), /PRIVATE-PROVIDER-DETAIL|PRIVATE-TOKEN/);
  workflow.dispose();
});
test("SOURCE-CHECK-COOLDOWN: invalidating edited input cannot bypass the server retry hint", async () => {
  let clock = now,
    checks = 0;
  const access = new StateStore({ ownerKey: "source-owner", allowed: true });
  const workflow = createSourceRegistrationWorkflow(
    {
      readSources: async () => ({ asOfMs: now, items: [record] }),
      checkSource: async () => {
        checks++;
        if (checks === 1)
          throw new AppError(AppErrorKind.RATE_LIMITED, "Private provider detail", {
            status: 429,
            retryAfterMs: 1_500,
          });
        return {
          status: "reachable",
          capabilities: ["read"],
          checkedAtMs: now,
          expiresAtMs: now + 10_000,
        };
      },
      mutateSource: async () => {
        throw new Error("unused");
      },
      readSourceOperation: async () => {
        throw new Error("unused");
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
    () => "source-request-cooldown",
    { clock: () => clock, timeoutMs: 100 },
  );

  await workflow.registry.load(null);
  await assert.rejects(workflow.checkSource(sourceRegistrationDraft(record), record));
  const retryDeadline = workflow.getSnapshot().checkRetryUntilMs;
  assert.equal(retryDeadline, clock + 1_500);

  workflow.invalidateCheck();
  await assert.rejects(
    workflow.checkSource(sourceRegistrationDraft({ ...record, name: "Edited source" }), record),
    (error) => error.kind === AppErrorKind.RATE_LIMITED && error.retryAfterMs === 1_500,
  );
  assert.equal(checks, 1, "the provider port is not called during the local cooldown");
  assert.equal(workflow.getSnapshot().checkRetryUntilMs, retryDeadline);

  clock += 1_500;
  await workflow.checkSource(sourceRegistrationDraft(record), record);
  assert.equal(checks, 2);
  assert.equal(workflow.getSnapshot().checkRetryUntilMs, 0);
  workflow.dispose();
});
test("SOURCE-COMMAND: stale revision never dispatches; equivalent reordered read facts do not falsely conflict", async () => {
  const { workflow, writes } = topology();
  await workflow.registry.load(null);
  await assert.rejects(
    workflow.submit(sourceRegistrationDraft(record), { ...record, revision: "wrong" }),
  );
  assert.equal(writes(), 0);
  const reordered = Object.fromEntries(Object.entries(record).reverse());
  const result = await workflow.submit(sourceRegistrationDraft(reordered), reordered);
  assert.equal(result.id, record.id);
  assert.equal(writes(), 1);
  workflow.dispose();
});
test("SOURCE-UNKNOWN: lost ACK retains only safe identity; pending/not-found lookup never replays, original completion refreshes registry", async () => {
  let writes = 0,
    lookup = "pending",
    original;
  const { workflow } = topology({
    mutateSource: async (mutation) => {
      writes++;
      original = mutation.requestKey;
      throw new AppError(AppErrorKind.NETWORK, "PRIVATE-SOURCE-CREDENTIAL");
    },
    readSourceOperation: async () =>
      lookup === "completed"
        ? { status: "completed", requestKey: original, record }
        : { status: lookup, requestKey: original },
  });
  await workflow.registry.load(null);
  await assert.rejects(workflow.submit(sourceRegistrationDraft(record), record));
  assert.equal(workflow.getSnapshot().command.status, "result-unknown");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-SOURCE/);
  for (const value of ["pending", "not-found"]) {
    lookup = value;
    await workflow.inspect();
    await assert.rejects(workflow.submit(sourceRegistrationDraft(record), record));
    assert.equal(writes, 1);
  }
  lookup = "completed";
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().command.status, "success");
  assert.equal(writes, 1);
  workflow.dispose();
});
test("SOURCE-UNKNOWN: rate-limited operation inspection preserves only safe retry metadata", async () => {
  const privateMessage = "PRIVATE-LOOKUP-DETAIL";
  const { workflow, writes } = topology({
    mutateSource: async () => {
      throw new AppError(AppErrorKind.NETWORK, "PRIVATE-LOST-ACK");
    },
    readSourceOperation: async () => {
      throw new AppError(AppErrorKind.RATE_LIMITED, privateMessage, {
        status: 429,
        retryAfterMs: 1200,
        responseBody: { token: "PRIVATE-LOOKUP-TOKEN" },
      });
    },
  });
  await workflow.registry.load(null);
  await assert.rejects(workflow.submit(sourceRegistrationDraft(record), record));
  await assert.rejects(workflow.inspect());
  const snapshot = workflow.getSnapshot();
  assert.equal(snapshot.command.status, "result-unknown");
  assert.equal(snapshot.inspectionError.status, 429);
  assert.equal(snapshot.inspectionError.retryAfterMs, 1200);
  assert.equal(snapshot.inspectionError.message, "Source operation failed");
  assert.equal(snapshot.inspectionError.responseBody, undefined);
  assert.equal(writes(), 0);
  assert.doesNotMatch(
    JSON.stringify(snapshot),
    /PRIVATE-LOOKUP-DETAIL|PRIVATE-LOOKUP-TOKEN|PRIVATE-LOST-ACK/,
  );
  workflow.dispose();
});
test("SOURCE-SAVE-COOLDOWN: retry metadata blocks workflow dispatch until its deadline", async () => {
  let clock = 1_000,
    writes = 0;
  const { workflow } = topology(
    {
      mutateSource: async (mutation) => {
        writes++;
        if (writes === 1)
          throw new AppError(AppErrorKind.RATE_LIMITED, "Private save detail", {
            status: 429,
            retryAfterMs: 1_200,
          });
        return {
          status: "completed",
          requestKey: mutation.requestKey,
          record: { ...record, revision: "save-revision-two" },
        };
      },
    },
    { clock: () => clock },
  );
  await workflow.registry.load(null);
  await assert.rejects(workflow.submit(sourceRegistrationDraft(record), record));
  for (const remainingMs of [1_200, 1]) {
    await assert.rejects(
      workflow.submit(sourceRegistrationDraft(record), record),
      (error) => error.kind === AppErrorKind.RATE_LIMITED && error.retryAfterMs === remainingMs,
    );
    assert.equal(writes, 1);
    clock += remainingMs === 1_200 ? 1_199 : 1;
  }
  await workflow.submit(sourceRegistrationDraft(record), record);
  assert.equal(writes, 2);
  assert.equal(workflow.getSnapshot().command.status, "success");
  workflow.dispose();
});
test("SOURCE-INSPECT-COOLDOWN: rate limit blocks a repeated lookup and recovers at expiry", async () => {
  let clock = 5_000,
    lookups = 0,
    requestKey;
  const { workflow } = topology(
    {
      mutateSource: async (mutation) => {
        throw new AppError(AppErrorKind.NETWORK, "Private lost acknowledgement");
      },
      readSourceOperation: async (key) => {
        requestKey = key;
        lookups++;
        if (lookups === 1)
          throw new AppError(AppErrorKind.RATE_LIMITED, "Private lookup detail", {
            status: 429,
            retryAfterMs: 900,
          });
        return { status: "pending", requestKey: key };
      },
    },
    { clock: () => clock },
  );
  await workflow.registry.load(null);
  await assert.rejects(workflow.submit(sourceRegistrationDraft(record), record));
  assert.equal(workflow.getSnapshot().command.status, "result-unknown");
  await assert.rejects(workflow.inspect());
  assert.equal(lookups, 1);
  await assert.rejects(
    workflow.inspect(),
    (error) => error.kind === AppErrorKind.RATE_LIMITED && error.retryAfterMs === 900,
  );
  assert.equal(lookups, 1);
  clock += 899;
  await assert.rejects(
    workflow.inspect(),
    (error) => error.kind === AppErrorKind.RATE_LIMITED && error.retryAfterMs === 1,
  );
  assert.equal(lookups, 1);
  clock += 1;
  const observation = await workflow.inspect();
  assert.equal(observation.status, "pending");
  assert.equal(observation.requestKey, requestKey);
  assert.equal(lookups, 2);
  assert.equal(workflow.getSnapshot().command.status, "result-unknown");
  assert.doesNotMatch(
    JSON.stringify(workflow.getSnapshot()),
    /Private lookup detail|Private lost acknowledgement/,
  );
  workflow.dispose();
});
test("SOURCE-REVOKE: first notification hides registry, checks and command facts; a new session cannot inherit the registered source owner", async () => {
  const { workflow, access, writes } = topology();
  await workflow.registry.load(null);
  await workflow.checkSource(sourceRegistrationDraft(record), record);
  await workflow.submit(sourceRegistrationDraft(record), record);
  const snapshots = [];
  workflow.subscribe(() => snapshots.push(workflow.getSnapshot()));
  snapshots.length = 0; // StateStore.subscribe immediately emits the current, still-authorized snapshot.
  access.set({ ownerKey: "source-owner", allowed: false });
  assert.equal(snapshots[0].authorized, false);
  assert.ok(!("data" in snapshots[0].registry));
  assert.ok(!("data" in snapshots[0].check));
  assert.equal(snapshots[0].command.status, "idle");
  access.set({ ownerKey: "new-owner", allowed: true });
  await assert.rejects(workflow.submit(sourceRegistrationDraft(record), record));
  assert.equal(writes(), 1);
  workflow.dispose();
});
