import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createAccountManagementWorkflow } from "../../src/features/identity/application/accountManagementWorkflow";
import {
  createRoleDraft,
  changeRoleDraft,
} from "../../src/features/identity/model/accountManagement";
import { accountFeedbackKey } from "../../src/features/identity/presentation/accountFeedback";

const owner = Object.freeze({
  accountId: "admin",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "session-one",
});
const record = Object.freeze({
  id: "one",
  username: "viewer",
  roleId: "view",
  status: "active",
  builtIn: false,
  lastActiveAdmin: false,
  lastLoginAt: null,
  revision: "9007199254740993",
});
const query = Object.freeze({ page: 1, pageSize: 20, search: "" });
const draft = Object.freeze({
  username: " viewer ",
  password: " SYNTHETIC-ACCOUNT-PASSWORD ",
  roleId: "view",
});
function deferred() {
  let resolve;
  const promise = new Promise((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
function make(overrides = {}, options = {}, sessionOverrides = {}) {
  let access = { phase: "resolved", facts: { kind: "authenticated", identity: owner } },
    key = 0;
  const listeners = new Set();
  const calls = [];
  const port = {
    listAccounts: async (input) => {
      calls.push(["list", input]);
      return { items: [record], page: input.page, pageSize: input.pageSize, total: 1 };
    },
    readAccount: async (id) => {
      calls.push(["read", id]);
      return id === record.id ? record : null;
    },
    mutateAccount: async (input) => {
      calls.push(["mutate", input.kind]);
      return { status: "completed", requestKey: input.requestKey, account: record };
    },
    readAccountOperation: async (requestKey) => {
      calls.push(["inspect", requestKey]);
      return { status: "completed", requestKey, account: record };
    },
    ...overrides,
  };
  const session = {
    read: () => access,
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    revalidateAccess: async () => undefined,
    ...sessionOverrides,
  };
  const workflow = createAccountManagementWorkflow(
    port,
    owner,
    session,
    () => `request-${++key}`,
    options,
  );
  return {
    workflow,
    calls,
    listeners,
    setAccess: (next) => {
      access = next;
      [...listeners].forEach((fn) => fn());
    },
  };
}
test("ACCOUNT-LIFECYCLE: allow own password reset while protecting self-delete, foreign built-in, and last admin", async () => {
  const seen = [];
  const { workflow } = make({
    mutateAccount: async (input) => {
      seen.push(input);
      return {
        status: "completed",
        requestKey: input.requestKey,
        account: {
          ...record,
          id: input.accountId,
          revision: "9007199254740994",
          status: input.kind === "delete" ? "disabled" : "active",
        },
      };
    },
  });
  assert.equal(workflow.ownerAccountId, owner.accountId);
  await workflow.resetPassword(record, draft.password);
  assert.equal(seen[0].revision, record.revision);
  assert.equal(seen[0].password, draft.password);
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC-ACCOUNT-PASSWORD/);
  await workflow.deleteAccount(record);
  assert.equal(seen[1].kind, "delete");
  const selfReset = await workflow.resetPassword(
    { ...record, id: owner.accountId },
    draft.password,
  );
  assert.equal(selfReset.status, "completed");
  assert.equal(seen[2].kind, "reset_password");
  assert.equal(seen[2].accountId, owner.accountId);
  for (const target of [{ ...record, builtIn: true }]) {
    await assert.rejects(workflow.resetPassword(target, draft.password));
    await assert.rejects(workflow.deleteAccount(target));
  }
  await assert.rejects(workflow.deleteAccount({ ...record, id: owner.accountId }));
  await assert.rejects(workflow.deleteAccount({ ...record, lastActiveAdmin: true }));
  await assert.rejects(workflow.resetPassword(record, "short"));
  assert.equal(seen.length, 3);
  workflow.dispose();
});

test("ACCOUNT-OWNER: viewer/unresolved/new session cannot read or mutate; privilege loss immediately drops every published directory/detail", async () => {
  const { workflow, calls, setAccess } = make();
  await workflow.list(query);
  await workflow.select("one");
  const states = [];
  const stop = workflow.subscribe(() => states.push(workflow.getSnapshot()));
  // StateStore sends the current value immediately; observe transitions after expiry only.
  states.length = 0;
  setAccess({
    phase: "resolved",
    facts: { kind: "authenticated", identity: { ...owner, roleId: "view" } },
  });
  assert.equal(workflow.getSnapshot().authorized, false);
  assert.equal(workflow.getSnapshot().directory.status, "idle");
  assert.equal(workflow.getSnapshot().detail.status, "idle");
  for (const action of [
    () => workflow.list(query),
    () => workflow.select("one"),
    () => workflow.create(draft),
  ])
    await assert.rejects(action(), (error) => error.kind === AppErrorKind.FORBIDDEN);
  assert.equal(calls.length, 2);
  assert.ok(
    states.every(
      (snapshot) =>
        !snapshot.authorized &&
        snapshot.directory.status === "idle" &&
        snapshot.detail.status === "idle",
    ),
  );
  stop();
  workflow.dispose();
});
test("ACCOUNT-LIST: complete ownership/filter key; unknown target is empty, never another account", async () => {
  const { workflow, calls } = make();
  await assert.rejects(workflow.list({ ...query, page: 0 }));
  assert.equal(calls.length, 0);
  await workflow.list(query);
  const key = workflow.getSnapshot().directory.key;
  await workflow.list({ ...query, search: "other", page: 2 });
  assert.notEqual(workflow.getSnapshot().directory.key, key);
  await workflow.list({ ...query, search: "  VIEWER  " });
  assert.equal(calls.at(-1)[1].search, "VIEWER");
  await workflow.select("missing");
  assert.equal(workflow.getSnapshot().detail.status, "empty");
  assert.equal(workflow.getSnapshot().detail.data, null);
  workflow.dispose();
});
test("ACCOUNT-LIST: cancelling a directory query does not cancel selected detail or a pending command", async () => {
  const listing = deferred(),
    detail = deferred(),
    mutation = deferred();
  const { workflow, calls } = make({
    listAccounts: async (input) => {
      calls.push(["list", input]);
      return listing.promise;
    },
    readAccount: async (id) => {
      calls.push(["read", id]);
      return detail.promise;
    },
    mutateAccount: async (input) => {
      calls.push(["mutate", input.kind]);
      return mutation.promise;
    },
  });
  const listRequest = workflow.list(query),
    detailRequest = workflow.select(record.id),
    commandRequest = workflow.create(draft);

  workflow.cancelDirectory();

  await assert.rejects(listRequest, (error) => error.kind === AppErrorKind.CANCELLED);
  assert.equal(workflow.getSnapshot().detail.status, "loading");
  assert.equal(workflow.getSnapshot().mutation.status, "pending");
  detail.resolve(record);
  assert.equal(await detailRequest, record);
  workflow.dispose();
  await assert.rejects(commandRequest, (error) => error.kind === AppErrorKind.CANCELLED);
});
test("ACCOUNT-SELECT: a late detail read cannot replace the current URL account target", async () => {
  const first = deferred(),
    second = deferred();
  const { workflow } = make({
    readAccount: (id) => (id === "one" ? first.promise : second.promise),
  });
  const previous = workflow.select("one");
  const current = workflow.select("two");
  second.resolve({ ...record, id: "two", username: "second" });
  assert.equal((await current).id, "two");
  first.resolve(record);
  await assert.rejects(previous, (error) => error.kind === AppErrorKind.CANCELLED);
  assert.equal(workflow.getSnapshot().detail.data.id, "two");
  assert.equal(workflow.getSnapshot().detail.data.username, "second");
  workflow.dispose();
});
test("ACCOUNT-CREATE: pending single flight, safe operation identity and server generated record, confirmed success invalidates/refetches only current reads", async () => {
  const pending = deferred();
  let received;
  const { workflow, calls } = make({
    mutateAccount: async (input) => {
      received = input;
      calls.push(["mutate", input.kind]);
      return pending.promise;
    },
  });
  await workflow.list(query);
  const running = workflow.create(draft);
  await Promise.resolve();
  await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(workflow.getSnapshot().mutation.status, "pending");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC/);
  assert.deepEqual(received.input, {
    username: "viewer",
    password: draft.password,
    roleId: "view",
  });
  pending.resolve({ status: "completed", requestKey: received.requestKey, account: record });
  const result = await running;
  assert.equal(result.status, "completed");
  assert.equal(workflow.getSnapshot().mutation.status, "success");
  assert.equal(calls.filter(([kind]) => kind === "mutate").length, 1);
  assert.equal(calls.filter(([kind]) => kind === "list").length, 2);
  workflow.dispose();
});
test("ACCOUNT-CREATE: completed receipts must match active non-built-in never-logged-in creation facts", async () => {
  const mismatchedFacts = [
    { status: "disabled" },
    { builtIn: true },
    { lastLoginAt: "2026-10-11T00:00:00Z" },
  ];

  for (const facts of mismatchedFacts) {
    let writes = 0;
    const { workflow } = make({
      mutateAccount: async (input) => {
        writes++;
        return {
          status: "completed",
          requestKey: input.requestKey,
          account: { ...record, ...facts },
        };
      },
    });

    await assert.rejects(
      workflow.create(draft),
      (error) => error.code === "account_receipt_invalid",
    );
    assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /SYNTHETIC/);
    await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
    assert.equal(writes, 1, "a malformed completion must never be blindly replayed");
    workflow.dispose();
  }
});
test("ACCOUNT-CREATE: operation inspection cannot accept a mismatched completed account", async () => {
  let writes = 0;
  const { workflow } = make({
    mutateAccount: async () => {
      writes++;
      throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-ACCOUNT-ERROR");
    },
    readAccountOperation: async (requestKey) => ({
      status: "completed",
      requestKey,
      account: { ...record, status: "disabled" },
    }),
  });

  await assert.rejects(workflow.create(draft));
  await assert.rejects(workflow.inspect(), (error) => error.code === "account_receipt_invalid");
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-ACCOUNT-ERROR|SYNTHETIC/);
  await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(writes, 1);
  workflow.dispose();
});
test("ACCOUNT-CREATE: unknown result cannot be replayed; correlated explicit lookup resolves it, missing/incorrect lookup never unlocks", async () => {
  let mode = "missing",
    writes = 0;
  const { workflow } = make({
    mutateAccount: async () => {
      writes++;
      throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-ACCOUNT-ERROR");
    },
    readAccountOperation: async (requestKey) =>
      mode === "missing"
        ? { status: "not-found", requestKey }
        : mode === "mismatch"
          ? { status: "completed", requestKey: "wrong", account: record }
          : { status: "completed", requestKey, account: record },
  });
  await assert.rejects(workflow.create(draft));
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-ACCOUNT-ERROR|SYNTHETIC/);
  for (const value of ["missing", "mismatch"]) {
    mode = value;
    await workflow.inspect().catch(() => {});
    await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
  }
  mode = "completed";
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().mutation.status, "success");
  assert.equal(writes, 1);
  workflow.dispose();
});
test("ACCOUNT-INSPECT-CONCURRENCY: unknown mutation allows one lookup, keeps reads available, and blocks writes", async () => {
  const lookup = deferred();
  const lookupStarted = deferred();
  let writes = 0,
    lookups = 0;
  const { workflow, calls } = make({
    mutateAccount: async () => {
      writes++;
      calls.push(["mutate", "create"]);
      throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-ACCOUNT-ERROR");
    },
    readAccountOperation: (requestKey) => {
      lookups++;
      calls.push(["inspect", requestKey]);
      lookupStarted.resolve();
      return lookup.promise.then(() => ({ status: "not-found", requestKey }));
    },
  });

  await assert.rejects(workflow.create(draft));
  const inspecting = workflow.inspect();
  await lookupStarted.promise;

  assert.equal(workflow.getSnapshot().inspecting, true);
  await assert.rejects(workflow.inspect(), (error) => error.kind === AppErrorKind.DUPLICATE);
  await workflow.list(query);
  await workflow.select(record.id);
  assert.equal(workflow.getSnapshot().inspecting, true);
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.equal(lookups, 1);
  assert.equal(writes, 1);

  lookup.resolve();
  assert.deepEqual(await inspecting, { status: "not-found", requestKey: "request-1" });
  assert.equal(workflow.getSnapshot().inspecting, false);
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  assert.equal(calls.filter(([kind]) => kind === "mutate").length, 1);
  assert.equal(calls.filter(([kind]) => kind === "inspect").length, 1);
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-ACCOUNT-ERROR|SYNTHETIC/);
  workflow.dispose();
});
test("ACCOUNT-CREATE: an HTTP timeout is unknown until final server rejection is inspected; retry uses a new key", async () => {
  const keys = [];
  const { workflow } = make({
    mutateAccount: async (input) => {
      keys.push(input.requestKey);
      throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-ACCOUNT-ERROR");
    },
    readAccountOperation: async (requestKey) => ({
      status: "rejected",
      requestKey,
      reason: "username_taken",
    }),
  });
  await assert.rejects(workflow.create(draft));
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().mutation.status, "conflict");
  await assert.rejects(workflow.create(draft));
  assert.deepEqual(keys, ["request-1", "request-2"]);
  workflow.dispose();
});
test("ACCOUNT-STATUS / ROLE-COMMIT: missing/protected/unchanged and stale baseline never dispatch; revision and target accompany actual commands", async () => {
  const mutations = [];
  const { workflow } = make({
    mutateAccount: async (input) => {
      mutations.push(input);
      return {
        status: "completed",
        requestKey: input.requestKey,
        account: {
          ...record,
          roleId: input.roleId ?? record.roleId,
          status: input.status ?? record.status,
          revision: "9007199254740994",
        },
      };
    },
  });
  for (const target of [null, { ...record, builtIn: true }, { ...record, lastActiveAdmin: true }])
    await assert.rejects(workflow.setStatus(target, "disabled"));
  assert.equal(mutations.length, 0);
  const changed = changeRoleDraft(createRoleDraft(record), "admin");
  await assert.rejects(
    workflow.setRole({ ...record, revision: "9007199254740994" }, changed),
    (error) => error.status === 409,
  );
  assert.equal(mutations.length, 0);
  await workflow.setRole(record, changed);
  assert.equal(mutations[0].accountId, record.id);
  assert.equal(mutations[0].revision, record.revision);
  assert.equal(mutations[0].roleId, "admin");
  workflow.dispose();
});
test("ROLE-REFRESH: an authoritative latest read clears a terminal role conflict without replaying the write", async () => {
  const latest = { ...record, roleId: "admin", revision: "9007199254740994" };
  let writes = 0,
    failRead = false;
  const { workflow } = make({
    readAccount: async (id) => {
      if (failRead) throw new AppError(AppErrorKind.NETWORK, "private account read failure");
      return id === record.id ? latest : null;
    },
    mutateAccount: async (input) => {
      writes++;
      return { status: "rejected", requestKey: input.requestKey, reason: "conflict" };
    },
  });
  const changed = changeRoleDraft(createRoleDraft(record), "admin");

  const receipt = await workflow.setRole(record, changed);
  assert.equal(receipt.status, "rejected");
  assert.equal(workflow.getSnapshot().mutation.status, "conflict");

  failRead = true;
  await assert.rejects(workflow.select(record.id));
  assert.equal(workflow.getSnapshot().mutation.status, "conflict");
  failRead = false;
  const reread = await workflow.select(record.id);
  assert.equal(reread.revision, latest.revision);
  assert.equal(reread.roleId, latest.roleId);
  assert.equal(workflow.getSnapshot().detail.data.revision, latest.revision);
  assert.equal(workflow.getSnapshot().mutation.status, "idle");
  assert.equal(workflow.getSnapshot().operation, null);
  assert.equal(writes, 1, "reading the latest record must not replay the rejected command");
  workflow.dispose();
});
test("ROLE-REFRESH: an authoritative latest read clears a locally detected stale-revision conflict", async () => {
  const latest = { ...record, revision: "9007199254740994" };
  let writes = 0;
  const { workflow } = make({
    readAccount: async (id) => (id === record.id ? latest : null),
    mutateAccount: async () => {
      writes++;
      return { status: "completed", requestKey: "unexpected", account: latest };
    },
  });
  const staleDraft = changeRoleDraft(createRoleDraft(record), "admin");

  await assert.rejects(workflow.setRole(latest, staleDraft), (error) => error.status === 409);
  assert.equal(workflow.getSnapshot().mutation.status, "conflict");
  assert.equal(
    workflow.getSnapshot().operation,
    null,
    "local validation must not invent a request key",
  );
  await workflow.select(record.id);
  assert.equal(workflow.getSnapshot().mutation.status, "idle");
  assert.equal(writes, 0, "a stale local draft must never reach the mutation port");
  workflow.dispose();
});
test("ROLE-REFRESH: a latest read cannot clear an unknown write outcome", async () => {
  let writes = 0;
  const { workflow } = make({
    readAccount: async (id) => (id === record.id ? { ...record, revision: "2" } : null),
    mutateAccount: async () => {
      writes++;
      throw new AppError(AppErrorKind.TIMEOUT, "private account write timeout");
    },
  });
  const changed = changeRoleDraft(createRoleDraft(record), "admin");

  await assert.rejects(workflow.setRole(record, changed));
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  await workflow.select(record.id);
  assert.equal(workflow.getSnapshot().detail.data.revision, "2");
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  assert.equal(workflow.getSnapshot().operation.requestKey, "request-1");
  assert.equal(writes, 1);
  workflow.dispose();
});
test("ROLE-IN-FLIGHT: synchronous role command stays single-flight until its final receipt arrives", async () => {
  const response = deferred();
  let current = record,
    received,
    writeCount = 0;
  const changed = Object.freeze({ ...record, roleId: "admin", revision: "9007199254740994" });
  const { workflow } = make({
    listAccounts: async (input) => ({
      items: [current],
      page: input.page,
      pageSize: input.pageSize,
      total: 1,
    }),
    readAccount: async (id) => (id === current.id ? current : null),
    mutateAccount: async (input) => {
      received = input;
      writeCount++;
      return response.promise;
    },
    readAccountOperation: async (requestKey) => {
      current = changed;
      return { status: "completed", requestKey, account: changed };
    },
  });
  await workflow.list(query);
  await workflow.select(record.id);
  const roleDraft = changeRoleDraft(createRoleDraft(record), "admin");
  const running = workflow.setRole(record, roleDraft);
  await Promise.resolve();
  assert.equal(workflow.getSnapshot().mutation.status, "pending");
  assert.deepEqual(received, {
    kind: "role",
    requestKey: "request-1",
    accountId: record.id,
    revision: record.revision,
    roleId: "admin",
  });
  await assert.rejects(
    workflow.setRole(record, roleDraft),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  current = changed;
  response.resolve({ status: "completed", requestKey: received.requestKey, account: changed });
  const confirmed = await running;
  assert.equal(confirmed.status, "completed");
  assert.equal(workflow.getSnapshot().mutation.status, "success");
  assert.equal(workflow.getSnapshot().directory.data.items[0].roleId, "admin");
  assert.equal(workflow.getSnapshot().detail.data.roleId, "admin");
  assert.equal(writeCount, 1);
  workflow.dispose();
});
test("ACCOUNT-STATUS: confirmation command uses the selected revision and refreshes the active directory only after a correlated success", async () => {
  const changed = { ...record, status: "disabled", revision: "9007199254740994" };
  let mutation;
  const calls = [];
  const { workflow } = make({
    listAccounts: async (input) => {
      calls.push(["list", input]);
      return { items: [changed], page: input.page, pageSize: input.pageSize, total: 1 };
    },
    mutateAccount: async (input) => {
      mutation = input;
      return { status: "completed", requestKey: input.requestKey, account: changed };
    },
  });
  await workflow.list(query);
  const receipt = await workflow.setStatus(record, "disabled");
  assert.equal(receipt.status, "completed");
  assert.deepEqual(mutation, {
    kind: "status",
    requestKey: "request-1",
    accountId: record.id,
    revision: record.revision,
    status: "disabled",
  });
  assert.equal(workflow.getSnapshot().mutation.status, "success");
  assert.equal(workflow.getSnapshot().directory.data.items[0].status, "disabled");
  assert.equal(calls.length, 2);
  workflow.dispose();
});
test("ACCOUNT-STATUS: concurrent last-admin rejection stays visible and keeps the server-refreshed decision boundary", async () => {
  const { workflow } = make({
    mutateAccount: async (input) => ({
      status: "rejected",
      requestKey: input.requestKey,
      reason: "last_admin",
    }),
  });
  await workflow.list(query);
  const receipt = await workflow.setStatus(record, "disabled");
  assert.equal(receipt.status, "rejected");
  assert.equal(workflow.getSnapshot().mutation.status, "conflict");
  assert.equal(accountFeedbackKey(workflow.getSnapshot()), "management.lastAdmin");
  assert.equal(workflow.getSnapshot().directory.data.items[0].status, "active");
  workflow.dispose();
});
test("ACCOUNT-SELF-MUTATION: direct and inspected role/status confirmations revalidate authority and immediately drop admin data", async () => {
  for (const kind of ["role", "status"]) {
    for (const inspect of [false, true]) {
      const own = {
        ...record,
        id: owner.accountId,
        username: owner.username,
        roleId: "admin",
        status: "active",
      };
      let changedAccess = false,
        revalidationCalls = 0,
        readCalls = 0;
      const confirmed = (requestKey, input) => ({
        status: "completed",
        requestKey,
        account: {
          ...own,
          roleId: input.roleId ?? own.roleId,
          status: input.status ?? own.status,
          revision: "9007199254740994",
        },
      });
      const { workflow, setAccess } = make(
        {
          listAccounts: async (input) => {
            readCalls++;
            return { items: [own], page: input.page, pageSize: input.pageSize, total: 1 };
          },
          readAccount: async () => own,
          mutateAccount: async (input) => {
            if (inspect) throw new AppError(AppErrorKind.TIMEOUT, "private transport detail");
            return confirmed(input.requestKey, input);
          },
          readAccountOperation: async (requestKey) =>
            confirmed(requestKey, kind === "role" ? { roleId: "view" } : { status: "disabled" }),
        },
        {},
        {
          revalidateAccess: async () => {
            revalidationCalls++;
            if (kind === "role" && !changedAccess) {
              changedAccess = true;
              setAccess({
                phase: "resolved",
                facts: {
                  kind: "authenticated",
                  identity: { ...owner, roleId: "view", capabilities: ["metrics:view"] },
                },
              });
              return {
                kind: "authenticated",
                identity: { ...owner, roleId: "view", capabilities: ["metrics:view"] },
              };
            }
            if (kind === "status" && !changedAccess) {
              changedAccess = true;
              setAccess({ phase: "resolved", facts: { kind: "anonymous" } });
              return { kind: "anonymous" };
            }
            return { kind: "authenticated", identity: owner };
          },
        },
      );
      await workflow.list(query);
      await workflow.select(owner.accountId);
      const write = () =>
        kind === "role"
          ? workflow.setRole(own, changeRoleDraft(createRoleDraft(own), "view"))
          : workflow.setStatus(own, "disabled");
      if (inspect) {
        await assert.rejects(write());
        assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
        await workflow.inspect();
      } else {
        await write();
      }
      assert.equal(revalidationCalls, 1);
      assert.equal(changedAccess, true);
      assert.equal(workflow.getSnapshot().authorized, false);
      assert.equal(workflow.getSnapshot().directory.status, "idle");
      assert.equal(workflow.getSnapshot().detail.status, "idle");
      assert.equal(
        readCalls,
        1,
        "must not refresh admin-owned account data after authority is lost",
      );
      workflow.dispose();
    }
  }
});
test("ACCOUNT-SELF-MUTATION: failed authority read preserves the confirmed write but fails closed", async () => {
  const own = {
    ...record,
    id: owner.accountId,
    username: owner.username,
    roleId: "admin",
  };
  let readCalls = 0;
  const { workflow, setAccess } = make(
    {
      listAccounts: async (input) => {
        readCalls++;
        return { items: [own], page: input.page, pageSize: input.pageSize, total: 1 };
      },
      readAccount: async () => own,
      mutateAccount: async (input) => ({
        status: "completed",
        requestKey: input.requestKey,
        account: { ...own, roleId: input.roleId, revision: "9007199254740994" },
      }),
    },
    {},
    {
      revalidateAccess: async () => {
        setAccess({ phase: "unavailable" });
        throw new AppError(AppErrorKind.NETWORK, "private session read detail");
      },
    },
  );
  await workflow.list(query);
  await workflow.select(owner.accountId);
  const receipt = await workflow.setRole(own, changeRoleDraft(createRoleDraft(own), "view"));
  assert.equal(receipt.status, "completed");
  assert.equal(workflow.getSnapshot().authorized, false);
  assert.equal(workflow.getSnapshot().directory.status, "idle");
  assert.equal(workflow.getSnapshot().detail.status, "idle");
  assert.equal(readCalls, 1);
  workflow.dispose();
});
test("ACCOUNT-COMMIT: confirmed write remains success when refresh fails; do not turn committed mutation into safe repeat", async () => {
  let fail = false,
    writes = 0;
  const { workflow } = make({
    listAccounts: async (input) => {
      if (fail) throw new AppError(AppErrorKind.NETWORK, "private");
      return { items: [record], page: input.page, pageSize: input.pageSize, total: 1 };
    },
    mutateAccount: async (input) => {
      writes++;
      fail = true;
      return { status: "completed", requestKey: input.requestKey, account: record };
    },
  });
  await workflow.list(query);
  await workflow.create(draft);
  assert.equal(workflow.getSnapshot().mutation.status, "success");
  assert.equal(workflow.getSnapshot().directory.status, "error");
  assert.equal(writes, 1);
  workflow.dispose();
});
test("ACCOUNT-OWNER: session change aborts an issued command, late result cannot repopulate data, disposal detaches listeners", async () => {
  const pending = deferred();
  let signal;
  const { workflow, setAccess, listeners } = make({
    mutateAccount: async (_input, received) => {
      signal = received;
      return pending.promise;
    },
  });
  const running = workflow.create(draft),
    rejected = assert.rejects(running);
  await Promise.resolve();
  setAccess({ phase: "expired" });
  await rejected;
  assert.ok(signal.aborted);
  pending.resolve({ status: "completed", requestKey: "request-1", account: record });
  await Promise.resolve();
  assert.equal(workflow.getSnapshot().authorized, false);
  assert.equal(workflow.getSnapshot().mutation.status, "idle");
  workflow.dispose();
  workflow.dispose();
  assert.equal(listeners.size, 0);
  await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.CANCELLED);
});
test("ACCOUNT-LOOKUP: bounded read timeout and wrong desired role cannot resolve an unknown mutation", async () => {
  let mode = "hang",
    receivedSignal;
  const { workflow } = make(
    {
      mutateAccount: async () => {
        throw new AppError(AppErrorKind.TIMEOUT, "private");
      },
      readAccountOperation: async (requestKey, signal) => {
        receivedSignal = signal;
        if (mode === "hang") return new Promise(() => {});
        return {
          status: "completed",
          requestKey,
          account: { ...record, roleId: mode === "wrong" ? "view" : "admin" },
        };
      },
    },
    { timeoutMs: 10 },
  );
  const changed = changeRoleDraft(createRoleDraft(record), "admin");
  await assert.rejects(workflow.setRole(record, changed));
  await assert.rejects(workflow.inspect(), (error) => error.kind === AppErrorKind.TIMEOUT);
  assert.ok(receivedSignal.aborted);
  assert.equal(workflow.getSnapshot().inspecting, false);
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  mode = "wrong";
  await assert.rejects(workflow.inspect(), (error) => error.code === "account_receipt_invalid");
  assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
  mode = "correct";
  await workflow.inspect();
  assert.equal(workflow.getSnapshot().mutation.status, "success");
  workflow.dispose();
});
test("ACCOUNT-RECEIPT: malformed commit acknowledgement never unlocks a safe repeat", async () => {
  for (const receipt of [
    null,
    undefined,
    {},
    { status: "completed", requestKey: "request-1", account: { ...record, username: "other" } },
  ]) {
    const { workflow } = make({ mutateAccount: async () => receipt });
    await assert.rejects(workflow.create(draft));
    assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
    await assert.rejects(workflow.create(draft), (error) => error.kind === AppErrorKind.DUPLICATE);
    workflow.dispose();
  }
});
