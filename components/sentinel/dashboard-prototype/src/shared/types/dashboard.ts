/**
 * 跨 feature 共享的页面契约类型。
 *
 * 中文
 * ----
 * 这里只放**多个 feature 真的共同需要**的稳定形状。feature 私有类型留在各自目录，
 * 不因为「将来可能用到」就提升到 shared（`REACT_PROJECT_SKELETON` §2）。
 */
import type { RouteId, TimeRangeId } from "../../app/router/route.constants";

/** 导航命令可携带的上下文。字段与 `app/router` 的 `NavigationContext` 对应。 */
export type NavigateContext = {
  readonly appId?: string;
  readonly accountId?: string;
  /** 路由内子视图（系统管理的 tab 等），必须是稳定 id 而非展示文案。 */
  readonly view?: string;
};

/**
 * 导航命令。
 *
 * 中文
 * ----
 * 参数是 `RouteId` 而不是 `string`：调用方写错路由名会在编译期失败，而不是运行时
 * 静默落到总览页。第二个参数是可选的导航上下文（应用 id / 账号 id / 子视图），
 * 由 `app` 层序列化进 URL query，调用方不需要知道 URL 形态。
 */
export type Navigate = (route: RouteId, context?: NavigateContext) => void;

/**
 * 数据页共用的筛选状态。
 *
 * 中文
 * ----
 * `range` 是稳定协议值（`15m` / `1h`），不是中文展示文案。时间窗口标签由
 * `core/i18n` 解析 `TIME_RANGE_LABEL_KEY` 得到；把「最近 1 小时」当状态值会让切换
 * 语言时状态与比较条件同时失效。
 */
export type DashboardFilters = {
  readonly appId: string;
  readonly range: TimeRangeId;
};

/**
 * 数据页容器共用的 props。
 *
 * 中文
 * ----
 * 页面容器负责「取 feature 状态、组合区域、把用户动作映射为命令或导航」，
 * 不自行发请求、不自行拼 URL。这里只传应用层已经解析好的筛选状态和导航命令。
 */
export type DashboardPageProps = DashboardFilters & {
  readonly navigate: Navigate;
  readonly setAppId: (appId: string) => void;
  readonly setRange: (range: TimeRangeId) => void;
  /**
   * 当前界面语言。
   *
   * 中文
   * ----
   * 语言属于 app 级状态。阶段 1 接入 `core/session` 的 UI store 后，页面应改为
   * 从 store 订阅，而不是继续靠 props 下传；此处先保持既有调用形态。
   */
  readonly locale: string;
  /**
   * URL 里的子视图标识（当前只有系统管理的 tab 使用）。
   *
   * 中文
   * ----
   * 不需要子视图的页面不要解构这个字段——它属于「可分享导航状态」，与
   * `appId` / `range` 同级，由路由边界解析、由 `app` 层透传。
   */
  readonly view: string;
};

/**
 * 可绘制的指标序列字段。
 *
 * 中文
 * ----
 * 图表按 key 取值。用字面量联合而不是 `Record<string, string | number>` 索引签名，
 * 是为了让 `metric="qqs"` 这类拼写错误在编译期暴露。
 */
export type MetricKey = "qps" | "rt" | "blocked" | "cpu" | "memory";

/**
 * 一个采样点上的指标集合。
 *
 * 中文
 * ----
 * 字段语义与 Console API 的 `MetricPoint` 对齐（见 `REWRITE_PLAN.md` §4.1）：
 *
 * - `time` 是展示用时间标签。生产实现应改用毫秒时间戳 + locale 格式化，
 *   不在协议层传本地化字符串。
 * - `qps` / `rt` 是 **HTTP 层**口径：QPS = 入站 HTTP 请求增量/秒，RT 为同窗口完成
 *   请求耗时。TPS 必须由业务事务埋点定义，**不得**由 QPS 推算。
 * - `blocked` 是 Sentinel 拒绝占比。
 * - `cpu` / `memory` 为 0..1 比率，不是百分数。
 *
 * 当前类型尚未包含 `scope` / `source` / `freshness`。这三项是 `DASHBOARD_CONTROL_PLANE.md`
 * §3.1 的硬要求，接入 Console API 时必须补齐，否则无法区分「应用总量」与「单进程」口径。
 */
export interface MetricPoint {
  readonly time: string;
  readonly qps: number;
  readonly blocked: number;
  readonly cpu: number;
  readonly memory: number;
  readonly rt: number;
}
