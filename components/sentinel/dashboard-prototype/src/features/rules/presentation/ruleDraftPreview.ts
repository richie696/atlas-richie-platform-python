import { RULE_KIND } from "../model/ruleKinds";
import type { TypedRuleDraft } from "../editor/ruleDraft";

/** Local, possibly invalid form preview; NOT a validated publication request or full snapshot. */
export function ruleDraftPreview(rule: TypedRuleDraft) {
  if (rule.kind !== RULE_KIND.ParamFlow) return rule.draft;
  return {
    ...rule.draft,
    paramFlowItemList: rule.draft.paramFlowItemList.map(({ formKey: _formKey, ...item }) => item),
  };
}
