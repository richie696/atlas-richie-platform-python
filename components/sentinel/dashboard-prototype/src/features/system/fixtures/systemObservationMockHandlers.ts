import { http, HttpResponse } from "msw";
import type { z } from "zod";
import { CONSOLE_HEADER } from "../../../core/api/protocol/common";
import {
  AuditQueryParametersSchema,
  SystemConnectionsSchema,
  DeploymentGuidesSchema,
  SystemProtocolsSchema,
  AgentReportingObservationPageSchema,
  IncidentEventObservationPageSchema,
} from "../api/systemObservationWire";
type AuditParameters = z.infer<typeof AuditQueryParametersSchema>;

const instant = (value: number) => new Date(value).toISOString();
const response = (body: unknown, requestId: string | null, status = 200) => {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  return new HttpResponse(JSON.stringify(body), { status, headers });
};
interface SystemObservationScenario {
  readonly sourceId: string;
  readonly administratorId: string;
  readonly environmentId: string;
  readonly applicationId: string;
  readonly bindingId: string;
  readonly publicationId: string;
  readonly connections: readonly ConnectionFact[];
  readonly protocols: readonly ProtocolFact[];
  readonly auditEvents: readonly AuditFact[];
}

interface ConnectionFact {
  readonly id: string;
  readonly kind: string;
  readonly sourceRef: "primary" | null;
  readonly provider: string | null;
  readonly state: string;
  readonly checkedAtOffsetMs: number | null;
  readonly validForMs: number | null;
  readonly latencyMs: number | null;
  readonly capabilities: readonly string[];
  readonly reason: string | null;
}

interface ProtocolFact {
  readonly kind: string;
  readonly supported: readonly string[];
  readonly active: string | null;
  readonly compatibility: string;
  readonly observedAtOffsetMs: number | null;
}

interface AuditFact {
  readonly id: string;
  readonly occurredAtOffsetMs: number;
  readonly actorRef: "administrator";
  readonly action: string;
  readonly targetRef: "administrator" | "application";
  readonly result: string;
  readonly requestId: string;
  readonly scopeRef: "rule-publication" | null;
}

function connectionWire(asOf: number, scenario: SystemObservationScenario) {
  return {
    asOf: instant(asOf),
    items: scenario.connections.map((fact) => ({
      id: fact.id,
      kind: fact.kind,
      sourceId: fact.sourceRef === "primary" ? scenario.sourceId : null,
      provider: fact.provider,
      state: fact.state,
      checkedAt: fact.checkedAtOffsetMs === null ? null : instant(asOf + fact.checkedAtOffsetMs),
      expiresAt: fact.validForMs === null ? null : instant(asOf + fact.validForMs),
      latencyMs: fact.latencyMs,
      capabilities: fact.capabilities,
      reason: fact.reason,
    })),
  };
}
function protocolWire(asOf: number, scenario: SystemObservationScenario) {
  return {
    asOf: instant(asOf),
    items: scenario.protocols.map((fact) => ({
      kind: fact.kind,
      supported: fact.supported,
      active: fact.active,
      compatibility: fact.compatibility,
      observedAt: fact.observedAtOffsetMs === null ? null : instant(asOf + fact.observedAtOffsetMs),
    })),
  };
}
function parseQuery(url: URL) {
  const input: Record<string, string | number> = {};
  for (const [key, value] of url.searchParams) {
    if (key === "page" || key === "pageSize") {
      if (!/^[1-9]\d*$/.test(value)) return null;
      input[key] = Number(value);
    } else input[key] = value;
  }
  return AuditQueryParametersSchema.safeParse(input);
}
function auditWire(query: AuditParameters, asOf: number, scenario: SystemObservationScenario) {
  const records = scenario.auditEvents
    .map((fact) => ({
      id: fact.id,
      occurredAtMs: asOf + fact.occurredAtOffsetMs,
      actorId: scenario.administratorId,
      action: fact.action,
      targetId:
        fact.targetRef === "administrator" ? scenario.administratorId : scenario.applicationId,
      result: fact.result,
      requestId: fact.requestId,
      environmentId: fact.scopeRef === "rule-publication" ? scenario.environmentId : null,
      appId: fact.scopeRef === "rule-publication" ? scenario.applicationId : null,
      bindingId: fact.scopeRef === "rule-publication" ? scenario.bindingId : null,
      publicationId: fact.scopeRef === "rule-publication" ? scenario.publicationId : null,
    }))
    .filter(
      (item) =>
        item.occurredAtMs >= Date.parse(query.start) &&
        item.occurredAtMs < Date.parse(query.end) &&
        (!query.actorId || item.actorId === query.actorId) &&
        (!query.action || item.action === query.action) &&
        (!query.result || item.result === query.result),
    );
  const offset = (query.page - 1) * query.pageSize;
  return {
    query: {
      start: query.start,
      end: query.end,
      actorId: query.actorId ?? "",
      action: query.action ?? null,
      result: query.result ?? null,
      page: query.page,
      pageSize: query.pageSize,
    },
    asOf: instant(asOf),
    total: records.length,
    items: records.slice(offset, offset + query.pageSize).map(({ occurredAtMs, ...record }) => ({
      ...record,
      occurredAt: instant(occurredAtMs),
    })),
  };
}

/** Create system observation handlers with the application-owned identities and a replaceable clock. */
export function createSystemObservationMockHandlers(
  scenario: SystemObservationScenario,
  now: () => number = Date.now,
) {
  return Object.freeze([
    http.get("*/api/v1/system/connections", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const data = connectionWire(now(), scenario);
      if (!SystemConnectionsSchema.safeParse(data).success)
        return response({ error: { code: "dependency_unavailable", requestId } }, requestId, 503);
      return response(data, requestId);
    }),
    http.get("*/api/v1/system/deployment-guides", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const data = {
        catalogRevision: "2026-10-17.1",
        runtimeCollector: { state: "not_configured", endpoint: null },
        paths: [
          { id: "existing", readiness: "configuration-required", profileRevision: null },
          { id: "linux", readiness: "guide-only", profileRevision: null },
          { id: "kubernetes", readiness: "guide-only", profileRevision: null },
        ],
      };
      if (!DeploymentGuidesSchema.safeParse(data).success)
        return response({ error: { code: "dependency_unavailable", requestId } }, requestId, 503);
      return response(data, requestId);
    }),
    http.get("*/api/v1/system/protocols", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const data = protocolWire(now(), scenario);
      if (!SystemProtocolsSchema.safeParse(data).success)
        return response({ error: { code: "dependency_unavailable", requestId } }, requestId, 503);
      return response(data, requestId);
    }),
    http.get("*/api/v2/system/protocol-observations/agent-reporting", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const query = new URL(request.url).searchParams;
      const page = Number(query.get("page") ?? 1);
      const pageSize = Number(query.get("pageSize") ?? 20);
      if (
        !Number.isSafeInteger(page) ||
        page < 1 ||
        !Number.isSafeInteger(pageSize) ||
        pageSize < 1 ||
        pageSize > 100
      )
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const asOf = now();
      const data = {
        asOf: instant(asOf),
        page,
        pageSize,
        total: 1,
        items:
          page === 1
            ? [
                {
                  environmentId: scenario.environmentId,
                  appId: scenario.applicationId,
                  instanceId: "orders-worker-0",
                  processId: "mock-process-0",
                  reporterId: "mock-reporter-0",
                  boundary: "agent-reporting",
                  collectorSupported: ["atlas-richie.reporting/v1"],
                  runtimeVersion: null,
                  compatibility: "unknown",
                  observedAt: null,
                },
              ]
            : [],
      };
      if (!AgentReportingObservationPageSchema.safeParse(data).success)
        return response({ error: { code: "dependency_unavailable", requestId } }, requestId, 503);
      return response(data, requestId);
    }),
    http.get("*/api/v2/system/protocol-observations/incident-events", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const query = new URL(request.url).searchParams;
      const page = Number(query.get("page") ?? 1);
      const pageSize = Number(query.get("pageSize") ?? 20);
      if (
        !Number.isSafeInteger(page) ||
        page < 1 ||
        !Number.isSafeInteger(pageSize) ||
        pageSize < 1 ||
        pageSize > 100
      )
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const asOf = now();
      const data = {
        asOf: instant(asOf),
        page,
        pageSize,
        total: 1,
        items:
          page === 1
            ? [
                {
                  environmentId: scenario.environmentId,
                  appId: scenario.applicationId,
                  instanceId: "orders-worker-0",
                  processId: "mock-process-0",
                  reporterId: "mock-reporter-0",
                  boundary: "incident-events",
                  collectorSupported: ["atlas-richie.incident-events/v1"],
                  runtimeVersion: null,
                  compatibility: "unknown",
                  observedAt: null,
                },
              ]
            : [],
      };
      if (!IncidentEventObservationPageSchema.safeParse(data).success)
        return response({ error: { code: "dependency_unavailable", requestId } }, requestId, 503);
      return response(data, requestId);
    }),
    http.get("*/api/v1/system/audit", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = parseQuery(new URL(request.url));
      if (!parsed?.success)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      return response(auditWire(parsed.data, now(), scenario), requestId);
    }),
  ]);
}
