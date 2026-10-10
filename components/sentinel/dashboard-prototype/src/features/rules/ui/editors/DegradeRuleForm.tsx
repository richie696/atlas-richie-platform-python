import rulesStyles from "../Rules.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";
/**
 * DegradeRule 表单。
 *
 * 中文
 * ----
 * `count` 的业务含义随 `grade` 切换：慢调用比例策略下它是临界 RT（毫秒），异常
 * 比例 / 异常数策略下是异常阈值。字段提示由语言包提供，表单不重复解释。
 *
 * 慢调用比例策略额外要求 `slowRatioThreshold` 取值区间 (0, 1]。
 */
import { RuleInput, RuleSelect, type RuleFieldError } from "../fields/RuleFields";
import { FormGrid } from "../../../../shared/ui/FormGrid";
import { parseNumericDraft, type DegradeRuleDraft } from "../../editor/ruleDraft";
import { SentinelCode } from "../../model/ruleKinds";
import { localizedOptions } from "../../i18n/localizedOptions";
import type { RuleFieldCopy, RuleOptionCopy, RuleTypeCopy } from "../../i18n/ruleMessages";

const styleModules = [rulesStyles] as const;

export interface DegradeRuleFormProps {
  readonly draft: DegradeRuleDraft;
  readonly disabled: boolean;
  readonly typeCopy: RuleTypeCopy;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly onChange: (next: DegradeRuleDraft) => void;
  readonly errorFor: RuleFieldError;
}

export function DegradeRuleForm({
  draft,
  disabled,
  typeCopy,
  fields,
  options,
  onChange,
  errorFor,
}: DegradeRuleFormProps) {
  const update = (patch: Partial<DegradeRuleDraft>) => onChange({ ...draft, ...patch });
  const updateNumber = (
    field: "count" | "timeWindow" | "minRequestAmount" | "statIntervalMs" | "slowRatioThreshold",
    value: string,
  ) => update({ [field]: parseNumericDraft(value) });
  const isSlowRequest = draft.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO;

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
          label={fields.circuitStrategy.label}
          hint={fields.circuitStrategy.hint}
          value={draft.grade}
          error={errorFor("grade")}
          options={localizedOptions("degrade", options)}
          onChange={(value) => update({ grade: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.circuitThreshold.label}
          hint={fields.circuitThreshold.hint}
          value={draft.count}
          error={errorFor("count")}
          onChange={(value) => updateNumber("count", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.breakDuration.label}
          hint={fields.breakDuration.hint}
          value={draft.timeWindow}
          error={errorFor("timeWindow")}
          onChange={(value) => updateNumber("timeWindow", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.minimumRequests.label}
          hint={fields.minimumRequests.hint}
          value={draft.minRequestAmount}
          error={errorFor("minRequestAmount")}
          onChange={(value) => updateNumber("minRequestAmount", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.statisticWindow.label}
          hint={fields.statisticWindow.hint}
          value={draft.statIntervalMs}
          error={errorFor("statIntervalMs")}
          onChange={(value) => updateNumber("statIntervalMs", value)}
          disabled={disabled}
          numeric
        />
        {isSlowRequest && (
          <RuleInput
            label={fields.slowCallRatio.label}
            hint={fields.slowCallRatio.hint}
            value={draft.slowRatioThreshold ?? ""}
            error={errorFor("slowRatioThreshold")}
            onChange={(value) => updateNumber("slowRatioThreshold", value)}
            disabled={disabled}
            numeric
          />
        )}
      </FormGrid>
    </div>
  );
}
