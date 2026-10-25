import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createQueryResource } from "../../src/shared/state/queryResource";
import { createCommandResource } from "../../src/shared/state/commandResource";
import { routePageOwnerKey } from "../../src/app/router/routeOwner";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const keyOf = (query) =>
  JSON.stringify([query.session, query.env, query.app, query.instance, query.scope, query.range]);
const query = Object.freeze({
  session: "s1",
  env: "prod",
  app: "orders",
  instance: null,
  scope: "application",
  range: "1h",
});
const make = (read, classify = () => "ready") =>
  createQueryResource({ keyOf, read, classify, clock: () => 42 });

test("F2 page owner identity changes with the authenticated session, not just the route", () => {
  assert.equal(
    routePageOwnerKey("realtime", "session-one"),
    routePageOwnerKey("realtime", "session-one"),
  );
  assert.notEqual(
    routePageOwnerKey("realtime", "session-one"),
    routePageOwnerKey("realtime", "session-two"),
  );
  assert.notEqual(
    routePageOwnerKey("realtime", null),
    routePageOwnerKey("realtime", "session-one"),
  );
  assert.notEqual(
    routePageOwnerKey("faults", "session-one"),
    routePageOwnerKey("realtime", "session-one"),
  );
});

test("F2 no-op cleanup keeps stable snapshots and unsubscribe is idempotent", () => {
  const resource = make(async () => []),
    command = createCommandResource(async () => ({}));
  for (const owner of [resource, command]) {
    const original = owner.getSnapshot();
    let notifications = 0;
    const unsubscribe = owner.subscribe(() => notifications++);
    const initialNotifications = notifications;
    owner.reset();
    owner.reset();
    assert.strictEqual(owner.getSnapshot(), original);
    assert.equal(notifications, initialNotifications);
    unsubscribe();
    unsubscribe();
    owner.dispose();
  }
});

for (const quality of ["ready", "empty", "filtered-empty", "partial"]) {
  test(`F2 query represents ${quality} with one valid discriminator`, async () => {
    const resource = make(
      async () => [],
      () => quality,
    );
    assert.equal(resource.getSnapshot().status, "idle");
    const result = resource.load(query);
    assert.equal(resource.getSnapshot().status, "loading");
    await result;
    assert.equal(resource.getSnapshot().status, quality);
    assert.equal(resource.getSnapshot().receivedAt, 42);
    resource.dispose();
  });
}

test("F2 refresh retains same-key data, marks stale on failure and recovers", async () => {
  let fail = false;
  const resource = make(async () => {
    if (fail) throw new AppError(AppErrorKind.NETWORK, "offline");
    return [1];
  });
  await resource.load(query);
  fail = true;
  const refresh = resource.load(query);
  assert.equal(resource.getSnapshot().status, "refreshing");
  assert.deepEqual(resource.getSnapshot().data, [1]);
  await assert.rejects(refresh);
  assert.equal(resource.getSnapshot().status, "stale");
  assert.deepEqual(resource.getSnapshot().data, [1]);
  fail = false;
  await resource.load(query);
  assert.equal(resource.getSnapshot().status, "ready");
  resource.dispose();
});

for (const dimension of ["session", "env", "app", "instance", "scope", "range"]) {
  test(`F2 changing ${dimension} never displays the old query's value`, async () => {
    const next = deferred();
    let count = 0;
    const resource = make(() => (++count === 1 ? Promise.resolve(["old"]) : next.promise));
    await resource.load(query);
    const changed = resource.load({ ...query, [dimension]: "changed" });
    assert.equal(resource.getSnapshot().status, "loading");
    assert.equal("data" in resource.getSnapshot(), false);
    next.resolve(["new"]);
    await changed;
    assert.deepEqual(resource.getSnapshot().data, ["new"]);
    resource.dispose();
  });
}

test("F2 stale response cannot overwrite a new key even if the Port ignores AbortSignal", async () => {
  const old = deferred(),
    recent = deferred();
  let count = 0,
    oldSignal;
  const resource = make((_, signal) => {
    count++;
    if (count === 1) oldSignal = signal;
    return count === 1 ? old.promise : recent.promise;
  });
  const earlier = resource.load(query);
  const rejection = assert.rejects(earlier, (error) => error.kind === AppErrorKind.CANCELLED);
  const latest = resource.load({ ...query, app: "new" });
  assert.ok(oldSignal.aborted);
  await rejection;
  recent.resolve(["current"]);
  await latest;
  old.resolve(["obsolete"]);
  await Promise.resolve();
  assert.deepEqual(resource.getSnapshot().data, ["current"]);
  resource.dispose();
});

for (const kind of [AppErrorKind.UNAUTHORIZED, AppErrorKind.FORBIDDEN]) {
  test(`F2 ${kind} drops last-known-good instead of retaining privileged data`, async () => {
    let count = 0;
    const resource = make(async () => {
      if (++count > 1) throw new AppError(kind, "denied");
      return ["private"];
    });
    await resource.load(query);
    await assert.rejects(resource.load(query));
    assert.equal(resource.getSnapshot().status, "denied");
    assert.equal("data" in resource.getSnapshot(), false);
    resource.dispose();
  });
}

test("F2 reset/unmount cancel clears ownership and disposal rejects future work", async () => {
  const pending = deferred();
  const resource = make(() => pending.promise);
  const rejection = assert.rejects(resource.load(query));
  resource.reset();
  await rejection;
  pending.resolve(["late"]);
  await Promise.resolve();
  assert.equal(resource.getSnapshot().status, "idle");
  resource.dispose();
  await assert.rejects(resource.load(query), (error) => error.kind === AppErrorKind.CANCELLED);
});

test("F2 query timeout is an error, not zero/empty data", async () => {
  let signal;
  const resource = createQueryResource({
    keyOf,
    read: (_input, received) => {
      signal = received;
      return new Promise(() => {});
    },
    classify: () => "ready",
    timeoutMs: 5,
  });
  await assert.rejects(resource.load(query));
  assert.equal(resource.getSnapshot().status, "error");
  assert.equal("data" in resource.getSnapshot(), false);
  assert.ok(signal.aborted, "Timeout must abort the loader, not only stop observing it");
  resource.dispose();
});

for (const status of [404, 410])
  test(`F2 authoritative ${status} clears a previously trusted same-key value; cancel cannot resurrect it`, async () => {
    let missing = false;
    const resource = make(async () => {
      if (missing) throw new AppError(AppErrorKind.SERVER, "PRIVATE", { status });
      return ["obsolete-target"];
    });
    await resource.load(query);
    missing = true;
    await assert.rejects(resource.load(query));
    assert.equal(resource.getSnapshot().status, "error");
    assert.equal("data" in resource.getSnapshot(), false);
    resource.cancel();
    assert.equal("data" in resource.getSnapshot(), false);
    resource.dispose();
  });

test("F2 command rejects double-clicks and success is explicit", async () => {
  const pending = deferred();
  let calls = 0;
  const command = createCommandResource(() => {
    calls++;
    return pending.promise;
  });
  const running = command.run({ password: "not-stored" });
  assert.equal(command.getSnapshot().status, "pending");
  assert.equal("password" in command.getSnapshot(), false);
  await assert.rejects(command.run({}), (error) => error.kind === AppErrorKind.DUPLICATE);
  assert.throws(
    () => command.reset(),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  pending.resolve({ id: "created" });
  await running;
  assert.equal(calls, 1);
  assert.equal(command.getSnapshot().status, "success");
  command.dispose();
});

test("F2 command conflict differs from validation failure and never retries", async () => {
  for (const [status, expected] of [
    [409, "conflict"],
    [422, "error"],
  ]) {
    let calls = 0;
    const command = createCommandResource(async () => {
      calls++;
      throw new AppError(AppErrorKind.SERVER, "safe reason", { status });
    });
    await assert.rejects(command.run({}));
    assert.equal(command.getSnapshot().status, expected);
    assert.equal(calls, 1);
    command.dispose();
  }
});

for (const kind of [AppErrorKind.NETWORK, AppErrorKind.TIMEOUT]) {
  test(`F2 ${kind} write is unknown, never success or automatic replay`, async () => {
    let calls = 0;
    const command = createCommandResource(async () => {
      calls++;
      throw new AppError(kind, "safe reason");
    });
    await assert.rejects(command.run({}));
    assert.equal(command.getSnapshot().status, "result-unknown");
    await assert.rejects(command.run({}), (error) => error.kind === AppErrorKind.DUPLICATE);
    assert.equal(calls, 1);
    command.reset();
    assert.equal(command.getSnapshot().status, "idle");
    command.dispose();
  });
}

test("F2 cancelling an issued write preserves uncertainty and ignores late success", async () => {
  const pending = deferred();
  const command = createCommandResource(() => pending.promise);
  const rejection = assert.rejects(command.run({}));
  await Promise.resolve();
  command.cancel();
  await rejection;
  assert.equal(command.getSnapshot().status, "result-unknown");
  pending.resolve({ ok: true });
  await Promise.resolve();
  assert.equal(command.getSnapshot().status, "result-unknown");
  command.dispose();
});

test("F2 cancellation proven before dispatch is idle, not an unknown server write", async () => {
  let calls = 0;
  const command = createCommandResource(async () => {
    calls++;
    return {};
  });
  const failed = assert.rejects(command.run({}));
  command.cancel();
  await failed;
  assert.equal(calls, 0);
  assert.equal(command.getSnapshot().status, "idle");
  await command.run({});
  assert.equal(calls, 1);
  command.dispose();
  command.dispose();
});

for (const status of [500, 502, 503])
  test(`F2 HTTP ${status} cannot prove a dispatched write was not committed`, async () => {
    const command = createCommandResource(async () => {
      throw new AppError(AppErrorKind.SERVER, "safe", { status });
    });
    await assert.rejects(command.run({}));
    assert.equal(command.getSnapshot().status, "result-unknown");
    await assert.rejects(command.run({}), (error) => error.kind === AppErrorKind.DUPLICATE);
    command.dispose();
  });
