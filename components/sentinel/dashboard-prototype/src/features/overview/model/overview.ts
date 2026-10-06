/**
 * 总览页的读模型类型、协议常量与纯规则。
 *
 * 中文
 * ----
 * 字段对应 `REWRITE_PLAN.md` §4.1：异常摘要、基础组件状态、应用摘要、趋势序列。
 * 本模块不依赖 React、语言包或网络，只接收数据、返回结论。
 *
 * 旧实现（`OverviewPage.tsx` 单文件 179 行）的问题：
 *
 * - 「18 个应用运行中，2 个需要关注」「142 / 145 · 98%」「演示列表显示 3 / 18」
 *   这些**领域事实**写死在 JSX 文本里，与图例、筛选结果、表格行数各说各话：
 *   演示列表只有 3 行，标题却说 18 个应用，改 fixture 时没有任何一处会提示
 *   数字已经对不上。
 * - 表格的告警阈值（cpu > 75、rt > 350、blocked > 10）是裸字面量，没有名字，
 *   也没有第二个消费者。
 * - 「TPS 暂无接入」这条产品硬要求只是一行 `<span>` 文案，没有任何类型或常量
 *   表明它是**未接入**而不是「恰好是 0」。
 *
 * 已知口径缺口：`MetricPoint` 还没有 `scope` / `source` / `freshness`
 * （`DASHBOARD_CONTROL_PLANE.md` §3.1 的硬要求），因此本模块**不声明**
 * `FleetTrendSeries`；接入 Console API 时由 gateway 连同这三个字段一起补齐，
 * 前端不得在此之前把它们推断出来。
 */
import { TIME_RANGE, type TimeRangeId } from "../../../app/router/route.constants";
import type { MetricPoint } from "../../../shared/types/dashboard";

/** 应用健康等级。同时是表格状态标签的 tone。 */
export type ApplicationHealth = "critical" | "warning" | "healthy";

/**
 * 应用级关键指标摘要。
 *
 * 中文
 * ----
 * - `httpQps` / `rtP95Ms` 是 **HTTP 层**口径：QPS = 入站 HTTP 请求增量/秒，
 *   RT 为同窗口完成请求耗时。TPS 必须由业务事务埋点定义，不得由 QPS 推算。
 * - `cpuPercent` / `memoryPercent` 是应用内实例的平均值百分数（0..100），
 *   不是服务器 CPU/内存；跨实例汇总只合并同口径、同窗口且可识别实例身份的数据。
 * - `rtP95Ms` 在没有可聚合 histogram 时应为 `null`，不得用累计 `avg_rt_ns` 做差伪造。
 *   演示数据是固定示例，因此这里是具体数值。
 */
export interface ApplicationSummary {
  readonly id: string;
  /** 展示名，筛选下拉与表格首列共用。 */
  readonly name: string;
  readonly health: ApplicationHealth;
  readonly runningInstances: number;
  readonly totalInstances: number;
  readonly cpuPercent: number;
  readonly memoryPercent: number;
  readonly httpQps: number;
  readonly rtP95Ms: number;
  readonly blockedRatePercent: number;
  readonly ruleVersion: string;
}

/** 应用状态表格的告警阈值。示例阈值，接入后端后应与后端健康判定保持一致。 */
export const CELL_ALERT_THRESHOLDS = Object.freeze({
  cpuPercent: 75,
  rtP95Ms: 350,
  blockedRatePercent: 10,
} as const);

/** 应用状态表格的列头。值是语言键，译文在 `i18n/locales.ts`。 */
export const APPLICATION_TABLE_HEADERS: readonly string[] = Object.freeze([
  "overview.table.head.name",
  "overview.table.head.status",
  "overview.table.head.instances",
  "overview.table.head.cpuAvg",
  "overview.table.head.memoryAvg",
  "overview.table.head.httpQps",
  "overview.table.head.rtP95",
  "overview.table.head.blockedRate",
  "overview.table.head.ruleVersion",
  "overview.table.head.actions",
]);

/**
 * 健康等级的展示文案键。
 *
 * 中文
 * ----
 * 曾经还有一个 `healthReason: string` 字段，由 fixture 直接给中文（"资源压力"）。
 * 它的取值与 `health` 一一对应，于是同一份事实存在两份：改枚举要记得改 fixture，
 * 改 fixture 又不影响枚举——两份都可能对不上，且中文绕过了语言包。
 *
 * 这里收敛成「枚举 -> 语言键」的单向映射，`healthReason` 从模型里删除。
 * 将来若真需要自由文本说明（例如「CPU 连续 5 分钟高于 90%」），应另加一个
 * 明确的 `healthDetail` 字段，而不是让枚举标签兼职说明文字。
 */
export const APPLICATION_HEALTH_LABEL_KEY: Readonly<Record<ApplicationHealth, string>> =
  Object.freeze({
    critical: "overview.table.health.critical",
    warning: "overview.table.health.warning",
    healthy: "overview.table.health.healthy",
  } as const);

/**
 * 异常摘要。
 *
 * 中文
 * ----
 * - `totalApps` 是**该 worker 视角下的应用总数**，不是集群规模；一个 worker 的
 *   数字不能被标成「应用总量」（`DASHBOARD_CONTROL_PLANE.md` §3.1）。
 * - `focusedAppIds` 是需要下钻的应用，首个即摘要区与表格区共用的下钻目标。
 * - `summary` 是**已确认的观察结论**，不是原因推断；页面不得据此断言因果。
 */
export interface FleetAttention {
  readonly totalApps: number;
  readonly attentionCount: number;
  readonly focusedAppIds: readonly string[];
  readonly summary: string;
}

/** 异常摘要的下钻目标：焦点列表里的第一个应用。 */
export function attentionDrilldownAppId(attention: FleetAttention): string {
  return attention.focusedAppIds[0];
}

/**
 * 业务吞吐的接入状态。
 *
 * 中文
 * ----
 * TPS = 完成的**业务事务**数/秒，必须由应用明确标记事务边界与成功口径。
 * 当前未接入业务事务埋点，因此 `integrated` 为 `false`，界面必须显示缺口文案，
 * **不得**用 HTTP QPS 或 `succeeded` entry 推算，也不显示 0。
 *
 * 缺口文案本身在 `features/overview/i18n/locales.ts` 的 `overview.trend.tpsNote`，
 * 不在这里——model 层持有界面文案会让「这个接入状态」和「这句话怎么说」耦在一起，
 * 接入 TPS 后改文案要动 model。
 */
export const TPS_INTEGRATION = Object.freeze({
  integrated: false,
} as const);

/**
 * 配置中心的连接状态。
 *
 * 中文
 * ----
 * 是枚举而不是 `string`：连接状态是**界面**决定的取值集合，`"可用"` 这种中文字面量
 * 放在 fixture 里等于让演示数据绕过语言包（与曾经的 `healthReason` 同一个毛病）。
 */
export type InfraConnectionState = "available" | "unavailable" | "connecting";

/** 连接状态的展示文案键。 */
export const INFRA_STATE_LABEL_KEY: Readonly<Record<InfraConnectionState, string>> =
  Object.freeze({
    available: "overview.infra.state.available",
    unavailable: "overview.infra.state.unavailable",
    connecting: "overview.infra.state.connecting",
  } as const);

/**
 * 基础组件与规则下发状态。
 *
 * 中文
 * ----
 * 判别联合而不是一个全可空的大对象：配置中心有延迟观测值，规则下发覆盖只有
 * 实例数与百分比，两者的「缺什么」不同，合成一个结构会让调用方用 `?? 0`
 * 伪造出「延迟 0 ms」这种不存在的观测。
 *
 * `name` 在两个分支里语义不同，因此也分成两种形态：
 * - `config-center` 的 `name` 是**产品名**（Nacos / Consul），属于数据，保持原样。
 * - `rule-delivery` 的 `name` 是**功能名**（规则版本下发），属于界面文案，用语言键。
 *
 * 之前两边共用一个 `name: string`，于是「Nacos」和「规则版本下发」被同一条路径渲染，
 * 一个能翻译一个不能——差异藏在一个共用字段里，只有切到非中文语言才暴露。
 */
export type InfraStatus =
  | {
      readonly component: "config-center";
      /** Nacos / Consul。产品名，不翻译。 */
      readonly name: string;
      readonly state: InfraConnectionState;
      readonly latencyMs: number;
    }
  | {
      readonly component: "rule-delivery";
      /** 展示名的语言键。 */
      readonly nameKey: string;
      readonly appliedInstances: number;
      readonly totalInstances: number;
      readonly coveragePercent: number;
    };

/**
 * 趋势面板副标题的语言键。
 *
 * 中文
 * ----
 * 15 分钟窗口与 1 小时窗口对「发布时点是否落在窗口内」的结论不同，因此是两句话
 * 而不是同一句话加一个时间标签：`DASHBOARD_CONTROL_PLANE.md` §4.1 要求
 * 「窗口外的发布时点不画标记」。这里只放语言键，翻译在 UI 层。
 */
export const TREND_SUBTITLE_KEYS = Object.freeze({
  windowExcludesRelease: "overview.trend.windowExcludesRelease",
  sharedWindow: "overview.trend.sharedWindow",
} as const);

/** 趋势序列的展示窗口。 */
export type FleetTrendWindow = TimeRangeId;

/** 一个趋势窗口内的只读点列。 */
export type FleetTrendPoints = readonly MetricPoint[];

/**
 * 按当前应用作用域挑选表格要显示的行。
 *
 * 中文
 * ----
 * 总览是 `fleet` 粒度路由（`ROUTE.Overview.appFilter`），「全部应用」返回全集，
 * 具体应用返回该应用自己的行。**没有实例级数据时必须显示缺口，不能用另一应用
 * 的行填充**，所以这里只做精确匹配，不做模糊回退。
 */
export function selectApplicationScope(
  applications: readonly ApplicationSummary[],
  appId: string,
  allApplicationsId: string,
): readonly ApplicationSummary[] {
  if (appId === allApplicationsId) return applications;
  return applications.filter((application) => application.id === appId);
}

/** 当前时间窗口是否为 15 分钟。用于「示例窗口」与发布标注的分支。 */
export function isShortWindow(window: FleetTrendWindow): boolean {
  return window === TIME_RANGE.Last15Minutes;
}
