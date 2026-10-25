import rulesStyles from "../Rules.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";
/**
 * ParamFlowRule 表单。
 *
 * 中文
 * ----
 * 例外项的 `classType` / `object` 是 Sentinel Java 格式表达。跨语言 runtime 必须由
 * codec 显式校验，不能把它当作 Python 或其他语言的通用类型系统——这一点由表单底部的
 * 兼容性说明常驻提示，而不是只在文档里。
 *
 * 例外项的 formKey 是稳定的表单身份，不随 object 内容变化，不进入配置预览/协议。
 */
import { InfoIcon as Info } from "@phosphor-icons/react";

import { ActionButton } from "../../../../shared/ui/ActionButton";
import { RuleInput, RuleSelect, type RuleFieldError } from "../fields/RuleFields";
import { FormGrid } from "../../../../shared/ui/FormGrid";
import { parseNumericDraft, type ParamFlowRuleDraft } from "../../editor/ruleDraft";
import { localizedOptions } from "../../i18n/localizedOptions";
import type { RuleFieldCopy, RuleOptionCopy, RuleTypeCopy } from "../../i18n/ruleMessages";

const styleModules = [rulesStyles] as const;

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
  readonly errorFor: RuleFieldError;
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
  errorFor,
}: ParamFlowRuleFormProps) {
  const items = draft.paramFlowItemList;
  const update = (patch: Partial<ParamFlowRuleDraft>) => onChange({ ...draft, ...patch });
  const updateNumber = (field: "count" | "durationInSec" | "paramIdx", value: string) =>
    update({ [field]: parseNumericDraft(value) });

  const updateItem = (index: number, patch: Partial<(typeof items)[number]>) =>
    update({
      paramFlowItemList: items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    });

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
          label={fields.thresholdType.label}
          hint={fields.thresholdType.hint}
          value={draft.grade}
          error={errorFor("grade")}
          options={localizedOptions("paramGrade", options)}
          onChange={(value) => update({ grade: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.singleNodeThreshold.label}
          hint={fields.singleNodeThreshold.hint}
          value={draft.count}
          error={errorFor("count")}
          onChange={(value) => updateNumber("count", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.statisticPeriod.label}
          hint={fields.statisticPeriod.hint}
          value={draft.durationInSec}
          error={errorFor("durationInSec")}
          onChange={(value) => updateNumber("durationInSec", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.parameterIndex.label}
          hint={fields.parameterIndex.hint}
          value={draft.paramIdx}
          error={errorFor("paramIdx")}
          onChange={(value) => updateNumber("paramIdx", value)}
          disabled={disabled}
          numeric
        />
      </FormGrid>
      <div className={scopedClasses(styleModules, "param-exceptions")}>
        <div className={scopedClasses(styleModules, "param-exceptions-head")}>
          <b>{fields.parameterExceptions.label}</b>
          <ActionButton
            type="button"
            className={scopedClasses(styleModules, "text-button")}
            disabled={disabled}
            onClick={() =>
              update({
                paramFlowItemList: [
                  ...items,
                  {
                    formKey: crypto.randomUUID(),
                    classType: "java.lang.String",
                    object: "",
                    count: draft.count,
                  },
                ],
              })
            }
          >
            {addLabel}
          </ActionButton>
        </div>
        {items.map((item, index) => (
          <div className={scopedClasses(styleModules, "param-item")} key={item.formKey}>
            <FormGrid columns={3}>
              <RuleInput
                label={fields.parameterType.label}
                hint={fields.parameterType.hint}
                value={item.classType}
                error={errorFor(`paramFlowItemList.${index}.classType`)}
                onChange={(value) => updateItem(index, { classType: value })}
                disabled={disabled}
              />
              <RuleInput
                label={fields.parameterValue.label}
                hint={fields.parameterValue.hint}
                value={item.object}
                error={errorFor(`paramFlowItemList.${index}.object`)}
                onChange={(value) => updateItem(index, { object: value })}
                disabled={disabled}
              />
              <RuleInput
                label={fields.exceptionThreshold.label}
                hint={fields.exceptionThreshold.hint}
                value={item.count}
                error={errorFor(`paramFlowItemList.${index}.count`)}
                onChange={(value) =>
                  updateItem(index, { count: value === "" ? "" : Number(value) })
                }
                disabled={disabled}
                numeric
              />
            </FormGrid>
            <ActionButton
              type="button"
              className={scopedClasses(styleModules, "icon-text-button")}
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
      <div className={scopedClasses(styleModules, "compatibility-note")}>
        <Info size={15} /> {compatibilityNote}
      </div>
    </div>
  );
}
