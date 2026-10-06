/**
 * 故障分析的事件时间线状态。
 *
 * 中文
 * ----
 * 旧实现在 `FaultsPage` 组件体内用两个 `useState` 加上五段内联过滤/计数表达式完成
 * 全部逻辑：级别筛选、选中项、作用域事件、四个计数。页面组件因此既管数据推导又管
 * 渲染，而这些推导**只能靠渲染页面来验证**。
 *
 * 本 Hook 拥有两件事，判定规则全部委托给 `model/incidentPolicy`：
 *
 * - **级别筛选**是用户当前的视角。
 * - **作用域**（应用 + 时间窗口）来自路由筛选状态；摘要卡计数基于**未按级别过滤**的
 *   作用域事件，回答「这个窗口里发生了什么」，而不是「我现在正在看哪一类」。
 *
 * 选中项在列表变化后不自动改写状态：失效的选中由 `resolveSelection` 回落到列表第一条
 * 并由界面显示，避免出现「界面显示 A、状态记着 B」。
 */
import { useMemo, useState } from "react";

import type { TimeRangeId } from "../../../app/router/route.constants";
import {
  SEVERITY_FILTER_ALL,
  type IncidentEvent,
  type SeverityFilter,
} from "../model/incident";
import {
  countIncidents,
  filterBySeverity,
  resolveSelection,
  scopeIncidents,
  type IncidentCounts,
} from "../model/incidentPolicy";

/** 时间线可以取用的全部状态与命令。 */
export interface IncidentTimelineState {
  readonly severity: SeverityFilter;
  readonly setSeverity: (severity: SeverityFilter) => void;
  /** 当前作用域（应用 + 时间窗口）内的事件，未按级别过滤。 */
  readonly scoped: readonly IncidentEvent[];
  /** 作用域 + 级别过滤后应展示的事件。 */
  readonly visible: readonly IncidentEvent[];
  readonly selected: IncidentEvent | null;
  readonly counts: IncidentCounts;
  readonly select: (id: string) => void;
}

export function useIncidentTimeline(
  events: readonly IncidentEvent[],
  appId: string,
  range: TimeRangeId,
): IncidentTimelineState {
  const [severity, setSeverity] = useState<SeverityFilter>(SEVERITY_FILTER_ALL);
  const [selectedId, setSelectedId] = useState(() => events[0]?.id ?? "");

  const scoped = useMemo(() => scopeIncidents(events, { appId, range }), [events, appId, range]);
  const visible = useMemo(() => filterBySeverity(scoped, severity), [scoped, severity]);
  const selected = useMemo(() => resolveSelection(visible, selectedId), [visible, selectedId]);
  const counts = useMemo(() => countIncidents(scoped), [scoped]);

  return { severity, setSeverity, scoped, visible, selected, counts, select: setSelectedId };
}
