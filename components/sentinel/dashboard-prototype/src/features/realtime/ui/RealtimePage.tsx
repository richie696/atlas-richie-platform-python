/**
 * 实时监控页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：取 feature 状态、组合区域、把用户动作映射为命令或导航。
 * 播放游标在 `useRealtimeSeries`，指标元数据在 `model/realtime`，展示在三个私有组件里。
 *
 * 当前序列来自 `fixtures/` 的静态样本：页面**按 1.2 秒一步回放**，不是实时数据流。
 * 接入 Console API 后由 `requestStream` + `TimeSeriesStore` 替换（`REWRITE_PLAN.md`
 * §2.2），在那之前「示例回放」标注与底部 TPS 说明都不得去掉。
 */
import { useMemo } from "react";
import { InfoIcon as Info } from "@phosphor-icons/react";

import { ALL_APPLICATIONS, ROUTE } from "../../../app/router/route.constants";
import { useTranslation } from "react-i18next";
import { Filters } from "../../../shared/ui/Filters";
import { Intro } from "../../../shared/ui/Intro";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { Select } from "../../../shared/ui/Select";
import { Status } from "../../../shared/ui/Status";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import {
  METRIC_FILTER_LABEL_KEY,
  METRIC_FILTER_ORDER,
  type MetricFilter,
  type StreamMode,
} from "../model/realtime";
import {
  FLEET_TREND,
  REALTIME_APP_FIXTURES,
  REALTIME_SUMMARY_FIXTURES,
  seriesForRange,
} from "../fixtures/realtimeFixtures";
import { useRealtimeSeries } from "../state/useRealtimeSeries";
import { RealtimeChartGrid } from "./RealtimeChartGrid";
import { RealtimeSummaryCards } from "./RealtimeSummaryCards";
import { StreamStatusBar } from "./StreamStatusBar";

/**
 * 采样模式对应的状态标注。
 *
 * 中文
 * ----
 * 未接入实时后端时 `mode` 恒为 `Replay`，因此这一行永远显示「示例回放」。保留这张映射
 * 是为了让「模式 → 文案」只有一个所有者：接入真实流时改 `mode`，标注自动跟着变，
 * 不需要去页面里找字符串。
 */
const STREAM_MODE_LABEL_KEY: Readonly<Record<StreamMode, string>> = Object.freeze({
  live: "realtime.stream.live",
  replay: "realtime.stream.replay",
  static: "realtime.stream.static",
});

/** Synchronized telemetry charts for the selected application and time range. */
export function RealtimePage({ navigate, appId, setAppId, range, setRange }: DashboardPageProps) {
  const { t } = useTranslation();
  const trend = useMemo(() => seriesForRange(FLEET_TREND, range), [range]);
  const series = useRealtimeSeries(trend);
  return (
    <>
      <Intro
        eyebrow="LIVE / TELEMETRY"
        title={t("realtime.intro.title")}
        description={t("realtime.intro.description")}
        aside={
          <Status tone={series.paused ? "warning" : "healthy"}>
            {series.paused
              ? t("realtime.stream.paused")
              : t(STREAM_MODE_LABEL_KEY[series.status.mode])}
          </Status>
        }
      />
      <Filters
        appId={appId}
        setAppId={(id) =>
          id === ALL_APPLICATIONS ? setAppId(id) : navigate(ROUTE.Applications, { appId: id })
        }
        range={range}
        setRange={setRange}
        all
        applications={REALTIME_APP_FIXTURES}
        extra={
          <Select<MetricFilter>
            label={t("realtime.filter.metric")}
            value={series.metric}
            onChange={series.setMetric}
            options={METRIC_FILTER_ORDER.map((value) => ({
              value,
              label: t(METRIC_FILTER_LABEL_KEY[value]),
            }))}
          />
        }
      />
      <StreamStatusBar range={range} status={series.status} onToggle={series.togglePlayback} />
      <RealtimeSummaryCards cards={REALTIME_SUMMARY_FIXTURES} />
      <RealtimeChartGrid
        series={trend}
        cursorTime={series.cursorTime}
        cards={series.cards}
      />
      <div className="bottom-note">
        <Info size={18} /> {t("realtime.note.tps")}
        <LinkButton onClick={() => navigate(ROUTE.Faults)}>
          {t("realtime.action.viewFaults")}
        </LinkButton>
      </div>
    </>
  );
}
