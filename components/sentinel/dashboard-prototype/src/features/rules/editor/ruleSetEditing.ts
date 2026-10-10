import { editableRule, materializeRuleDraft } from "./ruleMaterialization";
import {
  MAX_RULE_SET_SIZE,
  validRuleSetSnapshot,
  type RuleSetSnapshot,
  type RuleSetCandidate,
} from "../model/ruleSet";
import type { TypedRuleDraft } from "./ruleDraft";
import { RULE_ISSUE, type RuleIssue } from "./rulePolicy";

export interface EditableRuleRecord {
  /** Local React/form identity only. New rule keys are never promoted to server record identities. */
  readonly formKey: string;
  readonly recordId: string | null;
  readonly rule: TypedRuleDraft;
}
/** Explicit edit owner: reading a new live snapshot cannot overwrite this baseline or dirty values. */
export interface RuleSetEditing {
  readonly baseline: RuleSetSnapshot;
  readonly records: readonly EditableRuleRecord[];
}
export interface RuleSetIssue {
  readonly formKey: string;
  readonly issue: RuleIssue;
}
export type CandidatePreparation =
  | { readonly valid: false; readonly issues: readonly RuleSetIssue[] }
  | { readonly valid: true; readonly candidate: RuleSetCandidate };

/** Begin/discard is an explicit command, not an Effect synchronized to every backend refresh. */
export function beginRuleSetEditing(snapshot: RuleSetSnapshot): RuleSetEditing {
  return {
    baseline: structuredClone(snapshot),
    records: snapshot.records.map((item) => ({
      recordId: item.id,
      formKey: item.id,
      rule: editableRule(item.rule, (index) => `${item.id}:${index}`),
    })),
  };
}
export function addRuleToSet(
  editing: RuleSetEditing,
  formKey: string,
  rule: TypedRuleDraft,
): RuleSetEditing {
  if (
    !formKey.trim() ||
    editing.records.some((item) => item.formKey === formKey) ||
    editing.records.length >= MAX_RULE_SET_SIZE ||
    rule.kind !== editing.baseline.binding.kind
  )
    throw new Error("Invalid local rule insertion");
  return {
    ...editing,
    records: [...editing.records, { formKey, recordId: null, rule: structuredClone(rule) }],
  };
}
export function updateRuleInSet(
  editing: RuleSetEditing,
  formKey: string,
  rule: TypedRuleDraft,
): RuleSetEditing {
  if (
    !editing.records.some((item) => item.formKey === formKey) ||
    rule.kind !== editing.baseline.binding.kind
  )
    throw new Error("Invalid local rule target");
  return {
    ...editing,
    records: editing.records.map((item) =>
      item.formKey === formKey ? { ...item, rule: structuredClone(rule) } : item,
    ),
  };
}
export function removeRuleFromSet(editing: RuleSetEditing, formKey: string): RuleSetEditing {
  if (!editing.records.some((item) => item.formKey === formKey))
    throw new Error("Invalid local rule target");
  return { ...editing, records: editing.records.filter((item) => item.formKey !== formKey) };
}
/** Validate/materialize every record; preserve order and unaffected rules, including a deliberate empty full set. */
export function prepareRuleSetCandidate(editing: RuleSetEditing): CandidatePreparation {
  const issues: RuleSetIssue[] = [],
    rules: RuleSetCandidate["rules"][number][] = [];
  // Action guards are not the submission boundary. Check the complete local structure too.
  if (
    !validRuleSetSnapshot(editing.baseline, editing.baseline.binding.id) ||
    editing.records.length > MAX_RULE_SET_SIZE
  )
    return {
      valid: false,
      issues: [{ formKey: "", issue: { code: RULE_ISSUE.Choice, path: "ruleset" } }],
    };
  const formKeys = new Set<string>(),
    recordIds = new Set<string>();
  const baselineIds = new Set(editing.baseline.records.map((record) => record.id));
  for (const record of editing.records) {
    if (!record.formKey.trim() || formKeys.has(record.formKey))
      issues.push({
        formKey: record.formKey,
        issue: { code: RULE_ISSUE.Duplicate, path: "formKey" },
      });
    formKeys.add(record.formKey);
    if (record.recordId !== null) {
      if (!baselineIds.has(record.recordId) || recordIds.has(record.recordId))
        issues.push({
          formKey: record.formKey,
          issue: { code: RULE_ISSUE.Choice, path: "recordId" },
        });
      recordIds.add(record.recordId);
    }
    if (record.rule.kind !== editing.baseline.binding.kind) {
      issues.push({ formKey: record.formKey, issue: { code: RULE_ISSUE.Choice, path: "kind" } });
      continue;
    }
    const materialized = materializeRuleDraft(record.rule);
    if (!materialized.valid)
      issues.push(...materialized.issues.map((issue) => ({ formKey: record.formKey, issue })));
    else rules.push({ recordId: record.recordId, rule: materialized.rule });
  }
  if (issues.length) return { valid: false, issues };
  const baseline = editing.baseline;
  return {
    valid: true,
    candidate: {
      bindingId: baseline.binding.id,
      profile: baseline.binding.profile,
      kind: baseline.binding.kind,
      baseVersionId: baseline.versionId,
      baseChecksum: baseline.checksum,
      sourceRevision: baseline.sourceRevision,
      rules,
    },
  };
}
/** Invalid/incomplete forms are dirty. Numeric spelling alone is not a changed configuration value. */
export function ruleSetIsDirty(editing: RuleSetEditing): boolean {
  const current = prepareRuleSetCandidate(editing);
  const baseline = prepareRuleSetCandidate(beginRuleSetEditing(editing.baseline));
  return (
    !current.valid ||
    !baseline.valid ||
    JSON.stringify(current.candidate.rules) !== JSON.stringify(baseline.candidate.rules)
  );
}
