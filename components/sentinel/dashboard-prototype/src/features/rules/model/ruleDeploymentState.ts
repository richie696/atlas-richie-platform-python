import type { RuleBinding, RuleSetCollection } from "./ruleSet";
import { MAX_RULE_SET_SIZE } from "./ruleSet";
import type { RuleSetVersion } from "./ruleDeployment";
import { ACTIVATION_STATE, validIanaTimeZone, type RuleActivationPlan } from "./ruleActivation";
import { validRuleValue } from "./ruleValue";

export const MAX_RULE_COLLECTION_SIZE = 1000;
const identity = (value: string) => !!value.trim();
const time = (value: number) => Number.isSafeInteger(value) && value >= 0;
/** Immutable versions belong to one binding/profile. These internal fact checks do not replace the F6 wire decoder. */
export function validRuleSetVersion(
  value: RuleSetVersion,
  binding: RuleBinding,
  versionId = value.id,
): boolean {
  return (
    value.id === versionId &&
    [value.id, value.checksum, value.name, value.createdById].every(identity) &&
    value.bindingId === binding.id &&
    value.kind === binding.kind &&
    value.profile === binding.profile &&
    (value.baseVersionId === null || identity(value.baseVersionId)) &&
    time(value.createdAtMs) &&
    value.records.length <= MAX_RULE_SET_SIZE &&
    new Set(value.records.map((record) => record.id)).size === value.records.length &&
    value.records.every(
      (record) =>
        identity(record.id) && record.rule.kind === binding.kind && validRuleValue(record.rule),
    )
  );
}
/** Plans carry UTC execution facts, not frontend timers or inferred active-version flags. */
export function validRuleActivationPlan(value: RuleActivationPlan, bindingId: string): boolean {
  return (
    value.bindingId === bindingId &&
    [value.id, value.revision, value.versionId, value.restoreVersionId].every(identity) &&
    value.versionId !== value.restoreVersionId &&
    time(value.activateAtMs) &&
    time(value.deactivateAtMs) &&
    value.deactivateAtMs > value.activateAtMs &&
    validIanaTimeZone(value.timeZone) &&
    Object.values(ACTIVATION_STATE).includes(value.state) &&
    [value.activationPublicationId, value.restorePublicationId].every(
      (id) => id === null || identity(id),
    )
  );
}
/** Collections are complete bounded facts. Reject excess/duplicates; never trim a plan list and then claim no overlap. */
export function validRuleCollection<Value extends { readonly id: string }>(
  value: RuleSetCollection<Value>,
  bindingId: string,
  validItem: (item: Value) => boolean,
): boolean {
  return (
    value.bindingId === bindingId &&
    time(value.asOfMs) &&
    value.items.length <= MAX_RULE_COLLECTION_SIZE &&
    new Set(value.items.map((item) => item.id)).size === value.items.length &&
    value.items.every(validItem)
  );
}
