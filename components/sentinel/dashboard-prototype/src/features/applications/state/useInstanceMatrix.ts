/**
 * 实例矩阵的状态机。
 *
 * 中文
 * ----
 * 旧实现在 `ApplicationsPage` 里用三个 `useState` 直接表达「选中了哪个实例 / 是否只看
 * 异常 / 详情看哪个层级」，并把派生量（按宿主机分组、异常实例数、选中实例的曲线）写成
 * render 里的表达式。问题是三条状态之间有真实约束，却只存在于 render 顺序里：
 *
 * - **选中实例从完整目录解析**，不从「仅看异常」过滤后的行里解析。切到只看异常时，
 *   已选中的正常实例仍留在详情面板；否则筛选会悄悄撤销用户的选中动作。
 * - **应用目录总数与异常数不随筛选变化**。副标题里的「共 N 个实例」是目录口径，
 *   不是当前可见行数。
 * - **曲线随选中实例与时间窗口变化**，但不由本 Hook 造数：序列由调用方注入的读模型
 *   提供，接入 Console API 后换成 gateway 即可，Hook 签名不变。
 *
 * 本 Hook 不发请求，也不做校验之外的领域判断。
 */
import { useMemo, useState } from "react";

import type { TimeRangeId } from "../../../app/router/route.constants";
import type { MetricPoint } from "../../../shared/types/dashboard";
import {
  DEFAULT_INSTANCE_SCOPE,
  DEFAULT_SELECTED_INSTANCE_ID,
  type ApplicationRecord,
  type HostGroup,
  type InstanceRecord,
  type InstanceScope,
} from "../model/instance";
import {
  countAnomalous,
  filterInstances,
  findApplication,
  findInstance,
  groupByHost,
  hasInstanceSamples,
} from "../model/instancePolicy";

/** 空序列的稳定引用，避免在无选中实例时每次 render 造新数组。 */
const EMPTY_SERIES: readonly MetricPoint[] = Object.freeze([]);

export interface UseInstanceMatrixOptions {
  /** 应用目录。生产实现来自 gateway；原型阶段由 fixture 提供。 */
  readonly applications: readonly ApplicationRecord[];
  /** 实例目录全集。 */
  readonly instances: readonly InstanceRecord[];
  /** 当前选中的应用 id。 */
  readonly appId: string;
  /** 当前时间窗口。 */
  readonly range: TimeRangeId;
  /**
   * 读模型：产出某个实例在给定窗口的指标序列。
   *
   * 原型阶段由 `fixtures` 的 `seriesForRange(makeInstanceTrend(...), range)` 提供；
   * 接入 Console API 后改为按 `range` 查询的 gateway 调用。必须是模块级稳定引用，
   * 否则 Hook 无法对曲线做记忆化。
   */
  readonly readSeries: (instance: InstanceRecord, range: TimeRangeId) => readonly MetricPoint[];
}

export interface InstanceMatrix {
  /** 当前应用；`null` 表示目录里没有这个 id。 */
  readonly app: ApplicationRecord | null;
  /** 该应用是否有实例数据，决定下方矩阵与提示是否可信。 */
  readonly hasInstanceSamples: boolean;
  /** 实例目录总数，不随「仅看异常」变化。 */
  readonly instanceCount: number;
  /** 目录中资源压力偏高的实例数。 */
  readonly anomalyCount: number;
  /** 当前选中的实例；`null` 表示实例目录为空。 */
  readonly selected: InstanceRecord | null;
  readonly selectedId: string;
  /** 按宿主机分组的当前可见行。 */
  readonly hosts: readonly HostGroup[];
  readonly anomaliesOnly: boolean;
  readonly scope: InstanceScope;
  /** 选中实例在当前窗口的指标序列；未接入的层级不被渲染，因此为空。 */
  readonly series: readonly MetricPoint[];

  setSelectedId: (id: string) => void;
  setAnomaliesOnly: (value: boolean) => void;
  setScope: (scope: InstanceScope) => void;
}

export function useInstanceMatrix(options: UseInstanceMatrixOptions): InstanceMatrix {
  const { applications, instances, appId, range, readSeries } = options;
  const [selectedId, setSelectedId] = useState<string>(DEFAULT_SELECTED_INSTANCE_ID);
  const [anomaliesOnly, setAnomaliesOnly] = useState(false);
  const [scope, setScope] = useState<InstanceScope>(DEFAULT_INSTANCE_SCOPE);

  const app = useMemo(() => findApplication(applications, appId), [appId, applications]);
  // 依据**解析后的应用**判断是否有实例数据，而不是 URL 里的原始 id：`app` 不校验
  // 合法性，未知 id 会回落到首个应用，此时摘要与提示仍应按回落后的应用判断。
  const hasSamples = app ? hasInstanceSamples(app.id) : false;
  const visible = useMemo(
    () => filterInstances(instances, { anomaliesOnly }),
    [anomaliesOnly, instances],
  );
  const hosts = useMemo(() => groupByHost(visible), [visible]);
  const anomalyCount = useMemo(() => countAnomalous(instances), [instances]);

  // 回落顺序：选中项 → 默认实例 → 空。见文件头「选中实例从完整目录解析」。
  const selected = useMemo(
    () =>
      findInstance(instances, selectedId) ??
      findInstance(instances, DEFAULT_SELECTED_INSTANCE_ID),
    [instances, selectedId],
  );

  const series = useMemo(
    () => (selected ? readSeries(selected, range) : EMPTY_SERIES),
    [range, readSeries, selected],
  );

  return {
    app,
    hasInstanceSamples: hasSamples,
    instanceCount: instances.length,
    anomalyCount,
    selected,
    selectedId,
    hosts,
    anomaliesOnly,
    scope,
    series,
    setSelectedId,
    setAnomaliesOnly,
    setScope,
  };
}
