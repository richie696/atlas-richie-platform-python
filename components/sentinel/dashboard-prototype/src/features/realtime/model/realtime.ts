/**
 * 实时监控的读模型：采样模式、指标筛选与图表卡片元数据。
 *
 * 中文
 * ----
 * 本文件只负责**领域值与纯规则**：采样模式、指标筛选的取值范围、指标卡的元数据
 * （顺序、单位、次轴、固定值域），以及「某个筛选下应该画哪几张图」这一判断。
 * 不依赖 React、语言包与网络。
 *
 * 旧实现在 `RealtimePage` 的组件函数体里内联这段元数据：每渲染一次就重建一次
 * `chartCards` 数组，并把「选全部指标时画四张图、选单个指标时画一张图」写成页内三元
 * 表达式。于是「实时监控到底有哪些指标、单位是什么、次轴是哪条曲线」这个领域事实
 * 没有任何所有者，第二个消费者只能复制一份再各自漂移。
 *
 * 口径硬约束（`DASHBOARD_CONTROL_PLANE.md` §3）：
 *
 * - `qps` / `rt` 是 **HTTP 层**口径。TPS 必须由业务成功交易事件定义并单独接入，
 *   **不得**由 HTTP QPS 推算，因此本模块不提供 `tps` 指标。
 * - `rt` p95 需要可聚合的 histogram；没有 histogram 时后端不提供 p95 序列，
 *   前端不得用各实例百分位或累计平均再求平均（§3「响应时间」行）。
 * - `cpu` / `memory` 是 0..100 的使用率，值域固定，不随数据自适应。
 */
import type { ChartSeriesColor } from "../../../shared/ui/charts/chartTheme";
import type { MetricKey } from "../../../shared/types/dashboard";

/**
 * 采样模式。
 *
 * 中文
 * ----
 * 未接入实时后端时只能是 `Replay`：界面必须显示「示例回放」标注，不允许让静态样本
 * 看起来像实时数据（§4.4 硬约束）。
 */
export const STREAM_MODE = Object.freeze({
  /** 已接入实时数据流，游标跟随服务端推送。 */
  Live: "live",
  /** 未接入后端：按固定节奏回放一份静态样本。 */
  Replay: "replay",
  /** 一次性快照，不做回放也不自动刷新。 */
  Static: "static",
} as const);

/** {@link STREAM_MODE} 的值联合。 */
export type StreamMode = (typeof STREAM_MODE)[keyof typeof STREAM_MODE];

/**
 * 数据流状态。
 *
 * 中文
 * ----
 * 对应 `REWRITE_PLAN.md` §4.4 的 `StreamStatus`。`lastFrameAt` 暂不声明：它需要时钟，
 * 而当前阶段没有任何可被验证的时间来源，随手塞一个 `Date.now()` 只会制造一个看起来
 * 有新鲜度、实际不成立的字段。接入真实流后由 feature 数据层提供。
 */
export interface StreamStatus {
  readonly mode: StreamMode;
  /** 播放是否被用户暂停。 */
  readonly paused: boolean;
  /** 是否已安装服务端采样器。为 `false` 时界面必须标注「示例」。 */
  readonly samplerInstalled: boolean;
}

/**
 * 可独立成图的指标。
 *
 * 中文
 * ----
 * `memory` 只作为 CPU 卡的次轴出现，不单独成图，也不进入指标筛选：把它放进筛选值域
 * 会让「按指标筛选」多出一个没有对应图表的选项。旧实现的筛选值域直接用 `MetricKey`，
 * 这个不一致只有在下拉真正新增选项时才会暴露。
 */
export type RealtimeChartMetric = Exclude<MetricKey, "memory">;

/**
 * 指标筛选的「全部」哨兵值。
 *
 * 它是协议值而不是展示文案；下拉标签由共享语言资源的 `realtime.metric.*` 提供。
 */
export const METRIC_FILTER_ALL = "all";

/** 指标筛选的可选值。 */
export type MetricFilter = RealtimeChartMetric | typeof METRIC_FILTER_ALL;

/** 指标筛选下拉的可选值，顺序即渲染顺序。 */
export const METRIC_FILTER_ORDER: readonly MetricFilter[] = Object.freeze([
  METRIC_FILTER_ALL,
  "qps",
  "rt",
  "blocked",
  "cpu",
]);

/** 指标筛选项的文案键。键与共享语言资源一一对应，翻译发生在渲染时。 */
export const METRIC_FILTER_LABEL_KEY: Readonly<Record<MetricFilter, string>> = Object.freeze({
  [METRIC_FILTER_ALL]: "realtime.metric.all",
  qps: "realtime.metric.qps",
  rt: "realtime.metric.rt",
  blocked: "realtime.metric.blocked",
  cpu: "realtime.metric.cpu",
});

/**
 * 一张指标卡的元数据。
 *
 * 这里只有**指标语义**（哪条曲线、单位、次轴、值域），不含标题与副标题：标题是界面
 * 文案，归渲染它的组件所有。旧实现把 `title` / `subtitle` 一起塞进页面内的数组，
 * 于是「这张图画的是什么指标」和「这句话怎么写」两件事被绑成一份数据。
 */
export interface RealtimeMetricCard {
  readonly key: RealtimeChartMetric;
  /** 序列色语义键；色值由 shared/ui/charts/chartTheme 从 CSS token 解析。 */
  readonly color: ChartSeriesColor;
  /** 数值后缀。缺省表示无量纲。 */
  readonly unit?: string;
  /** 双轴展示时的次指标键（CPU 卡同时画内存）。 */
  readonly second?: MetricKey;
  /**
   * 固定值域。
   *
   * 使用率类指标固定 0..100：按数据自适应会把几十个百分点的波动拉满整幅图，
   * 让轻微的资源压力看起来像剧烈抖动。
   */
  readonly domain?: [number, number];
}

/** 指标卡元数据。顺序即渲染顺序，也是 `metric=all` 时的默认展示顺序。 */
export const REALTIME_METRIC_CARDS: readonly RealtimeMetricCard[] = Object.freeze([
  { key: "qps", color: "primary" },
  { key: "rt", color: "secondary" },
  { key: "blocked", color: "danger", unit: "%" },
  { key: "cpu", color: "primary", unit: "%", second: "memory", domain: [0, 100] },
]);

/**
 * 某个指标筛选下应渲染的卡片。
 *
 * 单一所有者：页面不再自己判断「全部 = 四张、单选 = 一张」。
 */
export function visibleMetricCards(filter: MetricFilter): readonly RealtimeMetricCard[] {
  return filter === METRIC_FILTER_ALL
    ? REALTIME_METRIC_CARDS
    : REALTIME_METRIC_CARDS.filter((card) => card.key === filter);
}

/** 规则发布时点在时间轴上的位置标签。曲线上的发布标记按这个标签定位。 */
export const RELEASE_MARKER_TIME = "14:02";

/**
 * 当前窗口内是否包含发布时点。
 *
 * 中文
 * ----
 * 旧实现用 `range === TIME_RANGE.Last15Minutes` 判断「窗口里有没有发布时点」——
 * 那是拿筛选条件冒充数据事实：15 分钟窗口恰好不含发布点只是巧合，窗口一旦滑到发布点
 * 之后，副标题就会一边画着发布标记一边说「无发布时点」。这里改为直接看窗口里有没有
 * 标记样本，副标题因此始终与图上画的东西一致。
 */
export function hasReleaseMarker(times: readonly { readonly time: string }[]): boolean {
  return times.some((item) => item.time === RELEASE_MARKER_TIME);
}

/**
 * 静态样本回放的推进间隔（毫秒）。
 *
 * 中文
 * ----
 * 这是**示例回放**的节奏，不是刷新 SLA。真实采样间隔由后端能力决定，界面不得假定固定
 * 值（`DASHBOARD_CONTROL_PLANE.md` §3）。接入实时流后本常量与游标推进一起删除，
 * 改由 `requestStream` + `TimeSeriesStore` 供给有界窗口（`REWRITE_PLAN.md` §2.2）。
 */
export const REPLAY_TICK_MS = 1200;

/**
 * 首屏摘要卡。
 *
 * 中文
 * ----
 * 这是 `REWRITE_PLAN.md` §4.4 `RealtimeSummary` 的**当前阶段替身**：只保留界面要显示的
 * 四个字段，缺少 §3.1 要求的 `scope` / `source` / `asOf` / 窗口标注。缺口是已知且必须
 * 显式的——在 Console API 接入之前，这些卡展示的是**示例数值**，界面不得把它们描述成
 * 真实指标。接入后由 feature gateway 填充完整字段，本类型相应扩展或替换。
 */
export interface RealtimeSummaryCard {
  readonly label: string;
  /** 已格式化好的展示值。格式化不写进协议值。 */
  readonly value: string;
  readonly unit: string;
  /** 与上一状态的对比说明。数据不足时不得画趋势箭头。 */
  readonly note: string;
  /** 语义色：`green` / `amber` / `red`。 */
  readonly tone: string;
}
