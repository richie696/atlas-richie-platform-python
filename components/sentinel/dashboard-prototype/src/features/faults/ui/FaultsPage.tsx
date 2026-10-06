/**
 * 故障分析页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：取 feature 状态、组合区域、把用户动作映射为命令或导航。
 * 事件筛选与计数在 `useIncidentTimeline`，判定规则在 `model/incidentPolicy`，时间线与
 * 证据各自是私有展示组件。
 *
 * 事件数据当前来自 `fixtures/`。接入 Console API 后由 `faults.gateway` 依据 Agent
 * Reporting 事件流 + 控制面发布审计提供，本组件的调用形态不变。
 *
 * 产品硬要求：事件之间的关联是**示例**。页面不提供自动根因断言，建议动作也不会自动
 * 更改规则（`DASHBOARD_CONTROL_PLANE.md` §4 故障分析行）。
 */
import { ROUTE } from "../../../app/router/route.constants";
import { fixtureGateway } from "../../../core/api/fixtureGateway";
import { Filters } from "../../../shared/ui/Filters";
import { Intro } from "../../../shared/ui/Intro";
import { NumberCard } from "../../../shared/ui/NumberCard";
import { Status } from "../../../shared/ui/Status";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { useTranslation } from "react-i18next";
import { useIncidentTimeline } from "../state/useIncidentTimeline";
import { IncidentEvidence } from "./IncidentEvidence";
import { IncidentTimeline } from "./IncidentTimeline";

/** Incident timeline and evidence panel for operational diagnosis. */
export function FaultsPage({ navigate, appId, setAppId, range, setRange, locale }: DashboardPageProps) {
  const { t } = useTranslation();
  // 数据从 gateway 取，页面不感知来源。
  const { incidents, applications: faultApps } = fixtureGateway.readFaultsSync();
  const timeline = useIncidentTimeline(incidents, appId, range);
  return (
    <>
      <Intro
        eyebrow={t("faults.intro.eyebrow")}
        title={t("faults.intro.title")}
        description={t("faults.intro.description")}
        // 刻意写成「数字 + 空格 + 译文」三个子节点，而不是把整句交给一次插值：
        // Astryx 的 `Badge` 只在 `label` 是**单个非空字符串**时才渲染 `title`
        // 属性（见 @astryxdesign/core Badge.js 的 `labelTitle`），用于标签被截断时
        // 让全文仍可达。合成一个字符串会让 Status 突然多出一个 tooltip，
        // 那是展示行为变化，不是文案迁移。
        aside={
          <Status tone="critical">
            {timeline.counts.critical} {t("faults.summary.criticalUnit")}
          </Status>
        }
      />
      <Filters
        appId={appId}
        setAppId={setAppId}
        range={range}
        setRange={setRange}
        all
        applications={faultApps}
      />
      <div className="number-grid">
        <NumberCard
          label={t("faults.summary.critical")}
          value={timeline.counts.critical}
          note={t("faults.summary.criticalNote")}
          tone="red"
        />
        <NumberCard
          label={t("faults.summary.warning")}
          value={timeline.counts.warning}
          note={t("faults.summary.warningNote")}
          tone="amber"
        />
        <NumberCard label={t("faults.summary.ruleChange")} value={timeline.counts.ruleChanges} note={t("faults.summary.affectedAppsNote")} />
        <NumberCard label={t("faults.summary.affectedApps")} value={timeline.counts.affectedApps} note={t("faults.summary.affectedAppsNote")} />
      </div>
      <div className="fault-layout">
        <IncidentTimeline
          events={timeline.visible}
          selectedId={timeline.selected?.id ?? ""}
          severity={timeline.severity}
          onSeverityChange={timeline.setSeverity}
          onSelect={timeline.select}
        />
        <IncidentEvidence
          event={timeline.selected}
          onOpenApplication={(target) => navigate(ROUTE.Applications, { appId: target })}
        />
      </div>
    </>
  );
}
