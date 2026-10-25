import { test } from "node:test";
import assert from "node:assert/strict";
import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import { createIncidentResources } from "../../src/features/faults/application/incidentResources";
import {
  validIncidentQuery,
  validIncidentDetailQuery,
  validIncidentPage,
  validIncidentEvidence,
  validIncidentFact,
  incidentMatches,
  incidentQueryKey,
  incidentDetailKey,
  incidentQueryFromRoute,
} from "../../src/features/faults/model/incidentObservation";
import { incidentQuery, incidentPageFor, eventsFor, evidenceFor } from "../fixtures/incidents";
import { incidentPrecedes } from "../../src/features/faults/model/incidentObservation";
import { incidentFactText } from "../../src/features/faults/presentation/observedIncident";
import { OBSERVATION_SCOPE } from "../../src/shared/model/observation";
test("INCIDENT-PRESENTATION: scalar-value ID ordering and ratios format once with stable translated keys", () => {
  const event = eventsFor()[0];
  assert.equal(incidentPrecedes({ ...event, id: "😀" }, { ...event, id: "\ue000" }), true);
  assert.equal(incidentPrecedes({ ...event, id: "a" }, { ...event, id: "a" }), false);
  let captured;
  const translate = (key, values) => {
    captured = { key, values };
    return key;
  };
  assert.equal(incidentFactText(event.caption, translate, "en-US"), "faults.observed.pressure");
  assert.equal(captured.values.value, "90");
  assert.equal(captured.values.threshold, "80");
  assert.equal(
    incidentFactText({ code: "rule_published", versionId: "opaque" }, translate, "ja-JP"),
    "faults.observed.published",
  );
  assert.equal(captured.values.version, "opaque");
});
const detail = () => ({
  context: incidentQuery.context,
  eventId: "event-c",
  severity: null,
  category: null,
});
const topology = (overrides = {}) => {
  const access = new StateStore({ ownerKey: "incident-test-session", allowed: true });
  const resources = createIncidentResources(
    {
      readTimeline: async (query) => incidentPageFor(query),
      readEvidence: async (query) => evidenceFor(query),
      ...overrides,
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
  );
  return { access, resources };
};
test("INCIDENT-TIME: UTC across midnight, late receipt and skew do not replace occurred-at filtering", () => {
  const query = incidentQuery,
    event = eventsFor()[0];
  assert.equal(incidentMatches(event, query), true);
  assert.ok(event.receivedAtMs > query.context.window.toMs);
  assert.equal(incidentMatches({ ...event, receivedAtMs: event.occurredAtMs - 1000 }, query), true);
  for (const occurredAtMs of [query.context.window.fromMs - 1, query.context.window.toMs])
    assert.equal(incidentMatches({ ...event, occurredAtMs }, query), false);
  assert.equal(incidentMatches({ ...event, environmentId: "wrong" }, query), false);
  assert.equal(incidentMatches({ ...event, instanceId: null, processEpoch: "old" }, query), false);
});
test("F4.13 incident filters restore from URL values and reject unknown filters or overlong cursors", () => {
  const restored = incidentQueryFromRoute(incidentQuery, {
    severity: "critical",
    category: "resource",
    cursor: "opaque/cursor",
  });
  assert.equal(restored.severity, "critical");
  assert.equal(restored.category, "resource");
  assert.equal(restored.cursor, "opaque/cursor");
  assert.equal(validIncidentQuery(restored), true);
  const invalid = incidentQueryFromRoute(incidentQuery, {
    severity: "root-cause",
    category: "unknown",
    cursor: "x".repeat(513),
  });
  assert.equal(invalid.severity, null);
  assert.equal(invalid.category, null);
  assert.equal(invalid.cursor, null);
  assert.equal(validIncidentQuery(invalid), true);
});
test("F6.1 INCIDENT-SCOPE: only supported scope and identity combinations are valid", () => {
  const context = incidentQuery.context;
  assert.equal(validIncidentQuery(incidentQuery), true);
  for (const invalidContext of [
    { ...context, scope: OBSERVATION_SCOPE.Host },
    { ...context, scope: OBSERVATION_SCOPE.Container },
    { ...context, scope: OBSERVATION_SCOPE.Application },
    { ...context, scope: OBSERVATION_SCOPE.Process },
    { ...context, scope: OBSERVATION_SCOPE.Fleet, appId: "checkout" },
    {
      ...context,
      scope: OBSERVATION_SCOPE.Application,
      appId: "checkout",
      instanceId: "checkout-1",
    },
    { ...context, scope: OBSERVATION_SCOPE.Fleet, resource: "cpu" },
  ]) {
    assert.equal(validIncidentQuery({ ...incidentQuery, context: invalidContext }), false);
    assert.equal(validIncidentDetailQuery({ ...detail(), context: invalidContext }), false);
  }
  assert.equal(
    validIncidentQuery({
      ...incidentQuery,
      context: {
        ...context,
        scope: OBSERVATION_SCOPE.Process,
        appId: "checkout",
        instanceId: "checkout-1",
      },
    }),
    true,
  );
});
test("INCIDENT-PAGE: stable time/id ordering, full-scope counts independent of severity and cursor", () => {
  const value = incidentPageFor();
  assert.equal(validIncidentPage(value, incidentQuery), true);
  assert.equal(value.statistics.total, 3);
  assert.equal(value.items.length, 2);
  assert.equal(value.items[0].id, "event-c");
  assert.equal(value.items[1].id, "event-b");
  const next = { ...incidentQuery, cursor: value.nextCursor },
    page = incidentPageFor(next);
  assert.equal(validIncidentPage(page, next), true);
  assert.equal(page.statistics.total, 3);
  assert.equal(page.items[0].id, "event-a");
  const filtered = { ...incidentQuery, severity: "warning" },
    filteredPage = incidentPageFor(filtered);
  assert.equal(validIncidentPage(filteredPage, filtered), true);
  assert.equal(filteredPage.filteredTotal, 1);
  assert.equal(filteredPage.statistics.total, 3);
  for (const bad of [
    { ...value, items: [...value.items].reverse() },
    { ...value, items: [value.items[0], value.items[0]] },
    { ...value, statistics: { ...value.statistics, total: 2 } },
    { ...value, nextCursor: " ".repeat(3) },
    { ...value, filteredTotal: 4 },
    { ...value, query: { ...incidentQuery, severity: "info" } },
  ])
    assert.equal(validIncidentPage(bad, incidentQuery), false);
  assert.notEqual(incidentQueryKey(next), incidentQueryKey(incidentQuery));
});
test("INCIDENT-FACT: bounded typed facts, category consistency, ratio units and no raw exception captions", () => {
  assert.equal(
    validIncidentFact({
      code: "resource_pressure",
      metric: "cpu_ratio",
      value: 0.9,
      threshold: 0.8,
    }),
    true,
  );
  for (const bad of [
    { code: "raw_exception", message: "private" },
    { code: "resource_pressure", metric: "cpu_ratio", value: 90, threshold: 80 },
    { code: "response_time", valueMs: NaN, thresholdMs: 10 },
    { code: "rule_published", versionId: "" },
  ])
    assert.equal(validIncidentFact(bad), false);
  assert.equal(
    incidentMatches({ ...eventsFor()[0], category: "rulePublished" }, incidentQuery),
    false,
  );
  for (const query of [
    { ...incidentQuery, pageSize: 0 },
    { ...incidentQuery, pageSize: 101 },
    { ...incidentQuery, cursor: "x".repeat(513) },
    { ...incidentQuery, cursor: "\u001c" },
    { ...incidentQuery, cursor: "\u0085" },
    { ...incidentQuery, cursor: "\ufeff" },
    { ...incidentQuery, cursor: "\ud800" },
    { ...incidentQuery, category: "unknown" },
  ])
    assert.equal(validIncidentQuery(query), false);
  assert.equal(validIncidentQuery({ ...incidentQuery, cursor: "opaque\ufefftoken" }), true);
  assert.equal(validIncidentQuery({ ...incidentQuery, cursor: "opaque\ud800token" }), false);
});
test("INCIDENT-EVIDENCE: partial/unavailable are explicit, missing event or invalid targets never substitute another event", () => {
  const query = detail(),
    value = evidenceFor(query),
    ruleEvidence = evidenceFor({ ...query, eventId: "event-b" });
  assert.equal(validIncidentEvidence(value, query), true);
  assert.equal(
    validIncidentEvidence({ ...value, completeness: "partial", facts: [] }, query),
    true,
  );
  assert.equal(
    validIncidentEvidence({ ...value, completeness: "unavailable", facts: [] }, query),
    true,
  );
  for (const bad of [
    { ...value, event: eventsFor()[1] },
    { ...value, facts: [] },
    { ...value, facts: [value.facts[0], value.facts[0]] },
    { ...value, completeness: "unavailable" },
    { ...value, suggestedViews: ["rules"] },
    {
      ...value,
      facts: Array.from({ length: 101 }, (_, i) => ({ ...value.facts[0], id: String(i) })),
    },
  ])
    assert.equal(validIncidentEvidence(bad, query), false);
  assert.equal(
    validIncidentEvidence(
      { ...ruleEvidence, relatedRule: { ...ruleEvidence.relatedRule, appId: "foreign-app" } },
      { ...query, eventId: "event-b" },
    ),
    false,
  );
  assert.equal(
    validIncidentEvidence(
      {
        ...ruleEvidence,
        relatedRule: { ...ruleEvidence.relatedRule, publicationId: "foreign-publication" },
      },
      { ...query, eventId: "event-b" },
    ),
    false,
  );
  assert.equal(validIncidentEvidence(value, { ...query, severity: "warning" }), false);
  assert.notEqual(incidentDetailKey(query), incidentDetailKey({ ...query, eventId: "missing" }));
});
test("INCIDENT-READ: list filtering remains independent of evidence; wrong target loses old data and read failures are safe stale", async () => {
  let offline = false;
  const { resources } = topology({
    readEvidence: async (query) => {
      if (offline) throw new AppError(AppErrorKind.NETWORK, "PRIVATE");
      return evidenceFor(query);
    },
  });
  const query = detail();
  await resources.evidence.load(query);
  await resources.timeline.load({ ...incidentQuery, severity: "warning" });
  assert.equal(resources.evidence.getSnapshot().data.event.id, "event-c");
  offline = true;
  await assert.rejects(resources.evidence.load(query));
  assert.equal(resources.evidence.getSnapshot().status, "stale");
  await assert.rejects(resources.evidence.load({ ...query, eventId: "missing" }));
  assert.equal(resources.evidence.getSnapshot().status, "error");
  assert.ok(!("data" in resources.evidence.getSnapshot()));
  resources.dispose();
});
test("INCIDENT-OWNER: revocation drops both owners immediately and late detail cannot refill privileged facts", async () => {
  let resolve, signal;
  const { access, resources } = topology({
    readEvidence: async (query, s) => {
      signal = s;
      return new Promise((done) => {
        resolve = () => done(evidenceFor(query));
      });
    },
  });
  await resources.timeline.load(incidentQuery);
  const pending = resources.evidence.load(detail());
  const seen = [];
  resources.timeline.subscribe(() => seen.push(resources.timeline.getSnapshot()));
  seen.length = 0;
  access.set({ ownerKey: "incident-test-session", allowed: false });
  assert.equal(seen[0].status, "denied");
  assert.equal(signal.aborted, true);
  resolve();
  await assert.rejects(pending);
  assert.equal(resources.evidence.getSnapshot().status, "denied");
  assert.ok(!("data" in resources.timeline.getSnapshot()));
  resources.dispose();
});
