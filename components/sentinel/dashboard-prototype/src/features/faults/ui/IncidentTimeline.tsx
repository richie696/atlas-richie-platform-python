/**
 * 事件时间线面板。
 *
 * 中文
 * ----
 * 旧实现把时间线、级别筛选下拉和空态全部内联在页面组件里。拆出来的原因是级别筛选是
 * 这个面板自己的输入：它只负责展示筛选控件与事件列表，把用户选择抛给上层，不自己
 * 持有筛选状态。
 *
 * 组件是纯展示：不做时间比较、不做因果推断。倒序由读模型保证，本组件保持输入顺序。
 */
import { ArrowRightIcon as ArrowRight } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import { Select } from "../../../shared/ui/Select";
import { useTranslator } from "../../../core/i18n/useTranslator";
import {
  CATEGORY_LABEL,
  SEVERITY_FILTER_LABEL,
  SEVERITY_FILTER_ORDER,
  type IncidentEvent,
  type SeverityFilter,
} from "../model/incident";

export interface IncidentTimelineProps {
  /** 当前作用域 + 级别过滤后的事件，按时间倒序。 */
  readonly events: readonly IncidentEvent[];
  /** 当前选中事件的 id；为空表示没有选中。 */
  readonly selectedId: string;
  readonly severity: SeverityFilter;
  readonly onSeverityChange: (severity: SeverityFilter) => void;
  readonly onSelect: (id: string) => void;
}

export function IncidentTimeline({
  events,
  selectedId,
  severity,
  onSeverityChange,
  onSelect,
}: IncidentTimelineProps) {
  const t = useTranslator();
  return (
    <Panel
      title={t("faults.timeline.title")}
      subtitle={t("faults.timeline.subtitle")}
      action={
        <Select<SeverityFilter>
          label={t("faults.timeline.severityFilter")}
          isLabelHidden
          value={severity}
          onChange={onSeverityChange}
          options={SEVERITY_FILTER_ORDER.map((value) => ({ value, label: SEVERITY_FILTER_LABEL[value] }))}
        />
      }
    >
      <div className="events">
        {events.map((item) => (
          <ActionButton
            type="button"
            className={`event ${selectedId === item.id ? "active" : ""}`}
            key={item.id}
            onClick={() => onSelect(item.id)}
          >
            <i className={`event-dot ${item.severity}`} />
            <span>{item.at}</span>
            <div>
              <b>{item.title}</b>
              <small>
                {item.appId} · {CATEGORY_LABEL[item.category]}
              </small>
            </div>
            <ArrowRight size={16} />
          </ActionButton>
        ))}
      </div>
      {events.length === 0 && (
        <div className="empty">{t("faults.timeline.empty")}</div>
      )}
    </Panel>
  );
}
