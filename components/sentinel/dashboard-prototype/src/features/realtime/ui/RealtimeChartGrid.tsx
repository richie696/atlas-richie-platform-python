/**
 * 指标趋势图网格。
 *
 * 中文
 * ----
 * 旧实现在页面组件体内维护一个 `chartCards` 数组（连标题、副标题一起），再在 JSX 里
 * `filter` + `map` 画图。这里拆成展示组件，**指标语义来自 `model/realtime`**，
 * **文案留在本文件**：标题是界面文案，不该和指标元数据绑成一份数据。
 *
 * 副标题里「窗口内有无发布时点」由 `hasReleaseMarker(series)` 决定，而不是由
 * `range` 决定：判断依据是图上真实有没有那个标记，而不是用户选了哪个下拉项。
 *
 * 组件是纯展示：不取数、不生成样本、不推进游标；游标时间由 `useRealtimeSeries` 提供。
 */
import { Panel } from "../../../shared/ui/Panel";
import { TrendChart as Trend } from "../../../shared/ui/charts/TrendChart";
import type { MetricPoint } from "../../../shared/types/dashboard";
import {
  hasReleaseMarker,
  type RealtimeChartMetric,
  type RealtimeMetricCard,
} from "../model/realtime";

/** 各图标题。键必须覆盖所有可成图指标，缺键在编译期暴露。 */
const CHART_TITLES: Readonly<Record<RealtimeChartMetric, string>> = Object.freeze({
  qps: "HTTP QPS",
  rt: "RT p95",
  blocked: "请求拦截率",
  cpu: "CPU 与内存使用率",
});

/** 与窗口无关的副标题。 */
const CHART_SUBTITLES: Readonly<Record<RealtimeChartMetric, string>> = Object.freeze({
  qps: "整体请求量与规则发布时点",
  rt: "尾部响应时间，单位 ms",
  blocked: "被 Sentinel 拒绝的请求占比",
  cpu: "示例应用资源压力",
});

/** QPS 图在窗口不含发布时点时的副标题。 */
const QPS_SUBTITLE_WITHOUT_RELEASE = "当前窗口请求量（无发布时点）";

/** 图表高度（像素）。同一屏四图需要统一高度，否则刻度密度不一致。 */
const CHART_HEIGHT = 240;

export interface RealtimeChartGridProps {
  /** 已按时间窗口裁剪的样本序列。 */
  readonly series: readonly MetricPoint[];
  /** 游标所在采样点的时间标签。 */
  readonly cursorTime: string | undefined;
  /** 当前指标筛选下应渲染的卡片。 */
  readonly cards: readonly RealtimeMetricCard[];
}

export function RealtimeChartGrid({ series, cursorTime, cards }: RealtimeChartGridProps) {
  const releaseVisible = hasReleaseMarker(series);
  return (
    <div className="monitor-grid">
      {cards.map((item) => (
        <Panel
          key={item.key}
          title={CHART_TITLES[item.key]}
          subtitle={
            item.key === "qps" && !releaseVisible ? QPS_SUBTITLE_WITHOUT_RELEASE : CHART_SUBTITLES[item.key]
          }
        >
          <Trend
            data={series}
            cursorTime={cursorTime}
            metric={item.key}
            color={item.color}
            unit={item.unit}
            second={item.second}
            domain={item.domain}
            height={CHART_HEIGHT}
          />
        </Panel>
      ))}
    </div>
  );
}
