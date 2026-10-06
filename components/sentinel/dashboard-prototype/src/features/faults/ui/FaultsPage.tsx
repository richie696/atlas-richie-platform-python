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
import { Filters } from "../../../shared/ui/Filters";
import { Intro } from "../../../shared/ui/Intro";
import { NumberCard } from "../../../shared/ui/NumberCard";
import { Status } from "../../../shared/ui/Status";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { useTranslator } from "../../../core/i18n/useTranslator";
import { INCIDENT_FIXTURES, FAULTS_APP_FIXTURES } from "../fixtures/faultsFixtures";
import { useIncidentTimeline } from "../state/useIncidentTimeline";
import { IncidentEvidence } from "./IncidentEvidence";
import { IncidentTimeline } from "./IncidentTimeline";

/** Incident timeline and evidence panel for operational diagnosis. */
export function FaultsPage({ navigate, appId, setAppId, range, setRange, locale }: DashboardPageProps) {
  const t = useTranslator();
  const timeline = useIncidentTimeline(INCIDENT_FIXTURES, appId, range);
  return (
    <>
      <Intro
        eyebrow={t("faults.intro.eyebrow")}
        title={t("faults.intro.title")}
        description={t("faults.intro.description")}
        aside={<Status tone="critical">{timeline.counts.critical} 个严重事件</Status>}
      />
      <Filters
        appId={appId}
        setAppId={setAppId}
        range={range}
        setRange={setRange}
        all
        locale={locale}
        applications={FAULTS_APP_FIXTURES}
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
