/** Connection identity/state, supported tabs and capability values. Labels, formatted cells and prototype product explanations belong to presentation/systemPresentation. */

/**
 * 连接类别。
 *
 * 中文
 * ----
 * 这是 `规则控制台与运行观测设计.md` §2/§4.2 的链路分类：配置中心、指标后端、
 * 上报采集器三条链路各自独立健康，任何一条断开都不代表其余两条不可用。
 * 分类值只用于读模型自身，页面文案由 UI 层决定。
 */
import { SESSION_CAPABILITY, type SessionCapability } from "../../../core/session/capabilities";

export const CONNECTION_KIND = Object.freeze({
  ConfigCenter: "config-center",
  MetricsBackend: "metrics-backend",
  ReportingCollector: "reporting-collector",
} as const);

/** {@link CONNECTION_KIND} 的值联合。 */
export type ConnectionKind = (typeof CONNECTION_KIND)[keyof typeof CONNECTION_KIND];

/**
 * 连接状态（协议值）。
 *
 * 中文
 * ----
 * 原本这里是 `CONNECTION_AVAILABLE_STATE = "可用"`，而 `connectionStatusTone` 用
 * `state === CONNECTION_AVAILABLE_STATE` 判定状态色——**用展示文案做判定**。
 * 翻译一次就会让所有链路变成中性蓝，而这种失效没有任何测试能发现：页面照常渲染，
 * 只是所有连接都不再是健康绿。
 *
 * 状态色是判断，展示是文案，两者必须分开。判定基于枚举值，译文在
 * `system.connection.state.*`。
 */
export const CONNECTION_STATE = Object.freeze({
  /** 真实探测到连通。 */
  Available: "available",
  /**
   * 原型未接入采集器。
   *
   * 这是**产品事实**不是故障：演示阶段「未接入」用中性蓝而不是红色，
   * 不得为了让页面「看起来健康」而把它写成 `Available`。
   */
  Demo: "demo",
} as const);

/** {@link CONNECTION_STATE} 的值联合。 */
export type ConnectionState = (typeof CONNECTION_STATE)[keyof typeof CONNECTION_STATE];

/**
 * 页面 tab 的稳定标识。
 *
 * 中文
 * ----
 * 值是**协议 id**（会进 URL query），不是展示文案。旧实现用中文标签同时充当状态值
 * 与展示文本，改一次文案就会让已分享的链接失效——与时间范围曾经的
 * `"最近 1 小时"` 是同一类错误，这里不再重复。
 *
 * 标签由 presentation/systemPresentation 提供，翻译归应用 i18next 资源。
 * 深链使用稳定 id；顺序即渲染顺序，调整会改变首屏按钮排列。
 */
export const SYSTEM_TAB = Object.freeze({
  Connections: "connections",
  Permissions: "permissions",
  Protocol: "protocol",
  Audit: "audit",
  Accounts: "accounts",
  Roles: "roles",
  Settings: "settings",
} as const);

/** {@link SYSTEM_TAB} 的值联合。 */
export type SystemTab = (typeof SYSTEM_TAB)[keyof typeof SYSTEM_TAB];

/** tab 渲染顺序。首屏默认停在 {@link SYSTEM_TAB.Connections}。 */
export const SYSTEM_TABS: readonly SystemTab[] = Object.freeze([
  SYSTEM_TAB.Connections,
  SYSTEM_TAB.Permissions,
  SYSTEM_TAB.Protocol,
  SYSTEM_TAB.Audit,
  SYSTEM_TAB.Accounts,
  SYSTEM_TAB.Roles,
  SYSTEM_TAB.Settings,
]);

/** 首屏默认 tab。 */
export const DEFAULT_SYSTEM_TAB: SystemTab = SYSTEM_TAB.Connections;

/** Runtime guard for a system tab received through an untrusted route value. */
export function isSystemTab(value: unknown): value is SystemTab {
  return typeof value === "string" && SYSTEM_TABS.some((tab) => tab === value);
}

/**
 * 把 URL 里的 `view` 解析成受控 tab。
 *
 * 中文
 * ----
 * 合法值集合属于本 feature，因此校验放在这里而不是路由边界——`app/router` 不应该
 * 知道某个页面有几个 tab。非法或缺失一律回落默认 tab，绝不「就近猜一个」：
 * 猜错会让用户以为自己在看某个分区。
 */
export function resolveSystemTab(value: string | undefined): SystemTab {
  return isSystemTab(value) ? value : DEFAULT_SYSTEM_TAB;
}

/** 控制台只判断的两项能力（`规则控制台与运行观测设计.md` §2）。 */
export const CAPABILITY = SESSION_CAPABILITY;

/** 能力值联合。与 `core/session` 同一份定义。 */
export type Capability = SessionCapability;

/** 协议边界的稳定 id，同时是面板选择图标的键。 */
export type ProtocolBoundaryId = "rule-config" | "agent-reporting" | "cluster-token";
