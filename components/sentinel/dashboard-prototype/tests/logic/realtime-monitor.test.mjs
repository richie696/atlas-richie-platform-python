import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createRealtimeMonitor } from "../../src/features/realtime/application/realtimeMonitor";
import {
  resolveRealtimeQuery,
  realtimeSelectionKey,
  selectRealtimeInstance,
  validRealtimeSelection,
} from "../../src/features/realtime/model/monitoring";
import { query, bundleFor, toMs } from "../fixtures/observations";
const selected = {
  context: query.context,
  metrics: bundleFor().query.metrics,
  stepMs: query.stepMs,
  windowMode: "rolling",
};
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(check) {
  for (let index = 0; index < 100; index++) {
    if (check()) return;
    await delay(5);
  }
  assert.fail("monitor condition deadline");
}
const access = () => new StateStore({ ownerKey: "monitor-owner", allowed: true });
const observer = (state) => ({ read: state.getSnapshot, subscribe: state.subscribe });
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

test("MONITOR-QUERY: rolling attempts have real exact windows; fixed windows never move, identities include mode/metrics/scope", () => {
  const actual = resolveRealtimeQuery(selected, toMs + 60_000);
  assert.equal(actual.context.window.toMs, toMs + 60_000);
  assert.equal(actual.context.window.fromMs, query.context.window.fromMs + 60_000);
  assert.equal(selected.context.window.toMs, toMs);
  assert.deepEqual(
    resolveRealtimeQuery({ ...selected, windowMode: "fixed" }, toMs + 60_000).context.window,
    query.context.window,
  );
  assert.notEqual(
    realtimeSelectionKey({ ...selected, windowMode: "fixed" }),
    realtimeSelectionKey(selected),
  );
  assert.equal(validRealtimeSelection({ ...selected, windowMode: "unknown" }), false);
  assert.throws(() => resolveRealtimeQuery(selected, NaN));
});
test("MONITOR-FILTERS: instance selection binds exact app and advertised scope; clearing returns to app/fleet", () => {
  const instance = selectRealtimeInstance(selected, {
    appId: "app-two",
    instanceId: "instance-3",
    supportedScopes: ["process"],
  });
  assert.equal(instance.context.appId, "app-two");
  assert.equal(instance.context.instanceId, "instance-3");
  assert.equal(instance.context.scope, "process");
  const cleared = selectRealtimeInstance(instance, null);
  assert.equal(cleared.context.appId, "app-two");
  assert.equal(cleared.context.instanceId, null);
  assert.equal(cleared.context.scope, "application");
  const allApps = selectRealtimeInstance(
    { ...selected, context: { ...selected.context, appId: null } },
    { appId: "app-two", instanceId: "instance-3", supportedScopes: ["container"] },
  );
  assert.equal(allApps.context.scope, "container");
  assert.equal(
    selectRealtimeInstance(selected, {
      appId: "app-one",
      instanceId: "unsupported",
      supportedScopes: [],
    }),
    null,
  );
  assert.notEqual(realtimeSelectionKey(instance), realtimeSelectionKey(selected));
});
test("MONITOR-POLL: one effect owner, no overlap or duplicate start, pause aborts pending read and stops browser requests only", async () => {
  const permission = access();
  let calls = 0,
    signal;
  const hold = deferred();
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input, s) {
        calls++;
        signal = s;
        return calls === 1 ? hold.promise : bundleFor(input.context, input.stepMs);
      },
    },
    observer(permission),
    { intervalMs: 100, clock: () => toMs },
  );
  try {
    monitor.start(selected);
    monitor.start({ ...selected });
    await until(() => calls === 1);
    await delay(240);
    assert.equal(calls, 1);
    assert.equal(monitor.getSnapshot().observation.status, "loading");
    monitor.pause();
    assert.equal(signal.aborted, true);
    assert.equal(monitor.getSnapshot().mode, "paused");
    hold.resolve(bundleFor());
    await delay(150);
    assert.equal(calls, 1);
    assert.equal(monitor.getSnapshot().observation.status, "idle");
    monitor.resume();
    await until(() => calls === 2 && monitor.getSnapshot().observation.status === "partial");
    monitor.pause();
    await delay(150);
    assert.equal(calls, 2);
  } finally {
    monitor.dispose();
  }
});
test("MONITOR-STALE: rolling refresh failure retains the original data/window/asOf, recovery replaces rather than appends", async () => {
  let now = toMs,
    mode = "success",
    lastQuery,
    calls = 0;
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input) {
        calls++;
        lastQuery = input;
        if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "synthetic offline");
        return bundleFor(input.context, input.stepMs);
      },
    },
    observer(access()),
    { intervalMs: 100, clock: () => now },
  );
  try {
    monitor.start(selected);
    await until(() => monitor.getSnapshot().observation.status === "partial");
    const original = monitor.getSnapshot().observation.data;
    now += 60_000;
    mode = "offline";
    await until(() => monitor.getSnapshot().observation.status === "stale");
    assert.equal(lastQuery.context.window.toMs, now);
    assert.equal(monitor.getSnapshot().observation.data, original);
    assert.equal(original.query.context.window.toMs, toMs);
    mode = "success";
    await until(
      () =>
        monitor.getSnapshot().observation.status === "partial" &&
        monitor.getSnapshot().observation.data.asOfMs === now,
    );
    monitor.pause();
    assert.equal(monitor.getSnapshot().observation.data.series[0].samples.length, 15);
    assert.ok(calls >= 3);
  } finally {
    monitor.dispose();
  }
});
test("MONITOR-RATE-LIMIT: polling honors the server retry hint before reading again", async () => {
  let calls = 0;
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input) {
        calls++;
        if (calls === 2)
          throw new AppError(AppErrorKind.RATE_LIMITED, "rate limited", {
            status: 429,
            code: "rate_limited",
            retryAfterMs: 260,
          });
        return bundleFor(input.context, input.stepMs);
      },
    },
    observer(access()),
    { intervalMs: 100, clock: () => toMs },
  );
  try {
    monitor.start(selected);
    await until(() => calls === 1 && monitor.getSnapshot().observation.status === "partial");
    const lastGood = monitor.getSnapshot().observation.data;
    await until(() => calls === 2 && monitor.getSnapshot().observation.status === "stale");
    await delay(180);
    assert.equal(calls, 2, "ticks before retryAfterMs must not issue another HTTP read");
    assert.equal(monitor.getSnapshot().observation.data, lastGood);
    await until(() => calls === 3 && monitor.getSnapshot().observation.status === "partial");
    assert.notEqual(monitor.getSnapshot().observation.data, lastGood);
    monitor.pause();
    assert.equal(calls, 3);
  } finally {
    monitor.dispose();
  }
});
test("MONITOR-OWNER: changing query aborts previous work; revocation immediately clears selection/data and stops ticks", async () => {
  const permission = access();
  let calls = 0,
    signal;
  const hold = deferred();
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input, s) {
        calls++;
        signal = s;
        return calls === 1 ? hold.promise : bundleFor(input.context, input.stepMs);
      },
    },
    observer(permission),
    { intervalMs: 100, clock: () => toMs },
  );
  try {
    monitor.start(selected);
    await until(() => calls === 1);
    const oldSignal = signal;
    const next = {
      ...selected,
      context: { ...selected.context, appId: "app-two", scope: "application" },
    };
    monitor.start(next);
    assert.equal(oldSignal.aborted, true);
    assert.ok(!("data" in monitor.getSnapshot().observation));
    await until(() => monitor.getSnapshot().observation.status === "partial");
    hold.resolve(bundleFor());
    await delay(10);
    assert.equal(monitor.getSnapshot().observation.data.query.context.appId, "app-two");
    const seen = [];
    monitor.subscribe(() => seen.push(monitor.getSnapshot()));
    seen.length = 0;
    permission.set({ ownerKey: "monitor-owner", allowed: false });
    assert.ok(seen.every((snapshot) => !("data" in snapshot.observation)));
    assert.equal(monitor.getSnapshot().observation.status, "denied");
    assert.equal(monitor.getSnapshot().selection, null);
    const before = calls;
    await delay(150);
    assert.equal(calls, before);
    assert.throws(
      () => monitor.start(selected),
      (error) => error.kind === AppErrorKind.FORBIDDEN,
    );
  } finally {
    monitor.dispose();
  }
});
test("MONITOR-LATE-REVOKED: an abort-ignoring read cannot restore metrics after access revocation", async () => {
  const permission = access();
  let calls = 0,
    signal;
  const held = deferred();
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input, requestSignal) {
        calls++;
        signal = requestSignal;
        return calls === 1 ? held.promise : bundleFor(input.context, input.stepMs);
      },
    },
    observer(permission),
    { intervalMs: 100, clock: () => toMs },
  );
  try {
    monitor.start(selected);
    await until(() => calls === 1);
    permission.set({ ownerKey: "monitor-owner", allowed: false });

    assert.equal(signal.aborted, true);
    assert.equal(monitor.getSnapshot().observation.status, "denied");
    assert.equal(monitor.getSnapshot().selection, null);
    assert.ok(!("data" in monitor.getSnapshot().observation));

    held.resolve(bundleFor());
    await delay(20);
    assert.equal(calls, 1);
    assert.equal(monitor.getSnapshot().observation.status, "denied");
    assert.ok(!("data" in monitor.getSnapshot().observation));

    permission.set({ ownerKey: "next-monitor-owner", allowed: true });
    monitor.start(selected);
    await until(() => calls === 2 && monitor.getSnapshot().observation.status === "partial");
    assert.equal(monitor.getSnapshot().observation.data.query.context.appId, selected.context.appId);
  } finally {
    monitor.dispose();
  }
});
test("MONITOR-TIMEOUT: bounded attempt aborts loader; malformed mixed-window payload never becomes a trusted metric frame", async () => {
  let mode = "held",
    signal;
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input, s) {
        signal = s;
        if (mode === "held") return new Promise(() => {});
        return bundleFor(query.context, input.stepMs);
      },
    },
    observer(access()),
    { intervalMs: 100, timeoutMs: 15, clock: () => toMs + 60_000 },
  );
  try {
    monitor.start(selected);
    await until(() => monitor.getSnapshot().observation.status === "error");
    assert.equal(monitor.getSnapshot().observation.error.kind, AppErrorKind.TIMEOUT);
    assert.equal(signal.aborted, true);
    monitor.pause();
    mode = "wrong";
    monitor.resume();
    await until(() => monitor.getSnapshot().observation.status === "error");
    assert.equal(monitor.getSnapshot().observation.error.code, "invalid_observation");
    assert.ok(!("data" in monitor.getSnapshot().observation));
  } finally {
    monitor.dispose();
  }
});
test("MONITOR-CLEANUP: cancel/start is reusable for StrictMode, disposal detaches access and cannot restart", async () => {
  const permission = access();
  let listeners = 0,
    calls = 0;
  const monitored = {
    read: permission.getSnapshot,
    subscribe(listener) {
      listeners++;
      const off = permission.subscribe(listener);
      return () => {
        listeners--;
        off();
      };
    },
  };
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input) {
        calls++;
        return bundleFor(input.context, input.stepMs);
      },
    },
    monitored,
    { intervalMs: 100, clock: () => toMs },
  );
  monitor.start(selected);
  monitor.cancel();
  monitor.start(selected);
  await until(() => monitor.getSnapshot().observation.status === "partial");
  assert.equal(calls, 1);
  monitor.dispose();
  assert.equal(listeners, 0);
  assert.equal(monitor.getSnapshot().selection, null);
  assert.equal(monitor.getSnapshot().observation.status, "idle");
  monitor.dispose();
  assert.throws(
    () => monitor.start(selected),
    (error) => error.kind === AppErrorKind.CANCELLED,
  );
  await delay(150);
  assert.equal(calls, 1);
});

test("MONITOR-LIFECYCLE-STRESS: repeated monitor owners release subscriptions and polling timers", async () => {
  let activeAccessSubscriptions = 0,
    calls = 0;
  const ownerCount = 64;

  for (let index = 0; index < ownerCount; index++) {
    const permission = access();
    const observedAccess = {
      read: permission.getSnapshot,
      subscribe(listener) {
        activeAccessSubscriptions++;
        const unsubscribe = permission.subscribe(listener);
        return () => {
          activeAccessSubscriptions--;
          unsubscribe();
        };
      },
    };
    const monitor = createRealtimeMonitor(
      {
        async readMetrics(input) {
          calls++;
          return bundleFor(input.context, input.stepMs);
        },
      },
      observedAccess,
      { intervalMs: 100, clock: () => toMs },
    );

    monitor.start(selected);
    await until(() => monitor.getSnapshot().observation.status === "partial");
    monitor.dispose();
    assert.equal(activeAccessSubscriptions, 0, `owner ${index + 1} leaked an access subscription`);
    assert.equal(monitor.getSnapshot().selection, null);
    assert.equal(monitor.getSnapshot().observation.status, "idle");
  }

  await delay(150);
  assert.equal(calls, ownerCount, "a disposed owner left a polling timer behind");
  assert.equal(activeAccessSubscriptions, 0);
});
