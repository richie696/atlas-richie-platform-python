/**
 * 规则编辑器的类型分发器。
 *
 * 中文
 * ----
 * 五类表单各自独立成文件后，本组件只负责「按规则类型选中正确的表单」。旧实现在
 * 一个 520 行的文件里用 `if (type === "flow") … else if` 串起五套表单，条件分支与
 * 字段定义混在一起，任意一类规则的字段变化都要在长文件里定位。
 *
 * 草稿与规则类型的对应关系由 `useRuleWorkbench` 保证：草稿永远来自当前选中条目的
 * `sentinelRule`，而条目自带 `ruleType`。因此下面的收窄是安全的；若该不变量被破坏，
 * 表单会读到 undefined 字段并立刻暴露，而不是静默渲染空值。
 */
import { narrowDraft, type RuleDraft } from "../model/ruleDraft";
import { RULE_KIND, type RuleKind } from "../model/ruleKinds";
import type { RuleWorkbenchMessages } from "../model/ruleMessages";
import { AuthorityRuleForm } from "./editors/AuthorityRuleForm";
import { DegradeRuleForm } from "./editors/DegradeRuleForm";
import { FlowRuleForm } from "./editors/FlowRuleForm";
import { ParamFlowRuleForm } from "./editors/ParamFlowRuleForm";
import { SystemRuleForm } from "./editors/SystemRuleForm";

export interface RuleEditorProps {
  readonly kind: RuleKind;
  readonly draft: RuleDraft;
  readonly editable: boolean;
  readonly messages: RuleWorkbenchMessages;
  readonly onChange: (draft: RuleDraft) => void;
}

export function RuleEditor({ kind, draft, editable, messages, onChange }: RuleEditorProps) {
  const disabled = !editable;
  const { fields, options, types, rules } = messages;

  if (kind === RULE_KIND.Flow) {
    return (
      <FlowRuleForm
        draft={narrowDraft(RULE_KIND.Flow, draft)}
        disabled={disabled}
        fields={fields}
        options={options}
        onChange={onChange}
      />
    );
  }
  if (kind === RULE_KIND.Degrade) {
    return (
      <DegradeRuleForm
        draft={narrowDraft(RULE_KIND.Degrade, draft)}
        disabled={disabled}
        typeCopy={types.degrade}
        fields={fields}
        options={options}
        onChange={onChange}
      />
    );
  }
  if (kind === RULE_KIND.System) {
    return (
      <SystemRuleForm
        draft={narrowDraft(RULE_KIND.System, draft)}
        disabled={disabled}
        typeCopy={types.system}
        fields={fields}
        disabledNote={rules.systemDisabled}
        onChange={onChange}
      />
    );
  }
  if (kind === RULE_KIND.Authority) {
    return (
      <AuthorityRuleForm
        draft={narrowDraft(RULE_KIND.Authority, draft)}
        disabled={disabled}
        typeCopy={types.authority}
        fields={fields}
        options={options}
        onChange={onChange}
      />
    );
  }
  return (
    <ParamFlowRuleForm
      draft={narrowDraft(RULE_KIND.ParamFlow, draft)}
      disabled={disabled}
      typeCopy={types.param}
      fields={fields}
      options={options}
      addLabel={rules.addException}
      removeLabel={rules.remove}
      compatibilityNote={rules.paramCompatibility}
      onChange={onChange}
    />
  );
}
