import type { RuleRecord } from "./ruleSet";
import type { RuleKind } from "./ruleKinds";
import {
  validInventoryCoverage,
  type InventoryCoverage,
} from "../../../shared/model/inventoryCoverage";

/** Immutable content facts. Active/scheduled are deployment facts, not mutable fields on a version. */
export interface RuleSetVersion {
  readonly id: string;
  readonly bindingId: string;
  readonly kind: RuleKind;
  readonly profile: string;
  readonly baseVersionId: string | null;
  readonly checksum: string;
  readonly name: string;
  readonly note: string;
  readonly createdAtMs: number;
  readonly createdById: string;
  readonly records: readonly RuleRecord[];
}
export const PUBLICATION_STAGE = Object.freeze({
  Awaiting: "awaiting",
  Running: "running",
  Succeeded: "succeeded",
  Failed: "failed",
  Unknown: "unknown",
} as const);
export type PublicationStageState = (typeof PUBLICATION_STAGE)[keyof typeof PUBLICATION_STAGE];
const READBACK_WRITE_STATES: ReadonlySet<PublicationStageState> = new Set([
  PUBLICATION_STAGE.Succeeded,
  PUBLICATION_STAGE.Unknown,
]);
export const RECEIPT_PAGE_SIZE_LIMIT = 100;
/** Only finite safe reason classes; raw configuration-center errors never become UI text. */
export const PUBLICATION_REASON = Object.freeze({
  Conflict: "conflict",
  Unavailable: "unavailable",
  Rejected: "rejected",
  ReadBackMismatch: "readback_mismatch",
  Unsupported: "unsupported",
  Unknown: "unknown",
} as const);
export interface PublicationPhase {
  readonly state: PublicationStageState;
  readonly observedAtMs: number | null;
  readonly reason: (typeof PUBLICATION_REASON)[keyof typeof PUBLICATION_REASON] | null;
}
export interface RulePublication {
  readonly id: string;
  readonly bindingId: string;
  readonly targetVersionId: string;
  readonly targetChecksum: string;
  readonly baseVersionId: string | null;
  readonly createdAtMs: number;
  readonly validation: PublicationPhase;
  readonly configurationWrite: PublicationPhase;
  readonly readBack: PublicationPhase;
}
export const RECEIPT_STATE = Object.freeze({
  Applied: "applied",
  Pending: "pending",
  Failed: "failed",
  Unknown: "unknown",
  RestartRequired: "restart_required",
} as const);
export type ReceiptState = (typeof RECEIPT_STATE)[keyof typeof RECEIPT_STATE];
export interface PublicationReceipt {
  readonly instanceId: string;
  readonly processEpoch: string | null;
  readonly loadedProcessEpoch: string | null;
  readonly targetVersionId: string;
  readonly loadedVersionId: string | null;
  readonly loadedChecksum: string | null;
  readonly appliedAtMs: number | null;
  readonly lastReportAtMs: number | null;
  readonly state: ReceiptState;
}
export interface PublicationReceiptPage extends InventoryCoverage {
  readonly publicationId: string;
  readonly bindingId: string;
  readonly page: number;
  readonly pageSize: number;
  readonly asOfMs: number;
  /** Number of rows represented by the status counters; independent from an unknown target population. */
  readonly total: number;
  readonly applied: number;
  readonly pending: number;
  readonly failed: number;
  readonly unknown: number;
  readonly restartRequired: number;
  readonly items: readonly PublicationReceipt[];
}
const identity = (value: string) => !!value.trim();
const time = (value: number) => Number.isSafeInteger(value) && value >= 0;
const nullableTime = (value: number | null) => value === null || time(value);
function validPhase(value: PublicationPhase): boolean {
  return (
    Object.values(PUBLICATION_STAGE).includes(value.state) &&
    nullableTime(value.observedAtMs) &&
    (value.reason === null || Object.values(PUBLICATION_REASON).includes(value.reason)) &&
    (value.state !== PUBLICATION_STAGE.Succeeded ||
      (value.observedAtMs !== null && value.reason === null)) &&
    (value.state !== PUBLICATION_STAGE.Failed || value.reason !== null)
  );
}
/** Phases are independent facts. A read-back match is not a lost write ACK or an instance receipt. */
export function validRulePublication(
  value: RulePublication,
  bindingId: string,
  publicationId?: string,
): boolean {
  return (
    value.bindingId === bindingId &&
    (publicationId === undefined || value.id === publicationId) &&
    [value.id, value.targetVersionId, value.targetChecksum].every(identity) &&
    time(value.createdAtMs) &&
    (value.baseVersionId === null || identity(value.baseVersionId)) &&
    [value.validation, value.configurationWrite, value.readBack].every(validPhase) &&
    (value.configurationWrite.state === PUBLICATION_STAGE.Awaiting ||
      value.validation.state === PUBLICATION_STAGE.Succeeded) &&
    (value.readBack.state === PUBLICATION_STAGE.Awaiting ||
      READBACK_WRITE_STATES.has(value.configurationWrite.state))
  );
}
/** Positive evidence is process-incarnation and content bound; pending/unknown/restart-needed never count as applied. */
export function validPublicationReceipts(
  value: PublicationReceiptPage,
  publication: RulePublication,
  page: number,
  pageSize: number,
): boolean {
  const counts = [
    value.total,
    value.applied,
    value.pending,
    value.failed,
    value.unknown,
    value.restartRequired,
  ];
  if (
    value.publicationId !== publication.id ||
    value.bindingId !== publication.bindingId ||
    value.page !== page ||
    value.pageSize !== pageSize ||
    !time(value.asOfMs) ||
    !Number.isSafeInteger(page) ||
    page < 1 ||
    !Number.isSafeInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > RECEIPT_PAGE_SIZE_LIMIT ||
    !counts.every(time) ||
    !validInventoryCoverage(value) ||
    (value.expected !== null && value.expected !== value.total) ||
    value.total !==
      value.applied + value.pending + value.failed + value.unknown + value.restartRequired ||
    value.items.length > pageSize ||
    value.items.length > value.total ||
    (page - 1) * pageSize + value.items.length > value.total ||
    new Set(value.items.map((item) => item.instanceId)).size !== value.items.length
  )
    return false;
  const totals: Readonly<Record<ReceiptState, number>> = {
    applied: value.applied,
    pending: value.pending,
    failed: value.failed,
    unknown: value.unknown,
    restart_required: value.restartRequired,
  };
  if (
    Object.values(RECEIPT_STATE).some(
      (state) => value.items.filter((item) => item.state === state).length > totals[state],
    )
  )
    return false;
  return value.items.every(
    (item) =>
      identity(item.instanceId) &&
      (item.processEpoch === null
        ? item.state === RECEIPT_STATE.Unknown &&
          item.loadedProcessEpoch === null &&
          item.loadedVersionId === null &&
          item.loadedChecksum === null &&
          item.appliedAtMs === null &&
          item.lastReportAtMs === null
        : identity(item.processEpoch)) &&
      item.targetVersionId === publication.targetVersionId &&
      Object.values(RECEIPT_STATE).includes(item.state) &&
      nullableTime(item.lastReportAtMs) &&
      nullableTime(item.appliedAtMs) &&
      [item.loadedProcessEpoch, item.loadedVersionId, item.loadedChecksum].every(
        (id) => id === null || identity(id),
      ) &&
      (item.state !== RECEIPT_STATE.Applied ||
        (item.processEpoch !== null &&
          item.loadedProcessEpoch === item.processEpoch &&
          item.loadedVersionId === publication.targetVersionId &&
          item.loadedChecksum === publication.targetChecksum &&
          item.appliedAtMs !== null &&
          item.lastReportAtMs !== null)),
  );
}
