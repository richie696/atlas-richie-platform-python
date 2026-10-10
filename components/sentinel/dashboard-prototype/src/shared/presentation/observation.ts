import {
  METRIC_UNIT,
  validObservationWindow,
  type MetricId,
  type MetricReading,
  type MetricSeries,
  type ObservationContext,
  type MetricBasis,
  type ObservationWindow,
} from "../model/observation";
import type { TranslationKey } from "../types/translation";
import { formatLocaleNumber } from "./formatLocaleNumber";
export const METRIC_BASIS_LABEL_KEY: Readonly<Record<MetricBasis, TranslationKey>> = Object.freeze({
  reporting_processes: "observation.basis.processes",
  reporting_hosts: "observation.basis.hosts",
  reporting_containers: "observation.basis.containers",
  cpu_cores: "observation.basis.cpuCores",
  memory_limit_bytes: "observation.basis.memoryLimit",
  completed_http_requests: "observation.basis.completedRequests",
  attempted_entries: "observation.basis.attemptedEntries",
  business_transactions: "observation.basis.transactions",
  elapsed_seconds: "observation.basis.seconds",
});
import type { MetricKey } from "../types/dashboard";
import {
  ALL_APPLICATIONS,
  TIME_RANGE_MS,
  type NavigationContext,
  type TimeRangeId,
} from "../types/navigation";
import type { TrendPoint } from "../ui/charts/trendPlot";

export const OBSERVATION_METRIC_LABEL_KEY: Readonly<Record<MetricId, TranslationKey>> =
  Object.freeze({
    http_qps: "observation.metric.httpQps",
    resource_entry_rate: "observation.metric.entryRate",
    tps: "observation.metric.tps",
    rt_p95: "observation.metric.rtP95",
    blocked_ratio: "observation.metric.blocked",
    cpu_ratio: "observation.metric.cpu",
    memory_ratio: "observation.metric.memory",
    memory_bytes: "observation.metric.memoryBytes",
  });
export const OBSERVATION_QUALITY_LABEL_KEY = Object.freeze({
  available: "observation.quality.available",
  partial: "observation.quality.partial",
  stale: "observation.quality.stale",
  no_samples: "observation.quality.noSamples",
  not_integrated: "observation.quality.notIntegrated",
} as const);
export const OBSERVATION_SCOPE_LABEL_KEY = Object.freeze({
  fleet: "observation.scope.fleet",
  application: "observation.scope.application",
  host: "observation.scope.host",
  container: "observation.scope.container",
  process: "observation.scope.process",
} as const);
const PLOT_METRIC: Readonly<Record<MetricId, MetricKey>> = Object.freeze({
  http_qps: "qps",
  resource_entry_rate: "entryRate",
  tps: "tps",
  rt_p95: "rt",
  blocked_ratio: "blocked",
  cpu_ratio: "cpu",
  memory_ratio: "memory",
  memory_bytes: "memoryBytes",
});
const UNIT_SYMBOL = Object.freeze({
  requests_per_second: "req/s",
  entries_per_second: "entries/s",
  transactions_per_second: "txn/s",
  milliseconds: "ms",
  ratio: "%",
  bytes: "B",
});
/** Unit conversion occurs only at presentation; typed domain values and protocol ratios stay untouched. */
export function metricDisplayValue(metric: MetricId, value: number | null): number | null {
  return value === null ? null : METRIC_UNIT[metric] === "ratio" ? value * 100 : value;
}
export function metricUnitSymbol(metric: MetricId): string {
  return UNIT_SYMBOL[METRIC_UNIT[metric]];
}
export function formatMetricReading(reading: MetricReading, locale: string): string {
  const value = metricDisplayValue(reading.metric, reading.value);
  return value === null ? "—" : formatLocaleNumber(value, locale, { maximumFractionDigits: 2 });
}
/** Independently sampled metrics retain their own gaps/timestamps; no frontend percentile or QPS aggregation. */
export function metricPlot(series: MetricSeries): {
  readonly metric: MetricKey;
  readonly points: readonly TrendPoint[];
  readonly unit: string;
} {
  const metric = PLOT_METRIC[series.metric];
  return {
    metric,
    unit: metricUnitSymbol(series.metric),
    points: series.samples.map((point) => ({
      timestampMs: point.atMs,
      [metric]: metricDisplayValue(series.metric, point.value),
    })),
  };
}
/** Preserve the actual window on drill-down, not a newly evaluated "last 15 minutes". */
export function observationNavigation(context: ObservationContext): NavigationContext {
  return {
    environmentId: context.environmentId,
    appId: context.appId ?? ALL_APPLICATIONS,
    instanceId: context.instanceId ?? undefined,
    resource: context.resource ?? undefined,
    metricScope: context.scope,
    from: new Date(context.window.fromMs).toISOString(),
    to: new Date(context.window.toMs).toISOString(),
  };
}
/** Resolve an exact URL window when valid; otherwise use the selected relative range once. */
export function observationWindowFromRoute(
  from: string | undefined,
  to: string | undefined,
  range: TimeRangeId,
  anchorMs: number,
): ObservationWindow {
  const parsed = {
    fromMs: from ? Date.parse(from) : Number.NaN,
    toMs: to ? Date.parse(to) : Number.NaN,
  };
  return validObservationWindow(parsed)
    ? parsed
    : { fromMs: anchorMs - TIME_RANGE_MS[range], toMs: anchorMs };
}
/** Shared directory health vocabulary; health classification remains server-owned. */
export const OBSERVATION_HEALTH_LABEL_KEY = Object.freeze({
  healthy: "observation.health.healthy",
  attention: "observation.health.attention",
  unknown: "observation.health.unknown",
} as const);
