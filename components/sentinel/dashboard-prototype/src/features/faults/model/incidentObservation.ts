import { compareScalarText } from "../../../shared/model/scalarTextOrder";
import {
  validObservationContext,
  observationContextKey,
  withinObservationWindow,
  isObservationTime,
  METRIC_ID,
  OBSERVATION_SCOPE,
  type ObservationContext,
} from "../../../shared/model/observation";
import {
  INCIDENT_CATEGORY,
  INCIDENT_SEVERITY,
  type IncidentCategory,
  type IncidentSeverity,
} from "./incident";
import { MAX_NAVIGATION_CURSOR_LENGTH } from "../../../shared/types/navigation";
import {
  hasNonBlankWireContent,
  hasOnlyUnicodeScalarValues,
} from "../../../core/api/protocol/wireString";

export const MAX_INCIDENT_PAGE_SIZE = 100;
export const MAX_INCIDENT_CURSOR_LENGTH = MAX_NAVIGATION_CURSOR_LENGTH;
export const MAX_INCIDENT_EVIDENCE_ITEMS = 100;
export const INCIDENT_FACT_CODE = Object.freeze({
  ResourcePressure: "resource_pressure",
  ResponseTime: "response_time",
  RulePublished: "rule_published",
  RuleApplied: "rule_applied",
} as const);
/** Finite structured captions replace raw exception/business-log text. Values are facts, not translated prose. */
export type IncidentFact =
  | {
      readonly code: typeof INCIDENT_FACT_CODE.ResourcePressure;
      readonly metric: typeof METRIC_ID.CpuRatio | typeof METRIC_ID.MemoryRatio;
      readonly value: number;
      readonly threshold: number;
    }
  | {
      readonly code: typeof INCIDENT_FACT_CODE.ResponseTime;
      readonly valueMs: number;
      readonly thresholdMs: number;
    }
  | { readonly code: typeof INCIDENT_FACT_CODE.RulePublished; readonly versionId: string }
  | { readonly code: typeof INCIDENT_FACT_CODE.RuleApplied; readonly versionId: string };
export interface ObservedIncident {
  readonly id: string;
  readonly environmentId: string;
  readonly appId: string;
  readonly instanceId: string | null;
  readonly processEpoch: string | null;
  readonly occurredAtMs: number;
  /** Collector time may be later than the observation window; client clock skew does not imply invalid receipt. */
  readonly receivedAtMs: number;
  readonly severity: IncidentSeverity;
  readonly category: IncidentCategory;
  readonly sourceEventId: string | null;
  readonly publicationId: string | null;
  readonly caption: IncidentFact;
}
export interface IncidentQuery {
  readonly context: ObservationContext;
  readonly severity: IncidentSeverity | null;
  readonly category: IncidentCategory | null;
  readonly cursor: string | null;
  readonly pageSize: number;
}
/** Whole unfiltered scope statistics are separate from severity/category filtering and cursor pagination. */
export interface IncidentStatistics {
  readonly total: number;
  readonly critical: number;
  readonly warning: number;
  readonly info: number;
  readonly ruleChanges: number;
  readonly affectedApplications: number;
}
export interface IncidentPage {
  readonly query: IncidentQuery;
  readonly asOfMs: number;
  readonly statistics: IncidentStatistics;
  readonly items: readonly ObservedIncident[];
  readonly filteredTotal: number;
  readonly nextCursor: string | null;
}
export interface IncidentDetailQuery {
  readonly context: ObservationContext;
  readonly eventId: string;
  readonly severity: IncidentSeverity | null;
  readonly category: IncidentCategory | null;
}
export interface IncidentEvidenceFact {
  readonly id: string;
  readonly source: string;
  readonly atMs: number;
  readonly fact: IncidentFact;
}
export interface IncidentEvidence {
  readonly query: IncidentDetailQuery;
  readonly asOfMs: number;
  readonly event: ObservedIncident;
  readonly facts: readonly IncidentEvidenceFact[];
  readonly completeness: "complete" | "partial" | "unavailable";
  /** Suggestions navigate to facts; they never execute writes, tune thresholds or declare a root cause. */
  readonly suggestedViews: readonly ("instance" | "metrics" | "rules")[];
  /** Exact rule identities are a server-owned projection; none are inferred from display text. */
  readonly relatedRule: {
    readonly environmentId: string;
    readonly appId: string;
    readonly bindingId: string;
    readonly versionId: string;
    readonly publicationId: string;
  } | null;
}
/** URL query is untrusted; map only recognized filters and bounded opaque cursors into a feature query. */
export function incidentQueryFromRoute(
  base: IncidentQuery,
  route: {
    readonly severity?: string;
    readonly category?: string;
    readonly cursor?: string;
  },
): IncidentQuery {
  const severity =
    Object.values(INCIDENT_SEVERITY).find((value) => value === route.severity) ?? null;
  const category =
    Object.values(INCIDENT_CATEGORY).find((value) => value === route.category) ?? null;
  const cursor = cursorValid(route.cursor ?? null) ? (route.cursor ?? null) : null;
  return { ...base, severity, category, cursor };
}
const identifier = (value: string) =>
  hasOnlyUnicodeScalarValues(value) && hasNonBlankWireContent(value);
const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
const cursorValid = (value: string | null) =>
  value === null ||
  (hasOnlyUnicodeScalarValues(value) &&
    hasNonBlankWireContent(value) &&
    value.length <= MAX_INCIDENT_CURSOR_LENGTH);
const finiteNonnegative = (value: number) => Number.isFinite(value) && value >= 0;
const FACT_CATEGORY = Object.freeze({
  [INCIDENT_FACT_CODE.ResourcePressure]: INCIDENT_CATEGORY.Resource,
  [INCIDENT_FACT_CODE.ResponseTime]: INCIDENT_CATEGORY.ResponseTime,
  [INCIDENT_FACT_CODE.RulePublished]: INCIDENT_CATEGORY.RulePublished,
  [INCIDENT_FACT_CODE.RuleApplied]: INCIDENT_CATEGORY.RuleEffective,
});
function validFilters(query: Pick<IncidentQuery, "context" | "severity" | "category">): boolean {
  const { appId, instanceId, scope } = query.context;
  const validScopeIdentity =
    (scope === OBSERVATION_SCOPE.Fleet && appId === null && instanceId === null) ||
    (scope === OBSERVATION_SCOPE.Application && appId !== null && instanceId === null) ||
    (scope === OBSERVATION_SCOPE.Process && appId !== null && instanceId !== null);
  return (
    validObservationContext(query.context) &&
    query.context.resource === null &&
    validScopeIdentity &&
    (query.severity === null || Object.values(INCIDENT_SEVERITY).includes(query.severity)) &&
    (query.category === null || Object.values(INCIDENT_CATEGORY).includes(query.category))
  );
}
export function incidentQueryKey(query: IncidentQuery): string {
  return JSON.stringify([
    observationContextKey(query.context),
    query.severity,
    query.category,
    query.cursor,
    query.pageSize,
  ]);
}
export function incidentDetailKey(query: IncidentDetailQuery): string {
  return JSON.stringify([
    observationContextKey(query.context),
    query.eventId,
    query.severity,
    query.category,
  ]);
}
export function validIncidentQuery(query: IncidentQuery): boolean {
  return (
    validFilters(query) &&
    cursorValid(query.cursor) &&
    count(query.pageSize) &&
    query.pageSize > 0 &&
    query.pageSize <= MAX_INCIDENT_PAGE_SIZE
  );
}
export function validIncidentDetailQuery(query: IncidentDetailQuery): boolean {
  return validFilters(query) && identifier(query.eventId);
}
export function validIncidentFact(value: IncidentFact): boolean {
  switch (value.code) {
    case INCIDENT_FACT_CODE.ResourcePressure:
      return (
        [METRIC_ID.CpuRatio, METRIC_ID.MemoryRatio].includes(value.metric) &&
        finiteNonnegative(value.value) &&
        value.value <= 1 &&
        finiteNonnegative(value.threshold) &&
        value.threshold <= 1
      );
    case INCIDENT_FACT_CODE.ResponseTime:
      return finiteNonnegative(value.valueMs) && finiteNonnegative(value.thresholdMs);
    case INCIDENT_FACT_CODE.RulePublished:
    case INCIDENT_FACT_CODE.RuleApplied:
      return identifier(value.versionId);
    default:
      return false;
  }
}
export function incidentMatches(
  value: ObservedIncident,
  query: Pick<IncidentQuery, "context" | "severity" | "category">,
): boolean {
  return (
    identifier(value.id) &&
    identifier(value.appId) &&
    value.environmentId === query.context.environmentId &&
    (query.context.appId === null || value.appId === query.context.appId) &&
    (query.context.instanceId === null || value.instanceId === query.context.instanceId) &&
    [value.instanceId, value.processEpoch, value.sourceEventId, value.publicationId].every(
      (item) => item === null || identifier(item),
    ) &&
    (value.instanceId !== null || value.processEpoch === null) &&
    withinObservationWindow(value.occurredAtMs, query.context.window) &&
    isObservationTime(value.receivedAtMs) &&
    Object.values(INCIDENT_SEVERITY).includes(value.severity) &&
    Object.values(INCIDENT_CATEGORY).includes(value.category) &&
    (query.severity === null || value.severity === query.severity) &&
    (query.category === null || value.category === query.category) &&
    validIncidentFact(value.caption) &&
    value.category === FACT_CATEGORY[value.caption.code]
  );
}
/** Code-point ID tie-breaker is locale-independent; preserve server order, never sort after pagination. */
export function incidentPrecedes(first: ObservedIncident, second: ObservedIncident): boolean {
  if (first.occurredAtMs !== second.occurredAtMs) return first.occurredAtMs > second.occurredAtMs;
  return compareScalarText(first.id, second.id) > 0;
}
function validStatistics(value: IncidentStatistics): boolean {
  return (
    Object.values(value).every(count) &&
    value.total === value.critical + value.warning + value.info &&
    value.ruleChanges <= value.total &&
    value.affectedApplications <= value.total
  );
}
export function validIncidentPage(value: IncidentPage, query: IncidentQuery): boolean {
  return (
    validIncidentQuery(query) &&
    incidentQueryKey(value.query) === incidentQueryKey(query) &&
    isObservationTime(value.asOfMs) &&
    validStatistics(value.statistics) &&
    count(value.filteredTotal) &&
    value.filteredTotal <= value.statistics.total &&
    (query.severity === null || value.filteredTotal <= value.statistics[query.severity]) &&
    value.items.length <= query.pageSize &&
    value.items.length <= value.filteredTotal &&
    new Set(value.items.map((item) => item.id)).size === value.items.length &&
    value.items.every(
      (item, index) =>
        incidentMatches(item, query) &&
        (index === 0 || incidentPrecedes(value.items[index - 1], item)),
    ) &&
    cursorValid(value.nextCursor) &&
    (value.nextCursor === null || (value.nextCursor !== query.cursor && value.items.length > 0))
  );
}
/** An explicit filtered-out/missing event is not replaced by the first timeline item. */
export function validIncidentEvidence(
  value: IncidentEvidence,
  query: IncidentDetailQuery,
): boolean {
  return (
    validIncidentDetailQuery(query) &&
    incidentDetailKey(value.query) === incidentDetailKey(query) &&
    value.event.id === query.eventId &&
    incidentMatches(value.event, query) &&
    isObservationTime(value.asOfMs) &&
    ["complete", "partial", "unavailable"].includes(value.completeness) &&
    value.facts.length <= MAX_INCIDENT_EVIDENCE_ITEMS &&
    (value.completeness !== "complete" || value.facts.length > 0) &&
    (value.completeness !== "unavailable" || value.facts.length === 0) &&
    new Set(value.facts.map((item) => item.id)).size === value.facts.length &&
    value.facts.every(
      (item) =>
        identifier(item.id) &&
        identifier(item.source) &&
        isObservationTime(item.atMs) &&
        validIncidentFact(item.fact),
    ) &&
    (value.relatedRule === null ||
      ([
        value.relatedRule.bindingId,
        value.relatedRule.versionId,
        value.relatedRule.publicationId,
        value.relatedRule.environmentId,
        value.relatedRule.appId,
      ].every(identifier) &&
        value.event.environmentId === value.relatedRule.environmentId &&
        value.event.appId === value.relatedRule.appId &&
        value.event.publicationId === value.relatedRule.publicationId &&
        (value.event.caption.code === INCIDENT_FACT_CODE.RulePublished ||
          value.event.caption.code === INCIDENT_FACT_CODE.RuleApplied) &&
        value.event.caption.versionId === value.relatedRule.versionId)) &&
    new Set(value.suggestedViews).size === value.suggestedViews.length &&
    value.suggestedViews.every(
      (view) =>
        ["instance", "metrics", "rules"].includes(view) &&
        (view !== "instance" || value.event.instanceId !== null) &&
        (view !== "rules" || value.relatedRule !== null),
    )
  );
}
