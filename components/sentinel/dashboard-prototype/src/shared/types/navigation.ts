/** Shared navigation intents and observation windows. No router, React or fixture dependency. */
import type { TranslationKey } from "./translation";
/** 稳定路由标识。值即 URL path 段，便于人工阅读和排障。 */
export const ROUTE = Object.freeze({
  Overview: "overview",
  Applications: "applications",
  Rules: "rules",
  Realtime: "realtime",
  Faults: "faults",
  System: "system",
  Documentation: "docs",
  Accounts: "accounts",
  Roles: "roles",
  ChangePassword: "change-password",
  Login: "login",
  Setup: "setup",
} as const);

/** {@link ROUTE} 的值联合。 */
export type RouteId = (typeof ROUTE)[keyof typeof ROUTE];

/**
 * 可分享的时间窗口标识。
 *
 * 中文
 * ----
 * 原实现把中文字面量（"最近 15 分钟"）直接当状态值，并在六个页面里用 `===` 比较。
 * 展示文案属于 i18n 资源，一旦切换语言，状态值与比较条件会同时失效。这里改为稳定
 * 协议值，标签由 {@link TIME_RANGE_LABEL_KEY} 指向语言资源。
 */
export const TIME_RANGE = Object.freeze({
  Last15Minutes: "15m",
  Last1Hour: "1h",
} as const);

/** {@link TIME_RANGE} 的值联合。 */
export type TimeRangeId = (typeof TIME_RANGE)[keyof typeof TIME_RANGE];

/** 时间窗口的文案键；协议值与展示文案分离。 */
export const TIME_RANGE_LABEL_KEY: Readonly<Record<TimeRangeId, TranslationKey>> = Object.freeze({
  [TIME_RANGE.Last15Minutes]: "shell.range.last15Minutes",
  [TIME_RANGE.Last1Hour]: "shell.range.last1Hour",
});

/** 全部可选时间窗口，保持与语言资源一一对应。 */
export const TIME_RANGES: readonly TimeRangeId[] = Object.freeze([
  TIME_RANGE.Last15Minutes,
  TIME_RANGE.Last1Hour,
]);

/** 时间窗口的毫秒跨度。图表与查询共用，避免各处重复换算。 */
export const TIME_RANGE_MS: Readonly<Record<TimeRangeId, number>> = Object.freeze({
  [TIME_RANGE.Last15Minutes]: 15 * 60 * 1000,
  [TIME_RANGE.Last1Hour]: 60 * 60 * 1000,
});

/**
 * 序列化为 URL query 的导航上下文。
 *
 * 这些值决定页面看到什么数据，因此必须可分享、可刷新恢复，且不进入规则草稿、
 * 配置中心或审计事件。
 */
export interface NavigationContext {
  /** Local route requested before authentication; re-authorized before use. */
  readonly returnTo?: RouteId;
  /** Stable deployment environment identity, never its translated label. */
  readonly environmentId?: string;
  /** 选中的应用 id；`all` 表示不限定应用。 */
  readonly appId?: string;
  /** 选中的时间窗口。 */
  readonly range?: TimeRangeId;
  /** Exact RFC3339 observation window; the feature validates [from,to), not the label of a relative range. */
  readonly from?: string;
  readonly to?: string;
  /** 身份页正在操作的账号 id。 */
  readonly accountId?: string;
  readonly instanceId?: string;
  readonly resource?: string;
  readonly eventId?: string;
  /** Fault timeline severity filter; interpretation and allowed values belong to the faults feature. */
  readonly incidentSeverity?: string;
  /** Fault timeline category filter; interpretation and allowed values belong to the faults feature. */
  readonly incidentCategory?: string;
  /** Opaque, non-secret fault timeline cursor. */
  readonly incidentCursor?: string;
  readonly versionId?: string;
  /** Exact publication identity for a deep link; not interchangeable with versionId. */
  readonly publicationId?: string;
  /** Exact rule configuration binding identity; independent from appId/kind filters. */
  readonly bindingId?: string;
  /** Feature validates supported metric scopes and resource identities. */
  readonly metricScope?: string;
  /** Shareable non-sensitive search; frequent edits use replace, not push. */
  readonly search?: string;
  /**
   * 路由内的子视图标识（系统管理的 tab 等）。
   *
   * 用稳定 id 而不是展示文案：文案会随语言与改版变化，进了 URL 就等于把展示层
   * 绑进深链。合法值集合由**拥有该视图的 feature** 校验（见
   * `features/system/model/systemStatus.ts` 的 `resolveSystemTab`），路由边界不认识
   * 任何页面的具体 tab，因此只做「非空字符串」这一层解析。
   */
  readonly view?: string;
  /** Rules page section; stable URL state for the user's current task. */
  readonly section?: string;
}

/** Maximum cursor length shared by the URL codec and feature-owned incident query contract. */
export const MAX_NAVIGATION_CURSOR_LENGTH = 512;

/** 全局不限定应用的哨兵值。它是协议值，不是展示文案。 */
export const ALL_APPLICATIONS = "all";

/** Typed application command; the app router owns serialization and history. */
export const NAVIGATION_HISTORY = Object.freeze({ Push: "push", Replace: "replace" } as const);
export interface NavigateOptions {
  readonly history?: (typeof NAVIGATION_HISTORY)[keyof typeof NAVIGATION_HISTORY];
  /** Replace defaults to no scrolling; explicit commands can override. */
  readonly scroll?: boolean;
}
export type Navigate = (
  route: RouteId,
  context?: NavigationContext,
  options?: NavigateOptions,
) => void;
