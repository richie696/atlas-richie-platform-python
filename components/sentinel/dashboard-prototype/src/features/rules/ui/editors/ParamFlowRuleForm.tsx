/**
 * ParamFlowRule 表单。
 *
 * 中文
 * ----
 * 例外项的 `classType` / `object` 是 Sentinel Java 格式表达。跨语言 runtime 必须由
 * codec 显式校验，不能把它当作 Python 或其他语言的通用类型系统——这一点由表单底部的
 * 兼容性说明常驻提示，而不是只在文档里。
 *
 * 例外项的 `key` 使用 `object` + 下标：同一 `object` 可能重复出现，单独用 `object`
 * 会让 React 复用错误的输入节点。
 */
import { InfoIcon as Info } from "@phosphor-icons/react";

import { ActionButton } from "../../../../shared/ui/ActionButton";
import { RuleInput, RuleSelect } from "../fields/RuleFields";
import { paramItemsOf, type ParamFlowRuleDraft } from "../../model/ruleDraft";
import { localizedOptions } from "../../model/ruleOptions";
import type { RuleFieldCopy, RuleOptionCopy, RuleTypeCopy } from "../../model/ruleMessages";

export interface ParamFlowRuleFormProps {
  readonly draft: ParamFlowRuleDraft;
  readonly disabled: boolean;
  readonly typeCopy: RuleTypeCopy;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  /** 「添加例外值」按钮文案。 */
  readonly addLabel: string;
  /** 「移除」按钮文案。 */
  readonly removeLabel: string;
  /** 兼容性常驻说明。 */
  readonly compatibilityNote: string;
  readonly onChange: (next: ParamFlowRuleDraft) => void;
}

export function ParamFlowRuleForm({
  draft,
  disabled,
  typeCopy,
  fields,
  options,
  addLabel,
  removeLabel,
  compatibilityNote,
  onChange,
}: ParamFlowRuleFormProps) {
  const items = paramItemsOf(draft);
  const update = (patch: Partial<ParamFlowRuleDraft>) => onChange({ ...draft, ...patch });
  const updateNumber = (field: "count" | "durationInSec" | "paramIdx", value: string) =>
    update({ [field]: value === "" ? "" : Number(value) } as Partial<ParamFlowRuleDraft>);

  const updateItem = (index: number, patch: Partial<(typeof items)[number]>) =>
    update({
      paramFlowItemList: items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    });

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
          label={fields.thresholdType.label}
          hint={fields.thresholdType.hint}
          value={draft.grade}
          options={localizedOptions("flowGrade", options)}
          onChange={(value) => update({ grade: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.singleNodeThreshold.label}
          hint={fields.singleNodeThreshold.hint}
          value={draft.count}
          onChange={(value) => updateNumber("count", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.statisticPeriod.label}
          hint={fields.statisticPeriod.hint}
          value={draft.durationInSec}
          onChange={(value) => updateNumber("durationInSec", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.parameterIndex.label}
          hint={fields.parameterIndex.hint}
          value={draft.paramIdx}
          onChange={(value) => updateNumber("paramIdx", value)}
          disabled={disabled}
          numeric
        />
      </div>
      <div className="param-exceptions">
        <div className="param-exceptions-head">
          <b>{fields.parameterExceptions.label}</b>
          <ActionButton
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() =>
              update({
                paramFlowItemList: [
                  ...items,
                  { classType: "java.lang.String", object: "", count: draft.count },
                ],
              })
            }
          >
            {addLabel}
          </ActionButton>
        </div>
        {items.map((item, index) => (
          <div className="param-item" key={`${item.object}-${index}`}>
            <RuleInput
              label={fields.parameterType.label}
              hint={fields.parameterType.hint}
              value={item.classType}
              onChange={(value) => updateItem(index, { classType: value })}
              disabled={disabled}
            />
            <RuleInput
              label={fields.parameterValue.label}
              hint={fields.parameterValue.hint}
              value={item.object}
              onChange={(value) => updateItem(index, { object: value })}
              disabled={disabled}
            />
            <RuleInput
              label={fields.exceptionThreshold.label}
              hint={fields.exceptionThreshold.hint}
              value={item.count}
              onChange={(value) =>
                updateItem(index, { count: value === "" ? "" : Number(value) })
              }
              disabled={disabled}
              numeric
            />
            <ActionButton
              type="button"
              className="icon-text-button"
              disabled={disabled}
              onClick={() =>
                update({
                  paramFlowItemList: items.filter((_, itemIndex) => itemIndex !== index),
                })
              }
            >
              {removeLabel}
            </ActionButton>
          </div>
        ))}
      </div>
      <div className="compatibility-note">
        <Info size={15} /> {compatibilityNote}
      </div>
    </div>
  );
}
