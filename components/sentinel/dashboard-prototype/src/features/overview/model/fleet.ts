import {
  OPERATIONAL_METRICS,
  OBSERVATION_SCOPE,
  isObservationTime,
  observationContextKey,
  validCoverage,
  validMetricBundle,
  validMetricReading,
  validObservationContext,
  validMetricQuery,
  type MetricBundle,
  type MetricReading,
  type ObservationContext,
  type ObservationCoverage,
} from "../../../shared/model/observation";

/** Fleet statistics cover the selected environment/application/window, not the current table page. */
export const FLEET_METRICS = OPERATIONAL_METRICS;
export interface FleetQuery {
  readonly context: ObservationContext;
  readonly page: number;
  readonly pageSize: number;
  readonly search: string;
  readonly stepMs: number;
}
export interface FleetApplication {
  readonly appId: string;
  readonly name: string;
  readonly health: "healthy" | "attention" | "unknown";
  readonly instanceCoverage: ObservationCoverage;
  readonly ruleCoverage: ObservationCoverage;
  /** Readings for this appId/application scope; never substitute the fleet aggregate bundle. */
  readonly metrics: readonly MetricReading[];
}
/** A dependency probe, distinct from the selected application's traffic/sample timestamp. */
export interface FleetConnection {
  readonly id: string;
  readonly provider: "nacos" | "consul" | "collector";
  readonly state: "available" | "unavailable" | "not_configured" | "unknown";
  readonly checkedAtMs: number | null;
  readonly latencyMs: number | null;
}
export interface FleetSnapshot {
  readonly query: FleetQuery;
  readonly asOfMs: number;
  readonly coverage: ObservationCoverage;
  readonly totalApplications: number;
  readonly attentionApplications: number;
  /** Available explicit drill-down targets; absence never invents the first application. */
  readonly attentionTargets: readonly string[];
  readonly applications: {
    readonly items: readonly FleetApplication[];
    readonly total: number;
    readonly page: number;
    readonly pageSize: number;
  };
  readonly metrics: MetricBundle;
  readonly connections: readonly FleetConnection[];
}
export function fleetQueryKey(query: FleetQuery): string {
  return JSON.stringify([
    observationContextKey(query.context),
    query.page,
    query.pageSize,
    query.search,
    query.stepMs,
  ]);
}
export function validFleetQuery(query: FleetQuery): boolean {
  const context = query.context;
  return (
    validObservationContext(context) &&
    context.instanceId === null &&
    context.resource === null &&
    context.scope ===
      (context.appId === null ? OBSERVATION_SCOPE.Fleet : OBSERVATION_SCOPE.Application) &&
    Number.isSafeInteger(query.page) &&
    query.page > 0 &&
    Number.isSafeInteger(query.pageSize) &&
    query.pageSize > 0 &&
    query.pageSize <= 100 &&
    Number.isSafeInteger(query.stepMs) &&
    query.stepMs > 0 &&
    validMetricQuery({ context, metrics: FLEET_METRICS, stepMs: query.stepMs })
  );
}
const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
/** Reject mixed-scope/incorrect pagination/units rather than silently lending another application's values. */
export function validFleetSnapshot(value: FleetSnapshot, query: FleetQuery): boolean {
  const page = value.applications;
  return (
    validFleetQuery(query) &&
    fleetQueryKey(value.query) === fleetQueryKey(query) &&
    isObservationTime(value.asOfMs) &&
    validCoverage(value.coverage) &&
    count(value.totalApplications) &&
    (query.context.appId === null || value.totalApplications <= 1) &&
    count(value.attentionApplications) &&
    value.attentionApplications <= value.totalApplications &&
    new Set(value.attentionTargets).size === value.attentionTargets.length &&
    value.attentionTargets.length <= value.attentionApplications &&
    value.attentionTargets.every(
      (id) => !!id.trim() && (query.context.appId === null || id === query.context.appId),
    ) &&
    page.page === query.page &&
    page.pageSize === query.pageSize &&
    count(page.total) &&
    page.total <= value.totalApplications &&
    page.items.length <= query.pageSize &&
    page.items.length <= page.total &&
    new Set(page.items.map((item) => item.appId)).size === page.items.length &&
    page.items.every(
      (item) =>
        !!item.appId.trim() &&
        !!item.name.trim() &&
        (query.context.appId === null || item.appId === query.context.appId) &&
        ["healthy", "attention", "unknown"].includes(item.health) &&
        validCoverage(item.instanceCoverage) &&
        validCoverage(item.ruleCoverage) &&
        item.metrics.length === FLEET_METRICS.length &&
        new Set(item.metrics.map((reading) => reading.metric)).size === item.metrics.length &&
        item.metrics.every(
          (reading) =>
            FLEET_METRICS.includes(reading.metric) &&
            validMetricReading(reading, query.context.window),
        ),
    ) &&
    validMetricBundle(value.metrics, {
      context: query.context,
      metrics: FLEET_METRICS,
      stepMs: query.stepMs,
    }) &&
    value.metrics.asOfMs === value.asOfMs &&
    new Set(value.connections.map((item) => item.id)).size === value.connections.length &&
    value.connections.every(
      (item) =>
        !!item.id.trim() &&
        ["nacos", "consul", "collector"].includes(item.provider) &&
        ["available", "unavailable", "not_configured", "unknown"].includes(item.state) &&
        (item.checkedAtMs === null || isObservationTime(item.checkedAtMs)) &&
        (item.latencyMs === null || (Number.isFinite(item.latencyMs) && item.latencyMs >= 0)),
    )
  );
}
