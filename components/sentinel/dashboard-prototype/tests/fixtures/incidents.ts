// Finite synthetic incident facts, not the production seed or Reporter schema.
import type {
  IncidentQuery,
  IncidentPage,
  ObservedIncident,
  IncidentDetailQuery,
  IncidentEvidence,
} from "../../src/features/faults/model/incidentObservation";
import { query } from "./observations";
export const incidentQuery: IncidentQuery = {
  context: query.context,
  severity: null,
  category: null,
  cursor: null,
  pageSize: 2,
};
export function eventsFor(
  input: Pick<IncidentQuery, "context"> = incidentQuery,
): readonly ObservedIncident[] {
  const context = input.context;
  return [
    {
      id: "event-c",
      occurredAtMs: context.window.fromMs + 600_000,
      severity: "critical",
      category: "resource",
      caption: { code: "resource_pressure", metric: "cpu_ratio", value: 0.9, threshold: 0.8 },
      instanceId: "instance-1",
      processEpoch: "incarnation-1",
      publicationId: null,
    },
    {
      id: "event-b",
      occurredAtMs: context.window.fromMs + 600_000,
      severity: "info",
      category: "rulePublished",
      caption: { code: "rule_published", versionId: "version-one" },
      instanceId: null,
      processEpoch: null,
      publicationId: "publication-one",
    },
    {
      id: "event-a",
      occurredAtMs: context.window.fromMs + 60_000,
      severity: "warning",
      category: "rt",
      caption: { code: "response_time", valueMs: 180, thresholdMs: 150 },
      instanceId: "instance-1",
      processEpoch: "incarnation-1",
      publicationId: null,
    },
  ].map(
    (value) =>
      ({
        ...value,
        environmentId: context.environmentId,
        appId: "app-one",
        sourceEventId: `source-${value.id}`,
        receivedAtMs: context.window.toMs + 120_000,
      }) as ObservedIncident,
  );
}
export function incidentPageFor(input: IncidentQuery = incidentQuery): IncidentPage {
  const all = eventsFor(input).filter(
    (item) =>
      (input.context.appId === null || input.context.appId === item.appId) &&
      (input.context.instanceId === null || input.context.instanceId === item.instanceId),
  );
  const filtered = all.filter(
    (item) =>
      (input.severity === null || item.severity === input.severity) &&
      (input.category === null || item.category === input.category),
  );
  const start = input.cursor === null ? 0 : Number(input.cursor);
  return {
    query: input,
    asOfMs: input.context.window.toMs + 180_000,
    statistics: {
      total: all.length,
      critical: all.filter((item) => item.severity === "critical").length,
      warning: all.filter((item) => item.severity === "warning").length,
      info: all.filter((item) => item.severity === "info").length,
      ruleChanges: all.filter((item) => item.category === "rulePublished").length,
      affectedApplications: all.length > 0 ? 1 : 0,
    },
    filteredTotal: filtered.length,
    items: filtered.slice(start, start + input.pageSize),
    nextCursor: start + input.pageSize < filtered.length ? String(start + input.pageSize) : null,
  };
}
export function evidenceFor(input: IncidentDetailQuery): IncidentEvidence {
  const event = eventsFor(input).find((item) => item.id === input.eventId);
  if (!event) throw new Error("Synthetic missing incident");
  const version =
    event.caption.code === "rule_published" || event.caption.code === "rule_applied"
      ? event.caption.versionId
      : null;
  return {
    query: input,
    asOfMs: input.context.window.toMs + 180_000,
    event,
    completeness: "complete",
    facts: [
      { id: "fact-one", source: "test-collector", atMs: event.occurredAtMs, fact: event.caption },
    ],
    relatedRule:
      version === null
        ? null
        : {
            environmentId: event.environmentId,
            appId: event.appId,
            bindingId: "binding-app-one",
            versionId: version,
            publicationId: event.publicationId!,
          },
    suggestedViews: version === null ? ["instance", "metrics"] : ["rules", "metrics"],
  };
}
