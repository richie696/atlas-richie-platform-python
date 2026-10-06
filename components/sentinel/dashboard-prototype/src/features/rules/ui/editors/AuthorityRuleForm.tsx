/**
 * AuthorityRule 表单。
 *
 * 中文
 * ----
 * `limitApp` 是英文逗号分隔的 origin 列表，不是数组。白名单与黑名单对「未匹配来源」
 * 的结果相反，因此模式说明由语言包 `types.authority.description` 提供，表单不自行
 * 解释，避免与配置中心的实际语义脱节。
 */
import { RuleInput, RuleSelect } from "../fields/RuleFields";
import type { AuthorityRuleDraft } from "../../model/ruleDraft";
import { localizedOptions } from "../../model/ruleOptions";
import type { RuleFieldCopy, RuleOptionCopy, RuleTypeCopy } from "../../model/ruleMessages";

export interface AuthorityRuleFormProps {
  readonly draft: AuthorityRuleDraft;
  readonly disabled: boolean;
  readonly typeCopy: RuleTypeCopy;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly onChange: (next: AuthorityRuleDraft) => void;
}

export function AuthorityRuleForm({
  draft,
  disabled,
  typeCopy,
  fields,
  options,
  onChange,
}: AuthorityRuleFormProps) {
  const update = (patch: Partial<AuthorityRuleDraft>) => onChange({ ...draft, ...patch });

  return (
    <div className="rule-form">
      <p className="form-description">{typeCopy.description}</p>
      <div className="rule-form-grid">
        <RuleInput
          label={fields.resourceName.label}
          hint={fields.resourceName.hint}
          value={draft.resource}
          onChange={(value) => update({ resource: value })}
          disabled={disabled}
        />
        <RuleSelect
          label={fields.authorityMode.label}
          hint={fields.authorityMode.hint}
          value={draft.strategy}
          options={localizedOptions("authority", options)}
          onChange={(value) => update({ strategy: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.originList.label}
          hint={fields.originList.hint}
          value={draft.limitApp}
          onChange={(value) => update({ limitApp: value })}
          disabled={disabled}
        />
      </div>
    </div>
  );
}
