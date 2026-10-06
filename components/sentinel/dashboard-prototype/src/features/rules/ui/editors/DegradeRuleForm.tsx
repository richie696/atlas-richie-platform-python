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
import { RuleInput, RuleSelect } from "../fields/RuleFields";
import type { DegradeRuleDraft } from "../../model/ruleDraft";
import { SentinelCode } from "../../model/ruleKinds";
import { localizedOptions } from "../../model/ruleOptions";
import type { RuleFieldCopy, RuleOptionCopy, RuleTypeCopy } from "../../model/ruleMessages";

export interface DegradeRuleFormProps {
  readonly draft: DegradeRuleDraft;
  readonly disabled: boolean;
  readonly typeCopy: RuleTypeCopy;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly onChange: (next: DegradeRuleDraft) => void;
}

export function DegradeRuleForm({
  draft,
  disabled,
  typeCopy,
  fields,
  options,
  onChange,
}: DegradeRuleFormProps) {
  const update = (patch: Partial<DegradeRuleDraft>) => onChange({ ...draft, ...patch });
  const updateNumber = (field: keyof DegradeRuleDraft, value: string) =>
    update({ [field]: value === "" ? "" : Number(value) } as Partial<DegradeRuleDraft>);
  const isSlowRequest = draft.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO;

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
          label={fields.circuitStrategy.label}
          hint={fields.circuitStrategy.hint}
          value={draft.grade}
          options={localizedOptions("degrade", options)}
          onChange={(value) => update({ grade: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.circuitThreshold.label}
          hint={fields.circuitThreshold.hint}
          value={draft.count}
          onChange={(value) => updateNumber("count", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.breakDuration.label}
          hint={fields.breakDuration.hint}
          value={draft.timeWindow}
          onChange={(value) => updateNumber("timeWindow", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.minimumRequests.label}
          hint={fields.minimumRequests.hint}
          value={draft.minRequestAmount}
          onChange={(value) => updateNumber("minRequestAmount", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.statisticWindow.label}
          hint={fields.statisticWindow.hint}
          value={draft.statIntervalMs}
          onChange={(value) => updateNumber("statIntervalMs", value)}
          disabled={disabled}
          numeric
        />
        {isSlowRequest && (
          <RuleInput
            label={fields.slowCallRatio.label}
            hint={fields.slowCallRatio.hint}
            value={draft.slowRatioThreshold ?? ""}
            onChange={(value) => updateNumber("slowRatioThreshold", value)}
            disabled={disabled}
            numeric
          />
        )}
      </div>
    </div>
  );
}
