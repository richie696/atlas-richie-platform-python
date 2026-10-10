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
