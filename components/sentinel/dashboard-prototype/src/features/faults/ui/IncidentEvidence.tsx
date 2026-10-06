/**
 * 事件证据面板。
 *
 * 中文
 * ----
 * 旧实现在页面里用一个大三元表达式渲染「有选中事件」与「无选中事件」两种形态。现在是
 * 组件内部的早返回：两种形态的标题不同、class 不同，但都属于这一个面板的职责。
 *
 * 组件是纯展示：**只陈述观测事实与建议下一步，不解释原因**。时间接近不等于因果关系，
 * 因此底部固定保留「关联为示例，不提供自动根因断言」。产品硬要求：建议动作不会自动
 * 更改规则，也不代替人去点确认（`DASHBOARD_CONTROL_PLANE.md` §4 故障分析行）。
 */
import { InfoIcon as Info } from "@phosphor-icons/react";

import { LinkButton } from "../../../shared/ui/LinkButton";
import { Panel } from "../../../shared/ui/Panel";
import { useTranslator } from "../../../core/i18n/useTranslator";
import { Status } from "../../../shared/ui/Status";
import { SEVERITY_LABEL, type IncidentEvent } from "../model/incident";

export interface IncidentEvidenceProps {
  /** 当前选中的事件；`null` 表示没有可展示的事件。 */
  readonly event: IncidentEvent | null;
  /** 跳到该事件所属应用与实例。 */
  readonly onOpenApplication: (appId: string) => void;
}

export function IncidentEvidence({ event, onOpenApplication }: IncidentEvidenceProps) {
  const t = useTranslator();
  if (!event) {
    return (
      <Panel title={t("faults.evidence.title")} subtitle={t("faults.evidence.emptySubtitle")}>
        <div className="empty">{t("faults.evidence.empty")}</div>
      </Panel>
    );
  }
  return (
    <Panel
      title={t("faults.evidence.title")}
      subtitle={t("faults.evidence.subtitle")}
      className="event-detail"
    >
      <Status tone={event.severity}>
        {SEVERITY_LABEL[event.severity]}
      </Status>
      <h2>{event.title}</h2>
      <div className="key-value">
        <span>{t("faults.evidence.occurredAt")}</span>
        <b>{event.date} {event.at}</b>
      </div>
      <div className="key-value">
        <span>{t("faults.evidence.affectedApp")}</span>
        <b>{event.appId}</b>
      </div>
      <div className="key-value">
        <span>{t("faults.evidence.relatedInstance")}</span>
        <b>{event.instanceId}</b>
      </div>
      <div className="divider" />
      <h3>观测事实</h3>
      <p>{event.observedFact}</p>
      <h3>建议下一步</h3>
      <p>{event.suggestedAction}</p>
      <div className="inline-note">
        <Info size={16} /> {t("faults.evidence.noCausality")}
      </div>
      <LinkButton onClick={() => onOpenApplication(event.appId)}>
        查看应用与实例
      </LinkButton>
    </Panel>
  );
}
