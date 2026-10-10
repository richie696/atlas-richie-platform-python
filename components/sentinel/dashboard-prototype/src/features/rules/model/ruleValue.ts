import { DISABLED_SYSTEM_THRESHOLD, RULE_KIND, SentinelCode, type RuleKind } from "./ruleKinds";
import {
  AUTHORITY_VALUES,
  DEGRADE_VALUES,
  FLOW_BEHAVIOR_VALUES,
  FLOW_GRADE_VALUES,
  FLOW_STRATEGY_VALUES,
} from "./ruleOptions";

/** Internal numeric rule facts, not a Console DTO or a promise of runtime codec support. */
export interface ClusterConfigValue {
  readonly thresholdType: number;
  readonly fallbackToLocalWhenFail: boolean;
  readonly sampleCount: number;
  readonly windowIntervalMs: number;
}
export interface FlowRuleValue {
  readonly resource: string;
  readonly limitApp: string;
  readonly grade: number;
  readonly count: number;
  readonly strategy: number;
  readonly controlBehavior: number;
  readonly clusterMode: boolean;
  readonly refResource?: string;
  readonly warmUpPeriodSec?: number;
  readonly maxQueueingTimeMs?: number;
  readonly clusterConfig?: ClusterConfigValue;
}
export interface DegradeRuleValue {
  readonly resource: string;
  readonly grade: number;
  readonly count: number;
  readonly timeWindow: number;
  readonly minRequestAmount: number;
  readonly statIntervalMs: number;
  readonly slowRatioThreshold?: number;
}
export interface SystemRuleValue {
  readonly highestSystemLoad: number;
  readonly avgRt: number;
  readonly maxThread: number;
  readonly qps: number;
  readonly highestCpuUsage: number;
}
export interface AuthorityRuleValue {
  readonly resource: string;
  readonly limitApp: string;
  readonly strategy: number;
}
export interface ParamFlowItemValue {
  readonly classType: string;
  readonly object: string;
  readonly count: number;
}
export interface ParamFlowRuleValue {
  readonly resource: string;
  readonly grade: number;
  readonly count: number;
  readonly durationInSec: number;
  readonly paramIdx: number;
  readonly paramFlowItemList: readonly ParamFlowItemValue[];
}
export interface RuleValueMap {
  [RULE_KIND.Flow]: FlowRuleValue;
  [RULE_KIND.Degrade]: DegradeRuleValue;
  [RULE_KIND.System]: SystemRuleValue;
  [RULE_KIND.Authority]: AuthorityRuleValue;
  [RULE_KIND.ParamFlow]: ParamFlowRuleValue;
}
export type RuleValueOf<K extends RuleKind> = RuleValueMap[K];
/** Category and numeric rule facts remain correlated outside editable forms too. */
export type TypedRuleValue = {
  [K in RuleKind]: { readonly kind: K; readonly value: RuleValueOf<K> };
}[RuleKind];

const finite = (value: number) => Number.isFinite(value);
const positive = (value: number) => finite(value) && value > 0;
const nonNegative = (value: number) => finite(value) && value >= 0;
const positiveInteger = (value: number) => Number.isSafeInteger(value) && value > 0;
const nonNegativeInteger = (value: number) => Number.isSafeInteger(value) && value >= 0;
const nonEmpty = (value: string) => !!value.trim();

/** Validate internal numeric rule facts without constructing UI form drafts. */
export function validRuleValue(rule: TypedRuleValue): boolean {
  switch (rule.kind) {
    case RULE_KIND.Flow: {
      const value = rule.value;
      if (
        !nonEmpty(value.resource) ||
        !nonEmpty(value.limitApp) ||
        !(FLOW_GRADE_VALUES as readonly number[]).includes(value.grade) ||
        !(FLOW_STRATEGY_VALUES as readonly number[]).includes(value.strategy) ||
        !(FLOW_BEHAVIOR_VALUES as readonly number[]).includes(value.controlBehavior) ||
        !positive(value.count) ||
        (value.grade === SentinelCode.FLOW_GRADE_THREAD && !Number.isSafeInteger(value.count))
      )
        return false;
      if (
        value.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT &&
        !nonEmpty(value.refResource ?? "")
      )
        return false;
      if (
        value.controlBehavior === SentinelCode.FLOW_BEHAVIOR_WARM_UP &&
        !positiveInteger(value.warmUpPeriodSec ?? NaN)
      )
        return false;
      if (
        value.controlBehavior === SentinelCode.FLOW_BEHAVIOR_QUEUEING &&
        !positiveInteger(value.maxQueueingTimeMs ?? NaN)
      )
        return false;
      if (!value.clusterMode) return true;
      const cluster = value.clusterConfig;
      return (
        !!cluster &&
        (
          [
            SentinelCode.CLUSTER_THRESHOLD_AVERAGE_LOCAL,
            SentinelCode.CLUSTER_THRESHOLD_GLOBAL,
          ] as readonly number[]
        ).includes(cluster.thresholdType) &&
        typeof cluster.fallbackToLocalWhenFail === "boolean" &&
        positiveInteger(cluster.sampleCount) &&
        positiveInteger(cluster.windowIntervalMs) &&
        cluster.windowIntervalMs >= cluster.sampleCount &&
        cluster.windowIntervalMs % cluster.sampleCount === 0
      );
    }
    case RULE_KIND.Degrade: {
      const value = rule.value;
      return (
        nonEmpty(value.resource) &&
        (DEGRADE_VALUES as readonly number[]).includes(value.grade) &&
        positive(value.count) &&
        (value.grade !== SentinelCode.DEGRADE_ERROR_COUNT || Number.isSafeInteger(value.count)) &&
        (value.grade !== SentinelCode.DEGRADE_ERROR_RATIO || value.count <= 1) &&
        positiveInteger(value.timeWindow) &&
        positiveInteger(value.minRequestAmount) &&
        positiveInteger(value.statIntervalMs) &&
        (value.grade !== SentinelCode.DEGRADE_SLOW_REQUEST_RATIO ||
          (positive(value.slowRatioThreshold ?? NaN) && value.slowRatioThreshold! <= 1))
      );
    }
    case RULE_KIND.System: {
      const values = Object.values(rule.value);
      return (
        values.some((value) => value !== DISABLED_SYSTEM_THRESHOLD) &&
        values.every((value) => value === DISABLED_SYSTEM_THRESHOLD || nonNegative(value)) &&
        nonNegativeInteger(
          rule.value.maxThread === DISABLED_SYSTEM_THRESHOLD ? 0 : rule.value.maxThread,
        ) &&
        (rule.value.highestCpuUsage === DISABLED_SYSTEM_THRESHOLD ||
          rule.value.highestCpuUsage <= 1)
      );
    }
    case RULE_KIND.Authority: {
      const origins = rule.value.limitApp.split(",").map((origin) => origin.trim());
      return (
        nonEmpty(rule.value.resource) &&
        (AUTHORITY_VALUES as readonly number[]).includes(rule.value.strategy) &&
        origins.every(nonEmpty) &&
        new Set(origins).size === origins.length
      );
    }
    case RULE_KIND.ParamFlow: {
      const value = rule.value;
      const seen = new Set<string>();
      const validItems = value.paramFlowItemList.every((item) => {
        const key = JSON.stringify([item.classType.trim(), item.object]);
        const valid =
          nonEmpty(item.classType) &&
          nonEmpty(item.object) &&
          nonNegative(item.count) &&
          !seen.has(key);
        seen.add(key);
        return valid;
      });
      return (
        nonEmpty(value.resource) &&
        value.grade === SentinelCode.FLOW_GRADE_QPS &&
        positive(value.count) &&
        positiveInteger(value.durationInSec) &&
        nonNegativeInteger(value.paramIdx) &&
        validItems
      );
    }
  }
}
