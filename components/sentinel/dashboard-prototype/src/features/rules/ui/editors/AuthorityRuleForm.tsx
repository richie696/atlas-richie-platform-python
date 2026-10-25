import rulesStyles from "../Rules.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";
/**
 * AuthorityRule 表单。
 *
 * 中文
 * ----
 * `limitApp` 是英文逗号分隔的 origin 列表，不是数组。白名单与黑名单对「未匹配来源」
 * 的结果相反，因此模式说明由语言包 `types.authority.description` 提供，表单不自行
 * 解释，避免与配置中心的实际语义脱节。
 */
import { RuleInput, RuleSelect, type RuleFieldError } from "../fields/RuleFields";
import { FormGrid } from "../../../../shared/ui/FormGrid";
import type { AuthorityRuleDraft } from "../../editor/ruleDraft";
import { localizedOptions } from "../../i18n/localizedOptions";
import type { RuleFieldCopy, RuleOptionCopy, RuleTypeCopy } from "../../i18n/ruleMessages";

const styleModules = [rulesStyles] as const;

export interface AuthorityRuleFormProps {
  readonly draft: AuthorityRuleDraft;
  readonly disabled: boolean;
  readonly typeCopy: RuleTypeCopy;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly onChange: (next: AuthorityRuleDraft) => void;
  readonly errorFor: RuleFieldError;
}

export function AuthorityRuleForm({
  draft,
  disabled,
  typeCopy,
  fields,
  options,
  onChange,
  errorFor,
}: AuthorityRuleFormProps) {
  const update = (patch: Partial<AuthorityRuleDraft>) => onChange({ ...draft, ...patch });

  return (
    <div className={scopedClasses(styleModules, "rule-form")}>
      <p className={scopedClasses(styleModules, "form-description")}>{typeCopy.description}</p>
      <FormGrid className="rule-form-grid">
        <RuleInput
          label={fields.resourceName.label}
          hint={fields.resourceName.hint}
          value={draft.resource}
          error={errorFor("resource")}
          onChange={(value) => update({ resource: value })}
          disabled={disabled}
        />
        <RuleSelect
          label={fields.authorityMode.label}
          hint={fields.authorityMode.hint}
          value={draft.strategy}
          error={errorFor("strategy")}
          options={localizedOptions("authority", options)}
          onChange={(value) => update({ strategy: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.originList.label}
          hint={fields.originList.hint}
          value={draft.limitApp}
          error={errorFor("limitApp")}
          onChange={(value) => update({ limitApp: value })}
          disabled={disabled}
        />
      </FormGrid>
    </div>
  );
}
