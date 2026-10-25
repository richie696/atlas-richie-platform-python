import { validRulePublication } from "./ruleDeployment";
import { ACTIVATION_STATE } from "./ruleActivation";
import {
  RULE_MUTATION,
  RULE_REJECTION,
  type RuleMutation,
  type RuleMutationResult,
  type RuleOperationObservation,
} from "./ruleSetOperations";
import type { TypedRuleValue } from "./ruleValue";

const identifier = (value: string) => typeof value === "string" && !!value.trim();
/** Compare normalized typed facts, not JSON property order, form keys or a frontend-manufactured checksum. */
function sameRule(first: TypedRuleValue, second: TypedRuleValue): boolean {
  return first.kind === second.kind && JSON.stringify(first.value) === JSON.stringify(second.value);
}
/** Correlated durable operation receipts must match the original target and expected facts before unlocking writes. */
export function ruleMutationResultMatches(
  result: RuleMutationResult,
  mutation: RuleMutation,
): boolean {
  if (result.kind !== mutation.kind) return false;
  switch (mutation.kind) {
    case RULE_MUTATION.SaveDraft: {
      if (result.kind !== RULE_MUTATION.SaveDraft) return false;
      const draft = result.draft,
        candidate = mutation.candidate;
      return (
        identifier(draft.id) &&
        identifier(draft.revision) &&
        draft.bindingId === mutation.bindingId &&
        (mutation.draftId === null || draft.id === mutation.draftId) &&
        draft.revision !== mutation.expectedRevision &&
        draft.kind === candidate.kind &&
        draft.profile === candidate.profile &&
        draft.baseVersionId === candidate.baseVersionId &&
        draft.baseChecksum === candidate.baseChecksum &&
        draft.sourceRevision === candidate.sourceRevision &&
        Number.isSafeInteger(draft.updatedAtMs) &&
        draft.updatedAtMs >= 0 &&
        draft.records.length === candidate.rules.length &&
        new Set(draft.records.map((item) => item.id)).size === draft.records.length &&
        draft.records.every(
          (record, index) =>
            identifier(record.id) &&
            (candidate.rules[index].recordId === null ||
              candidate.rules[index].recordId === record.id) &&
            sameRule(record.rule, candidate.rules[index].rule),
        )
      );
    }
    case RULE_MUTATION.DeleteDraft:
      return result.kind === RULE_MUTATION.DeleteDraft && result.draftId === mutation.draftId;
    case RULE_MUTATION.FreezeVersion:
      return (
        result.kind === RULE_MUTATION.FreezeVersion &&
        result.draftId === mutation.draftId &&
        result.draftRevision === mutation.expectedRevision &&
        identifier(result.version.id) &&
        result.version.bindingId === mutation.bindingId &&
        result.version.checksum === mutation.candidateChecksum &&
        result.version.name === mutation.name &&
        result.version.note === mutation.note
      );
    case RULE_MUTATION.Publish:
      return (
        result.kind === RULE_MUTATION.Publish &&
        validRulePublication(result.publication, mutation.bindingId) &&
        result.publication.targetVersionId === mutation.versionId &&
        result.publication.targetChecksum === mutation.versionChecksum &&
        result.publication.baseVersionId === mutation.expectedVersionId
      );
    case RULE_MUTATION.CreatePlan: {
      if (result.kind !== RULE_MUTATION.CreatePlan) return false;
      const plan = result.plan,
        input = mutation.schedule;
      return (
        identifier(plan.id) &&
        identifier(plan.revision) &&
        plan.bindingId === mutation.bindingId &&
        plan.versionId === input.versionId &&
        plan.restoreVersionId === input.restoreVersionId &&
        plan.activateAtMs === input.activateAtMs &&
        plan.deactivateAtMs === input.deactivateAtMs &&
        plan.timeZone === input.timeZone &&
        Object.values(ACTIVATION_STATE).includes(plan.state)
      );
    }
    case RULE_MUTATION.CancelPlan:
      return (
        result.kind === RULE_MUTATION.CancelPlan &&
        result.plan.bindingId === mutation.bindingId &&
        result.plan.id === mutation.planId &&
        identifier(result.plan.revision) &&
        result.plan.revision !== mutation.expectedRevision &&
        result.plan.state === ACTIVATION_STATE.Cancelled
      );
    case RULE_MUTATION.ConfigureTarget:
      return (
        result.kind === RULE_MUTATION.ConfigureTarget &&
        result.target.bindingId === mutation.bindingId &&
        identifier(result.target.targetRevision) &&
        result.target.targetRevision !== mutation.expectedTargetRevision &&
        result.target.sourceRevision === mutation.expectedSourceRevision &&
        result.target.target.sourceId === mutation.target.sourceId &&
        result.target.target.provider === mutation.target.provider
      );
  }
}
/** Not-found is permitted only for lookup and never counts as a confirmed rejection/rollback. */
export function validRuleOperationObservation(
  value: RuleOperationObservation,
  mutation: RuleMutation,
  isLookup: boolean,
): boolean {
  if (!value || value.bindingId !== mutation.bindingId || value.requestKey !== mutation.requestKey)
    return false;
  switch (value.status) {
    case "not-found":
      return isLookup;
    case "pending":
      return true;
    case "rejected":
      return Object.values(RULE_REJECTION).includes(value.reason);
    case "completed":
      return ruleMutationResultMatches(value.result, mutation);
    default:
      return false;
  }
}
