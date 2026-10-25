import {
  METRIC_DENOMINATOR,
  METRIC_ID,
  METRIC_UNIT,
  MAX_OBSERVATION_POINTS,
  OBSERVATION_QUALITY,
  type MetricBundle,
  type MetricId,
  type MetricQuery,
  type ObservationAnnotation,
  type ObservationCoverage,
} from "./observation";

/** Scalar facts used to project a query-specific bundle; absent facts remain unavailable. */
export type MetricFacts = Readonly<Partial<Record<MetricId, number>>>;

/** Relative multipliers for synthetic series; seeded only by the opt-in demo scenario. */
export type MetricSeriesProfiles = Readonly<Partial<Record<MetricId, readonly number[]>>>;

const NEUTRAL_PROFILE_FACTOR = 1;

function profileFactorAt(profile: readonly number[], index: number, count: number): number {
  if (count <= 1) return profile[profile.length - 1] ?? NEUTRAL_PROFILE_FACTOR;
  const position = (index / (count - 1)) * (profile.length - 1);
  const leftIndex = Math.floor(position);
  const rightIndex = Math.ceil(position);
  const left = profile[leftIndex] ?? NEUTRAL_PROFILE_FACTOR;
  const right = profile[rightIndex] ?? left;
  return left + (right - left) * (position - leftIndex);
}

/**
 * Builds a deterministic metric bundle from already-owned facts.
 *
 * The function performs no aggregation or IO: callers must supply correct scope-specific facts
 * and inventory coverage. It preserves unavailable TPS and never turns an absent fact into zero.
 */
export function metricBundleFromFacts(
  query: MetricQuery,
  facts: MetricFacts,
  coverage: ObservationCoverage,
  source: string,
  annotations: readonly ObservationAnnotation[] = [],
  profiles: MetricSeriesProfiles = {},
): MetricBundle {
  const { fromMs, toMs } = query.context.window;
  const sampleCount = Math.min(MAX_OBSERVATION_POINTS, Math.ceil((toMs - fromMs) / query.stepMs));
  const sampledAtMs = fromMs + (sampleCount - 1) * query.stepMs;
  const midpointMs = fromMs + Math.floor((toMs - fromMs) / 2);
  const summary = query.metrics.map((metric) => {
    const integrated = metric !== METRIC_ID.Tps;
    const value = integrated ? (facts[metric] ?? null) : null;
    const metricCoverage = integrated ? coverage : { ...coverage, reporting: 0 };
    const quality = !integrated
      ? OBSERVATION_QUALITY.NotIntegrated
      : value === null
        ? OBSERVATION_QUALITY.NoSamples
        : coverage.expected !== null && coverage.expected === coverage.reporting
          ? OBSERVATION_QUALITY.Available
          : OBSERVATION_QUALITY.Partial;
    return {
      metric,
      unit: METRIC_UNIT[metric],
      value,
      sampledAtMs: value === null ? null : sampledAtMs,
      source,
      denominator: METRIC_DENOMINATOR[metric],
      coverage: metricCoverage,
      quality,
    };
  });
  const series = summary.map((reading) => {
    const profile = profiles[reading.metric];
    const readingValue = reading.value;
    const samples =
      readingValue === null
        ? []
        : profile && profile.length > 0
          ? Array.from({ length: sampleCount }, (_, index) => ({
              atMs: fromMs + index * query.stepMs,
              value: readingValue * profileFactorAt(profile, index, sampleCount),
            }))
          : sampledAtMs === fromMs
            ? [{ atMs: fromMs, value: readingValue }]
            : [
                { atMs: fromMs, value: readingValue },
                ...(midpointMs > fromMs && midpointMs < sampledAtMs
                  ? [{ atMs: midpointMs, value: null }]
                  : []),
                { atMs: sampledAtMs, value: readingValue },
              ];
    return {
      metric: reading.metric,
      unit: reading.unit,
      source: reading.source,
      denominator: reading.denominator,
      coverage: reading.coverage,
      quality: reading.quality,
      samples,
    };
  });
  return {
    query,
    asOfMs: toMs,
    summary,
    series,
    annotations,
  };
}
