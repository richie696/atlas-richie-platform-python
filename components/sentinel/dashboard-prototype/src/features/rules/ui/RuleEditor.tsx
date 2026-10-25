/**
 * 规则编辑器的类型分发器。
 *
 * 中文
 * ----
 * 五类表单各自独立成文件后，本组件只负责「按规则类型选中正确的表单」。旧实现在
 * 一个 520 行的文件里用 `if (type === "flow") … else if` 串起五套表单，条件分支与
 * 字段定义混在一起，任意一类规则的字段变化都要在长文件里定位。
 *
 * 输入是类别相关的 TypedRuleDraft。TypeScript 根据 kind 收窄字段，不使用断言。
 * 字段错误由检视器翻译，表单只展示，不再决定规则是否合法。
 */
import type { TypedRuleDraft } from "../editor/ruleDraft";
import { RULE_KIND } from "../model/ruleKinds";
import type { RuleWorkbenchMessages } from "../i18n/ruleMessages";
import { AuthorityRuleForm } from "./editors/AuthorityRuleForm";
import { DegradeRuleForm } from "./editors/DegradeRuleForm";
import { FlowRuleForm } from "./editors/FlowRuleForm";
import { ParamFlowRuleForm } from "./editors/ParamFlowRuleForm";
import { SystemRuleForm } from "./editors/SystemRuleForm";
import type { RuleFieldError } from "./fields/RuleFields";

export interface RuleEditorProps {
  readonly rule: TypedRuleDraft;
  readonly editable: boolean;
  readonly messages: RuleWorkbenchMessages;
  readonly onChange: (rule: TypedRuleDraft) => void;
  readonly errorFor: RuleFieldError;
}

export function RuleEditor({ rule, editable, messages, onChange, errorFor }: RuleEditorProps) {
  const disabled = !editable;
  const { fields, options, types, rules } = messages;

  if (rule.kind === RULE_KIND.Flow) {
    return (
      <FlowRuleForm
        errorFor={errorFor}
        draft={rule.draft}
        disabled={disabled}
        fields={fields}
        options={options}
        onChange={(draft) => onChange({ kind: RULE_KIND.Flow, draft })}
      />
    );
  }
  if (rule.kind === RULE_KIND.Degrade) {
    return (
      <DegradeRuleForm
        errorFor={errorFor}
        draft={rule.draft}
        disabled={disabled}
        typeCopy={types.degrade}
        fields={fields}
        options={options}
        onChange={(draft) => onChange({ kind: RULE_KIND.Degrade, draft })}
      />
    );
  }
  if (rule.kind === RULE_KIND.System) {
    return (
      <SystemRuleForm
        errorFor={errorFor}
        draft={rule.draft}
        disabled={disabled}
        typeCopy={types.system}
        fields={fields}
        disabledNote={rules.systemDisabled}
        onChange={(draft) => onChange({ kind: RULE_KIND.System, draft })}
      />
    );
  }
  if (rule.kind === RULE_KIND.Authority) {
    return (
      <AuthorityRuleForm
        errorFor={errorFor}
        draft={rule.draft}
        disabled={disabled}
        typeCopy={types.authority}
        fields={fields}
        options={options}
        onChange={(draft) => onChange({ kind: RULE_KIND.Authority, draft })}
      />
    );
  }
  return (
    <ParamFlowRuleForm
      errorFor={errorFor}
      draft={rule.draft}
      disabled={disabled}
      typeCopy={types.param}
      fields={fields}
      options={options}
      addLabel={rules.addException}
      removeLabel={rules.remove}
      compatibilityNote={rules.paramCompatibility}
      onChange={(draft) => onChange({ kind: RULE_KIND.ParamFlow, draft })}
    />
  );
}
