/**
 * 规则草稿的领域类型。
 *
 * 中文
 * ----
 * 五类规则各自有确定的字段集，因此用**判别联合**而不是 `Record<string, any>`：
 * 原来一个 `any` 索引让所有字段访问都失去检查，`rule.grade` 拼错也不会报错，
 * 而这些字段会原样写回配置中心。
 *
 * 草稿允许出现 `""`（表单清空态）。序列化时 `""` 会作为该协议字段的值写进 JSON，
 * 与旧实现一致；Sentinel 语义上的「未启用」只用于 SystemRule，用
 * {@link DISABLED_SYSTEM_THRESHOLD} 表示。
 */
import { RULE_KIND, type RuleKind } from "./ruleKinds";

/** 集群流控的附加配置。仅 FlowRule 在 `clusterMode` 为真时存在。 */
export interface ClusterConfigDraft {
  readonly thresholdType: number;
  readonly fallbackToLocalWhenFail: boolean;
  readonly sampleCount: number;
  readonly windowIntervalMs: number;
}

/** FlowRule 草稿。 */
export interface FlowRuleDraft {
  resource: string;
  limitApp: string;
  grade: number;
  count: number | string;
  strategy: number;
  controlBehavior: number;
  clusterMode: boolean;
  /** 非直接策略必填。 */
  refResource?: string;
  /** 慢启动时显示。 */
  warmUpPeriodSec?: number | string;
  /** 排队等待时显示。 */
  maxQueueingTimeMs?: number | string;
  clusterConfig?: ClusterConfigDraft;
}

/** DegradeRule 草稿。 */
export interface DegradeRuleDraft {
  resource: string;
  grade: number;
  count: number | string;
  timeWindow: number | string;
  minRequestAmount: number | string;
  statIntervalMs: number | string;
  /** 慢调用比例策略必填，取值区间 (0, 1]。 */
  slowRatioThreshold?: number | string;
}

/**
 * SystemRule 草稿。
 *
 * 该类型没有 resource；未启用的阈值用 {@link DISABLED_SYSTEM_THRESHOLD}（-1）。
 * `highestCpuUsage` 取值区间 0..1，不是百分数。
 */
export interface SystemRuleDraft {
  highestSystemLoad: number | string;
  avgRt: number | string;
  maxThread: number | string;
  qps: number | string;
  highestCpuUsage: number | string;
}

/** AuthorityRule 草稿。`limitApp` 是英文逗号分隔的 origin 列表。 */
export interface AuthorityRuleDraft {
  resource: string;
  limitApp: string;
  strategy: number;
}

/** ParamFlowRule 的单个例外项。`classType` / `object` 是 Sentinel Java 格式表达。 */
export interface ParamFlowItemDraft {
  classType: string;
  object: string;
  count: number | string;
}

/** ParamFlowRule 草稿。`paramIdx` 从 0 开始。 */
export interface ParamFlowRuleDraft {
  resource: string;
  grade: number;
  count: number | string;
  durationInSec: number | string;
  paramIdx: number | string;
  paramFlowItemList: ParamFlowItemDraft[];
}

/** 任一类型的规则草稿。 */
export type RuleDraft =
  | FlowRuleDraft
  | DegradeRuleDraft
  | SystemRuleDraft
  | AuthorityRuleDraft
  | ParamFlowRuleDraft;

/** 规则草稿与其类型的配对。表单组件据此拿到确定的字段类型。 */
export interface TypedRuleDraft {
  readonly kind: RuleKind;
  readonly draft: RuleDraft;
}

/** 集群流控的默认配置。与旧常量逐字一致，避免草稿初始 JSON 变化。 */
export const DEFAULT_CLUSTER_CONFIG: ClusterConfigDraft = Object.freeze({
  thresholdType: 0,
  fallbackToLocalWhenFail: true,
  sampleCount: 10,
  windowIntervalMs: 1000,
});

/**
 * 把草稿深拷贝为独立可编辑副本。
 *
 * 中文
 * ----
 * 旧实现用 `JSON.parse(JSON.stringify())`。它会静默丢弃值为 `undefined` 的键，
 * 也会把 `Date` 等非 JSON 值降级成字符串，而草稿是会被写回配置中心的结构。
 * 这里改用 `structuredClone`，保留键的存在性。
 */
export function cloneRule<T>(rule: T): T {
  return structuredClone(rule);
}

/** ParamFlowRule 的例外项列表；缺失时返回空数组而不是 `undefined`。 */
export function paramItemsOf(draft: RuleDraft): ParamFlowItemDraft[] {
  return "paramFlowItemList" in draft && Array.isArray(draft.paramFlowItemList)
    ? draft.paramFlowItemList
    : [];
}

/**
 * 规则类型到草稿形状的映射。
 *
 * 用它取代旧实现里的 `Record<string, any>`：字段访问获得真实检查，
 * 而键与 {@link RULE_KIND} 一一对应，新增规则类型时映射会立刻缺键。
 */
export interface RuleDraftMap {
  [RULE_KIND.Flow]: FlowRuleDraft;
  [RULE_KIND.Degrade]: DegradeRuleDraft;
  [RULE_KIND.System]: SystemRuleDraft;
  [RULE_KIND.Authority]: AuthorityRuleDraft;
  [RULE_KIND.ParamFlow]: ParamFlowRuleDraft;
}

/** 指定规则类型对应的草稿形状。 */
export type RuleDraftOf<K extends RuleKind> = RuleDraftMap[K];

/**
 * 把草稿收窄到它所属类型的具体字段集。
 *
 * 中文
 * ----
 * 唯一不变量由 `useRuleWorkbench` 保证：草稿永远复制自当前选中条目的 `sentinelRule`，
 * 而条目自带 `ruleType`，因此 `kind` 与草稿的字段集必然匹配。
 *
 * 这是**一处**集中的断言，而不是在每个表单里散落 `as Extract<...>`：不变量被破坏时
 * 表单会读到 undefined 字段并立刻暴露，不会静默渲染空值或 0。
 */
export function narrowDraft<K extends RuleKind>(kind: K, draft: RuleDraft): RuleDraftOf<K> {
  return draft as RuleDraftOf<K>;
}
