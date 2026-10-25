import { createQueryResource } from "../../../shared/state/queryResource";
import type { HostMetricsPort, HostMetricsSourceDirectoryPort } from "../api/hostMetricsPort";
import type { HostMetricsQuery } from "../api/hostMetricsHttp";
import type { HostMetricsSnapshot } from "../api/hostMetricsHttp";
import type { QueryResource } from "../../../shared/state/queryResource";

const HOST_METRICS_MAX_QUERY_POINTS = 300;
const HOST_METRICS_MIN_QUERY_STEP_MS = 1_000;

/**
 * Choose a bounded HOST graph resolution independently from process-metric polling.
 *
 * HOST samples come from a configurable Prometheus scrape cadence; reusing the
 * process dashboard's 60-second step can hide a newly registered source for a
 * full minute and can make a healthy source appear stale. A 300-point ceiling
 * keeps each fixed-profile range query bounded while retaining useful freshness.
 */
export function hostMetricsQueryStepMs(durationMs: number): number {
  if (!Number.isFinite(durationMs) || durationMs < 1) {
    throw new RangeError("Invalid HOST metrics query duration");
  }
  return Math.max(
    HOST_METRICS_MIN_QUERY_STEP_MS,
    Math.ceil(durationMs / HOST_METRICS_MAX_QUERY_POINTS),
  );
}

export interface HostMetricsDirectoryQuery {
  readonly environmentId: string;
}

export interface HostMetricsReadQuery {
  readonly sourceId: string;
  readonly window: HostMetricsQuery;
}

export type HostMetricsSourceResource = QueryResource<
  HostMetricsDirectoryQuery,
  Awaited<ReturnType<HostMetricsSourceDirectoryPort["readSources"]>>["items"]
>;
export type HostMetricsQueryResource = QueryResource<HostMetricsReadQuery, HostMetricsSnapshot>;
/** Safe observation projection consumed by the realtime view; wire parsing remains in api/. */
export type HostMetricsObservation = HostMetricsSnapshot;

/** Create page-owned query resources with complete environment/source/window keys. */
export function createHostMetricsResources(
  sourcesPort: HostMetricsSourceDirectoryPort,
  metricsPort: HostMetricsPort,
) {
  const sources = createQueryResource<
    HostMetricsDirectoryQuery,
    Awaited<ReturnType<HostMetricsSourceDirectoryPort["readSources"]>>["items"]
  >({
    keyOf: ({ environmentId }) => `host-source-directory:${environmentId}`,
    async read({ environmentId }, signal) {
      const value = await sourcesPort.readSources(signal);
      return value.items.filter(
        (source) => source.enabled && source.environmentId === environmentId,
      );
    },
    classify: (items) => (items.length === 0 ? "empty" : "ready"),
  });
  const metrics = createQueryResource<
    HostMetricsReadQuery,
    Awaited<ReturnType<HostMetricsPort["read"]>>
  >({
    keyOf: ({ sourceId, window }) =>
      `host-metrics:${sourceId}:${window.from}:${window.to}:${window.stepMs}`,
    read: ({ sourceId, window }, signal) => metricsPort.read(sourceId, window, signal),
    classify: (snapshot) => {
      if (snapshot.quality === "partial") return "partial";
      if (snapshot.hosts.length === 0 || snapshot.quality === "no_samples") return "empty";
      return "ready";
    },
  });
  return Object.freeze({ sources, metrics });
}
