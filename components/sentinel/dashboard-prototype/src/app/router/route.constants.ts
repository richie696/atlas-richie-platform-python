import {
  ROUTE,
  TIME_RANGES,
  ALL_APPLICATIONS,
  MAX_NAVIGATION_CURSOR_LENGTH,
  type RouteId,
  type TimeRangeId,
  type NavigationContext,
} from "../../shared/types/navigation";
import type { TranslationKey } from "../../shared/types/translation";
export {
  ROUTE,
  TIME_RANGE,
  TIME_RANGES,
  TIME_RANGE_LABEL_KEY,
  TIME_RANGE_MS,
  ALL_APPLICATIONS,
  type RouteId,
  type TimeRangeId,
  type NavigationContext,
} from "../../shared/types/navigation";

/**
 * Dashboard 路由静态地址的唯一来源。
 *
 * 中文
 * ----
 * 本模块只拥有「有哪些路由、每个路由的静态地址、访问前置条件和文案键」这一件事。
 * 它不依赖 React、不依赖图标库、不发请求，因此可以被路由表、导航、权限守卫和
 * 单元测试共同引用。
 *
 * 约束（来自 `REACT_CODING_STANDARD` §1/§3 与 `REACT_PROJECT_SKELETON` §3）：
 *
 * - 页面和组件**不允许**出现裸路由字符串，只能引用 {@link ROUTE} 的键。
 * - 图标不在本表内绑定。下标对齐（`ICONS[index]`）在导航增删或重排时会静默错位，
 *   图标属于 `navigation.ts` 的职责，且必须按路由 id 显式绑定。
 * - 标签来自 `i18nKey`，不在此处写死中文；`shell.navigation` 也不再是按序数组。
 * - 可分享的导航上下文（应用、时间范围、账号）序列化进 query，而不是靠 props
 *   逐层下传或组件内 state——刷新和深链后必须能恢复。
 *
 * English
 * -------
 * Single source of truth for dashboard route ids, static paths, access
 * requirements and label keys. Deliberately free of React, icon libraries and
 * network access so routing, navigation, guards and tests can share it.
 */

/**
 * 进入路由的前置条件。
 *
 * - `public`：任何访客可达。
 * - `session`：需要已登录会话；未登录时守卫重定向到 {@link ROUTE.Login}。
 * - `metrics`：需要带有指标查看能力的会话。
 * - `admin`：需要管理员会话。
 * - `setup`：仅在服务端尚未初始化时开放。初始化成功后服务端关闭该窗口，
 *   守卫必须把深链重定向到 {@link ROUTE.Login}（见 `AGENTS.md` 一次性 setup 约束）。
 */
export type RouteAccess = "public" | "setup" | "session" | "metrics" | "admin";

/**
 * 路由的应用筛选粒度。
 *
 * 中文
 * ----
 * - `fleet`：页面提供「全部应用」选项，`ALL_APPLICATIONS` 是合法取值。总览、实时监控、
 *   故障分析属于此类——它们可以从应用视角看全局，也可以下钻到单个应用。
 * - `single`：页面必须锁定一个具体应用，不提供「全部应用」选项。应用与实例页的实例
 *   矩阵、规则页的规则清单都属于此类。
 *
 * 这个区分不是 UI 细节：把 `ALL_APPLICATIONS` 喂给一个 `single` 页面，会让下拉框
 * 匹配不到任何选项而退化成占位符，同时后端也拿不到合法的应用作用域。原先这段逻辑
 * 藏在 `App.tsx` 的 `onNav` 里（`if (next === "applications" && appId === "all")`），
 * 属于与路由表重复的第二份事实来源，因此提升为路由元数据。
 */
export type RouteAppFilter = "fleet" | "single";

/** 路由静态元数据。只描述路由本身，不描述页面内容。 */
export interface RouteEntry {
  /** 稳定路由 id。 */
  readonly id: RouteId;
  /** 浏览器 hash 路径，形如 `#/overview`。 */
  readonly path: string;
  /** 进入前置条件。 */
  readonly access: RouteAccess;
  /** 该路由的应用筛选粒度。 */
  readonly appFilter: RouteAppFilter;
  /** 是否出现在主导航条。 */
  readonly inMainNav: boolean;
  /** 主导航排序位；非导航路由为 `null`。 */
  readonly order: number | null;
  /** 界面文案键；由 `core/i18n` 解析，缺键时回退而非显示协议键。 */
  readonly i18nKey: TranslationKey;
}

const entry = (
  id: RouteId,
  access: RouteAccess,
  appFilter: RouteAppFilter,
  inMainNav: boolean,
  order: number | null,
  i18nKey: TranslationKey,
): RouteEntry =>
  Object.freeze({
    id,
    path: `#/${id}`,
    access,
    appFilter,
    inMainNav,
    order,
    i18nKey,
  });

/** 全部路由的静态表，顺序与 {@link ROUTE} 声明顺序一致。 */
export const ROUTES: readonly RouteEntry[] = Object.freeze([
  entry(ROUTE.Overview, "metrics", "fleet", true, 0, "shell.nav.overview"),
  // The authorized observation catalog owns available applications; this page must not
  // fabricate a single-app default from the retired assembly fixture list.
  entry(ROUTE.Applications, "metrics", "fleet", true, 1, "shell.nav.applications"),
  // Rule bindings form a directory across apps; selecting one remains explicit within the page.
  entry(ROUTE.Rules, "metrics", "fleet", true, 2, "shell.nav.rules"),
  entry(ROUTE.Realtime, "metrics", "fleet", true, 3, "shell.nav.realtime"),
  entry(ROUTE.Faults, "metrics", "fleet", true, 4, "shell.nav.faults"),
  entry(ROUTE.System, "admin", "fleet", true, 5, "shell.nav.system"),
  entry(ROUTE.Accounts, "admin", "fleet", false, null, "shell.nav.accounts"),
  entry(ROUTE.Roles, "admin", "fleet", false, null, "shell.nav.roles"),
  entry(ROUTE.ChangePassword, "session", "fleet", false, null, "shell.nav.changePassword"),
  entry(ROUTE.Login, "public", "fleet", false, null, "shell.nav.login"),
  entry(ROUTE.Setup, "setup", "fleet", false, null, "shell.nav.setup"),
]);

const ROUTE_BY_ID: ReadonlyMap<RouteId, RouteEntry> = new Map(
  ROUTES.map((item) => [item.id, item]),
);

/** Runtime guard for local destinations received through an untrusted URL. */
export function isRouteId(value: unknown): value is RouteId {
  return typeof value === "string" && ROUTES.some((item) => item.id === value);
}

/** 主导航路由的有序 id 元组。类型是 `const`，供下游做 `Extract` 穷尽检查。 */
export const MAIN_NAVIGATION_IDS = Object.freeze([
  ROUTE.Overview,
  ROUTE.Applications,
  ROUTE.Rules,
  ROUTE.Realtime,
  ROUTE.Faults,
  ROUTE.System,
] as const);

/** 主导航路由 id 联合；用于让图标表在编译期与导航表保持一致。 */
export type MainNavRouteId = (typeof MAIN_NAVIGATION_IDS)[number];

/** Runtime guard for a route that owns a primary navigation icon. */
export function isMainNavRouteId(value: RouteId): value is MainNavRouteId {
  return MAIN_NAVIGATION_IDS.some((id) => id === value);
}

/** 主导航条目，已按展示顺序排好。 */
export const MAIN_NAVIGATION: readonly RouteEntry[] = Object.freeze(
  ROUTES.filter((item) => item.inMainNav).sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
);

/** 未知路由的回落目标。宁可显示总览，也不渲染未受控视图。 */
export const FALLBACK_ROUTE: RouteId = ROUTE.Overview;

const CONTEXT_KEYS = Object.freeze({
  returnTo: "returnTo",
  environmentId: "env",
  appId: "app",
  range: "range",
  from: "from",
  to: "to",
  accountId: "account",
  view: "view",
  instanceId: "instance",
  resource: "resource",
  eventId: "event",
  incidentSeverity: "severity",
  incidentCategory: "category",
  incidentCursor: "cursor",
  versionId: "version",
  publicationId: "publication",
  bindingId: "binding",
  metricScope: "scope",
  search: "q",
} as const);

/**
 * 构造路由的静态地址，可附带导航上下文。
 *
 * 中文
 * ----
 * 序列化只输出已定义的键，`undefined` 一律省略；`all` 应用选择保留，因为它改变了
 * 页面查询范围。读取端必须按 {@link NavigationContext} 校验，不接受任意 query。
 */
export function pathFor(route: RouteId, context: NavigationContext = {}): string {
  const known = ROUTE_BY_ID.get(route);
  if (!known) {
    throw new TypeError(`Unknown dashboard route: ${String(route)}`);
  }
  const search = new URLSearchParams();
  for (const [field, key] of Object.entries(CONTEXT_KEYS)) {
    if (field === "returnTo" && route !== ROUTE.Login) continue;
    if (
      route !== ROUTE.Faults &&
      (field === "incidentSeverity" || field === "incidentCategory" || field === "incidentCursor")
    )
      continue;
    const value = context[field as keyof NavigationContext];
    if (
      typeof value === "string" &&
      value.length > 0 &&
      (field !== "incidentCursor" || value.length <= MAX_NAVIGATION_CURSOR_LENGTH)
    )
      search.set(key, value);
  }
  const query = search.toString();
  return query ? `${known.path}?${query}` : known.path;
}

/** {@link pathFor} 的解析结果。 */
export interface ParsedRoute {
  /** Explicit nonempty paths outside the catalog are not silently treated as overview. */
  readonly notFound: boolean;
  /** 已校验的路由 id。 */
  readonly route: RouteId;
  /** 已校验的导航上下文；未提供的字段缺省。 */
  readonly context: NavigationContext;
}

const isTimeRange = (value: string): value is TimeRangeId =>
  (TIME_RANGES as readonly string[]).includes(value);

/**
 * 把任意来源的 hash 解析为受控路由与上下文。
 *
 * 中文
 * ----
 * `hash` 可以是完整 `#/x?y=z`、仅 path 段或空串。未识别的 path 段一律回落到
 * {@link FALLBACK_ROUTE}；非法的时间窗口值被丢弃而不是回落到某个「看起来合理」的
 * 窗口，避免用一个用户没选过的口径出图。
 */
export function routeFromPath(hash: string): ParsedRoute {
  const withoutHash = hash.replace(/^#\/?/, "");
  const separator = withoutHash.indexOf("?");
  const rawPath = separator < 0 ? withoutHash : withoutHash.slice(0, separator);
  const rawQuery = separator < 0 ? "" : withoutHash.slice(separator + 1);
  const route = ROUTES.find((item) => item.id === rawPath)?.id ?? FALLBACK_ROUTE;

  const search = new URLSearchParams(rawQuery);
  const appId = search.get(CONTEXT_KEYS.appId);
  const range = search.get(CONTEXT_KEYS.range);
  const from = search.get(CONTEXT_KEYS.from);
  const to = search.get(CONTEXT_KEYS.to);
  const accountId = search.get(CONTEXT_KEYS.accountId);
  const view = search.get(CONTEXT_KEYS.view);
  const environmentId = search.get(CONTEXT_KEYS.environmentId);
  const instanceId = search.get(CONTEXT_KEYS.instanceId);
  const resource = search.get(CONTEXT_KEYS.resource);
  const eventId = search.get(CONTEXT_KEYS.eventId);
  const incidentSeverity = search.get(CONTEXT_KEYS.incidentSeverity);
  const incidentCategory = search.get(CONTEXT_KEYS.incidentCategory);
  const incidentCursor = search.get(CONTEXT_KEYS.incidentCursor);
  const versionId = search.get(CONTEXT_KEYS.versionId);
  const publicationId = search.get(CONTEXT_KEYS.publicationId);
  const bindingId = search.get(CONTEXT_KEYS.bindingId);
  const metricScope = search.get(CONTEXT_KEYS.metricScope);
  const query = search.get(CONTEXT_KEYS.search);
  const returnTo = search.get(CONTEXT_KEYS.returnTo);
  const validReturnTo = route === ROUTE.Login && isRouteId(returnTo) ? returnTo : undefined;

  return {
    route,
    notFound: !!rawPath && !ROUTES.some((item) => item.id === rawPath),
    context: {
      ...(validReturnTo ? { returnTo: validReturnTo } : {}),
      ...(environmentId ? { environmentId } : {}),
      ...(appId ? { appId } : {}),
      ...(range && isTimeRange(range) ? { range } : {}),
      ...(from ? { from } : {}),
      ...(to ? { to } : {}),
      ...(accountId ? { accountId } : {}),
      // `view` 的合法值由拥有它的 feature 判定，这里只保证它是个非空字符串。
      ...(view ? { view } : {}),
      ...(instanceId ? { instanceId } : {}),
      ...(resource ? { resource } : {}),
      ...(eventId ? { eventId } : {}),
      ...(route === ROUTE.Faults && incidentSeverity ? { incidentSeverity } : {}),
      ...(route === ROUTE.Faults && incidentCategory ? { incidentCategory } : {}),
      ...(route === ROUTE.Faults &&
      incidentCursor &&
      incidentCursor.length <= MAX_NAVIGATION_CURSOR_LENGTH
        ? { incidentCursor }
        : {}),
      ...(versionId ? { versionId } : {}),
      ...(publicationId ? { publicationId } : {}),
      ...(bindingId ? { bindingId } : {}),
      ...(metricScope ? { metricScope } : {}),
      ...(query ? { search: query } : {}),
    },
  };
}

/** 返回某路由的访问前置条件；未知路由按需要会话处理，不放行。 */
export function accessFor(route: RouteId): RouteAccess {
  return ROUTE_BY_ID.get(route)?.access ?? "session";
}

/** 返回某路由的应用筛选粒度；未知路由按最宽松处理，不静默锁死。 */
export function appFilterFor(route: RouteId): RouteAppFilter {
  return ROUTE_BY_ID.get(route)?.appFilter ?? "fleet";
}

/**
 * 把当前应用选择收敛到目标路由允许的粒度。
 *
 * 中文
 * ----
 * `single` 路由不接受 `ALL_APPLICATIONS`。此时回落到应用目录里的第一个真实应用，
 * 而不是留在「全部应用」——后者会让下拉框匹配不到选项、页面拿不到合法应用作用域。
 * 目录为空时返回 `undefined`，由调用方决定展示空态。
 */
export function resolveAppIdForRoute(
  route: RouteId,
  appId: string,
  availableAppIds: readonly string[],
): string | undefined {
  if (appFilterFor(route) === "fleet") return appId;
  if (appId !== ALL_APPLICATIONS) return appId;
  return availableAppIds[0];
}
