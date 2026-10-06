/** Sentinel rule value objects and validation helpers used by the rules feature. */
export type RuleDraft = Record<string, any> & { clusterConfig?: Record<string, any>; paramFlowItemList?: Array<Record<string, any>> };
export type RuleOption = { value: number; label: string };
export const SentinelCode = Object.freeze({
  FLOW_GRADE_THREAD: 0,
  FLOW_GRADE_QPS: 1,
  FLOW_STRATEGY_DIRECT: 0,
  FLOW_STRATEGY_RELATE: 1,
  FLOW_STRATEGY_CHAIN: 2,
  FLOW_BEHAVIOR_REJECT: 0,
  FLOW_BEHAVIOR_WARM_UP: 1,
  FLOW_BEHAVIOR_QUEUEING: 2,
  DEGRADE_SLOW_REQUEST_RATIO: 0,
  DEGRADE_ERROR_RATIO: 1,
  DEGRADE_ERROR_COUNT: 2,
  AUTHORITY_WHITE: 0,
  AUTHORITY_BLACK: 1,
  DISABLED_SYSTEM_THRESHOLD: -1,
});

export const RULE_TYPE_META = Object.freeze({
  flow: {
    className: "FlowRule",
    configName: "flow-rules",
  },
  degrade: {
    className: "DegradeRule",
    configName: "degrade-rules",
  },
  system: {
    className: "SystemRule",
    configName: "system-rules",
  },
  authority: {
    className: "AuthorityRule",
    configName: "authority-rules",
  },
  param: {
    className: "ParamFlowRule",
    configName: "param-flow-rules",
  },
});

export const FLOW_GRADE_OPTIONS = Object.freeze([
  { value: SentinelCode.FLOW_GRADE_QPS, label: "QPS" },
  { value: SentinelCode.FLOW_GRADE_THREAD, label: "并发线程数" },
]);
export const FLOW_STRATEGY_OPTIONS = Object.freeze([
  { value: SentinelCode.FLOW_STRATEGY_DIRECT, label: "直接" },
  { value: SentinelCode.FLOW_STRATEGY_CHAIN, label: "链路" },
  { value: SentinelCode.FLOW_STRATEGY_RELATE, label: "关联" },
]);
export const FLOW_BEHAVIOR_OPTIONS = Object.freeze([
  { value: SentinelCode.FLOW_BEHAVIOR_REJECT, label: "直接拒绝" },
  { value: SentinelCode.FLOW_BEHAVIOR_WARM_UP, label: "慢启动" },
  { value: SentinelCode.FLOW_BEHAVIOR_QUEUEING, label: "排队等待" },
]);
export const DEGRADE_OPTIONS = Object.freeze([
  { value: SentinelCode.DEGRADE_SLOW_REQUEST_RATIO, label: "慢调用比例" },
  { value: SentinelCode.DEGRADE_ERROR_RATIO, label: "异常比例" },
  { value: SentinelCode.DEGRADE_ERROR_COUNT, label: "异常数" },
]);
export const AUTHORITY_OPTIONS = Object.freeze([
  { value: SentinelCode.AUTHORITY_WHITE, label: "白名单" },
  { value: SentinelCode.AUTHORITY_BLACK, label: "黑名单" },
]);
export const DEFAULT_CLUSTER_CONFIG = Object.freeze({
  thresholdType: 0,
  fallbackToLocalWhenFail: true,
  sampleCount: 10,
  windowIntervalMs: 1000,
});

export function cloneRule<T>(rule: T): T {
  return JSON.parse(JSON.stringify(rule)) as T;
}

/** Localizes numeric enum options without exposing wire values to the UI. */
export function localizedOptions(options: ReadonlyArray<RuleOption>, labels: readonly string[]) {
  return options.map((option, index) => ({ ...option, label: labels[index] }));
}

/** Validates the minimum safe fields before a rule draft can be published. */
export function validationErrors(ruleType: string, rule: RuleDraft, t: (path: string) => string) {
  const errors: string[] = [];
  if (ruleType !== "system" && !String(rule.resource ?? "").trim()) errors.push(t("rules.errors.resourceRequired"));
  if (["flow", "param"].includes(ruleType) && !(Number(rule.count) > 0)) errors.push(t("rules.errors.countPositive"));
  if (ruleType === "flow" && rule.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT && !String(rule.refResource ?? "").trim()) errors.push(t("rules.errors.referenceRequired"));
  if (ruleType === "degrade") {
    if (!(Number(rule.count) > 0) || !(Number(rule.timeWindow) > 0)) errors.push(t("rules.errors.degradePositive"));
    if (rule.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO && (!(Number(rule.slowRatioThreshold) > 0) || Number(rule.slowRatioThreshold) > 1)) errors.push(t("rules.errors.slowRatio"));
  }
  if (ruleType === "param" && (!Number.isInteger(Number(rule.paramIdx)) || Number(rule.paramIdx) < 0)) errors.push(t("rules.errors.parameterIndex"));
  if (ruleType === "authority" && !String(rule.limitApp ?? "").trim()) errors.push(t("rules.errors.originsRequired"));
  if (ruleType === "system" && ["highestSystemLoad", "avgRt", "maxThread", "qps", "highestCpuUsage"].every((field) => Number(rule[field]) === SentinelCode.DISABLED_SYSTEM_THRESHOLD)) errors.push(t("rules.errors.systemEnabled"));
  return errors;
}
