/** Authoritative target population, never inferred from the currently reporting cohort. */
export interface InventoryCoverage {
  readonly expected: number | null;
  readonly inventorySource: string | null;
}

/** Unknown population has no invented source; a known count must name its authority. */
export function validInventoryCoverage(value: InventoryCoverage): boolean {
  return value.expected === null
    ? value.inventorySource === null
    : Number.isSafeInteger(value.expected) &&
        value.expected >= 0 &&
        typeof value.inventorySource === "string" &&
        value.inventorySource.length <= 200 &&
        !!value.inventorySource.trim();
}
