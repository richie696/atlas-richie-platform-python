/**
 * FlowRule 表单。
 *
 * 中文
 * ----
 * 条件字段与 `DASHBOARD_CONTROL_PLANE.md` §4.3 的 FlowRule 合同一致：
 *
 * - 非直接策略必须填写 `refResource`；
 * - 慢启动显示 `warmUpPeriodSec`；
 * - 排队等待显示 `maxQueueingTimeMs`；
 * - 开启 clusterMode 才出现集群子表单。
 *
 * JSX 与类名与原 `RuleEditor` 的 flow 分支逐字一致，视觉基线不变。
 */
import { RuleInput, RuleSelect, RuleToggle } from "../fields/RuleFields";
import { DEFAULT_CLUSTER_CONFIG, cloneRule, type FlowRuleDraft } from "../../model/ruleDraft";
import { SentinelCode } from "../../model/ruleKinds";
import { localizedOptions } from "../../model/ruleOptions";
import type { RuleOptionCopy, RuleFieldCopy } from "../../model/ruleMessages";

export interface FlowRuleFormProps {
  readonly draft: FlowRuleDraft;
  readonly disabled: boolean;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly onChange: (next: FlowRuleDraft) => void;
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

export function FlowRuleForm({ draft, disabled, fields, options, onChange }: FlowRuleFormProps) {
  const { showRefResource, showWarmUp, showQueueing } = flowConditionalFields(draft);
  const update = (patch: Partial<FlowRuleDraft>) => onChange({ ...draft, ...patch });
  const updateNumber = (field: keyof FlowRuleDraft, value: string) =>
    update({ [field]: value === "" ? "" : Number(value) } as Partial<FlowRuleDraft>);
  const updateCluster = (patch: Partial<NonNullable<FlowRuleDraft["clusterConfig"]>>) =>
    update({ clusterConfig: { ...draft.clusterConfig, ...patch } as NonNullable<FlowRuleDraft["clusterConfig"]> });

  /** 集群模式是开关语义：关闭时保留 clusterConfig 以便再次开启，协议内容不含该键。 */
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
    <div className="rule-form">
      <div className="rule-form-grid">
        <RuleInput
          label={fields.resourceName.label}
          hint={fields.resourceName.hint}
          value={draft.resource}
          onChange={(value) => update({ resource: value })}
          disabled={disabled}
        />
        <RuleInput
          label={fields.callerOrigin.label}
          hint={fields.callerOrigin.hint}
          value={draft.limitApp}
          onChange={(value) => update({ limitApp: value })}
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
        <RuleSelect
          label={fields.controlStrategy.label}
          hint={fields.controlStrategy.hint}
          value={draft.strategy}
          options={localizedOptions("flowStrategy", options)}
          onChange={(value) => update({ strategy: value })}
          disabled={disabled}
        />
        <RuleSelect
          label={fields.controlBehavior.label}
          hint={fields.controlBehavior.hint}
          value={draft.controlBehavior}
          options={localizedOptions("flowBehavior", options)}
          onChange={(value) => update({ controlBehavior: value })}
          disabled={disabled}
        />
        {showRefResource && (
          <RuleInput
            label={fields.relatedResource.label}
            hint={fields.relatedResource.hint}
            value={draft.refResource ?? ""}
            onChange={(value) => update({ refResource: value })}
            disabled={disabled}
          />
        )}
        {showWarmUp && (
          <RuleInput
            label={fields.warmUpPeriod.label}
            hint={fields.warmUpPeriod.hint}
            value={draft.warmUpPeriodSec ?? ""}
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
            onChange={(value) => updateNumber("maxQueueingTimeMs", value)}
            disabled={disabled}
            numeric
          />
        )}
      </div>
      <div className="advanced-rule-section">
        <RuleToggle
          label={fields.clusterMode.label}
          hint={fields.clusterMode.hint}
          checked={Boolean(draft.clusterMode)}
          onChange={setClusterMode}
          disabled={disabled}
        />
        {draft.clusterMode && (
          <div className="rule-form-grid cluster-grid">
            <RuleInput
              label={fields.clusterThresholdType.label}
              hint={fields.clusterThresholdType.hint}
              value={draft.clusterConfig?.thresholdType ?? ""}
              onChange={(value) => updateCluster({ thresholdType: Number(value) })}
              disabled={disabled}
              numeric
            />
            <RuleToggle
              label={fields.localFallback.label}
              hint={fields.localFallback.hint}
              checked={Boolean(draft.clusterConfig?.fallbackToLocalWhenFail)}
              onChange={(value) => updateCluster({ fallbackToLocalWhenFail: value })}
              disabled={disabled}
            />
            <RuleInput
              label={fields.sampleCount.label}
              hint={fields.sampleCount.hint}
              value={draft.clusterConfig?.sampleCount ?? ""}
              onChange={(value) => updateCluster({ sampleCount: Number(value) })}
              disabled={disabled}
              numeric
            />
            <RuleInput
              label={fields.statisticWindow.label}
              hint={fields.statisticWindow.hint}
              value={draft.clusterConfig?.windowIntervalMs ?? ""}
              onChange={(value) => updateCluster({ windowIntervalMs: Number(value) })}
              disabled={disabled}
              numeric
            />
          </div>
        )}
      </div>
    </div>
  );
}
