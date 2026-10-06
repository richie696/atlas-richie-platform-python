/**
 * 应用与实例页的演示数据。
 *
 * 中文
 * ----
 * fixture 只在本 feature 的 UI 与测试中使用；生产代码路径不导入它
 * （`REACT_PROJECT_SKELETON` §2：`fixtures/` 是显式测试/演示数据）。接入 Console API 后
 * 本文件整体删除，数据改由 `applications.gateway` 按时间窗口返回。
 *
 * 数值全部**原样迁移**自旧的全局 `src/demoData.ts`：`APPLICATIONS` / `ORDER_INSTANCES` /
 * `makeInstanceTrend` / `seriesForRange` 一个值都没改，视觉基线因此不变。`numberText` 没有
 * 搬进来：它是格式化而不是数据，已归到 `model/instanceFormat.ts`。
 *
 * 为什么造数函数在这里再写一份（而不是继续 import `demoData`）
 * ------------------------------------------------------
 * `makeInstanceTrend` 依赖的那条基线序列原本是 `FLEET_TREND`，它是**总览大盘**的读模型：
 * 总览的采样窗口与指标口径由它自己决定。让实例矩阵复用同一份全局造数函数，等于把单实例
 * 曲线的口径绑在全机群曲线上——总览改一次窗口，实例详情跟着变，而且没有任何一处代码
 * 声明了这条依赖。每个 feature 持有自己的读模型与采样口径，接入 API 后这段重复自然消失。
 *
 * 口径提醒：`qps` / `rt` / `blocked` 是 HTTP 层口径，不是业务 TPS。TPS 必须由业务事务埋点
 * 定义，不得由 QPS 推算。
 */
import { TIME_RANGE, type TimeRangeId } from "../../../app/router/route.constants";
import type { MetricPoint } from "../../../shared/types/dashboard";
import type { ApplicationRecord, InstanceRecord } from "../model/instance";

/** 应用摘要。`cpu` / `memory` / `qps` / `rt` / `blocked` 在本页不渲染，保留以与 `demoData` 对账。 */
export const APPLICATION_FIXTURES: readonly ApplicationRecord[] = Object.freeze([
  {
    id: "order-service",
    label: "order-service",
    state: "critical",
    stateLabel: "资源压力",
    running: 11,
    total: 12,
    cpu: 78,
    memory: 76,
    qps: 1240,
    rt: 420,
    blocked: 12.3,
    version: "v20260914-01",
    provider: "Nacos",
  },
  {
    id: "payment-service",
    label: "payment-service",
    state: "warning",
    stateLabel: "CPU 偏高",
    running: 8,
    total: 8,
    cpu: 62,
    memory: 68,
    qps: 980,
    rt: 310,
    blocked: 4.1,
    version: "v20260913-02",
    provider: "Consul",
  },
  {
    id: "user-service",
    label: "user-service",
    state: "healthy",
    stateLabel: "运行正常",
    running: 12,
    total: 12,
    cpu: 24,
    memory: 38,
    qps: 2100,
    rt: 180,
    blocked: 0.6,
    version: "v20260914-01",
    provider: "Nacos",
  },
]);

/** order-service 的 12 个示例实例，按宿主机分组排列。 */
export const ORDER_INSTANCE_FIXTURES: readonly InstanceRecord[] = Object.freeze([
  {
    id: "order-1",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 12,
    memory: 34,
    qps: 1240,
    rt: 36,
    blocked: 0.01,
    version: "v20260914-01",
  },
  {
    id: "order-2",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 18,
    memory: 27,
    qps: 980,
    rt: 42,
    blocked: 0,
    version: "v20260914-01",
  },
  {
    id: "order-3",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 16,
    memory: 35,
    qps: 1102,
    rt: 38,
    blocked: 0.02,
    version: "v20260914-01",
  },
  {
    id: "order-4",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 14,
    memory: 32,
    qps: 876,
    rt: 41,
    blocked: 0,
    version: "v20260914-01",
  },
  {
    id: "order-5",
    host: "host-10-0-1-13",
    status: "critical",
    statusLabel: "CPU 高",
    cpu: 92,
    memory: 78,
    qps: 2341,
    rt: 420,
    blocked: 1.23,
    version: "v20260914-01",
  },
  {
    id: "order-6",
    host: "host-10-0-1-13",
    status: "healthy",
    statusLabel: "正常",
    cpu: 28,
    memory: 52,
    qps: 1420,
    rt: 68,
    blocked: 0.05,
    version: "v20260914-01",
  },
  {
    id: "order-7",
    host: "host-10-0-1-13",
    status: "healthy",
    statusLabel: "正常",
    cpu: 24,
    memory: 49,
    qps: 1306,
    rt: 63,
    blocked: 0.04,
    version: "v20260914-01",
  },
  {
    id: "order-8",
    host: "host-10-0-1-13",
    status: "healthy",
    statusLabel: "正常",
    cpu: 19,
    memory: 46,
    qps: 1035,
    rt: 59,
    blocked: 0.02,
    version: "v20260914-01",
  },
  {
    id: "order-9",
    host: "host-10-0-2-21",
    status: "healthy",
    statusLabel: "正常",
    cpu: 17,
    memory: 42,
    qps: 1005,
    rt: 47,
    blocked: 0.03,
    version: "v20260914-01",
  },
  {
    id: "order-10",
    host: "host-10-0-2-21",
    status: "warning",
    statusLabel: "内存高",
    cpu: 26,
    memory: 88,
    qps: 1562,
    rt: 120,
    blocked: 0.28,
    version: "v20260914-01",
  },
  {
    id: "order-11",
    host: "host-10-0-2-21",
    status: "healthy",
    statusLabel: "正常",
    cpu: 19,
    memory: 42,
    qps: 1290,
    rt: 58,
    blocked: 0.02,
    version: "v20260914-01",
  },
  {
    id: "order-12",
    host: "host-10-0-2-21",
    status: "healthy",
    statusLabel: "正常",
    cpu: 15,
    memory: 32,
    qps: 970,
    rt: 56,
    blocked: 0.02,
    version: "v20260914-01",
  },
]);

/**
 * 构造一条 61 点的小时级基线序列。
 *
 * 数值与旧的 `demoData.makeTrendSeries` 逐字一致（含 14:02 的发布变更点，图表用它画
 * 标注线）。这里重新实现而不是 import，见文件头「为什么造数函数在这里再写一份」。
 */
function makeInstanceBaseSeries(pointCount = 61): MetricPoint[] {
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

const INSTANCE_BASE_TREND: readonly MetricPoint[] = Object.freeze(makeInstanceBaseSeries());

/**
 * 由实例快照造一条小时级曲线。
 *
 * critical 实例的爬升更陡，数值与旧实现一致。CPU 与内存封顶 100。
 */
export function makeInstanceTrend(instance: InstanceRecord): MetricPoint[] {
  const highPressure = instance.status === "critical";
  return INSTANCE_BASE_TREND.map((item, index) => ({
    ...item,
    cpu: Math.min(
      100,
      Math.round(
        instance.cpu * (highPressure ? 0.62 : 0.75) +
          (index / 60) * instance.cpu * (highPressure ? 0.38 : 0.25) +
          Math.sin(index * 0.7) * 3,
      ),
    ),
    memory: Math.min(
      100,
      Math.round(
        instance.memory * (0.72 + (index / 60) * 0.28) +
          Math.sin(index * 0.38) * 2,
      ),
    ),
    qps: Math.max(
      0,
      Math.round(
        instance.qps * (0.55 + (index / 60) * 0.45) +
          Math.sin(index * 0.8) * 60,
      ),
    ),
    blocked: Number(
      Math.max(0, instance.blocked * (0.25 + (index / 60) * 0.75)).toFixed(2),
    ),
    rt: Math.max(
      0,
      Math.round(
        instance.rt * (0.65 + (index / 60) * 0.35) + Math.sin(index * 0.55) * 6,
      ),
    ),
  }));
}

/**
 * 按时间窗口裁剪演示曲线。
 *
 * `range` 是协议值（`15m` / `1h`）。演示序列按 1 小时 61 个点生成，15 分钟窗口取尾部
 * 16 个点。生产实现由 Console API 按 `TIME_RANGE_MS` 查询对应窗口，不在前端裁剪。
 */
export function seriesForRange(
  series: readonly MetricPoint[],
  range: TimeRangeId,
): readonly MetricPoint[] {
  return range === TIME_RANGE.Last15Minutes ? series.slice(-16) : series;
}

/**
 * 实例详情面板的读模型：产出某实例在指定窗口的序列。
 *
 * 必须是模块级稳定引用，页面把它注入 `useInstanceMatrix`，Hook 才对曲线做记忆化。
 */
export function readInstanceSeries(
  instance: InstanceRecord,
  range: TimeRangeId,
): readonly MetricPoint[] {
  return seriesForRange(makeInstanceTrend(instance), range);
}
