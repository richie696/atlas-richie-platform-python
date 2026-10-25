import { validInventoryCoverage, type InventoryCoverage } from "./inventoryCoverage";

/** Common observation identities and units, not Console wire DTOs or chart coordinates. */
export const OBSERVATION_SCOPE = Object.freeze({
  Fleet: "fleet",
  Application: "application",
  Host: "host",
  Container: "container",
  Process: "process",
} as const);
export type ObservationScope = (typeof OBSERVATION_SCOPE)[keyof typeof OBSERVATION_SCOPE];
export const METRIC_ID = Object.freeze({
  HttpQps: "http_qps",
  EntryRate: "resource_entry_rate",
  Tps: "tps",
  RtP95: "rt_p95",
  BlockedRatio: "blocked_ratio",
  CpuRatio: "cpu_ratio",
  MemoryRatio: "memory_ratio",
  MemoryBytes: "memory_bytes",
} as const);
export type MetricId = (typeof METRIC_ID)[keyof typeof METRIC_ID];
/** Common operational selection. TPS requires independent instrumentation, never a QPS alias. */
export const OPERATIONAL_METRICS: readonly MetricId[] = Object.freeze([
  METRIC_ID.HttpQps,
  METRIC_ID.Tps,
  METRIC_ID.RtP95,
  METRIC_ID.BlockedRatio,
  METRIC_ID.CpuRatio,
  METRIC_ID.MemoryRatio,
]);
export const METRIC_UNIT = Object.freeze({
  [METRIC_ID.HttpQps]: "requests_per_second",
  [METRIC_ID.EntryRate]: "entries_per_second",
  [METRIC_ID.Tps]: "transactions_per_second",
  [METRIC_ID.RtP95]: "milliseconds",
  [METRIC_ID.BlockedRatio]: "ratio",
  [METRIC_ID.CpuRatio]: "ratio",
  [METRIC_ID.MemoryRatio]: "ratio",
  [METRIC_ID.MemoryBytes]: "bytes",
} as const);
export type MetricUnit = (typeof METRIC_UNIT)[MetricId];
export const OBSERVATION_QUALITY = Object.freeze({
  Available: "available",
  Partial: "partial",
  Stale: "stale",
  NoSamples: "no_samples",
  NotIntegrated: "not_integrated",
} as const);
export type ObservationQuality = (typeof OBSERVATION_QUALITY)[keyof typeof OBSERVATION_QUALITY];
/** Stable aggregation basis; UI labels are translated, never exposed as protocol field names. */
export const METRIC_BASIS = Object.freeze({
  Processes: "reporting_processes",
  Hosts: "reporting_hosts",
  Containers: "reporting_containers",
  CpuCores: "cpu_cores",
  MemoryLimit: "memory_limit_bytes",
  CompletedRequests: "completed_http_requests",
  AttemptedEntries: "attempted_entries",
  BusinessTransactions: "business_transactions",
  ElapsedSeconds: "elapsed_seconds",
} as const);
export type MetricBasis = (typeof METRIC_BASIS)[keyof typeof METRIC_BASIS];
/** Aggregation basis is a property of the metric, not a caller-selected display option. */
export const METRIC_DENOMINATOR: Readonly<Record<MetricId, MetricBasis>> = Object.freeze({
  [METRIC_ID.HttpQps]: METRIC_BASIS.CompletedRequests,
  [METRIC_ID.EntryRate]: METRIC_BASIS.AttemptedEntries,
  [METRIC_ID.Tps]: METRIC_BASIS.BusinessTransactions,
  [METRIC_ID.RtP95]: METRIC_BASIS.CompletedRequests,
  [METRIC_ID.BlockedRatio]: METRIC_BASIS.AttemptedEntries,
  [METRIC_ID.CpuRatio]: METRIC_BASIS.CpuCores,
  [METRIC_ID.MemoryRatio]: METRIC_BASIS.MemoryLimit,
  [METRIC_ID.MemoryBytes]: METRIC_BASIS.Processes,
});
export const MAX_OBSERVATION_POINTS = 1000;
export const MAX_OBSERVATION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

/** UTC epoch milliseconds inside the application. HTTP conversion to RFC3339 belongs to the adapter. */
export interface ObservationWindow {
  readonly fromMs: number;
  readonly toMs: number;
}
export interface ObservationContext {
  readonly environmentId: string;
  readonly appId: string | null;
  readonly instanceId: string | null;
  readonly resource: string | null;
  readonly scope: ObservationScope;
  readonly window: ObservationWindow;
}
export interface ObservationCoverage extends InventoryCoverage {
  readonly reporting: number;
}
/** Denominator is explicit (e.g. reporting processes, not host cores). Never silently average percentiles. */
export interface MetricMetadata {
  readonly source: string;
  readonly denominator: MetricBasis;
  readonly coverage: ObservationCoverage;
  readonly quality: ObservationQuality;
}
export interface MetricReading extends MetricMetadata {
  readonly metric: MetricId;
  readonly unit: MetricUnit;
  readonly value: number | null;
  readonly sampledAtMs: number | null;
}
export interface MetricSample {
  readonly atMs: number;
  readonly value: number | null;
}
export interface MetricSeries extends MetricMetadata {
  readonly metric: MetricId;
  readonly unit: MetricUnit;
  readonly samples: readonly MetricSample[];
}
/** A management fact, not a Reporter wire event or inferred chart discontinuity. */
export interface ObservationAnnotation {
  readonly id: string;
  readonly kind: "publication" | "source_activation" | "incident";
  readonly atMs: number;
  readonly versionId?: string;
  readonly publicationId?: string;
  readonly incidentId?: string;
}
export interface MetricQuery {
  readonly context: ObservationContext;
  readonly metrics: readonly MetricId[];
  readonly stepMs: number;
}
export interface MetricBundle {
  readonly query: MetricQuery;
  /** Server read time, NOT each point's sample time. */
  readonly asOfMs: number;
  readonly summary: readonly MetricReading[];
  readonly series: readonly MetricSeries[];
  readonly annotations: readonly ObservationAnnotation[];
}
export function isObservationTime(value: number): boolean {
  return Number.isSafeInteger(value) && Number.isFinite(new Date(value).getTime());
}
export function validObservationWindow(window: ObservationWindow): boolean {
  return (
    isObservationTime(window.fromMs) &&
    isObservationTime(window.toMs) &&
    window.fromMs < window.toMs &&
    window.toMs - window.fromMs <= MAX_OBSERVATION_WINDOW_MS
  );
}
export function withinObservationWindow(atMs: number, window: ObservationWindow): boolean {
  return isObservationTime(atMs) && atMs >= window.fromMs && atMs < window.toMs;
}
export function validCoverage(coverage: ObservationCoverage): boolean {
  return (
    validInventoryCoverage(coverage) &&
    Number.isSafeInteger(coverage.reporting) &&
    coverage.reporting >= 0 &&
    (coverage.expected === null || coverage.reporting <= coverage.expected)
  );
}
/** A stable semantic key. IDs remain opaque; translating labels never changes the query. */
export function observationContextKey(context: ObservationContext): string {
  return JSON.stringify([
    context.environmentId,
    context.appId,
    context.instanceId,
    context.resource,
    context.scope,
    context.window.fromMs,
    context.window.toMs,
  ]);
}
export function metricQueryKey(query: MetricQuery): string {
  return JSON.stringify([
    observationContextKey(query.context),
    [...query.metrics].sort(),
    query.stepMs,
  ]);
}
export function validObservationContext(context: ObservationContext): boolean {
  return (
    !!context.environmentId.trim() &&
    [context.appId, context.instanceId, context.resource].every(
      (id) => id === null || !!id.trim(),
    ) &&
    Object.values(OBSERVATION_SCOPE).includes(context.scope) &&
    validObservationWindow(context.window) &&
    (context.instanceId === null || context.appId !== null)
  );
}
export function validMetricQuery(query: MetricQuery): boolean {
  return (
    validObservationContext(query.context) &&
    query.metrics.length > 0 &&
    new Set(query.metrics).size === query.metrics.length &&
    query.metrics.every((metric) => Object.hasOwn(METRIC_UNIT, metric)) &&
    Number.isSafeInteger(query.stepMs) &&
    query.stepMs > 0 &&
    Math.ceil((query.context.window.toMs - query.context.window.fromMs) / query.stepMs) <=
      MAX_OBSERVATION_POINTS
  );
}
function validMetadata(value: MetricMetadata, metric: MetricId): boolean {
  return (
    !!value.source.trim() &&
    Object.values(METRIC_BASIS).includes(value.denominator) &&
    value.denominator === METRIC_DENOMINATOR[metric] &&
    validCoverage(value.coverage) &&
    Object.values(OBSERVATION_QUALITY).includes(value.quality) &&
    (value.quality !== OBSERVATION_QUALITY.Available ||
      (value.coverage.reporting > 0 && value.coverage.reporting === value.coverage.expected)) &&
    (qualityAllowsValues(value.quality) || value.coverage.reporting === 0)
  );
}
function validMetricValue(metric: MetricId, value: number | null): boolean {
  return (
    value === null ||
    (Number.isFinite(value) && value >= 0 && (METRIC_UNIT[metric] !== "ratio" || value <= 1))
  );
}
function qualityAllowsValues(quality: ObservationQuality): boolean {
  return quality !== OBSERVATION_QUALITY.NoSamples && quality !== OBSERVATION_QUALITY.NotIntegrated;
}
/** Validate semantic compatibility after transport decoding, without filling missing metrics with zero. */
export function validMetricReading(value: MetricReading, window: ObservationWindow): boolean {
  return (
    Object.hasOwn(METRIC_UNIT, value.metric) &&
    value.unit === METRIC_UNIT[value.metric] &&
    validMetadata(value, value.metric) &&
    validMetricValue(value.metric, value.value) &&
    (value.value === null || value.coverage.reporting > 0) &&
    (value.value === null || qualityAllowsValues(value.quality)) &&
    (value.quality !== OBSERVATION_QUALITY.Available || value.value !== null) &&
    (value.value === null
      ? value.sampledAtMs === null
      : value.sampledAtMs !== null && withinObservationWindow(value.sampledAtMs, window))
  );
}
export function validMetricSeries(value: MetricSeries, window: ObservationWindow): boolean {
  if (
    !Object.hasOwn(METRIC_UNIT, value.metric) ||
    value.unit !== METRIC_UNIT[value.metric] ||
    !validMetadata(value, value.metric) ||
    value.samples.length > MAX_OBSERVATION_POINTS
  )
    return false;
  let previous = -Infinity;
  for (const sample of value.samples) {
    if (
      !withinObservationWindow(sample.atMs, window) ||
      sample.atMs <= previous ||
      !validMetricValue(value.metric, sample.value) ||
      (sample.value !== null && value.coverage.reporting === 0) ||
      (sample.value !== null && !qualityAllowsValues(value.quality))
    )
      return false;
    previous = sample.atMs;
  }
  return (
    value.quality !== OBSERVATION_QUALITY.Available ||
    value.samples.some((sample) => sample.value !== null)
  );
}
export function validMetricBundle(value: MetricBundle, query: MetricQuery): boolean {
  const sameMetrics = (items: readonly { readonly metric: MetricId }[]) =>
    items.length === query.metrics.length &&
    new Set(items.map((item) => item.metric)).size === items.length &&
    items.every((item) => query.metrics.includes(item.metric));
  return (
    validMetricQuery(query) &&
    metricQueryKey(value.query) === metricQueryKey(query) &&
    isObservationTime(value.asOfMs) &&
    sameMetrics(value.summary) &&
    sameMetrics(value.series) &&
    value.summary.every((item) => validMetricReading(item, query.context.window)) &&
    value.series.every((item) => validMetricSeries(item, query.context.window)) &&
    value.summary.every((reading) => {
      const series = value.series.find((item) => item.metric === reading.metric);
      return (
        series !== undefined &&
        reading.unit === series.unit &&
        reading.source === series.source &&
        reading.denominator === series.denominator &&
        reading.quality === series.quality &&
        reading.coverage.expected === series.coverage.expected &&
        reading.coverage.inventorySource === series.coverage.inventorySource &&
        reading.coverage.reporting === series.coverage.reporting
      );
    }) &&
    new Set(value.annotations.map((item) => item.id)).size === value.annotations.length &&
    value.annotations.every(
      (item) =>
        !!item.id.trim() &&
        ["publication", "source_activation", "incident"].includes(item.kind) &&
        withinObservationWindow(item.atMs, query.context.window),
    )
  );
}
