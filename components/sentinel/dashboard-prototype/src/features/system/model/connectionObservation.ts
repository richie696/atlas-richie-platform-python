import { CONNECTION_KIND, type ConnectionKind } from "./systemStatus";
import { identifier, timestamp, nullableTime, unique } from "./systemReadGuards";
export const HEALTH_STATE = Object.freeze({
  Available: "available",
  Unavailable: "unavailable",
  Unconfigured: "unconfigured",
  Unknown: "unknown",
} as const);
export type HealthState = (typeof HEALTH_STATE)[keyof typeof HEALTH_STATE];
export const HEALTH_CAPABILITY = Object.freeze({
  Read: "read",
  ConditionalWrite: "conditional-write",
  Watch: "watch",
  QueryMetrics: "query-metrics",
  Ingest: "ingest",
} as const);
export type HealthCapability = (typeof HEALTH_CAPABILITY)[keyof typeof HEALTH_CAPABILITY];
export const HEALTH_REASON = Object.freeze({
  Network: "network",
  Authentication: "authentication",
  Unsupported: "unsupported",
  NotConfigured: "not-configured",
  NoProbe: "no-probe",
} as const);
export type HealthReason = (typeof HEALTH_REASON)[keyof typeof HEALTH_REASON];
export const CONFIG_PROVIDER = Object.freeze({ Nacos: "nacos", Consul: "consul" } as const);
export type ConfigProvider = (typeof CONFIG_PROVIDER)[keyof typeof CONFIG_PROVIDER];
/** A server-side probe fact, not browser connectivity. No endpoints, raw exception or credential material. */
export interface ConnectionObservation {
  readonly id: string;
  readonly kind: ConnectionKind;
  readonly sourceId: string | null;
  readonly provider: ConfigProvider | null;
  readonly state: HealthState;
  readonly checkedAtMs: number | null;
  readonly expiresAtMs: number | null;
  readonly latencyMs: number | null;
  readonly capabilities: readonly HealthCapability[];
  readonly reason: HealthReason | null;
}
export interface SystemConnections {
  readonly asOfMs: number;
  readonly items: readonly ConnectionObservation[];
}
/** Probe validity is evaluated against the authoritative read instant, not the browser clock. */
export function connectionProbeExpired(item: ConnectionObservation, asOfMs: number): boolean {
  return item.expiresAtMs !== null && item.expiresAtMs <= asOfMs;
}
/** Missing service categories are incomplete observation, never an implicit successful zero-length probe. */
export function connectionCoverageComplete(value: SystemConnections): boolean {
  return Object.values(CONNECTION_KIND).every((kind) =>
    value.items.some((item) => item.kind === kind),
  );
}
export function validSystemConnections(value: SystemConnections): boolean {
  return (
    timestamp(value.asOfMs) &&
    unique(value.items, (item) => item.id) &&
    value.items.every(
      (item) =>
        identifier(item.id) &&
        Object.values(CONNECTION_KIND).includes(item.kind) &&
        Object.values(HEALTH_STATE).includes(item.state) &&
        nullableTime(item.checkedAtMs) &&
        nullableTime(item.expiresAtMs) &&
        (item.checkedAtMs === null
          ? item.expiresAtMs === null &&
            item.latencyMs === null &&
            (item.state === HEALTH_STATE.Unknown || item.state === HEALTH_STATE.Unconfigured)
          : item.checkedAtMs <= value.asOfMs &&
            item.expiresAtMs !== null &&
            item.expiresAtMs >= item.checkedAtMs) &&
        (item.latencyMs === null || (Number.isFinite(item.latencyMs) && item.latencyMs >= 0)) &&
        (item.state !== HEALTH_STATE.Available ||
          (item.checkedAtMs !== null && item.latencyMs !== null && item.reason === null)) &&
        (item.reason === null || Object.values(HEALTH_REASON).includes(item.reason)) &&
        new Set(item.capabilities).size === item.capabilities.length &&
        item.capabilities.every((capability) =>
          Object.values(HEALTH_CAPABILITY).includes(capability),
        ) &&
        (item.kind === CONNECTION_KIND.ConfigCenter
          ? item.sourceId === null
            ? item.provider === null && item.state === HEALTH_STATE.Unconfigured
            : identifier(item.sourceId) &&
              item.provider !== null &&
              Object.values(CONFIG_PROVIDER).includes(item.provider)
          : item.sourceId === null && item.provider === null),
    )
  );
}
