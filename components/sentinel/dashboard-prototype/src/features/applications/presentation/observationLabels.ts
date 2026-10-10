import type { InstanceRuleReceipt } from "../model/instanceObservation";
import type { TranslationKey } from "../../../shared/types/translation";
/** Receipt labels describe reported loading facts, never implied publication success. */
export const RULE_RECEIPT_LABEL_KEY: Readonly<
  Record<InstanceRuleReceipt["state"], TranslationKey>
> = Object.freeze({
  applied: "applications.observed.receipt.applied",
  pending: "applications.observed.receipt.pending",
  failed: "applications.observed.receipt.failed",
  unknown: "applications.observed.receipt.unknown",
});
