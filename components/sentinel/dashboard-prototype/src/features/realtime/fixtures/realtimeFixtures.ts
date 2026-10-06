/**
 * 实时监控的演示数据。
 *
 * 中文
 * ----
 * fixture 只在本目录与测试中使用；生产代码路径不导入它
 * （`REACT_PROJECT_SKELETON` §2：`fixtures/` 是显式测试/演示数据）。接入 Console API
 * 后本文件整体删除，序列改由 `realtime.gateway` + `TimeSeriesStore` 提供。
 *
 * 这里的样本是**静态回放源**，不是实时数据：游标每 1.2 秒推进一步，推到末尾回到开头。
 * 界面因此必须保留「示例回放」标注（`DASHBOARD_CONTROL_PLANE.md` §4.4 硬约束）。
 *
 * 口径：曲线上的 `qps` / `rt` 是 **HTTP 层**指标，不是业务 TPS。TPS 必须由业务成功
 * 交易事件单独定义，不得由 QPS 推算。
 */
import { TIME_RANGE, type TimeRangeId } from "../../../app/router/route.constants";
import type { MetricPoint } from "../../../shared/types/dashboard";
import type { RealtimeSummaryCard } from "../model/realtime";

/** 演示序列的点类型即共享契约 `MetricPoint`，不另立一份形状。 */
export type TrendPoint = MetricPoint;

/**
 * 造一份等间隔样本序列。
 *
 * 中文
 * ----
 * 采样间隔 1 分钟，覆盖 13:32 – 14:32 这一段时钟。曲线在「发布点」前后有一次台阶，
 * 用来验证发布标记与曲线变化对得上；`postRelease` 是这个台阶的唯一开关。
 *
 * 数值全部是**示例**，不代表任何真实部署。
 */
export function makeTrendSeries(pointCount = 61): TrendPoint[] {
  return Array.from({ length: pointCount }, (_, index) => {
    const minute =
      13 * 60 + 32 + Math.round((index * 60) / Math.max(1, pointCount - 1));
    const time = `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
    const postRelease = minute >= 14 * 60 + 2;
    const wave = Math.sin(index * 0.87) * 850 + Math.sin(index * 2.1) * 410;
    return {
      time,
      qps: Math.round((postRelease ? 15000 : 22900) + wave + index * 45),
      blocked: Number(
        ((postRelease ? 8.7 : 1.8) + Math.sin(index * 0.9) * 0.5).toFixed(2),
      ),
      cpu: Math.round(
        (postRelease ? 54 : 43) + index * 0.12 + Math.sin(index * 0.8) * 3,
      ),
      memory: Math.round(48 + index * 0.15 + Math.sin(index * 0.5) * 2),
      rt: Math.round(
        (postRelease ? 182 : 102) + Math.sin(index * 0.55) * 12 + index * 0.1,
      ),
    };
  });
}

/** 整段时钟的演示序列，实时监控页面回放的唯一数据源。 */
export const FLEET_TREND = Object.freeze(makeTrendSeries());

/**
 * 按时间窗口裁剪演示曲线。
 *
 * 中文
 * ----
 * `range` 是协议值（`15m` / `1h`）。演示序列由 {@link makeTrendSeries} 按 1 小时
 * 61 个点生成，15 分钟窗口取尾部 16 个点。
 *
 * 生产实现由 Console API 按 `TIME_RANGE_MS` 查询对应窗口，不在前端裁剪。
 */
export function seriesForRange(series: readonly TrendPoint[], range: TimeRangeId): readonly TrendPoint[] {
  return range === TIME_RANGE.Last15Minutes ? series.slice(-16) : series;
}

/**
 * 首屏四张摘要卡的示例数值。
 *
 * 中文
 * ----
 * 与曲线同一份示例时间轴（14:32 附近）。`note` 里的涨跌是**示例对比**，不代表真实
 * 环比：接入 Console API 前，界面不得把这些数字描述为真实指标（§3.1 要求同时给出
 * scope / 窗口 / 来源 / 新鲜度，当前这四项都还缺）。
 *
 * 这里刻意**没有** TPS 卡：TPS 需由业务成功交易事件定义并单独接入，不能由 HTTP QPS
 * 推算（`DASHBOARD_CONTROL_PLANE.md` §3「业务吞吐」行）。
 */
export const REALTIME_SUMMARY_FIXTURES: readonly RealtimeSummaryCard[] = Object.freeze([
  { label: "HTTP QPS", value: "17.6K", unit: "次/秒", note: "↓ 27% · 相对发布前", tone: "green" },
  { label: "RT p95", value: "188", unit: "ms", note: "↑ 86 ms · 需要排查", tone: "red" },
  { label: "请求拦截率", value: "8.6", unit: "%", note: "↑ 6.8% · 相对发布前", tone: "red" },
  { label: "CPU 平均使用率", value: "62", unit: "%", note: "↑ 14% · 进程资源", tone: "amber" },
]);

/**
 * 实时监控可见的应用目录。
 *
 * 中文
 * ----
 * 旧实现直接读跨 feature 的全局应用常量，于是「实时监控能选哪些应用」由一个所有页面
 * 共用的数组决定：任何 feature 改演示数据都会静默影响这里的下拉内容
 * （`DASHBOARD_CONTROL_PLANE.md` §4.2：应用目录属于各 feature 自己的读模型）。
 *
 * 生产实现来自指标后端可查询到的应用目录；`user-service` 在本窗口内没有任何样本，
 * 选中它会看到空图——这是诚实的「无数据」，不该靠从下拉里删掉该应用来隐藏。
 */
export const REALTIME_APP_FIXTURES: readonly { readonly id: string; readonly label: string }[] =
  Object.freeze([
    { id: "order-service", label: "order-service" },
    { id: "payment-service", label: "payment-service" },
    { id: "user-service", label: "user-service" },
  ]);
