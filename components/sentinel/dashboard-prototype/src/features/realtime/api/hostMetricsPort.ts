import type { HostMetricsQuery, HostMetricsSnapshot } from "./hostMetricsHttp";

/** Minimum safe source directory fact consumed by HOST metrics, not a system-management port. */
export interface HostMetricsSourceDirectoryPort {
  readSources(signal: AbortSignal): Promise<{
    readonly items: readonly {
      readonly id: string;
      readonly displayName: string;
      readonly environmentId: string;
      readonly enabled: boolean;
    }[];
  }>;
}

/** Fixed-profile HOST history query; provider connection material is never supplied by the page. */
export interface HostMetricsPort {
  read(
    sourceId: string,
    query: HostMetricsQuery,
    signal: AbortSignal,
  ): Promise<HostMetricsSnapshot>;
}
