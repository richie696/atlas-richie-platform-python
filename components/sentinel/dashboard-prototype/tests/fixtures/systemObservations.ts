import type {
  SystemConnections,
  SystemProtocols,
  AuditQuery,
  AuditPage,
  AuditRecord,
} from "../../src/features/system/model/systemObservation";
export const systemAsOfMs = Date.parse("2026-10-07T12:00:00Z");
/** Synthetic consumer facts only, never production fixtures or an integration/configuration source. */
export const systemConnections: SystemConnections = {
  asOfMs: systemAsOfMs,
  items: [
    {
      id: "config-nacos",
      kind: "config-center",
      sourceId: "source-nacos",
      provider: "nacos",
      state: "available",
      checkedAtMs: systemAsOfMs - 1000,
      expiresAtMs: systemAsOfMs + 10000,
      latencyMs: 3.5,
      capabilities: ["read", "conditional-write"],
      reason: null,
    },
    {
      id: "config-consul",
      kind: "config-center",
      sourceId: "source-consul",
      provider: "consul",
      state: "available",
      checkedAtMs: systemAsOfMs - 1000,
      expiresAtMs: systemAsOfMs,
      latencyMs: 4,
      capabilities: ["read", "watch"],
      reason: null,
    },
    {
      id: "metrics",
      kind: "metrics-backend",
      sourceId: null,
      provider: null,
      state: "unavailable",
      checkedAtMs: systemAsOfMs - 1000,
      expiresAtMs: systemAsOfMs + 10000,
      latencyMs: null,
      capabilities: [],
      reason: "network",
    },
    {
      id: "collector",
      kind: "reporting-collector",
      sourceId: null,
      provider: null,
      state: "unconfigured",
      checkedAtMs: null,
      expiresAtMs: null,
      latencyMs: null,
      capabilities: [],
      reason: "not-configured",
    },
  ],
};
export const systemProtocols: SystemProtocols = {
  asOfMs: systemAsOfMs,
  items: [
    {
      kind: "rule-config",
      supported: ["profile-a"],
      active: "profile-a",
      compatibility: "compatible",
      observedAtMs: systemAsOfMs - 1000,
    },
    {
      kind: "agent-reporting",
      supported: ["V1"],
      active: "V2",
      compatibility: "incompatible",
      observedAtMs: systemAsOfMs - 1000,
    },
    {
      kind: "cluster-token",
      supported: ["V1"],
      active: null,
      compatibility: "unknown",
      observedAtMs: null,
    },
  ],
};
export const auditQuery: AuditQuery = {
  startMs: systemAsOfMs - 60 * 60 * 1000,
  endMs: systemAsOfMs,
  actorId: "",
  action: null,
  result: null,
  page: 1,
  pageSize: 1,
};
const auditRecords: readonly AuditRecord[] = [
  {
    id: "audit-publish",
    occurredAtMs: systemAsOfMs - 1000,
    actorId: "admin-one",
    action: "rule-publish",
    targetId: "binding-one",
    result: "success",
    requestId: "request-publish",
    environmentId: "environment-one",
    appId: "app-one",
    bindingId: "binding-one",
    publicationId: "publication-one",
  },
  {
    id: "audit-account",
    occurredAtMs: systemAsOfMs - 2000,
    actorId: "admin-two",
    action: "account-create",
    targetId: "account-three",
    result: "rejected",
    requestId: "request-account",
    environmentId: null,
    appId: null,
    bindingId: null,
    publicationId: null,
  },
  {
    id: "audit-plan",
    occurredAtMs: systemAsOfMs - 3000,
    actorId: "admin-one",
    action: "plan-create",
    targetId: "plan-one",
    result: "unknown",
    requestId: "request-plan",
    environmentId: "environment-one",
    appId: "app-one",
    bindingId: "binding-one",
    publicationId: null,
  },
];
export function auditPage(query: AuditQuery = auditQuery): AuditPage {
  const items = auditRecords.filter(
    (item) =>
      item.occurredAtMs >= query.startMs &&
      item.occurredAtMs < query.endMs &&
      (!query.actorId || item.actorId === query.actorId) &&
      (!query.action || item.action === query.action) &&
      (!query.result || item.result === query.result),
  );
  return {
    query,
    asOfMs: systemAsOfMs,
    total: items.length,
    items: items.slice((query.page - 1) * query.pageSize, query.page * query.pageSize),
  };
}
