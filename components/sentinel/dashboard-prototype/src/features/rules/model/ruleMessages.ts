/**
 * 规则工作台消费的语言资源契约。
 *
 * 中文
 * ----
 * 旧实现把整包语言资源以 `messages: any` 传进编辑器与页面，于是
 * `messages.fields.resorceName` 这类拼写错误、缺失字段都不会被发现。
 *
 * 本模块只描述**规则 feature 真正读取的那部分形状**，并让 `ruleMessages()` 的返回
 * 值受该类型约束。语言资源本身仍是共享字典（阶段 1.3 会把整包拆成
 * `core/i18n/locales`），但从规则 feature 出去的那条边界是强类型的。
 *
 * 协议键与界面标签严格分离：`resourceName` 是本文件的键，`"资源名称"` 是它的值。
 * 任何 `label` 都不会被当作协议字段名使用。
 */
import type { RuleKind, RuleScope, RuleSourceKind } from "./ruleKinds";
import type { VersionPlanCopy } from "./ruleVersion";

/** 字段的标签与说明。 */
export interface FieldCopy {
  readonly label: string;
  readonly hint: string;
}

/**
 * 字段键的完整清单。
 *
 * 这里是元组而不是字符串字面量联合，便于用 `Record<RuleFieldKey, FieldCopy>`
 * 一次约束全部字段。
 */
export const RULE_FIELD_KEYS = [
  "resourceName",
  "callerOrigin",
  "thresholdType",
  "singleNodeThreshold",
  "controlStrategy",
  "controlBehavior",
  "relatedResource",
  "warmUpPeriod",
  "maxQueueingTime",
  "clusterMode",
  "clusterThresholdType",
  "localFallback",
  "sampleCount",
  "statisticWindow",
  "circuitStrategy",
  "circuitThreshold",
  "breakDuration",
  "minimumRequests",
  "slowCallRatio",
  "systemLoad",
  "averageRt",
  "maximumThreads",
  "entranceQps",
  "cpuUsage",
  "authorityMode",
  "originList",
  "parameterIndex",
  "statisticPeriod",
  "parameterExceptions",
  "parameterType",
  "parameterValue",
  "exceptionThreshold",
] as const;

/** 规则表单字段键。 */
export type RuleFieldKey = (typeof RULE_FIELD_KEYS)[number];

/** 全部字段的文案表。缺一个键即类型错误。 */
export type RuleFieldCopy = Readonly<Record<RuleFieldKey, FieldCopy>>;

/** 单类规则的名称与说明。 */
export interface RuleTypeCopy {
  readonly label: string;
  readonly description: string;
}

/** 各类规则文案。键与 {@link RuleKind} 一一对应。 */
export type RuleTypeCopyMap = Readonly<Record<RuleKind, RuleTypeCopy>>;

/** 枚举选项的本地化标签，顺序必须与 `ruleOptions.ts` 的协议值顺序一致。 */
export interface RuleOptionCopy {
  readonly flowGrade: readonly string[];
  readonly flowStrategy: readonly string[];
  readonly flowBehavior: readonly string[];
  readonly degrade: readonly string[];
  readonly authority: readonly string[];
}

/** 规则工作台自身的固定文案。 */
export interface RuleWorkbenchCopy {
  readonly addException: string;
  readonly remove: string;
  readonly systemDisabled: string;
  readonly paramCompatibility: string;
  /** 筛选条的标签。 */
  readonly filters: {
    readonly environment: string;
    readonly production: string;
    readonly application: string;
    readonly allApplications: string;
    readonly sample: string;
  };
  /** 生效范围标签，键是协议值。 */
  readonly scopes: Readonly<Record<RuleScope, string>>;
  /** 版本时间线面板文案。 */
  readonly versions: VersionPlanCopy;
}

/** 规则 feature 从语言包读取的完整契约。 */
export interface RuleWorkbenchMessages {
  readonly types: RuleTypeCopyMap;
  readonly fields: RuleFieldCopy;
  readonly options: RuleOptionCopy;
  readonly rules: RuleWorkbenchCopy;
}

/** 规则来源标签。用于把 {@link RuleSourceKind} 映射为展示文本。 */
export type RuleSourceLabel = Readonly<Record<RuleSourceKind, string>>;
