import { test } from "node:test";
import assert from "node:assert/strict";
import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import {
  validSystemConnections,
  connectionProbeExpired,
  connectionCoverageComplete,
  validSystemProtocols,
  validAuditQuery,
  validAuditPage,
  auditQueryKey,
  AUDIT_MAX_WINDOW_MS,
} from "../../src/features/system/model/systemObservation";
import { applyAuditFilters, auditFilterDraft } from "../../src/features/system/model/auditFilters";
import { createSystemObservationResources } from "../../src/features/system/application/systemObservationResources";
import {
  systemConnections,
  systemProtocols,
  auditQuery,
  auditPage,
  systemAsOfMs,
} from "../fixtures/systemObservations";
import {
  DEFAULT_SYSTEM_TAB,
  isSystemTab,
  resolveSystemTab,
  SYSTEM_TAB,
} from "../../src/features/system/model/systemStatus";
function topology(overrides = {}) {
  const system = new StateStore({ ownerKey: "system-owner", allowed: true }),
    audit = new StateStore({ ownerKey: "system-owner", allowed: true });
  let auditReads = 0;
  const resources = createSystemObservationResources(
    {
      health: { readConnections: async () => systemConnections, ...overrides.health },
      protocols: { readProtocols: async () => systemProtocols, ...overrides.protocols },
      audit: {
        readAudit: async (query) => {
          auditReads++;
          return auditPage(query);
        },
        ...overrides.audit,
      },
    },
    {
      system: { read: system.getSnapshot, subscribe: system.subscribe },
      audit: { read: audit.getSnapshot, subscribe: audit.subscribe },
    },
  );
  return { resources, system, audit, auditReads: () => auditReads };
}
test("SYSTEM-TAB: route values are narrowed only when they match a declared tab", () => {
  assert.equal(resolveSystemTab(SYSTEM_TAB.Roles), SYSTEM_TAB.Roles);
  assert.equal(resolveSystemTab("constructor"), DEFAULT_SYSTEM_TAB);
  assert.equal(resolveSystemTab(undefined), DEFAULT_SYSTEM_TAB);
  assert.equal(isSystemTab(SYSTEM_TAB.Audit), true);
  assert.equal(isSystemTab({}), false);
});
test("SYSTEM-PROBE: independent service categories, valid UTC/latency and expiry boundary; missing probe is not available", () => {
  assert.equal(validSystemConnections(systemConnections), true);
  assert.equal(connectionProbeExpired(systemConnections.items[1], systemAsOfMs), true);
  assert.equal(connectionCoverageComplete(systemConnections), true);
  assert.equal(
    connectionCoverageComplete({
      ...systemConnections,
      items: systemConnections.items.slice(0, 1),
    }),
    false,
  );
  const first = systemConnections.items[0];
  for (const item of [
    { ...first, checkedAtMs: null },
    { ...first, latencyMs: NaN },
    { ...first, expiresAtMs: first.checkedAtMs - 1 },
    { ...first, reason: "authentication" },
    { ...first, capabilities: ["read", "read"] },
    { ...first, kind: "metrics-backend" },
  ])
    assert.equal(validSystemConnections({ ...systemConnections, items: [item] }), false);
  assert.equal(validSystemConnections({ ...systemConnections, items: [first, first] }), false);
  for (const blank of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"])
    assert.equal(
      validSystemConnections({ ...systemConnections, items: [{ ...first, id: blank }] }),
      false,
    );
  assert.equal(
    validSystemConnections({
      ...systemConnections,
      items: [{ ...first, id: "source\ufeffprimary" }],
    }),
    true,
  );
});
test("SYSTEM-PROTOCOL: actual negotiation and compatibility cannot contradict supported versions or manufacture absent negotiation", () => {
  assert.equal(validSystemProtocols(systemProtocols), true);
  const first = systemProtocols.items[0];
  for (const item of [
    { ...first, active: "wrong" },
    { ...first, compatibility: "incompatible" },
    { ...first, active: null },
    { ...first, observedAtMs: null },
    { ...first, supported: ["profile-a", "profile-a"] },
    { ...first, observedAtMs: systemAsOfMs + 1 },
  ])
    assert.equal(validSystemProtocols({ ...systemProtocols, items: [item] }), false);
  assert.equal(validSystemProtocols({ ...systemProtocols, items: [first, first] }), false);
  for (const blank of ["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"])
    assert.equal(
      validSystemProtocols({
        ...systemProtocols,
        items: [{ ...first, supported: [blank] }],
      }),
      false,
    );
});
test("SYSTEM-AUDIT: bounded half-open independent range, every filter key and page scope reject foreign or contradictory facts", () => {
  assert.equal(validAuditQuery(auditQuery), true);
  assert.equal(validAuditPage(auditPage(), auditQuery), true);
  const systemEventPage = {
    ...auditPage(),
    items: [
      {
        ...auditPage().items[0],
        actorId: null,
        action: "system-initialize",
      },
    ],
  };
  assert.equal(validAuditPage(systemEventPage, auditQuery), true);
  for (const action of ["plan-activate", "plan-restore"]) {
    assert.equal(
      validAuditPage(
        {
          ...systemEventPage,
          items: [{ ...systemEventPage.items[0], action }],
        },
        auditQuery,
      ),
      true,
    );
  }
  for (const query of [
    { ...auditQuery, page: 0 },
    { ...auditQuery, pageSize: 101 },
    { ...auditQuery, endMs: auditQuery.startMs + AUDIT_MAX_WINDOW_MS + 1 },
    { ...auditQuery, startMs: auditQuery.endMs },
    { ...auditQuery, actorId: " ".repeat(3) },
    ...["\u001c", "\u0085", "\ufeff", "\u3000", "\ud800"].map((actorId) => ({
      ...auditQuery,
      actorId,
    })),
    { ...auditQuery, action: "__proto__" },
  ])
    assert.equal(validAuditQuery(query), false);
  assert.equal(validAuditQuery({ ...auditQuery, actorId: "operator\ufeffeast" }), true);
  for (const change of [
    { startMs: auditQuery.startMs + 1 },
    { endMs: auditQuery.endMs + 1 },
    { actorId: "admin-one" },
    { action: "rule-publish" },
    { result: "rejected" },
    { page: 2 },
    { pageSize: 2 },
  ])
    assert.notEqual(auditQueryKey({ ...auditQuery, ...change }), auditQueryKey(auditQuery));
  const page = auditPage(),
    row = page.items[0];
  for (const bad of [
    { ...page, total: 0 },
    { ...page, query: { ...auditQuery, page: 2 } },
    { ...page, items: [{ ...row, occurredAtMs: auditQuery.endMs }] },
    { ...page, items: [{ ...row, bindingId: null }] },
    { ...page, items: [row, row] },
    { ...page, items: [{ ...row, actorId: " " }] },
    {
      ...page,
      items: [{ ...row, action: "account-create", actorId: null }],
    },
  ])
    assert.equal(validAuditPage(bad, auditQuery), false);
  const filtered = { ...auditQuery, actorId: "admin-two" };
  assert.equal(validAuditPage({ ...auditPage(filtered), items: [row] }, filtered), false);
});
test("SYSTEM-AUDIT-FORM: explicit UTC apply rejects calendar normalization, reverse/long range and invalid enum instead of fallback", () => {
  const draft = auditFilterDraft(auditQuery);
  assert.equal(applyAuditFilters(draft, { ...auditQuery, page: 3 }).page, 1);
  for (const patch of [
    { startUtc: "2026-02-30T12:00" },
    { startUtc: "2026-10-07T12:00" },
    { startUtc: "" },
    { endUtc: "2026-12-07T12:00" },
    { action: "not-action" },
    { result: "not-result" },
  ])
    assert.equal(applyAuditFilters({ ...draft, ...patch }, auditQuery), null);
  assert.equal(
    applyAuditFilters({ ...draft, actorId: " admin-one " }, auditQuery).actorId,
    "admin-one",
  );
});
test("SYSTEM-AUDIT-PRECISION: changing only actor never rounds the existing UTC window to a different minute", () => {
  const exact = {
    ...auditQuery,
    startMs: auditQuery.startMs + 12345,
    endMs: auditQuery.endMs - 12345,
  };
  const next = applyAuditFilters({ ...auditFilterDraft(exact), actorId: "admin-one" }, exact);
  assert.equal(next.startMs, exact.startMs);
  assert.equal(next.endMs, exact.endMs);
});
test("SYSTEM-RESOURCES: health failure does not erase protocol/audit; missing coverage and expiry are partial rather than healthy", async () => {
  let offline = false;
  const { resources } = topology({
    health: {
      readConnections: async () => {
        if (offline) throw new AppError(AppErrorKind.NETWORK, "PRIVATE-HEALTH");
        return systemConnections;
      },
    },
  });
  await resources.connections.load(null);
  await resources.protocols.load(null);
  await resources.audit.load(auditQuery);
  assert.equal(resources.connections.getSnapshot().status, "partial");
  assert.equal(resources.protocols.getSnapshot().status, "partial");
  offline = true;
  await assert.rejects(resources.connections.load(null));
  assert.equal(resources.connections.getSnapshot().status, "stale");
  assert.equal(resources.audit.getSnapshot().status, "ready");
  assert.equal(resources.protocols.getSnapshot().status, "partial");
  resources.dispose();
  const incomplete = topology({
    health: {
      readConnections: async () => ({ ...systemConnections, items: [systemConnections.items[0]] }),
    },
  });
  await incomplete.resources.connections.load(null);
  assert.equal(incomplete.resources.connections.getSnapshot().status, "partial");
  incomplete.resources.dispose();
});
test("SYSTEM-AUDIT-OWNER: view/invalid query never dispatch, filtered-empty remains distinct; first revocation drops completed admin rows", async () => {
  const { resources, audit, auditReads } = topology();
  await assert.rejects(resources.audit.load({ ...auditQuery, page: 0 }));
  assert.equal(auditReads(), 0);
  await resources.audit.load(auditQuery);
  assert.equal(auditReads(), 1);
  audit.set({ ownerKey: "system-owner", allowed: false });
  assert.equal(resources.audit.getSnapshot().status, "denied");
  assert.ok(!("data" in resources.audit.getSnapshot()));
  await assert.rejects(resources.audit.load(auditQuery));
  assert.equal(auditReads(), 1);
  audit.set({ ownerKey: "system-owner", allowed: true });
  await resources.audit.load({ ...auditQuery, actorId: "absent" });
  assert.equal(resources.audit.getSnapshot().status, "filtered-empty");
  resources.dispose();
});
test("SYSTEM-LATE: revoked/changed owner aborts ignored requests; old protocol and audit responses cannot reappear", async () => {
  let resolve, signal;
  const { resources, system } = topology({
    protocols: {
      readProtocols: async (s) => {
        signal = s;
        return new Promise((done) => (resolve = done));
      },
    },
  });
  const pending = resources.protocols.load(null);
  system.set({ ownerKey: "system-next", allowed: false });
  assert.equal(signal.aborted, true);
  resolve(systemProtocols);
  await assert.rejects(pending);
  assert.equal(resources.protocols.getSnapshot().status, "denied");
  assert.ok(!("data" in resources.protocols.getSnapshot()));
  resources.dispose();
});
test("SYSTEM-PROTOCOL-COVERAGE: one compatible protocol cannot prove all three independent boundaries are observed", async () => {
  const { resources } = topology({
    protocols: {
      readProtocols: async () => ({ ...systemProtocols, items: [systemProtocols.items[0]] }),
    },
  });
  await resources.protocols.load(null);
  assert.equal(resources.protocols.getSnapshot().status, "partial");
  resources.dispose();
});
test("SYSTEM-AUDIT-ORDER: equal-time records require stable descending Unicode scalar identity ordering across pages", () => {
  const query = { ...auditQuery, pageSize: 2 },
    page = auditPage(query),
    row = page.items[0];
  const lower = { ...row, id: "record-\uE000" },
    higher = { ...row, id: "record-\u{10000}" };
  assert.equal(validAuditPage({ ...page, total: 2, items: [higher, lower] }, query), true);
  assert.equal(validAuditPage({ ...page, total: 2, items: [lower, higher] }, query), false);
});
