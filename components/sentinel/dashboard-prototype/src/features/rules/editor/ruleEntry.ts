import { RULE_KIND, type RuleKind, type RuleScope, type RuleSourceKind } from "../model/ruleKinds";
import type { TypedRuleDraft } from "./ruleDraft";
import { editableRule } from "./ruleMaterialization";
import type { RuleValueOf } from "../model/ruleValue";
import type { RuleCatalogEntry } from "./rulePolicy";

/** Category-correlated internal read model. Neither a form draft nor a Console wire DTO. */
export type RuleWorkbenchEntry = {
  [K in RuleKind]: RuleCatalogEntry & {
    readonly ruleType: K;
    readonly threshold: string;
    readonly scope: RuleScope;
    readonly provider: RuleSourceKind;
    readonly version: string;
    readonly sentinelRule: RuleValueOf<K>;
  };
}[RuleKind];

/** Copy the selected baseline without an assertion that can hide mismatched categories. */
export function draftFromEntry(entry: RuleWorkbenchEntry): TypedRuleDraft {
  switch (entry.ruleType) {
    case RULE_KIND.Flow:
      return editableRule(
        { kind: entry.ruleType, value: entry.sentinelRule },
        (index) => `${entry.id}:${index}`,
      );
    case RULE_KIND.Degrade:
      return editableRule(
        { kind: entry.ruleType, value: entry.sentinelRule },
        (index) => `${entry.id}:${index}`,
      );
    case RULE_KIND.System:
      return editableRule(
        { kind: entry.ruleType, value: entry.sentinelRule },
        (index) => `${entry.id}:${index}`,
      );
    case RULE_KIND.Authority:
      return editableRule(
        { kind: entry.ruleType, value: entry.sentinelRule },
        (index) => `${entry.id}:${index}`,
      );
    case RULE_KIND.ParamFlow:
      return editableRule(
        { kind: entry.ruleType, value: entry.sentinelRule },
        (index) => `${entry.id}:${index}`,
      );
  }
}
