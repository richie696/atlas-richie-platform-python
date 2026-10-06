/**
 * 故障分析的纯规则：按应用/时间窗口/级别筛选、计数与选中解析。
 *
 * 中文
 * ----
 * 本模块不依赖 React、语言包或网络，只接收数据、返回结论。
 *
 * 旧实现在 `FaultsPage` 组件体内连着算四件事：应用与时间窗口过滤、级别过滤、
 * 四张卡片的计数、以及「选中的事件被筛掉之后回落到哪一条」。这些全是**领域判断**，
 * 却只能通过渲染页面来验证；而且计数取自「未按级别过滤」的结果这件事没有任何注释，
 * 后来者很容易顺手改成用过滤后的列表——那样「切到只看信息」时严重事件数就会变成 0。
 */
import { ALL_APPLICATIONS, TIME_RANGE, type TimeRangeId } from "../../../app/router/route.constants";
import {
  INCIDENT_CATEGORY,
  INCIDENT_SEVERITY,
  LAST_15M_WINDOW_START,
  SEVERITY_FILTER_ALL,
  secondsOfDay,
  type IncidentEvent,
  type SeverityFilter,
} from "./incident";

/** 事件列表的筛选上下文。 */
export interface IncidentScope {
  readonly appId: string;
  readonly range: TimeRangeId;
}

/**
 * 按应用与时间窗口过滤事件。
 *
 * 中文
 * ----
 * 保持输入顺序：时间倒序是读模型（Agent Reporting 事件流）的责任，这里不重排，
 * 避免同一份数据在两个地方各排一次。
 *
 * 15 分钟窗口用真实时间比较（`secondsOfDay`），窗口外的旧实现是靠字符串比较判断的。
 */
export function scopeIncidents(
  events: readonly IncidentEvent[],
  scope: IncidentScope,
): readonly IncidentEvent[] {
  const windowStart = scope.range === TIME_RANGE.Last15Minutes
    ? secondsOfDay(LAST_15M_WINDOW_START)
    : null;
  return events.filter((event) => {
    if (scope.appId !== ALL_APPLICATIONS && event.appId !== scope.appId) return false;
    if (windowStart === null) return true;
    const at = secondsOfDay(event.at);
    return at !== null && at >= windowStart;
  });
}

/** 按严重级别过滤；`all` 表示不筛选。 */
export function filterBySeverity(
  events: readonly IncidentEvent[],
  filter: SeverityFilter,
): readonly IncidentEvent[] {
  return filter === SEVERITY_FILTER_ALL
    ? events
    : events.filter((event) => event.severity === filter);
}

/** 首屏四张摘要卡的计数。 */
export interface IncidentCounts {
  readonly critical: number;
  readonly warning: number;
  /** 规则发布条数：只计「已发布到配置中心」的事件。 */
  readonly ruleChanges: number;
  readonly affectedApps: number;
}

/**
 * 统计当前作用域内的事件计数。
 *
 * 中文
 * ----
 * 入参必须是**已按应用与时间窗口过滤、但未按级别过滤**的事件：级别筛选是用户当前的
 * 视角，摘要卡要回答的是「这个窗口里发生了什么」，而不是「我现在正在看哪一类」。
 *
 * 「规则变更」只计 {@link INCIDENT_CATEGORY.RulePublished}：版本漂移
 * （{@link INCIDENT_CATEGORY.RuleEffective}）是某次发布的后果，已经计入警告事件，
 * 再计一次会把一次发布算成两次变更。
 */
export function countIncidents(events: readonly IncidentEvent[]): IncidentCounts {
  const apps = new Set<string>();
  let critical = 0;
  let warning = 0;
  let ruleChanges = 0;
  for (const event of events) {
    apps.add(event.appId);
    if (event.severity === INCIDENT_SEVERITY.Critical) critical += 1;
    if (event.severity === INCIDENT_SEVERITY.Warning) warning += 1;
    if (event.category === INCIDENT_CATEGORY.RulePublished) ruleChanges += 1;
  }
  return { critical, warning, ruleChanges, affectedApps: apps.size };
}

/**
 * 解析当前应展示的事件。
 *
 * 中文
 * ----
 * 用户选中的事件被筛选条件排除后（换应用、换时间窗、换级别），回落到列表第一条；
 * 列表为空时返回 `null` 由界面显示空态。选中项失效时**不**回写成状态，避免出现
 * 「界面显示 A、状态记着 B」的不一致。
 */
export function resolveSelection(
  events: readonly IncidentEvent[],
  selectedId: string,
): IncidentEvent | null {
  return events.find((event) => event.id === selectedId) ?? events[0] ?? null;
}
