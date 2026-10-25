import { test } from "node:test";
import assert from "node:assert/strict";
import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstanceResources } from "../../src/features/applications/application/instanceResources";
import {
  instanceSelection,
  instanceCatalogKey,
  instanceDetailKey,
  isInstanceLayer,
  validInstanceDetailQuery,
  validInstanceCatalogQuery,
  validInstanceCatalog,
  validInstanceObservation,
  validRuleReceipt,
} from "../../src/features/applications/model/instanceObservation";
import { catalogQuery, catalogFor, instanceFor, detailFor } from "../fixtures/instances";
const selection = () => instanceSelection(instanceFor(1), catalogQuery.context);
const topology = (overrides = {}) => {
  const access = new StateStore({ ownerKey: "instance-test-session", allowed: true });
  const resources = createInstanceResources(
    {
      readCatalog: async (query) => catalogFor(query),
      readInstance: async (query) => detailFor(query),
      ...overrides,
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
  );
  return { access, resources };
};
test("INSTANCE-CATALOG: pagination and anomaly/search filters never redefine whole-scope counters", () => {
  const value = catalogFor();
  assert.equal(validInstanceCatalog(value, catalogQuery), true);
  assert.equal(value.totalInstances, 4);
  assert.equal(value.items.length, 2);
  const filtered = { ...catalogQuery, attentionOnly: true, search: "2" },
    result = catalogFor(filtered);
  assert.equal(validInstanceCatalog(result, filtered), true);
  assert.equal(result.totalInstances, 4);
  assert.equal(result.filteredTotal, 1);
  const beyondLastPage = { ...catalogQuery, page: 3 },
    emptyLastPage = catalogFor(beyondLastPage),
    impossibleNonEmptyPage = {
      ...emptyLastPage,
      items: [instanceFor(1, beyondLastPage)],
    };
  assert.equal(validInstanceCatalog(emptyLastPage, beyondLastPage), true);
  assert.equal(validInstanceCatalog(impossibleNonEmptyPage, beyondLastPage), false);
  for (const bad of [
    { ...value, totalInstances: 1 },
    { ...value, attentionInstances: 5 },
    { ...value, items: [value.items[0], value.items[0]] },
    { ...value, query: { ...catalogQuery, page: 2 } },
    { ...value, items: [{ ...value.items[0], environmentId: "wrong" }] },
  ])
    assert.equal(validInstanceCatalog(bad, catalogQuery), false);
  for (const bad of [
    { ...catalogQuery, page: 0 },
    { ...catalogQuery, pageSize: 101 },
    { ...catalogQuery, search: "x".repeat(201) },
    { ...catalogQuery, search: "😀".repeat(101) },
    { ...catalogQuery, context: { ...catalogQuery.context, instanceId: "instance" } },
  ])
    assert.equal(validInstanceCatalogQuery(bad), false);
  assert.equal(validInstanceCatalogQuery({ ...catalogQuery, search: "😀".repeat(100) }), true);
  assert.notEqual(instanceCatalogKey(catalogQuery), instanceCatalogKey(filtered));
});
test("INSTANCE-DETAIL: exact incarnation, scope, environment, application and metric units must agree", () => {
  const query = selection(),
    value = detailFor(query);
  assert.equal(validInstanceObservation(value, query), true);
  assert.equal(isInstanceLayer("process"), true);
  assert.equal(isInstanceLayer("fleet"), false);
  assert.equal(isInstanceLayer(null), false);
  assert.equal(
    validInstanceDetailQuery({ ...query, context: { ...query.context, scope: "fleet" } }),
    false,
  );
  assert.equal(
    validInstanceDetailQuery({ ...query, context: { ...query.context, scope: "unknown" } }),
    false,
  );
  for (const bad of [
    { ...value, instance: { ...value.instance, processEpoch: "old-process" } },
    { ...value, instance: { ...value.instance, appId: "wrong" } },
    {
      ...value,
      metrics: {
        ...value.metrics,
        query: { ...value.metrics.query, context: { ...query.context, scope: "container" } },
      },
    },
    { ...value, instance: { ...value.instance, supportedScopes: ["process", "process"] } },
  ])
    assert.equal(validInstanceObservation(bad, query), false);
  const host = { ...query, context: { ...query.context, scope: "host" } },
    unsupported = detailFor(host);
  assert.equal(validInstanceObservation(unsupported, host), true);
  assert.equal(unsupported.metrics, null);
  assert.equal(validInstanceObservation({ ...unsupported, metrics: value.metrics }, host), false);
  assert.notEqual(
    instanceDetailKey(query),
    instanceDetailKey({ ...query, processEpoch: "new-process" }),
  );
});
test("INSTANCE-RECEIPT: a previous process or a different desired version cannot prove current loading", () => {
  const receipt = instanceFor(1).ruleReceipt;
  assert.equal(validRuleReceipt(receipt, "incarnation-1"), true);
  for (const bad of [
    { ...receipt, processEpoch: "old" },
    { ...receipt, appliedVersionId: "old-version" },
    { ...receipt, receivedAtMs: null },
    { ...receipt, desiredVersionId: null },
  ])
    assert.equal(validRuleReceipt(bad, "incarnation-1"), false);
  assert.equal(
    validRuleReceipt(
      { ...receipt, state: "pending", appliedVersionId: "old-version" },
      "incarnation-1",
    ),
    true,
  );
});
test("INSTANCE-OWNERS: filtering away selected instance does not change its detail; unsupported stays explicit partial", async () => {
  const { resources } = topology();
  const query = selection();
  await resources.detail.load(query);
  await resources.catalog.load({ ...catalogQuery, attentionOnly: true });
  assert.equal(resources.catalog.getSnapshot().data.items[0].instanceId, "instance-2");
  assert.equal(resources.detail.getSnapshot().data.instance.instanceId, "instance-1");
  await resources.detail.load({ ...query, context: { ...query.context, scope: "host" } });
  assert.equal(resources.detail.getSnapshot().status, "partial");
  assert.equal(resources.detail.getSnapshot().data.metrics, null);
  resources.dispose();
});
test("INSTANCE-STALE: same-query disconnect labels retained data; changed incarnation never borrows it", async () => {
  let offline = false;
  const { resources } = topology({
    readInstance: async (query) => {
      if (offline) throw new AppError(AppErrorKind.NETWORK, "PRIVATE");
      return detailFor(query);
    },
  });
  const query = selection();
  await resources.detail.load(query);
  offline = true;
  await assert.rejects(resources.detail.load(query));
  assert.equal(resources.detail.getSnapshot().status, "stale");
  await assert.rejects(resources.detail.load({ ...query, processEpoch: "new-process" }));
  assert.equal(resources.detail.getSnapshot().status, "error");
  assert.ok(!("data" in resources.detail.getSnapshot()));
  resources.dispose();
});
test("INSTANCE-REVOKE: both completed owners clear on the first access notification and abort ignored late work", async () => {
  let resolve, signal;
  const { access, resources } = topology({
    readInstance: async (query, s) => {
      signal = s;
      return new Promise((done) => {
        resolve = () => done(detailFor(query));
      });
    },
  });
  await resources.catalog.load(catalogQuery);
  const query = selection(),
    loading = resources.detail.load(query);
  const seen = [];
  resources.catalog.subscribe(() => seen.push(resources.catalog.getSnapshot()));
  seen.length = 0;
  access.set({ ownerKey: "instance-test-session", allowed: false });
  assert.equal(seen[0].status, "denied");
  assert.equal(signal.aborted, true);
  resolve();
  await assert.rejects(loading);
  assert.equal(resources.detail.getSnapshot().status, "denied");
  assert.ok(!("data" in resources.catalog.getSnapshot()));
  resources.dispose();
});
test("INSTANCE-INCARNATION: authoritative same-key process replacement invalidates prior receipt, unlike ordinary offline reads", async () => {
  let changed = false;
  const { resources } = topology({
    readInstance: async (query) => {
      if (changed)
        throw new AppError(AppErrorKind.SERVER, "PRIVATE", {
          status: 409,
          code: "instance_incarnation_changed",
        });
      return detailFor(query);
    },
  });
  const query = selection();
  await resources.detail.load(query);
  changed = true;
  await assert.rejects(resources.detail.load(query));
  assert.equal(resources.detail.getSnapshot().status, "error");
  assert.ok(!("data" in resources.detail.getSnapshot()));
  resources.detail.cancel();
  assert.ok(!("data" in resources.detail.getSnapshot()));
  resources.dispose();
});
