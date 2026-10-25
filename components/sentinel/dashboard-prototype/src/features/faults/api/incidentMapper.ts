import type { z } from "zod";
import { instantToMilliseconds } from "../../../core/api/protocol/common";
import { observationContextFromWire } from "../../../shared/api/observationMapper";
import type {
  IncidentEvidence,
  IncidentPage,
  ObservedIncident,
} from "../model/incidentObservation";
import type {
  IncidentEvidenceSchema,
  IncidentPageSchema,
  ObservedIncidentSchema,
} from "./incidentWire";
export function observedIncidentFromWire(
  value: z.infer<typeof ObservedIncidentSchema>,
): ObservedIncident {
  const { occurredAt, receivedAt, ...incident } = value;
  return {
    ...incident,
    occurredAtMs: instantToMilliseconds(occurredAt),
    receivedAtMs: instantToMilliseconds(receivedAt),
  };
}
export function incidentPageFromWire(value: z.infer<typeof IncidentPageSchema>): IncidentPage {
  return {
    query: { ...value.query, context: observationContextFromWire(value.query.context) },
    asOfMs: instantToMilliseconds(value.asOf),
    statistics: value.statistics,
    items: value.items.map(observedIncidentFromWire),
    filteredTotal: value.filteredTotal,
    nextCursor: value.nextCursor,
  };
}
export function incidentEvidenceFromWire(
  value: z.infer<typeof IncidentEvidenceSchema>,
): IncidentEvidence {
  return {
    query: { ...value.query, context: observationContextFromWire(value.query.context) },
    asOfMs: instantToMilliseconds(value.asOf),
    event: observedIncidentFromWire(value.event),
    facts: value.facts.map(({ at, ...fact }) => ({ ...fact, atMs: instantToMilliseconds(at) })),
    completeness: value.completeness,
    suggestedViews: value.suggestedViews,
    relatedRule: value.relatedRule,
  };
}
