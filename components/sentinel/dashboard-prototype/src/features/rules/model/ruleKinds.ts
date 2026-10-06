/**
 * Sentinel 规则类型标识与协议常量。
 *
 * 中文
 * ----
 * 这里只放**协议层固定值**：Sentinel 兼容的编码、规则类别、以及每类规则在配置中心里的
 * 内容形态。展示文案、字段标签和选项名称都在 `features/rules/i18n` 与
 * `ruleOptions.ts`，不写进协议常量。
 *
 * `SentinelCode` 的数值直接决定写回 Nacos / Consul 的 JSON 内容，因此任何改动都会
 * 改变线上规则语义，不能为了「更易读」调整。
 */

/** 五类 Sentinel 兼容规则。值即配置中心的规则类型标识。 */
export const RULE_KIND = Object.freeze({
  Flow: "flow",
  Degrade: "degrade",
  System: "system",
  Authority: "authority",
  ParamFlow: "param",
} as const);

/** {@link RULE_KIND} 的值联合。 */
export type RuleKind = (typeof RULE_KIND)[keyof typeof RULE_KIND];

/** 全部规则类型，保持与语言包 `types` 键一一对应。 */
export const RULE_KINDS: readonly RuleKind[] = Object.freeze([
  RULE_KIND.Flow,
  RULE_KIND.Degrade,
  RULE_KIND.System,
  RULE_KIND.Authority,
  RULE_KIND.ParamFlow,
]);

/**
 * Sentinel 兼容编码。
 *
 * 数值来源见 `DASHBOARD_CONTROL_PLANE.md` §4.3。这些是线上协议值，不是界面枚举。
 */
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

/** SystemRule 未启用阈值的序列化值。 */
export const DISABLED_SYSTEM_THRESHOLD = SentinelCode.DISABLED_SYSTEM_THRESHOLD;

/** 单类规则的配置中心形态元数据。 */
export interface RuleTypeMeta {
  /** Sentinel 兼容类名，写在只读 JSON 预览里。 */
  readonly className: string;
  /** 配置中心内容名，例如 Nacos 的 dataId 后缀。 */
  readonly configName: string;
}

export const RULE_TYPE_META: Readonly<Record<RuleKind, RuleTypeMeta>> = Object.freeze({
  [RULE_KIND.Flow]: { className: "FlowRule", configName: "flow-rules" },
  [RULE_KIND.Degrade]: { className: "DegradeRule", configName: "degrade-rules" },
  [RULE_KIND.System]: { className: "SystemRule", configName: "system-rules" },
  [RULE_KIND.Authority]: { className: "AuthorityRule", configName: "authority-rules" },
  [RULE_KIND.ParamFlow]: { className: "ParamFlowRule", configName: "param-flow-rules" },
});

/**
 * 规则生效范围。值是协议值，标签由语言包 `rules.scopes.*` 提供。
 *
 * 值是**协议标识**而不是展示文案，因此用 ASCII 标识符：它们会随目录条目进入读模型，
 * 界面文字一律来自语言包。早年这里写的是「应用 / 资源」，于是同一份协议值既是
 * 中文又是数据来源；改成标识符后展示不受影响（`RuleInspectorPanel` 取的是
 * `scopes[entry.scope]`，即语言包的值）。
 */
export const RULE_SCOPE = Object.freeze({
  Application: "application",
  Resource: "resource",
} as const);

/** {@link RULE_SCOPE} 的值联合。 */
export type RuleScope = (typeof RULE_SCOPE)[keyof typeof RULE_SCOPE];

/** 规则来源配置中心。 */
export const RULE_SOURCE = Object.freeze({
  Nacos: "Nacos",
  Consul: "Consul",
} as const);

/** {@link RULE_SOURCE} 的值联合。 */
export type RuleSourceKind = (typeof RULE_SOURCE)[keyof typeof RULE_SOURCE];

/**
 * 配置中心类型筛选的「不限」哨兵值。
 *
 * 它是协议值而不是展示文案；语言包提供对应标签。
 */
export const RULE_KIND_ALL = "all";

/** 规则类型筛选的可选值。 */
export type RuleKindFilter = RuleKind | typeof RULE_KIND_ALL;

/**
 * 把 URL 的 `view` 参数解析成规则类型筛选。
 *
 * 中文
 * ----
 * 与 `resolveSystemTab` 同一模式：合法值集合属于本 feature，所以在 feature 侧校验。
 * 非法或缺失一律回落到「全部类型」，不「就近猜一个」——猜错会让用户以为自己在看
 * 某个类型的规则，实际看到的是全量。
 */
export function resolveRuleKindFilter(value: string | undefined): RuleKindFilter {
  const candidate = value ?? "";
  if (candidate === RULE_KIND_ALL) return RULE_KIND_ALL;
  return (RULE_KINDS as readonly string[]).includes(candidate)
    ? (candidate as RuleKind)
    : RULE_KIND_ALL;
}
