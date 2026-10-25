/** Numeric Sentinel option values only; labels are owned by rules/i18n. */
import { SentinelCode } from "./ruleKinds";
/** FlowRule 阈值类型。 */
export const FLOW_GRADE_VALUES = Object.freeze([
  SentinelCode.FLOW_GRADE_QPS,
  SentinelCode.FLOW_GRADE_THREAD,
]);

/** 当前热点规则模型仅支持每秒请求数，不提供会被策略拒绝的并发选项。 */
export const PARAM_GRADE_VALUES = Object.freeze([SentinelCode.FLOW_GRADE_QPS]);

/** 集群额度的两种解释；展示名称由语言资源提供，不让用户填写裸编码。 */
export const CLUSTER_THRESHOLD_VALUES = Object.freeze([
  SentinelCode.CLUSTER_THRESHOLD_AVERAGE_LOCAL,
  SentinelCode.CLUSTER_THRESHOLD_GLOBAL,
]);

/** FlowRule 流控模式。 */
export const FLOW_STRATEGY_VALUES = Object.freeze([
  SentinelCode.FLOW_STRATEGY_DIRECT,
  SentinelCode.FLOW_STRATEGY_CHAIN,
  SentinelCode.FLOW_STRATEGY_RELATE,
]);

/** FlowRule 流控效果。 */
export const FLOW_BEHAVIOR_VALUES = Object.freeze([
  SentinelCode.FLOW_BEHAVIOR_REJECT,
  SentinelCode.FLOW_BEHAVIOR_WARM_UP,
  SentinelCode.FLOW_BEHAVIOR_QUEUEING,
]);

/** DegradeRule 熔断策略。 */
export const DEGRADE_VALUES = Object.freeze([
  SentinelCode.DEGRADE_SLOW_REQUEST_RATIO,
  SentinelCode.DEGRADE_ERROR_RATIO,
  SentinelCode.DEGRADE_ERROR_COUNT,
]);

/** AuthorityRule 访问控制模式。 */
export const AUTHORITY_VALUES = Object.freeze([
  SentinelCode.AUTHORITY_WHITE,
  SentinelCode.AUTHORITY_BLACK,
]);

export const RULE_OPTION_VALUES = Object.freeze({
  flowGrade: FLOW_GRADE_VALUES,
  paramGrade: PARAM_GRADE_VALUES,
  clusterThreshold: CLUSTER_THRESHOLD_VALUES,
  flowStrategy: FLOW_STRATEGY_VALUES,
  flowBehavior: FLOW_BEHAVIOR_VALUES,
  degrade: DEGRADE_VALUES,
  authority: AUTHORITY_VALUES,
});
export type RuleOptionGroup = keyof typeof RULE_OPTION_VALUES;
