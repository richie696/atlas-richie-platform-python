/** Convert protocol choices to localized form options; mismatched resource lengths fail explicitly. */
import { RULE_OPTION_VALUES, type RuleOptionGroup } from "../model/ruleOptions";
import type { RuleOptionCopy } from "./ruleMessages";

/** 一个下拉选项：协议值 + 展示标签。 */
export interface RuleOption {
  readonly value: number;
  readonly label: string;
}

/** Fill a numeric choice group with translated labels, without changing protocol values. */
export function localizedOptions(
  group: RuleOptionGroup,
  copy: RuleOptionCopy,
): readonly RuleOption[] {
  const values = RULE_OPTION_VALUES[group],
    labels = copy[group];
  if (values.length !== labels.length)
    throw new Error(
      `[rules] localizedOptions("${group}"): ${values.length} protocol values but ${labels.length} labels`,
    );
  return values.map((value, index) => ({ value, label: labels[index] }));
}
