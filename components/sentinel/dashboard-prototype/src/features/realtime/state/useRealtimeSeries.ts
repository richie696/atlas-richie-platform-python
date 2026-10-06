/**
 * 实时监控的播放游标与指标筛选。
 *
 * 中文
 * ----
 * 旧实现在 `RealtimePage` 里用 `frame` 计数 + `setInterval` 做**假回放**：每 1.2 秒把
 * 游标推到下一个采样点，推到末尾回到开头。定时器、暂停分支、游标取样三件事混在页面
 * 组件体内，于是「这个页面上还有什么在动」只能读组件才能知道。
 *
 * 本 Hook 拥有这两件事：
 *
 * - **播放游标**：`frame` 是唯一的播放位置，`cursorTime` 由它派生。
 * - **指标筛选**：`metric` 决定画哪几张图，取值范围由 `model/realtime` 约束。
 *
 * 传入的 `series` 已经是**按时间窗口裁剪后**的样本（裁剪是读模型策略，页面用
 * `fixtures/seriesForRange` 得到）；本 Hook 不关心窗口有多长，只在序列变化时重建定时
 * 器，并保留既有游标位置——切换时间范围不应该让回放从头开始。
 *
 * 重要边界：当前是**静态样本回放**，不是实时数据流。接入 Console API 后，这里的
 * `setInterval` 与 `frame` 一起删除，改为 `HttpClient.requestStream` /
 * `parseEventStream` 拉取并交给 `TimeSeriesStore` 维护有界窗口
 * （`REWRITE_PLAN.md` §2.2）。在真正替换之前，界面上的「示例回放」标注**不得去掉**，
 * 回放节奏也不得改动。
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import type { MetricPoint } from "../../../shared/types/dashboard";
import {
  METRIC_FILTER_ALL,
  REPLAY_TICK_MS,
  STREAM_MODE,
  visibleMetricCards,
  type MetricFilter,
  type RealtimeMetricCard,
  type StreamStatus,
} from "../model/realtime";

/** 实时监控页面可以取用的全部状态与命令。 */
export interface RealtimeSeriesState {
  /** 当前指标筛选。 */
  readonly metric: MetricFilter;
  readonly setMetric: (metric: MetricFilter) => void;
  /** 当前筛选下应渲染的指标卡元数据，顺序即渲染顺序。 */
  readonly cards: readonly RealtimeMetricCard[];
  readonly paused: boolean;
  /** 切换播放/暂停。 */
  readonly togglePlayback: () => void;
  /** 游标所在采样点的时间标签；无样本时为 `undefined`。 */
  readonly cursorTime: string | undefined;
  readonly status: StreamStatus;
}

/**
 * 拥有回放游标与指标筛选。
 *
 * 中文
 * ----
 * 定时器在暂停时不启动，在卸载与序列变化时清理；Strict Mode 下的重挂载会重新建立
 * 定时器而不会泄漏前一个。
 */
export function useRealtimeSeries(series: readonly MetricPoint[]): RealtimeSeriesState {
  const [metric, setMetric] = useState<MetricFilter>(METRIC_FILTER_ALL);
  const [paused, setPaused] = useState(false);
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (paused) return undefined;
    const timer = window.setInterval(
      () => setFrame((index) => (index + 1) % series.length),
      REPLAY_TICK_MS,
    );
    return () => window.clearInterval(timer);
  }, [paused, series]);

  // 窗口切换后序列变短，`frame` 可能超出范围；取样时取模而不是重置游标，
  // 免得切换时间范围时画面跳回起点。
  const cursorTime = series[frame % series.length]?.time;
  const cards = useMemo(() => visibleMetricCards(metric), [metric]);
  const togglePlayback = useCallback(() => setPaused((value) => !value), []);

  // 未接入采样器，因此 `samplerInstalled` 恒为 false、`mode` 恒为 replay：
  // 这两个字段正是界面必须显示「示例回放」标注的依据。
  const status: StreamStatus = {
    mode: STREAM_MODE.Replay,
    paused,
    samplerInstalled: false,
  };

  return { metric, setMetric, cards, paused, togglePlayback, cursorTime, status };
}
