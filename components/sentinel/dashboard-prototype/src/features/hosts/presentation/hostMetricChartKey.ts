import type { MetricKey } from "../../../shared/types/dashboard";

export type HostMetricName =
  "host_cpu_busy_ratio" | "host_memory_used_bytes" | "host_memory_used_ratio" | "host_load_1m";

/** HOST wire metric names map to their own chart semantic key for labels and summaries. */
export const HOST_METRIC_CHART_KEY: Readonly<Record<HostMetricName, MetricKey>> = Object.freeze({
  host_cpu_busy_ratio: "hostCpu",
  host_memory_used_bytes: "hostMemoryBytes",
  host_memory_used_ratio: "hostMemoryRatio",
  host_load_1m: "hostLoad",
});
