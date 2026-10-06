/**
 * 实例矩阵的纯规则。
 *
 * 中文
 * ----
 * 本模块不依赖 React、语言包或网络，只接收数据、返回结论。
 *
 * 旧实现把这些判断全部写在 `ApplicationsPage` 的 render 里：按宿主机分组、过滤异常、
 * 统计异常数、判断某个采集层级有没有数据，都是 JSX 旁边的一次性表达式。结果是
 * 「什么算异常」「超过多少算资源压力」「哪个层级已接入」这三个领域判断没有归属，
 * 既无法单测，也无法被第二个消费者复用。现在它们都是具名纯函数。
 */
import {
  APP_WITH_INSTANCE_SAMPLES,
  BLOCKED_RATE_ALERT_PERCENT,
  HEALTH_LEVEL,
  INSTANCE_SCOPE,
  RESOURCE_PRESSURE_PERCENT,
  type ApplicationRecord,
  type HostGroup,
  type InstanceRecord,
  type InstanceScope,
} from "./instance";

/**
 * 实例是否计入「异常」。
 *
 * 口径：健康等级不为 `healthy` 即为异常。旧实现是散在组件里的
 * `item.status !== "healthy"`，出现三次；阈值一旦调整必然漏改。
 */
export function isAnomalous(instance: InstanceRecord): boolean {
  return instance.status !== HEALTH_LEVEL.Healthy;
}

/** 资源使用率是否越过压力阈值（严格大于，与旧实现一致）。 */
export function isUnderResourcePressure(percent: number): boolean {
  return percent > RESOURCE_PRESSURE_PERCENT;
}

/** 请求拦截率是否达到告警阈值（严格大于，与旧实现一致）。 */
export function isBlockingRateAlert(percent: number): boolean {
  return percent > BLOCKED_RATE_ALERT_PERCENT;
}

/** 目录中资源压力偏高的实例数。用于应用级摘要文案。 */
export function countAnomalous(instances: readonly InstanceRecord[]): number {
  return instances.filter(isAnomalous).length;
}

/** 矩阵的可见行筛选条件。 */
export interface InstanceFilter {
  /** 为 `true` 时只保留异常实例。 */
  readonly anomaliesOnly: boolean;
}

/**
 * 按「仅看异常」筛选实例。
 *
 * 不过滤时返回原数组引用，调用方不会因为一次无关渲染多出一份拷贝。
 */
export function filterInstances(
  instances: readonly InstanceRecord[],
  filter: InstanceFilter,
): readonly InstanceRecord[] {
  return filter.anomaliesOnly ? instances.filter(isAnomalous) : instances;
}

/**
 * 按宿主机分组，保持实例目录中的首次出现顺序。
 *
 * 纯函数：相同输入必然得到相同顺序，因此表格行不会在无关渲染中重排。旧实现是
 * `[...new Set(rows.map((item) => item.host))]` 加一次 `filter`，分组事实与渲染
 * 表达式缠在一起。
 */
export function groupByHost(instances: readonly InstanceRecord[]): readonly HostGroup[] {
  const groups = new Map<string, InstanceRecord[]>();
  for (const instance of instances) {
    const bucket = groups.get(instance.host);
    if (bucket) bucket.push(instance);
    else groups.set(instance.host, [instance]);
  }
  return [...groups].map(([host, rows]) => ({ host, instances: rows }));
}

/** 查找实例；`null` 表示目录里没有这个 id。 */
export function findInstance(
  instances: readonly InstanceRecord[],
  id: string,
): InstanceRecord | null {
  return instances.find((item) => item.id === id) ?? null;
}

/** 查找应用；`null` 表示目录里没有这个 id。回落策略由调用方决定。 */
export function findApplication(
  applications: readonly ApplicationRecord[],
  id: string,
): ApplicationRecord | null {
  return applications.find((item) => item.id === id) ?? null;
}

/** 该应用是否有实例示例数据。只有一个应用有，详见 `APP_WITH_INSTANCE_SAMPLES`。 */
export function hasInstanceSamples(appId: string): boolean {
  return appId === APP_WITH_INSTANCE_SAMPLES;
}

/**
 * 该采集层级是否已接入。
 *
 * 中文
 * ----
 * 这是产品硬要求（`DASHBOARD_CONTROL_PLANE.md` §4、`REWRITE_PLAN.md` §4.2）：宿主机层
 * 与进程层尚无采集源，UI 必须显示「未接入」，**不得**复用容器曲线伪造数据。为了让三种
 * 层级都能出图而编造数据，会让运维以为宿主机层已经上线采集。
 *
 * 旧实现把这个事实写成 `scope === "容器"`，与按钮文案混在一起；接入真实采集源时只需
 * 改这里和 `applications.gateway` 的响应。
 */
export function isScopeSupported(scope: InstanceScope): boolean {
  return scope === INSTANCE_SCOPE.Container;
}
