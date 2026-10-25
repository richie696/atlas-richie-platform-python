import { RULE_ISSUE, type RuleIssueCode } from "../editor/rulePolicy";
import type { TranslationKey } from "../../../shared/types/translation";

/** Exhaustive presentation projection; domain policy never depends on an i18n namespace. */
export const RULE_ISSUE_MESSAGES = Object.freeze({
  [RULE_ISSUE.ResourceRequired]: "rules.errors.resourceRequired",
  [RULE_ISSUE.Positive]: "rules.errors.countPositive",
  [RULE_ISSUE.ReferenceRequired]: "rules.errors.referenceRequired",
  [RULE_ISSUE.Ratio]: "rules.errors.ratio",
  [RULE_ISSUE.PositiveRatio]: "rules.errors.slowRatio",
  [RULE_ISSUE.NonNegative]: "rules.errors.nonNegative",
  [RULE_ISSUE.ParameterIndex]: "rules.errors.parameterIndex",
  [RULE_ISSUE.OriginsRequired]: "rules.errors.originsRequired",
  [RULE_ISSUE.SystemEnabled]: "rules.errors.systemEnabled",
  [RULE_ISSUE.Number]: "rules.errors.finiteNumber",
  [RULE_ISSUE.Integer]: "rules.errors.integer",
  [RULE_ISSUE.Choice]: "rules.errors.choice",
  [RULE_ISSUE.Required]: "rules.errors.required",
  [RULE_ISSUE.Window]: "rules.errors.window",
  [RULE_ISSUE.Duplicate]: "rules.errors.duplicate",
} satisfies Record<RuleIssueCode, TranslationKey>);
