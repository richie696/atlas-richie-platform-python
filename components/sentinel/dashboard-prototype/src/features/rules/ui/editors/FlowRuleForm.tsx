import rulesStyles from "../Rules.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";
/**
 * FlowRule 表单。
 *
 * 中文
 * ----
 * 条件字段与 `规则控制台与运行观测设计.md` §4.3 的 FlowRule 合同一致：
 *
 * - 非直接策略必须填写 `refResource`；
 * - 慢启动显示 `warmUpPeriodSec`；
 * - 排队等待显示 `maxQueueingTimeMs`；
 * - 开启 clusterMode 才出现集群子表单。
 *
 * 字段排列归共享 FormGrid；本组件只拥有条件字段和草稿更新。
 */
import { RuleInput, RuleSelect, RuleToggle, type RuleFieldError } from "../fields/RuleFields";
import { FormGrid } from "../../../../shared/ui/FormGrid";
import {
  DEFAULT_CLUSTER_CONFIG,
  cloneRule,
  parseNumericDraft,
  type FlowRuleDraft,
} from "../../editor/ruleDraft";
import { SentinelCode } from "../../model/ruleKinds";
import { localizedOptions } from "../../i18n/localizedOptions";
import type { RuleOptionCopy, RuleFieldCopy } from "../../i18n/ruleMessages";

const styleModules = [rulesStyles] as const;

export interface FlowRuleFormProps {
  readonly draft: FlowRuleDraft;
  readonly disabled: boolean;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly onChange: (next: FlowRuleDraft) => void;
  readonly errorFor: RuleFieldError;
}

/** FlowRule 专用的条件字段可见性判断。纯函数，表单只负责渲染。 */
export function flowConditionalFields(draft: FlowRuleDraft): {
  readonly showRefResource: boolean;
  readonly showWarmUp: boolean;
  readonly showQueueing: boolean;
} {
  return {
    showRefResource: draft.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT,
    showWarmUp: draft.controlBehavior === SentinelCode.FLOW_BEHAVIOR_WARM_UP,
    showQueueing: draft.controlBehavior === SentinelCode.FLOW_BEHAVIOR_QUEUEING,
  };
}

export function FlowRuleForm({
  draft,
  disabled,
  fields,
  options,
  onChange,
  errorFor,
}: FlowRuleFormProps) {
  const { showRefResource, showWarmUp, showQueueing } = flowConditionalFields(draft);
  const update = (patch: Partial<FlowRuleDraft>) => onChange({ ...draft, ...patch });
  const updateNumber = (field: "count" | "warmUpPeriodSec" | "maxQueueingTimeMs", value: string) =>
    update({ [field]: parseNumericDraft(value) });
  const updateCluster = (patch: Partial<NonNullable<FlowRuleDraft["clusterConfig"]>>) =>
    update({
      clusterConfig: { ...DEFAULT_CLUSTER_CONFIG, ...draft.clusterConfig, ...patch },
    });

  /** Preserve inactive values for editing; the later wire mapper must omit inactive clusterConfig. */
  const setClusterMode = (enabled: boolean) =>
    onChange(
      enabled
        ? {
            ...draft,
            clusterMode: true,
            clusterConfig: draft.clusterConfig ?? cloneRule(DEFAULT_CLUSTER_CONFIG),
          }
        : { ...draft, clusterMode: false },
    );

  return (
    <div className={scopedClasses(styleModules, "rule-form")}>
      <FormGrid className="rule-form-grid">
        <RuleInput
          label={fields.resourceName.label}
          hint={fields.resourceName.hint}
          value={draft.resource}
          error={errorFor("resource")}
          onChange={(value) => update({ resource: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.callerOrigin.label}
          hint={fields.callerOrigin.hint}
          value={draft.limitApp}
          error={errorFor("limitApp")}
          onChange={(value) => update({ limitApp: value })}
          disabled={disabled}
        />
        <RuleSelect
          label={fields.thresholdType.label}
          hint={fields.thresholdType.hint}
          value={draft.grade}
          error={errorFor("grade")}
          options={localizedOptions("flowGrade", options)}
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
        <RuleSelect
          label={fields.controlStrategy.label}
          hint={fields.controlStrategy.hint}
          value={draft.strategy}
          error={errorFor("strategy")}
          options={localizedOptions("flowStrategy", options)}
          onChange={(value) => update({ strategy: value })}
          disabled={disabled}
        />
        <RuleSelect
          label={fields.controlBehavior.label}
          hint={fields.controlBehavior.hint}
          value={draft.controlBehavior}
          error={errorFor("controlBehavior")}
          options={localizedOptions("flowBehavior", options)}
          onChange={(value) => update({ controlBehavior: value })}
          disabled={disabled}
        />
        {showRefResource && (
          <RuleInput
            label={fields.relatedResource.label}
            hint={fields.relatedResource.hint}
            value={draft.refResource ?? ""}
            error={errorFor("refResource")}
            onChange={(value) => update({ refResource: value })}
            disabled={disabled}
          />
        )}
        {showWarmUp && (
          <RuleInput
            label={fields.warmUpPeriod.label}
            hint={fields.warmUpPeriod.hint}
            value={draft.warmUpPeriodSec ?? ""}
            error={errorFor("warmUpPeriodSec")}
            onChange={(value) => updateNumber("warmUpPeriodSec", value)}
            disabled={disabled}
            numeric
          />
        )}
        {showQueueing && (
          <RuleInput
            label={fields.maxQueueingTime.label}
            hint={fields.maxQueueingTime.hint}
            value={draft.maxQueueingTimeMs ?? ""}
            error={errorFor("maxQueueingTimeMs")}
            onChange={(value) => updateNumber("maxQueueingTimeMs", value)}
            disabled={disabled}
            numeric
          />
        )}
      </FormGrid>
      <div className={scopedClasses(styleModules, "advanced-rule-section")}>
        <RuleToggle
          label={fields.clusterMode.label}
          hint={fields.clusterMode.hint}
          checked={Boolean(draft.clusterMode)}
          onChange={setClusterMode}
          disabled={disabled}
        />
        {draft.clusterMode && (
          <>
            <RuleToggle
              label={fields.localFallback.label}
              hint={fields.localFallback.hint}
              checked={Boolean(draft.clusterConfig?.fallbackToLocalWhenFail)}
              onChange={(value) => updateCluster({ fallbackToLocalWhenFail: value })}
              disabled={disabled}
            />
            <FormGrid className={scopedClasses(styleModules, "rule-form-grid cluster-grid")}>
              <RuleSelect
                label={fields.clusterThresholdType.label}
                hint={fields.clusterThresholdType.hint}
                value={draft.clusterConfig?.thresholdType ?? ""}
                error={errorFor("clusterConfig.thresholdType")}
                options={localizedOptions("clusterThreshold", options)}
                onChange={(value) => updateCluster({ thresholdType: value })}
                disabled={disabled}
              />
              <RuleInput
                label={fields.sampleCount.label}
                hint={fields.sampleCount.hint}
                value={draft.clusterConfig?.sampleCount ?? ""}
                error={errorFor("clusterConfig.sampleCount")}
                onChange={(value) => updateCluster({ sampleCount: parseNumericDraft(value) })}
                disabled={disabled}
                numeric
              />
              <RuleInput
                label={fields.statisticWindow.label}
                hint={fields.statisticWindow.hint}
                value={draft.clusterConfig?.windowIntervalMs ?? ""}
                error={errorFor("clusterConfig.windowIntervalMs")}
                onChange={(value) => updateCluster({ windowIntervalMs: parseNumericDraft(value) })}
                disabled={disabled}
                numeric
              />
            </FormGrid>
          </>
        )}
      </div>
    </div>
  );
}
