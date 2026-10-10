import { http, HttpResponse } from "msw";
import { CONSOLE_ERROR_STATUS, CONSOLE_HEADER } from "../../../core/api/protocol/common";
import { IncidentDetailParametersSchema, IncidentQueryParametersSchema } from "../api/incidentWire";
import { INCIDENT_CATEGORY } from "../model/incident";
import type { IncidentFact, ObservedIncident } from "../model/incidentObservation";
import {
  incidentFixturesFor,
  type IncidentObservationScenario,
} from "./incidentObservationFixtures";

const instant = (value: number) => new Date(value).toISOString();
const response = (body: unknown, requestId: string | null, status = 200) => {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  return new HttpResponse(JSON.stringify(body), { status, headers });
};
function queryInput(url: URL) {
  const input: Record<string, string | number> = {};
  for (const [key, value] of url.searchParams) {
    if (key === "pageSize") {
      if (!/^[1-9]\d*$/.test(value)) return null;
      input[key] = Number(value);
    } else input[key] = value;
  }
  return input;
}
function wireIncident(event: ObservedIncident) {
  const { occurredAtMs, receivedAtMs, ...identity } = event;
  return { ...identity, occurredAt: instant(occurredAtMs), receivedAt: instant(receivedAtMs) };
}
function contextFrom(parameters: {
  environmentId: string;
  appId?: string;
  instanceId?: string;
  scope: "fleet" | "application" | "process";
  from: string;
  to: string;
}) {
  return {
    environmentId: parameters.environmentId,
    appId: parameters.appId ?? null,
    instanceId: parameters.instanceId ?? null,
    resource: null,
    scope: parameters.scope,
    window: { from: parameters.from, to: parameters.to },
  } as const;
}
function incidentParameters(parameters: {
  readonly environmentId: string;
  readonly appId?: string;
  readonly instanceId?: string;
  readonly resource?: string;
  readonly scope: string;
  readonly from: string;
  readonly to: string;
}) {
  if (
    (parameters.scope !== "fleet" &&
      parameters.scope !== "application" &&
      parameters.scope !== "process") ||
    (parameters.scope === "fleet" && (parameters.appId !== undefined || parameters.instanceId)) ||
    (parameters.scope === "application" && (!parameters.appId || parameters.instanceId)) ||
    (parameters.scope === "process" && (!parameters.appId || !parameters.instanceId)) ||
    parameters.resource !== undefined
  )
    return null;
  return {
    environmentId: parameters.environmentId,
    appId: parameters.appId,
    instanceId: parameters.instanceId,
    scope: parameters.scope as "fleet" | "application" | "process",
    from: parameters.from,
    to: parameters.to,
  };
}
function scopedEvents(
  parameters: {
    readonly environmentId: string;
    readonly appId?: string;
    readonly instanceId?: string;
    readonly from: string;
    readonly to: string;
  },
  scenario: IncidentObservationScenario,
) {
  return incidentFixturesFor(
    {
      environmentId: parameters.environmentId,
      appId: parameters.appId ?? null,
      fromMs: Date.parse(parameters.from),
      toMs: Date.parse(parameters.to),
    },
    scenario,
  ).filter(
    (event) => parameters.instanceId === undefined || event.instanceId === parameters.instanceId,
  );
}
function statistics(events: readonly ObservedIncident[]) {
  const apps = new Set(events.map((event) => event.appId));
  return {
    total: events.length,
    critical: events.filter((event) => event.severity === "critical").length,
    warning: events.filter((event) => event.severity === "warning").length,
    info: events.filter((event) => event.severity === "info").length,
    ruleChanges: events.filter(
      (event) =>
        event.category === INCIDENT_CATEGORY.RulePublished ||
        event.category === INCIDENT_CATEGORY.RuleEffective,
    ).length,
    affectedApplications: apps.size,
  };
}
function offsetFromCursor(cursor: string | undefined) {
  if (!cursor) return 0;
  const match = /^offset:(\d+)$/.exec(cursor);
  return match ? Number(match[1]) : null;
}
function filteredEvents(
  events: readonly ObservedIncident[],
  severity: string | undefined,
  category: string | undefined,
) {
  return events.filter(
    (event) =>
      (severity === undefined || event.severity === severity) &&
      (category === undefined || event.category === category),
  );
}

/** Mock-only incident read handlers use the exact same UTC wire schemas as live mode. */
export function createIncidentMockHandlers(
  scenario: IncidentObservationScenario,
  now: () => number = Date.now,
) {
  let timelineReadCount = 0;
  return Object.freeze([
    http.get("*/api/v1/incidents", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = IncidentQueryParametersSchema.safeParse(queryInput(new URL(request.url)));
      if (!parsed.success)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const { cursor, pageSize, severity, category, ...parameters } = parsed.data;
      const requestParameters = incidentParameters(parameters);
      if (!requestParameters)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const offset = offsetFromCursor(cursor);
      if (offset === null)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const failurePlan = scenario.incidents.timelineFailure;
      if (requestParameters.appId === failurePlan.applicationId) timelineReadCount += 1;
      if (
        requestParameters.appId === failurePlan.applicationId &&
        timelineReadCount === failurePlan.failOnRead
      ) {
        const errorCode = failurePlan.errorCode;
        return response(
          { error: { code: errorCode, requestId } },
          requestId,
          CONSOLE_ERROR_STATUS[errorCode],
        );
      }
      const events = scopedEvents(requestParameters, scenario);
      const filtered = filteredEvents(events, severity, category);
      const items = filtered.slice(offset, offset + pageSize);
      const nextOffset = offset + items.length;
      const query = {
        context: contextFrom(requestParameters),
        severity: severity ?? null,
        category: category ?? null,
        cursor: cursor ?? null,
        pageSize,
      };
      return response(
        {
          query,
          asOf: instant(now()),
          statistics: statistics(events),
          items: items.map(wireIncident),
          filteredTotal: filtered.length,
          nextCursor: nextOffset < filtered.length ? `offset:${nextOffset}` : null,
        },
        requestId,
      );
    }),
    http.get("*/api/v1/incidents/:incidentId/evidence", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = IncidentDetailParametersSchema.safeParse(queryInput(new URL(request.url)));
      if (!parsed.success)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const { severity, category, ...parameters } = parsed.data;
      const requestParameters = incidentParameters(parameters);
      if (!requestParameters)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const event = filteredEvents(
        scopedEvents(requestParameters, scenario),
        severity,
        category,
      ).find((item) => item.id === params.incidentId);
      if (!event) return response({ error: { code: "not_found", requestId } }, requestId, 404);
      const [sampleEvidence, thresholdEvidence] = scenario.incidents.evidence;
      const at = (index: number) =>
        instant(event.occurredAtMs - scenario.incidents.evidence[index].minutesBefore * 60_000);
      const facts: { id: string; source: string; at: string; fact: IncidentFact }[] = [
        {
          id: sampleEvidence.id,
          source: sampleEvidence.source,
          at: at(0),
          fact: event.caption,
        },
        {
          id: thresholdEvidence.id,
          source: thresholdEvidence.source,
          at: at(1),
          fact:
            event.caption.code === "resource_pressure"
              ? {
                  ...event.caption,
                  value: Math.max(
                    0,
                    event.caption.value - scenario.incidents.resourcePressureValueDelta,
                  ),
                }
              : event.caption,
        },
      ];
      const relatedRule =
        event.appId === scenario.incidents.relatedRule.appId &&
        event.category === INCIDENT_CATEGORY.RulePublished &&
        event.publicationId === scenario.incidents.relatedRule.publicationId &&
        event.caption.code === "rule_published"
          ? {
              environmentId: event.environmentId,
              appId: event.appId,
              bindingId: scenario.incidents.relatedRule.bindingId,
              versionId: event.caption.versionId,
              publicationId: event.publicationId,
            }
          : null;
      const query = {
        context: contextFrom(requestParameters),
        eventId: event.id,
        severity: severity ?? null,
        category: category ?? null,
      };
      return response(
        {
          query,
          asOf: instant(now()),
          event: wireIncident(event),
          facts,
          completeness: "complete",
          suggestedViews: event.instanceId
            ? relatedRule
              ? ["instance", "metrics", "rules"]
              : ["instance", "metrics"]
            : relatedRule
              ? ["rules"]
              : [],
          relatedRule,
        },
        requestId,
      );
    }),
  ]);
}
