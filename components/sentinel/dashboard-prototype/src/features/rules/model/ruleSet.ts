import { RULE_KIND, type RuleKind } from "./ruleKinds";
import type { TypedRuleValue } from "./ruleValue";

/** One rule-set binding owns exactly one type/profile and one authoritative destination. */
export interface RuleBinding {
  readonly id: string;
  readonly environmentId: string;
  readonly appId: string;
  readonly kind: RuleKind;
  readonly profile: string;
  readonly sourceId: string;
  readonly sourceLabel: string;
  /** Redacted location only; credentials never belong to a binding read model. */
  readonly location: string;
}
/** Management identity is separate from a native rule object and is not written into configuration JSON. */
export interface RuleRecord {
  readonly id: string;
  readonly rule: TypedRuleValue;
}
/** Complete collection facts for a binding; transport pagination, if added, must be explicit rather than silently truncated. */
export interface RuleSetCollection<Value> {
  readonly bindingId: string;
  readonly asOfMs: number;
  readonly items: readonly Value[];
}
export interface RuleSetSnapshot {
  readonly binding: RuleBinding;
  readonly versionId: string | null;
  readonly checksum: string;
  readonly sourceRevision: string | null;
  readonly asOfMs: number;
  readonly records: readonly RuleRecord[];
}
/** Full candidate, never a single-rule patch that could silently discard other rules. */
export interface CandidateRule {
  readonly recordId: string | null;
  readonly rule: TypedRuleValue;
}
export interface RuleSetCandidate {
  readonly bindingId: string;
  readonly profile: string;
  readonly kind: RuleKind;
  readonly baseVersionId: string | null;
  readonly baseChecksum: string;
  readonly sourceRevision: string | null;
  readonly rules: readonly CandidateRule[];
}
export const MAX_RULE_SET_SIZE = 1000;
const identifier = (value: string) => !!value.trim();
/** Binding identity/profile/location are directory facts, not guessed from a selected rule. */
export function validRuleBinding(value: RuleBinding): boolean {
  return (
    [
      value.id,
      value.environmentId,
      value.appId,
      value.profile,
      value.sourceId,
      value.sourceLabel,
      value.location,
    ].every(identifier) && Object.values(RULE_KIND).includes(value.kind)
  );
}
/** Internal ownership/shape checks only. The F6 decoder must additionally reject unknown fields and decode facts. */
export function validRuleSetSnapshot(value: RuleSetSnapshot, bindingId: string): boolean {
  return (
    value.binding.id === bindingId &&
    validRuleBinding(value.binding) &&
    identifier(value.checksum) &&
    (value.versionId === null || identifier(value.versionId)) &&
    (value.sourceRevision === null || identifier(value.sourceRevision)) &&
    Number.isSafeInteger(value.asOfMs) &&
    value.asOfMs >= 0 &&
    value.records.length <= MAX_RULE_SET_SIZE &&
    new Set(value.records.map((item) => item.id)).size === value.records.length &&
    value.records.every((item) => identifier(item.id) && item.rule.kind === value.binding.kind)
  );
}
