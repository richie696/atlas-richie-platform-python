import { validRuleSetSnapshot, type RuleBinding, type RuleSetSnapshot } from "./ruleSet";
import {
  RULE_SERVER_ISSUE,
  type StoredRuleDraft,
  type RuleValidationReport,
  type RuleSetDiff,
} from "./ruleSetOperations";
import type { RuleSetCandidate } from "./ruleSet";

/** Resuming a stored draft preserves its original source baseline, not the latest live checksum. */
export function storedDraftSnapshot(draft: StoredRuleDraft, binding: RuleBinding): RuleSetSnapshot {
  return {
    binding,
    versionId: draft.baseVersionId,
    checksum: draft.baseChecksum,
    sourceRevision: draft.sourceRevision,
    asOfMs: draft.updatedAtMs,
    records: draft.records,
  };
}
export function validStoredDraft(
  draft: StoredRuleDraft,
  binding: RuleBinding,
  draftId: string,
): boolean {
  return (
    draft.id === draftId &&
    !!draft.id.trim() &&
    !!draft.revision.trim() &&
    draft.bindingId === binding.id &&
    draft.kind === binding.kind &&
    draft.profile === binding.profile &&
    validRuleSetSnapshot(storedDraftSnapshot(draft, binding), binding.id)
  );
}
const MAX_REPORT_ISSUES = 1000;
const MAX_ISSUE_PATH_LENGTH = 128;
/** A response belongs to the captured candidate. Editing invalidates the owning resource before another read. */
export function validValidationReport(
  value: RuleValidationReport,
  candidate: RuleSetCandidate,
): boolean {
  return (
    value.bindingId === candidate.bindingId &&
    value.profile === candidate.profile &&
    value.baseChecksum === candidate.baseChecksum &&
    !!value.candidateChecksum.trim() &&
    !!value.validationId.trim() &&
    (!value.isPublishable || value.issues.length === 0) &&
    value.issues.length <= MAX_REPORT_ISSUES &&
    value.issues.every(
      (issue) =>
        Object.values(RULE_SERVER_ISSUE).includes(issue.code) &&
        (issue.recordIndex === null ||
          (Number.isSafeInteger(issue.recordIndex) &&
            issue.recordIndex >= 0 &&
            issue.recordIndex < candidate.rules.length)) &&
        issue.path.length <= MAX_ISSUE_PATH_LENGTH &&
        /^[\w.\[\]]*$/.test(issue.path),
    )
  );
}
export function validRuleSetDiff(value: RuleSetDiff, candidate: RuleSetCandidate): boolean {
  const recordIds = new Set(
    candidate.rules.flatMap((rule) => (rule.recordId === null ? [] : [rule.recordId])),
  );
  return (
    value.bindingId === candidate.bindingId &&
    value.baseChecksum === candidate.baseChecksum &&
    !!value.candidateChecksum.trim() &&
    value.changes.length <= MAX_REPORT_ISSUES &&
    value.changes.every((change) => {
      switch (change.operation) {
        case "add":
          return change.after.kind === candidate.kind;
        case "remove":
          return !!change.recordId.trim() && change.before.kind === candidate.kind;
        case "replace":
          return (
            recordIds.has(change.recordId) &&
            change.before.kind === candidate.kind &&
            change.after.kind === candidate.kind
          );
        default:
          return false;
      }
    })
  );
}
