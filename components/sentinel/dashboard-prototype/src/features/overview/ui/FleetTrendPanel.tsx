/**
 * 全局流量与防护趋势：QPS 与拦截率两张同轴时间图。
 *
 * 中文
 * ----
 * 两张图**必须分图**，不能共用一套无单位刻度（`DASHBOARD_CONTROL_PLANE.md` §3.2）：
 * QPS 单位是次/秒，拦截率是百分比，同一 y 轴会读出错误的量级。
 *
 * 三条产品硬约束落在结构里而不是注释里：
 *
 * 1. 「TPS 暂无接入」由 `TPS_INTEGRATION.note` 提供。它**不是**「TPS 为 0」，
 *    也不允许由 HTTP QPS 推算。
 * 2. 15 分钟窗口内没有可对比的发布前后样本，因此只显示示例窗口，不画发布标注
 *    （窗口外的发布时点不画标记）。
 * 3. 「发布前 / 发布后」两个数字是**示例标注**，来自演示窗口的事实；生产实现由
 *    `FleetTrendSeries.annotations` 按发布事件提供，不在渲染层现算环比。
 */
import { Panel } from "../../../shared/ui/Panel";
import { TrendChart as Trend } from "../../../shared/ui/charts/TrendChart";
import { TIME_RANGE, TIME_RANGE_LABEL_KEY } from "../../../app/router/route.constants";
import { useTranslation } from "react-i18next";
import {
  isShortWindow,
  TREND_SUBTITLE_KEYS,
  type FleetTrendPoints,
  type FleetTrendWindow,
} from "../model/overview";

export interface FleetTrendPanelProps {
  /** 当前窗口的只读点列。 */
  readonly trend: FleetTrendPoints;
  readonly window: FleetTrendWindow;
}

export function FleetTrendPanel({ trend, window }: FleetTrendPanelProps) {
  const { t } = useTranslation();
  const shortWindow = isShortWindow(window);
  return (
    <Panel
      title={t("overview.trend.title")}
      subtitle={
        shortWindow
          ? t(TREND_SUBTITLE_KEYS.windowExcludesRelease, {
              longer: t(TIME_RANGE_LABEL_KEY[TIME_RANGE.Last1Hour]),
            })
          : t(TREND_SUBTITLE_KEYS.sharedWindow)
      }
      action={<span className="muted">{t("overview.trend.tpsNote")}</span>}
      className="overview-trends"
    >
      <div className="trend-block">
        <div className="trend-title">
          <h3>{t("overview.trend.qpsTitle")}</h3>
          {shortWindow ? (
            <span>{t("overview.trend.sampleWindow")}</span>
          ) : (
            <span>
              {t("overview.trend.beforeRelease")} <b>24.1K</b> →{" "}
              {t("overview.trend.afterRelease")} <b>17.6K</b>{" "}
              <em className="green">↓ 27%</em>
            </span>
          )}
        </div>
        <Trend data={trend} metric="qps" height={139} />
      </div>
      <div className="trend-block">
        <div className="trend-title">
          <h3>{t("overview.trend.blockedTitle")}</h3>
          {shortWindow ? (
            <span>{t("overview.trend.sampleWindow")}</span>
          ) : (
            <span>
              {t("overview.trend.beforeRelease")} <b>1.8%</b> →{" "}
              {t("overview.trend.afterRelease")} <b>8.6%</b>{" "}
              <em className="red">↑ 6.8%</em>
            </span>
          )}
        </div>
        <Trend
          data={trend}
          metric="blocked"
          color="danger"
          unit="%"
          height={139}
        />
      </div>
    </Panel>
  );
}
