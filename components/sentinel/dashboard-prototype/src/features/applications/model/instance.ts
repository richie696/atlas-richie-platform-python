/**
 * 实例矩阵的领域类型与协议常量。
 *
 * 中文
 * ----
 * 本文件只放**协议层固定值与领域形状**：应用/实例记录、健康等级、指标采集层级。
 * 纯计算（分组、筛选、阈值判断、是否已接入）在 `instancePolicy.ts`；展示文案、列头与
 * 状态标签渲染留在 UI 层，不写进协议常量。
 *
 * 旧实现的三个问题
 * --------------
 * 1. `scope` 状态直接存中文（`"容器"`）：按钮文案变成了状态值本身，换语言时状态与比较
 *    条件一起失效。这里改为协议值（`host` / `container` / `process`），标签由 UI 提供。
 * 2. 记录形状没有类型：实例状态是 `string`，`row.status !== "healthy"` 这种判断散在
 *    组件里，写错一个字不会报错。这里把健康等级收敛为字面量联合。
 * 3. 只有一个应用有实例数据，这个事实被写成两处 `app.id === "order-service"` 字面量
 *    比较。现在是具名协议常量 + `instancePolicy.hasInstanceSamples`。
 *
 * 关于字段名与口径（为什么与 `REWRITE_PLAN.md` §4.2 不完全一致）
 * ----------------------------------------------------
 * §4.2 的目标字段是 `cpuUsageRatio` / `memoryUsedBytes` / `rtP95Ms` / `blockedRatePercent`，
 * CPU 与内存为 0..1 比率。当前原型渲染的是**百分数整数**（矩阵单元格里直接输出 `92%`），
 * 状态文案也由数据自带。本轮只做代码结构改造、视觉基线必须逐字节不变，因此字段名与取值
 * 口径随数据原样保留；接入 Console API 时由 `applications.mapper` 一次性映射到 §4.2 的
 * 正式字段，不在 UI 层散落口径换算。
 */

/**
 * 健康等级。实例与应用的健康语义相同，共用一份协议值。
 *
 * 旧实现里实例与应用各写一遍 `"healthy" | "warning" | "critical"` 字面量，新增一级
 * 健康状态要改两处，漏一处只会表现为状态色缺失而没有编译错误。
 */
export const HEALTH_LEVEL = Object.freeze({
  Healthy: "healthy",
  Warning: "warning",
  Critical: "critical",
} as const);

/** {@link HEALTH_LEVEL} 的值联合。 */
export type HealthLevel = (typeof HEALTH_LEVEL)[keyof typeof HEALTH_LEVEL];

/**
 * 指标采集层级。
 *
 * 值为协议值，不是界面标签。`INSTANCE_SCOPES` 的顺序即分段控件的渲染顺序。
 */
export const INSTANCE_SCOPE = Object.freeze({
  Host: "host",
  Container: "container",
  Process: "process",
} as const);

/** {@link INSTANCE_SCOPE} 的值联合。 */
export type InstanceScope = (typeof INSTANCE_SCOPE)[keyof typeof INSTANCE_SCOPE];

/** 全部采集层级，顺序即 UI 顺序。 */
export const INSTANCE_SCOPES: readonly InstanceScope[] = Object.freeze([
  INSTANCE_SCOPE.Host,
  INSTANCE_SCOPE.Container,
  INSTANCE_SCOPE.Process,
]);

/** 详情面板默认展示的层级。原型只有容器级采样数据，见 `isScopeSupported`。 */
export const DEFAULT_INSTANCE_SCOPE = INSTANCE_SCOPE.Container;

/** 唯一有实例示例数据的应用。其余应用不伪造实例数据。 */
export const APP_WITH_INSTANCE_SAMPLES = "order-service";

/** 实例矩阵默认选中的实例。旧实现是 `ORDER_INSTANCES[4]` 这个下标，与实例 id 无关。 */
export const DEFAULT_SELECTED_INSTANCE_ID = "order-5";

/** 资源压力阈值（百分数）。CPU 与内存共用同一门槛。 */
export const RESOURCE_PRESSURE_PERCENT = 80;

/** 请求拦截率告警阈值（百分数）。 */
export const BLOCKED_RATE_ALERT_PERCENT = 1;

/**
 * 一条实例记录。
 *
 * 数值口径见文件头说明：`cpu` / `memory` 是 0..100 的百分数，`qps` 是 HTTP 层 QPS
 * （不是业务 TPS），`rt` 是同窗口 p95 耗时，`blocked` 是 Sentinel 拒绝占比。
 */
export interface InstanceRecord {
  readonly id: string;
  /** 所属宿主机。分组键。 */
  readonly host: string;
  readonly status: HealthLevel;
  /** 状态标签。阶段 1.3 迁入语言资源后由 `status` 派生，不再由数据自带。 */
  readonly statusLabel: string;
  readonly cpu: number;
  readonly memory: number;
  readonly qps: number;
  readonly rt: number;
  readonly blocked: number;
  /** 该实例当前生效的规则版本。 */
  readonly version: string;
}

/** 按宿主机分组的实例集合。分组顺序按实例在目录中首次出现的顺序，保持稳定。 */
export interface HostGroup {
  readonly host: string;
  readonly instances: readonly InstanceRecord[];
}

/**
 * 一个应用的摘要记录。
 *
 * `cpu` / `memory` / `qps` / `rt` / `blocked` 在本页不参与渲染，保留是为了与原
 * `demoData.APPLICATIONS` 逐字对账（阶段 2 删除 `demoData` 对应导出时能确认没漏字段）。
 */
export interface ApplicationRecord {
  readonly id: string;
  readonly label: string;
  readonly state: HealthLevel;
  /** 状态标签。与实例同理，阶段 1.3 后由语言资源提供。 */
  readonly stateLabel: string;
  /** 已生效规则的实例数。 */
  readonly running: number;
  /** 实例总数。 */
  readonly total: number;
  readonly cpu: number;
  readonly memory: number;
  readonly qps: number;
  readonly rt: number;
  readonly blocked: number;
  readonly version: string;
  /** 配置来源（配置中心）。 */
  readonly provider: string;
}
