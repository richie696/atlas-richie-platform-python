/**
 * 故障分析的事件值对象与协议常量。
 *
 * 中文
 * ----
 * 本文件只放**领域值**：事件结构、严重级别、事件类别，以及「`HH:mm:ss` 如何变成可以
 * 比较的时间」。不依赖 React、语言包与网络。
 *
 * 旧实现里 `severity` 是裸字符串、`kind` 直接存中文（"资源压力" / "规则发布"），于是
 * 「统计规则变更条数」这件事是在拿界面文案做判断：
 * `scopeEvents.filter((item) => item.kind === "规则发布")`。文案一改，统计就悄悄变错，
 * 而且没有任何测试会发现。这里把类别提升为协议值，中文只作为它的标签存在。
 *
 * 关联关系是**示例**：事件证据里的相关指标与发布时点都不构成因果断言
 * （`DASHBOARD_CONTROL_PLANE.md` §4 故障分析行：时间相关不直接断言因果）。
 */

/** 事件严重级别。 */
export const INCIDENT_SEVERITY = Object.freeze({
  Critical: "critical",
  Warning: "warning",
  Info: "info",
} as const);

/** {@link INCIDENT_SEVERITY} 的值联合。 */
export type IncidentSeverity = (typeof INCIDENT_SEVERITY)[keyof typeof INCIDENT_SEVERITY];

/**
 * 严重级别的展示文案**键**。
 *
 * 中文
 * ----
 * 协议值与文案分开维护。原先这里存的是中文字面量（"严重" / "警告" / "信息"），
 * 而 `i18n/locales.ts` 里又有一份 `faults.severity.*` 三语键——同一个概念两份
 * 定义，改一处不会提示另一处已经对不上。收敛成键，译文只存在于语言包。
 */
export const SEVERITY_LABEL_KEY: Readonly<Record<IncidentSeverity, string>> = Object.freeze({
  [INCIDENT_SEVERITY.Critical]: "faults.severity.critical",
  [INCIDENT_SEVERITY.Warning]: "faults.severity.warning",
  [INCIDENT_SEVERITY.Info]: "faults.severity.info",
});

/** 级别筛选的「全部」哨兵值。协议值，不是文案。 */
export const SEVERITY_FILTER_ALL = "all";

/** 级别筛选的可选值。 */
export type SeverityFilter = IncidentSeverity | typeof SEVERITY_FILTER_ALL;

/** 级别筛选下拉的可选值，顺序即渲染顺序。 */
export const SEVERITY_FILTER_ORDER: readonly SeverityFilter[] = Object.freeze([
  SEVERITY_FILTER_ALL,
  INCIDENT_SEVERITY.Critical,
  INCIDENT_SEVERITY.Warning,
  INCIDENT_SEVERITY.Info,
]);

/** 级别筛选项的展示文案键。 */
export const SEVERITY_FILTER_LABEL_KEY: Readonly<Record<SeverityFilter, string>> = Object.freeze({
  [SEVERITY_FILTER_ALL]: "faults.severity.all",
  ...SEVERITY_LABEL_KEY,
});

/**
 * 事件类别。
 *
 * 中文
 * ----
 * `REWRITE_PLAN.md` §4.5 列了 resource / rt / ruleChange 三类。这里把「规则发布」与
 * 「规则生效」保留为两个类别：配置中心写入成功与实例已生效是**两个事实**，合并成
 * 一个类别会让事件列表把「已发布」说成「已生效」，正是 §4.1 明确禁止的状态合并。
 */
export const INCIDENT_CATEGORY = Object.freeze({
  /** 资源压力。 */
  Resource: "resource",
  /** 响应时间。 */
  ResponseTime: "rt",
  /** 规则已发布到配置中心。 */
  RulePublished: "rulePublished",
  /** 规则已被实例应用（含版本漂移）。 */
  RuleEffective: "ruleEffective",
} as const);

/** {@link INCIDENT_CATEGORY} 的值联合。 */
export type IncidentCategory = (typeof INCIDENT_CATEGORY)[keyof typeof INCIDENT_CATEGORY];

/** 事件类别的展示文案键。 */
export const CATEGORY_LABEL_KEY: Readonly<Record<IncidentCategory, string>> = Object.freeze({
  [INCIDENT_CATEGORY.Resource]: "faults.category.resource",
  [INCIDENT_CATEGORY.ResponseTime]: "faults.category.responseTime",
  [INCIDENT_CATEGORY.RulePublished]: "faults.category.rulePublished",
  [INCIDENT_CATEGORY.RuleEffective]: "faults.category.ruleEffective",
});

/** 无关联实例时的占位值。配置面事件（例如发布）不属于任何单个实例。 */
export const NO_INSTANCE = "—";

/**
 * 一条事件。
 *
 * 中文
 * ----
 * 对应 `REWRITE_PLAN.md` §4.5 的 `IncidentEvent`。两处与目标契约的差异是**已知且必须
 * 显式**的，不能悄悄当成已满足：
 *
 * - `date` + `at` 是本地时钟的展示值，不是含时区的时间戳。接入 Agent Reporting 后
 *   `at` 应为带时区的时间戳，比较与格式化都在数据层完成。
 * - `observedFact` / `suggestedAction` 是单值。§4.5 的目标形态是
 *   `observedFacts[]` / `suggestedActions[]`；示例事件各只有一条事实与一条建议，
 *   因此当前按单值渲染。接入真实事件后改为数组渲染——那会是一次**有意的** DOM 变更。
 */
export interface IncidentEvent {
  readonly id: string;
  /** 发生日期，`YYYY-MM-DD`。 */
  readonly date: string;
  /** 一天内的时刻，`HH:mm:ss`。 */
  readonly at: string;
  readonly severity: IncidentSeverity;
  readonly category: IncidentCategory;
  readonly appId: string;
  /** 关联实例；配置面事件用 {@link NO_INSTANCE}。 */
  readonly instanceId: string;
  readonly title: string;
  /** 观测到的事实。描述事实，不解释原因。 */
  readonly observedFact: string;
  /** 建议的下一步。不会自动更改规则或执行动作。 */
  readonly suggestedAction: string;
}

/**
 * 15 分钟窗口的起点。
 *
 * 中文
 * ----
 * 示例时间轴固定在 14:32，15 分钟窗口即 14:17 之后。旧实现把这个值内联在页面的过滤
 * 条件里（`item.at >= "14:17:00"`），谁都不知道它代表什么。接入 Console API 后窗口由
 * 后端按 `TIME_RANGE_MS` 决定，前端不再自带起点。
 */
export const LAST_15M_WINDOW_START = "14:17:00";

/**
 * 把 `HH:mm:ss` 解析为当天已过秒数。
 *
 * 中文
 * ----
 * 旧实现用字符串比较做时间过滤（`item.at >= "14:17:00"`），依赖 `HH:mm:ss` 的字典序
 * 恰好等于时间序：一旦时刻带日期、毫秒或不补零（例如 `"9:05:00"`），比较结果就是错的
 * 且没有任何提示。这里改为真正的数值比较。
 *
 * 格式非法时返回 `null` 而不是 0：调用方据此判定「时间未知」并把事件排除在窗口外，
 * 不能当成零点——那会让所有合法事件都被算进窗口。
 *
 * 已知边界：跨零点的窗口（事件日期不同）需要绝对时间戳才能正确处理。示例事件同属
 * 一天，因此不受影响；接入真实事件时由 `at` 携带时区时间戳解决。
 */
export function secondsOfDay(at: string): number | null {
  const matched = /^(\d{2}):(\d{2}):(\d{2})$/.exec(at);
  if (!matched) return null;
  return Number(matched[1]) * 3600 + Number(matched[2]) * 60 + Number(matched[3]);
}
