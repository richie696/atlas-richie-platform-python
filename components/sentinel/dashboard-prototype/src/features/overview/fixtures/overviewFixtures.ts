/**
 * 总览页的演示数据。
 *
 * 中文
 * ----
 * fixture 只在本 feature 的 UI 与测试中使用；**生产代码路径不导入它**
 * （`REACT_PROJECT_SKELETON` §2：`fixtures/` 是显式测试/演示数据）。
 * 接入 Console API 后本文件整体删除，应用目录与趋势序列改由 `overview.gateway`
 * 提供（`GET /api/v1/applications`、`GET /api/v1/metrics/fleet-trend`）。
 *
 * 关于「为什么要复制一份而不是继续共用全局 `demoData`」：
 * 每个 feature 的读模型与采样口径应当独立（`DASHBOARD_CONTROL_PLANE.md` §4.2）。
 * 共用一份全局常量意味着任何一个 feature 改演示数据都会静默改变另外五个页面的
 * 图表内容，而 `qps` / `rt` / `blocked` 的口径、窗口、覆盖范围本就不一样。
 * 各 feature 在自己的 `fixtures/` 里持有自己那份，是这个边界的落地方式。
 *
 * 注意 `qps` / `rt` / `blocked` 是「HTTP 层」口径，不是业务 TPS。
 */
import { TIME_RANGE, type TimeRangeId } from "../../../app/router/route.constants";
import type { MetricPoint } from "../../../shared/types/dashboard";
import type { ApplicationSummary, FleetAttention, InfraStatus } from "../model/overview";

/** 异常摘要。`totalApps` 是该 worker 视角下的应用总数，不是集群规模。 */
export const FLEET_ATTENTION: FleetAttention = Object.freeze({
  totalApps: 18,
  attentionCount: 2,
  focusedAppIds: Object.freeze(["order-service", "payment-service"]),
  summary: "资源压力与阻断率上升集中在 order-service 和 payment-service。",
});

/** 基础组件与规则下发状态。 */
export const INFRA_STATUS: readonly InfraStatus[] = Object.freeze([
  { component: "config-center", name: "Nacos", state: "available", latencyMs: 12 },
  { component: "config-center", name: "Consul", state: "available", latencyMs: 18 },
  {
    component: "rule-delivery",
    nameKey: "overview.infra.component.ruleDelivery",
    appliedInstances: 142,
    totalInstances: 145,
    coveragePercent: 98,
  },
]);

/** 应用目录（演示 3 个，总览声称的应用总数见 {@link FLEET_ATTENTION}）。 */
export const APPLICATION_SUMMARIES: readonly ApplicationSummary[] = Object.freeze([
  {
    id: "order-service",
    name: "order-service",
    health: "critical",
    runningInstances: 11,
    totalInstances: 12,
    cpuPercent: 78,
    memoryPercent: 76,
    httpQps: 1240,
    rtP95Ms: 420,
    blockedRatePercent: 12.3,
    ruleVersion: "v20260914-01",
  },
  {
    id: "payment-service",
    name: "payment-service",
    health: "warning",
    runningInstances: 8,
    totalInstances: 8,
    cpuPercent: 62,
    memoryPercent: 68,
    httpQps: 980,
    rtP95Ms: 310,
    blockedRatePercent: 4.1,
    ruleVersion: "v20260913-02",
  },
  {
    id: "user-service",
    name: "user-service",
    health: "healthy",
    runningInstances: 12,
    totalInstances: 12,
    cpuPercent: 24,
    memoryPercent: 38,
    httpQps: 2100,
    rtP95Ms: 180,
    blockedRatePercent: 0.6,
    ruleVersion: "v20260914-01",
  },
]);

/**
 * 生成一段演示趋势序列。
 *
 * 中文
 * ----
 * 61 个点覆盖 1 小时，14:02 之后视为「发布后」。数值是**示例**，不代表任何真实
 * 部署的流量形状。
 */
export function makeTrendSeries(pointCount = 61): MetricPoint[] {
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

/**
 * 演示趋势序列。
 *
 * 中文
 * ----
 * **求值时机不变**：模块加载时求值并冻结，因此图表数据的随机性来源与时间基准
 * 在同一会话内保持一致。接入 `TimeSeriesStore` 后由有界窗口取代，前端不再持有
 * 冻结数组（`REWRITE_PLAN.md` §2.2）。
 */
export const FLEET_TREND: readonly MetricPoint[] = Object.freeze(makeTrendSeries());

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
export function seriesForRange(
  series: readonly MetricPoint[],
  range: TimeRangeId,
): readonly MetricPoint[] {
  return range === TIME_RANGE.Last15Minutes ? series.slice(-16) : series;
}
