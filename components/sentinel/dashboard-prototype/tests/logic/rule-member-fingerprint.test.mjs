import { test } from "node:test";
import assert from "node:assert/strict";
import { StateStore } from "@richie696/react-framework";
import {
  confirmedRuleInstanceUsage,
  ruleInstanceMembership,
  ruleMemberFingerprint,
} from "../../src/features/rules/application/ruleMemberFingerprint";
import { createRuleCatalogUsageResource } from "../../src/features/rules/application/ruleObservationResources";

const binding = {
  id: "java-binding",
  environmentId: "e2e-live",
  appId: "demo",
  kind: "flow",
  profile: "sentinel-java-v1",
  sourceId: "nacos",
  sourceLabel: "Nacos",
  location: "public/DEFAULT_GROUP",
};
const baseRule = {
  kind: "flow",
  value: {
    resource: "GET /api/hello",
    limitApp: "default",
    grade: 1,
    count: 3,
    strategy: 0,
    controlBehavior: 0,
    clusterMode: false,
  },
};
const entry = (profile = binding.profile, rule = baseRule) => ({
  binding: { ...binding, profile },
  record: { id: "rule-1", rule },
  snapshot: {
    checksum: "snapshot",
    sourceRevision: null,
    versionId: null,
    asOf: "2026-10-17T00:00:00Z",
  },
  read: { freshness: "current", lastAttemptAt: "2026-10-17T00:00:00Z" },
});

test("RULE-MEMBER-FINGERPRINT: Java, Go, and Rust use the shared acceptance vector", async () => {
  const expected = "9c11dd44491ed7625dad136d1238c8a23dcbb39c65b3db7d1e3220c65589047d";
  assert.equal(await ruleMemberFingerprint(entry("sentinel-java-v1")), expected);
  assert.equal(await ruleMemberFingerprint(entry("sentinel-go-v1")), expected);
  assert.equal(await ruleMemberFingerprint(entry("sentinel-rust-v1")), expected);
});

test("RULE-MEMBER-FINGERPRINT: unknown profiles and semantics fail closed", async () => {
  assert.equal(await ruleMemberFingerprint(entry("sentinel-python-v1")), null);
  assert.equal(
    await ruleMemberFingerprint(
      entry(binding.profile, {
        ...baseRule,
        value: { ...baseRule.value, controlBehavior: 1 },
      }),
    ),
    null,
  );
  assert.equal(
    await ruleMemberFingerprint(
      entry(binding.profile, {
        ...baseRule,
        value: { ...baseRule.value, resource: "GET /api/hello " },
      }),
    ),
    null,
  );
});

test("RULE-CATALOG-USAGE: reads exact binding scope and retains incomplete evidence as partial", async () => {
  const owner = new StateStore({ ownerKey: "catalog-test", allowed: true });
  const calls = [];
  const resource = createRuleCatalogUsageResource(
    {
      async readRuleLoadObservations(query) {
        calls.push(query);
        return {
          query,
          asOf: "2026-10-17T00:00:00Z",
          coverage: "partial",
          targets: {
            source: "active_reporter_enrollment",
            expected: null,
            observed: null,
            stale: null,
            notObserved: null,
          },
          total: null,
          hasMore: false,
          items: [],
        };
      },
    },
    { read: owner.getSnapshot, subscribe: owner.subscribe },
  );
  const query = {
    environmentId: "e2e-live",
    bindings: [{ bindingId: "java-binding", appId: "demo" }],
  };
  await resource.load(query);
  assert.deepEqual(calls, [
    {
      environmentId: "e2e-live",
      appId: "demo",
      bindingId: "java-binding",
      instanceId: null,
      page: 1,
      pageSize: 100,
    },
  ]);
  assert.equal(resource.getSnapshot().data.bindings["java-binding"].coverage, "partial");
  resource.dispose();
  owner.complete();
});

test("RULE-CATALOG-USAGE: reports membership only for complete, current, compatible exact-binding evidence", async () => {
  const catalogEntry = entry();
  const fingerprint = await ruleMemberFingerprint(catalogEntry);
  const observation = {
    bindingId: binding.id,
    instanceId: "worker-1",
    processId: "pid-1",
    processEpoch: "epoch-1",
    profileId: binding.profile,
    loadState: "applied",
    eventKind: "snapshot_applied",
    activeSnapshot: {
      sourceRevision: "revision-1",
      canonicalRulesSha256: "a".repeat(64),
      membershipComplete: true,
      members: [{ ruleKind: "flow", fingerprintSha256: fingerprint }],
    },
    attempt: null,
    observedAt: "2026-10-17T00:00:00Z",
    receivedAt: "2026-10-17T00:00:01Z",
    freshness: "current",
  };
  const page = {
    query: {
      environmentId: binding.environmentId,
      appId: binding.appId,
      bindingId: binding.id,
      instanceId: null,
      page: 1,
      pageSize: 100,
    },
    asOf: "2026-10-17T00:00:02Z",
    coverage: "complete",
    targets: {
      source: "active_reporter_enrollment",
      expected: 1,
      observed: 1,
      stale: 0,
      notObserved: 0,
    },
    total: 1,
    hasMore: false,
    items: [observation],
  };
  assert.deepEqual(confirmedRuleInstanceUsage(catalogEntry, fingerprint, page), {
    loaded: 1,
    notIncluded: 0,
    expected: 1,
    unconfirmed: 0,
  });
  assert.deepEqual(ruleInstanceMembership(catalogEntry, fingerprint, page), [
    {
      observation,
      membership: "included",
    },
  ]);
  assert.deepEqual(
    ruleInstanceMembership(catalogEntry, fingerprint, {
      ...page,
      items: [{ ...observation, activeSnapshot: { ...observation.activeSnapshot, members: [] } }],
    }),
    [
      {
        observation: {
          ...observation,
          activeSnapshot: { ...observation.activeSnapshot, members: [] },
        },
        membership: "not_included",
      },
    ],
  );
  assert.deepEqual(
    confirmedRuleInstanceUsage(catalogEntry, fingerprint, {
      ...page,
      items: [{ ...observation, activeSnapshot: { ...observation.activeSnapshot, members: [] } }],
    }),
    { loaded: 0, notIncluded: 1, expected: 1, unconfirmed: 0 },
  );
  assert.deepEqual(
    ruleInstanceMembership(catalogEntry, fingerprint, {
      ...page,
      items: [
        {
          ...observation,
          activeSnapshot: { ...observation.activeSnapshot, membershipComplete: false },
        },
      ],
    }),
    [
      {
        observation: {
          ...observation,
          activeSnapshot: { ...observation.activeSnapshot, membershipComplete: false },
        },
        membership: "unknown",
      },
    ],
  );
  const staleObservation = { ...observation, freshness: "stale" };
  const stalePage = {
    ...page,
    targets: { ...page.targets, stale: 1 },
    items: [staleObservation],
  };
  assert.deepEqual(ruleInstanceMembership(catalogEntry, fingerprint, stalePage), [
    {
      observation: staleObservation,
      membership: "unknown",
    },
  ]);
  assert.deepEqual(confirmedRuleInstanceUsage(catalogEntry, fingerprint, stalePage), {
    loaded: 0,
    notIncluded: 0,
    expected: 1,
    unconfirmed: 1,
  });

  const currentAndStalePage = {
    ...page,
    targets: {
      source: "active_reporter_enrollment",
      expected: 3,
      observed: 2,
      stale: 1,
      notObserved: 1,
    },
    total: 3,
    items: [
      observation,
      { ...staleObservation, instanceId: "worker-2" },
      {
        ...observation,
        instanceId: "worker-3",
        processEpoch: null,
        profileId: null,
        loadState: "not_observed",
        eventKind: null,
        activeSnapshot: null,
        observedAt: null,
        receivedAt: null,
        freshness: "unknown",
      },
    ],
  };
  assert.deepEqual(confirmedRuleInstanceUsage(catalogEntry, fingerprint, currentAndStalePage), {
    loaded: 1,
    notIncluded: 0,
    expected: 3,
    unconfirmed: 2,
  });
  assert.equal(
    ruleInstanceMembership(catalogEntry, fingerprint, {
      ...page,
      query: { ...page.query, bindingId: "other-binding" },
    }),
    null,
  );
  assert.equal(
    confirmedRuleInstanceUsage(catalogEntry, fingerprint, {
      ...page,
      targets: { ...page.targets, observed: null },
    }),
    null,
  );
  assert.equal(
    confirmedRuleInstanceUsage(catalogEntry, fingerprint, {
      ...page,
      targets: { ...page.targets, notObserved: 1 },
    }),
    null,
  );
  assert.deepEqual(
    confirmedRuleInstanceUsage(catalogEntry, fingerprint, {
      ...page,
      items: [{ ...observation, profileId: "unknown" }],
    }),
    { loaded: 0, notIncluded: 0, expected: 1, unconfirmed: 1 },
  );
  assert.equal(
    confirmedRuleInstanceUsage(catalogEntry, fingerprint, {
      ...page,
      query: { ...page.query, bindingId: "other-binding" },
    }),
    null,
  );
});
