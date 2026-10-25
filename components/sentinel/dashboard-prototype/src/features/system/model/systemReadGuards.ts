import { isBoundedWireIdentifier } from "../../../core/api/protocol/wireString";

/** Pure, bounded identities and UTC values shared by system read projections only. */
export const SYSTEM_COLLECTION_LIMIT = 1000;
export const SYSTEM_IDENTIFIER_LIMIT = 200;
export const SYSTEM_MAX_UTC_MS = 253402300799999;
export const identifier = (value: string) =>
  isBoundedWireIdentifier(value, SYSTEM_IDENTIFIER_LIMIT);
export const timestamp = (value: number) =>
  Number.isSafeInteger(value) && value >= 0 && value <= SYSTEM_MAX_UTC_MS;
export const nullableTime = (value: number | null) => value === null || timestamp(value);
export function unique<Value>(items: readonly Value[], key: (value: Value) => string): boolean {
  return items.length <= SYSTEM_COLLECTION_LIMIT && new Set(items.map(key)).size === items.length;
}

interface ProtocolObservationValidationPage {
  readonly asOfMs: number;
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly items: readonly {
    readonly environmentId: string;
    readonly appId: string;
    readonly instanceId: string;
    readonly processId: string;
    readonly reporterId: string;
    readonly boundary: string;
    readonly collectorSupported: readonly string[];
    readonly runtimeVersion: string | null;
    readonly compatibility: string;
    readonly observedAtMs: number | null;
  }[];
}

/** Validate shared worker-page invariants while pinning the expected authority boundary. */
export function validProtocolObservationPage(
  value: ProtocolObservationValidationPage,
  expectedBoundary: string,
): boolean {
  return (
    timestamp(value.asOfMs) &&
    Number.isSafeInteger(value.page) &&
    value.page >= 1 &&
    Number.isSafeInteger(value.pageSize) &&
    value.pageSize >= 1 &&
    value.pageSize <= 100 &&
    Number.isSafeInteger(value.total) &&
    value.total >= 0 &&
    value.items.length <= value.pageSize &&
    (value.page - 1) * value.pageSize + value.items.length <= value.total &&
    unique(
      value.items,
      (item) => `${item.environmentId}\u0000${item.appId}\u0000${item.instanceId}`,
    ) &&
    value.items.every(
      (item) =>
        identifier(item.environmentId) &&
        identifier(item.appId) &&
        identifier(item.instanceId) &&
        identifier(item.processId) &&
        identifier(item.reporterId) &&
        item.boundary === expectedBoundary &&
        item.collectorSupported.length <= 100 &&
        unique(item.collectorSupported, (version) => version) &&
        item.collectorSupported.every(identifier) &&
        (item.runtimeVersion === null || identifier(item.runtimeVersion)) &&
        ["compatible", "incompatible", "unknown"].includes(item.compatibility) &&
        nullableTime(item.observedAtMs) &&
        (item.observedAtMs === null || item.observedAtMs <= value.asOfMs) &&
        (item.runtimeVersion === null
          ? item.compatibility === "unknown" && item.observedAtMs === null
          : item.observedAtMs !== null &&
            item.compatibility !== "unknown" &&
            item.collectorSupported.includes(item.runtimeVersion) ===
              (item.compatibility === "compatible")),
    )
  );
}
