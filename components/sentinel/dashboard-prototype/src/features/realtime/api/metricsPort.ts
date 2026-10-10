import type { MetricBundle, MetricQuery } from "../../../shared/model/observation";

/** Read aggregated Console samples. No raw counter-to-QPS conversion, fixture or browser collector control. */
export interface RealtimePort {
  readonly readMetrics: (query: MetricQuery, signal: AbortSignal) => Promise<MetricBundle>;
}
