import {
  METRIC_BASIS,
  METRIC_ID,
  METRIC_UNIT,
  OBSERVATION_QUALITY,
  OPERATIONAL_METRICS,
  type MetricId,
} from "../model/observation";
import type { ObservationContextWire } from "./observationWire";

export const OBSERVATION_EXAMPLE_TIME = Object.freeze({
  from: "2026-10-09T00:45:00.000Z",
  to: "2026-10-09T01:00:00.000Z",
  asOf: "2026-10-09T01:00:01.123Z",
  occurredAt: "2026-10-09T00:59:00.000Z",
});

export const FLEET_OBSERVATION_CONTEXT = Object.freeze({
  environmentId: "prod",
  appId: null,
  instanceId: null,
  resource: null,
  scope: "fleet",
  window: Object.freeze({
    from: OBSERVATION_EXAMPLE_TIME.from,
    to: OBSERVATION_EXAMPLE_TIME.to,
  }),
});

export const APPLICATION_OBSERVATION_CONTEXT = Object.freeze({
  ...FLEET_OBSERVATION_CONTEXT,
  appId: "checkout",
  scope: "application",
});

export const PROCESS_OBSERVATION_CONTEXT = Object.freeze({
  ...APPLICATION_OBSERVATION_CONTEXT,
  instanceId: "checkout-1",
  scope: "process",
});

export const UNKNOWN_OBSERVATION_COVERAGE = Object.freeze({
  expected: null,
  inventorySource: null,
  reporting: 0,
});

const METRIC_DENOMINATOR: Readonly<Record<MetricId, string>> = Object.freeze({
  [METRIC_ID.HttpQps]: METRIC_BASIS.ElapsedSeconds,
  [METRIC_ID.EntryRate]: METRIC_BASIS.ElapsedSeconds,
  [METRIC_ID.Tps]: METRIC_BASIS.ElapsedSeconds,
  [METRIC_ID.RtP95]: METRIC_BASIS.CompletedRequests,
  [METRIC_ID.BlockedRatio]: METRIC_BASIS.AttemptedEntries,
  [METRIC_ID.CpuRatio]: METRIC_BASIS.Processes,
  [METRIC_ID.MemoryRatio]: METRIC_BASIS.Processes,
  [METRIC_ID.MemoryBytes]: METRIC_BASIS.Processes,
});

/** Builds explicit unavailable readings; examples never imply missing samples are zero. */
export function observationMetricReadings(metrics: readonly MetricId[]) {
  return metrics.map((metric) => ({
    source: "collector-not-integrated",
    denominator: METRIC_DENOMINATOR[metric],
    coverage: UNKNOWN_OBSERVATION_COVERAGE,
    quality: OBSERVATION_QUALITY.NotIntegrated,
    metric,
    unit: METRIC_UNIT[metric],
    value: null,
    sampledAt: null,
  }));
}

export function observationMetricBundle(
  context: ObservationContextWire,
  metrics: readonly MetricId[],
  stepMs: number,
) {
  const readings = observationMetricReadings(metrics);
  return {
    query: { context, metrics, stepMs },
    asOf: OBSERVATION_EXAMPLE_TIME.asOf,
    summary: readings,
    series: readings.map((reading) => ({
      source: reading.source,
      denominator: reading.denominator,
      coverage: reading.coverage,
      quality: reading.quality,
      metric: reading.metric,
      unit: reading.unit,
      samples: [],
    })),
    annotations: [],
  };
}

export const OPERATIONAL_METRIC_READINGS = observationMetricReadings(OPERATIONAL_METRICS);

/** Canonical safe error payload used by read-operation examples. */
export function observationErrorExample(
  code: "unauthenticated" | "forbidden" | "not_found" | "target_retired",
) {
  return { error: { code, requestId: `example-${code}` } };
}
