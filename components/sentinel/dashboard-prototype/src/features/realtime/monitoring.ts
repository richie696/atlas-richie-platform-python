/** Formal polling capability entry. Wire/HTTP and app assembly remain outside the feature. */
export { createRealtimeMonitor } from "./application/realtimeMonitor";
export { LiveMonitoringPage } from "./ui/LiveMonitoringPage";
export type { RealtimeMonitor, RealtimeMonitorSnapshot } from "./application/realtimeMonitor";
export type { RealtimePort } from "./api/metricsPort";
export type { RealtimeSelection } from "./model/monitoring";
