import type { ProtocolBoundaryId } from "./systemStatus";
import { identifier, timestamp, nullableTime, unique } from "./systemReadGuards";
export const PROTOCOL_COMPATIBILITY = Object.freeze({
  Compatible: "compatible",
  Incompatible: "incompatible",
  Unknown: "unknown",
} as const);
export type ProtocolCompatibility =
  (typeof PROTOCOL_COMPATIBILITY)[keyof typeof PROTOCOL_COMPATIBILITY];
export const PROTOCOL_BOUNDARY_IDS = [
  "rule-config",
  "agent-reporting",
  "cluster-token",
] as const satisfies readonly ProtocolBoundaryId[];
export const PROTOCOL_BOUNDARY_COUNT = PROTOCOL_BOUNDARY_IDS.length;
export const MAX_SUPPORTED_PROTOCOL_VERSIONS = 100;
/** Supported is backend capability; active is a deployment fact. An absent negotiation is never manufactured. */
export interface ProtocolObservation {
  readonly kind: ProtocolBoundaryId;
  readonly supported: readonly string[];
  readonly active: string | null;
  readonly compatibility: ProtocolCompatibility;
  readonly observedAtMs: number | null;
}
export interface SystemProtocols {
  readonly asOfMs: number;
  readonly items: readonly ProtocolObservation[];
}
/** Missing independent boundaries are partial observations, not a complete deployment compatibility check. */
export function protocolCoverageComplete(value: SystemProtocols): boolean {
  return PROTOCOL_BOUNDARY_IDS.every((kind) => value.items.some((item) => item.kind === kind));
}
export function validSystemProtocols(value: SystemProtocols): boolean {
  return (
    timestamp(value.asOfMs) &&
    unique(value.items, (item) => item.kind) &&
    value.items.every(
      (item) =>
        PROTOCOL_BOUNDARY_IDS.includes(item.kind) &&
        nullableTime(item.observedAtMs) &&
        (item.observedAtMs === null || item.observedAtMs <= value.asOfMs) &&
        item.supported.length <= 100 &&
        new Set(item.supported).size === item.supported.length &&
        item.supported.every(identifier) &&
        Object.values(PROTOCOL_COMPATIBILITY).includes(item.compatibility) &&
        (item.active === null
          ? item.compatibility === PROTOCOL_COMPATIBILITY.Unknown
          : identifier(item.active) &&
            item.observedAtMs !== null &&
            (item.compatibility === PROTOCOL_COMPATIBILITY.Unknown ||
              (item.compatibility === PROTOCOL_COMPATIBILITY.Compatible) ===
                item.supported.includes(item.active))),
    )
  );
}
