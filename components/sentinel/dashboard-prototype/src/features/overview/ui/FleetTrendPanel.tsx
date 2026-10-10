import { useTranslation } from "react-i18next";
import { Panel } from "../../../shared/ui/Panel";
import { TrendChart as Trend } from "../../../shared/ui/charts/TrendChart";
import presentationStyles from "../../../shared/ui/styles/Presentation.module.scss";
import { scopedClasses } from "../../../shared/ui/styles/scopedClasses";
import type { FleetTrendPoints } from "../model/overview";
import overviewStyles from "./Overview.module.scss";

const styleModules = [presentationStyles, overviewStyles] as const;

/** Trend presentation must not infer release comparisons from the selected time range. */
export interface FleetTrendPanelProps {
  /** Read-only samples for the currently selected window. */
  readonly trend: FleetTrendPoints;
}

/** Render separate charts because QPS and block rate have different units. */
export function FleetTrendPanel({ trend }: FleetTrendPanelProps) {
  const { t } = useTranslation();
  return (
    <Panel
      title={t("overview.trend.title")}
      subtitle={t("overview.trend.sharedWindow")}
      action={
        <span className={scopedClasses(styleModules, "muted")}>{t("overview.trend.tpsNote")}</span>
      }
      className={scopedClasses(styleModules, "overview-trends")}
    >
      <div className={scopedClasses(styleModules, "trend-block")}>
        <div className={scopedClasses(styleModules, "trend-title")}>
          <h3>{t("overview.trend.qpsTitle")}</h3>
          <span>{t("overview.trend.selectedWindow")}</span>
        </div>
        <Trend data={trend} metric="qps" height={139} />
      </div>
      <div className={scopedClasses(styleModules, "trend-block")}>
        <div className={scopedClasses(styleModules, "trend-title")}>
          <h3>{t("overview.trend.blockedTitle")}</h3>
          <span>{t("overview.trend.selectedWindow")}</span>
        </div>
        <Trend data={trend} metric="blocked" color="danger" unit="%" height={139} />
      </div>
    </Panel>
  );
}
