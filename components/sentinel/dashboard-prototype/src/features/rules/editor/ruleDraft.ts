/** Editable form types extend numeric domain facts; they are never transport DTOs. */
import { RULE_KIND, SentinelCode, type RuleKind } from "../model/ruleKinds";
import type {
  AuthorityRuleValue,
  ClusterConfigValue,
  DegradeRuleValue,
  FlowRuleValue,
  ParamFlowItemValue,
  ParamFlowRuleValue,
  SystemRuleValue,
} from "../model/ruleValue";

/** Only explicitly editable numeric fields admit temporary text/empty input. Enum codes stay numeric. */
type NumericDraft<T, K extends keyof T> = { [P in keyof T]: P extends K ? T[P] | string : T[P] };
export type ClusterConfigDraft = NumericDraft<
  ClusterConfigValue,
  "sampleCount" | "windowIntervalMs"
>;
export type FlowRuleDraft = Omit<
  NumericDraft<FlowRuleValue, "count" | "warmUpPeriodSec" | "maxQueueingTimeMs">,
  "clusterConfig"
> & { readonly clusterConfig?: ClusterConfigDraft };
export type DegradeRuleDraft = NumericDraft<
  DegradeRuleValue,
  "count" | "timeWindow" | "minRequestAmount" | "statIntervalMs" | "slowRatioThreshold"
>;
export type SystemRuleDraft = NumericDraft<SystemRuleValue, keyof SystemRuleValue>;
export type AuthorityRuleDraft = AuthorityRuleValue;

/** Form-only identity keeps focus/draft input stable when exception values change or rows are removed. */
export type ParamFlowItemDraft = NumericDraft<ParamFlowItemValue, "count"> & {
  readonly formKey: string;
};
export type ParamFlowRuleDraft = Omit<
  NumericDraft<ParamFlowRuleValue, "count" | "durationInSec" | "paramIdx">,
  "paramFlowItemList"
> & { readonly paramFlowItemList: readonly ParamFlowItemDraft[] };
export interface RuleDraftMap {
  [RULE_KIND.Flow]: FlowRuleDraft;
  [RULE_KIND.Degrade]: DegradeRuleDraft;
  [RULE_KIND.System]: SystemRuleDraft;
  [RULE_KIND.Authority]: AuthorityRuleDraft;
  [RULE_KIND.ParamFlow]: ParamFlowRuleDraft;
}
export type RuleDraftOf<K extends RuleKind> = RuleDraftMap[K];
export type RuleDraft = RuleDraftMap[RuleKind];

/** A genuine discriminated union makes category/payload mismatch a compile-time error. */
export type TypedRuleDraft = {
  [K in RuleKind]: { readonly kind: K; readonly draft: RuleDraftOf<K> };
}[RuleKind];

/** Explicit defaults for a new cluster subform, not a server-assigned identifier or live quota. */
export const DEFAULT_CLUSTER_CONFIG: ClusterConfigDraft = Object.freeze({
  thresholdType: SentinelCode.CLUSTER_THRESHOLD_AVERAGE_LOCAL,
  fallbackToLocalWhenFail: true,
  sampleCount: 10,
  windowIntervalMs: 1000,
});

/** Deep-copy a selected numeric baseline; never mutate the repository-owned value. */
export function cloneRule<T>(rule: T): T {
  return structuredClone(rule);
}

/** Empty input is explicit; validation rejects non-finite or malformed numeric text. */
export function parseNumericDraft(value: string): number | "" {
  return value.trim() === "" ? "" : Number(value);
}
