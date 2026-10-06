/**
 * 规则下拉选项的协议值与本地化标签配对。
 *
 * 中文
 * ----
 * 这里只放**协议值**。标签来自语言包 `options.*`，按下标与协议值配对，因此
 * 两边的数组顺序必须一致；`localizedOptions` 会在长度不匹配时抛错，而不是静默
 * 产生 `undefined` 标签。
 */
import type { RuleOptionCopy } from "./ruleMessages";
import { SentinelCode } from "./ruleKinds";

/** 一个下拉选项：协议值 + 展示标签。 */
export interface RuleOption {
  readonly value: number;
  readonly label: string;
}

const options = (...values: readonly number[]): readonly { value: number; label: "" }[] =>
  values.map((value) => ({ value, label: "" }));

/** FlowRule 阈值类型。 */
export const FLOW_GRADE_VALUES = options(
  SentinelCode.FLOW_GRADE_QPS,
  SentinelCode.FLOW_GRADE_THREAD,
);

/** FlowRule 流控模式。 */
export const FLOW_STRATEGY_VALUES = options(
  SentinelCode.FLOW_STRATEGY_DIRECT,
  SentinelCode.FLOW_STRATEGY_CHAIN,
  SentinelCode.FLOW_STRATEGY_RELATE,
);

/** FlowRule 流控效果。 */
export const FLOW_BEHAVIOR_VALUES = options(
  SentinelCode.FLOW_BEHAVIOR_REJECT,
  SentinelCode.FLOW_BEHAVIOR_WARM_UP,
  SentinelCode.FLOW_BEHAVIOR_QUEUEING,
);

/** DegradeRule 熔断策略。 */
export const DEGRADE_VALUES = options(
  SentinelCode.DEGRADE_SLOW_REQUEST_RATIO,
  SentinelCode.DEGRADE_ERROR_RATIO,
  SentinelCode.DEGRADE_ERROR_COUNT,
);

/** AuthorityRule 访问控制模式。 */
export const AUTHORITY_VALUES = options(
  SentinelCode.AUTHORITY_WHITE,
  SentinelCode.AUTHORITY_BLACK,
);

/** 某个枚举对应的标签数组键。 */
type OptionGroup = keyof RuleOptionCopy;

const GROUPS: Readonly<Record<OptionGroup, readonly { value: number; label: "" }[]>> = {
  flowGrade: FLOW_GRADE_VALUES,
  flowStrategy: FLOW_STRATEGY_VALUES,
  flowBehavior: FLOW_BEHAVIOR_VALUES,
  degrade: DEGRADE_VALUES,
  authority: AUTHORITY_VALUES,
};

/**
 * 用语言包标签填充一组协议值。
 *
 * 标签数量与协议值数量不一致是语言资源的缺陷，必须立刻暴露：界面上出现
 * `undefined` 标签会让用户无法判断当前选中项代表什么配置。
 *
 * 抛出的 `Error` 是**开发者诊断**而不是界面文案——它只在语言包与协议值写错时触发，
 * 此时组件树已经无法正常渲染，不会出现在页面上。因此这里用英文并带 `[rules]`
 * 前缀，让它与代码里其它不变量消息一致，也不占用 `rules.*` 文案键。
 */
export function localizedOptions(
  group: OptionGroup,
  copy: RuleOptionCopy,
): readonly RuleOption[] {
  const values = GROUPS[group];
  const labels = copy[group];
  if (values.length !== labels.length) {
    throw new Error(
      `[rules] localizedOptions("${group}"): ${values.length} protocol values but ${labels.length} labels`,
    );
  }
  return values.map((item, index) => ({ value: item.value, label: labels[index] }));
}
