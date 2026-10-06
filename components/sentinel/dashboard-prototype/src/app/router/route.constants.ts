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

/** 稳定路由标识。值即 URL path 段，便于人工阅读和排障。 */
export const ROUTE = Object.freeze({
  Overview: "overview",
  Applications: "applications",
  Rules: "rules",
  Realtime: "realtime",
  Faults: "faults",
  System: "system",
  Accounts: "accounts",
  Roles: "roles",
  ChangePassword: "change-password",
  Login: "login",
  Setup: "setup",
} as const);

/** {@link ROUTE} 的值联合。 */
export type RouteId = (typeof ROUTE)[keyof typeof ROUTE];

/**
 * 进入路由的前置条件。
 *
 * - `none`：任何访客可达。
 * - `session`：需要已登录会话；未登录时守卫重定向到 {@link ROUTE.Login}。
 * - `setup`：仅在服务端尚未初始化时开放。初始化成功后服务端关闭该窗口，
 *   守卫必须把深链重定向到 {@link ROUTE.Login}（见 `AGENTS.md` 一次性 setup 约束）。
 */
export type RouteAccess = "none" | "session" | "setup";

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
  readonly i18nKey: string;
}

const entry = (
  id: RouteId,
  access: RouteAccess,
  appFilter: RouteAppFilter,
  inMainNav: boolean,
  order: number | null,
  i18nKey: string,
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
  entry(ROUTE.Overview, "session", "fleet", true, 0, "shell.nav.overview"),
  entry(ROUTE.Applications, "session", "single", true, 1, "shell.nav.applications"),
  entry(ROUTE.Rules, "session", "single", true, 2, "shell.nav.rules"),
  entry(ROUTE.Realtime, "session", "fleet", true, 3, "shell.nav.realtime"),
  entry(ROUTE.Faults, "session", "fleet", true, 4, "shell.nav.faults"),
  entry(ROUTE.System, "session", "fleet", true, 5, "shell.nav.system"),
  entry(ROUTE.Accounts, "session", "fleet", false, null, "shell.nav.accounts"),
  entry(ROUTE.Roles, "session", "fleet", false, null, "shell.nav.roles"),
  entry(ROUTE.ChangePassword, "session", "fleet", false, null, "shell.nav.changePassword"),
  entry(ROUTE.Login, "none", "fleet", false, null, "shell.nav.login"),
  entry(ROUTE.Setup, "setup", "fleet", false, null, "shell.nav.setup"),
]);

const ROUTE_BY_ID: ReadonlyMap<RouteId, RouteEntry> = new Map(
  ROUTES.map((item) => [item.id, item]),
);

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

/** 主导航条目，已按展示顺序排好。 */
export const MAIN_NAVIGATION: readonly RouteEntry[] = Object.freeze(
  ROUTES.filter((item) => item.inMainNav).sort(
    (a, b) => (a.order ?? 0) - (b.order ?? 0),
  ),
);

/** 未知路由的回落目标。宁可显示总览，也不渲染未受控视图。 */
export const FALLBACK_ROUTE: RouteId = ROUTE.Overview;

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
export const TIME_RANGE_LABEL_KEY: Readonly<Record<TimeRangeId, string>> = Object.freeze({
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
  /** 选中的应用 id；`all` 表示不限定应用。 */
  readonly appId?: string;
  /** 选中的时间窗口。 */
  readonly range?: TimeRangeId;
  /** 身份页正在操作的账号 id。 */
  readonly accountId?: string;
  /**
   * 路由内的子视图标识（系统管理的 tab 等）。
   *
   * 用稳定 id 而不是展示文案：文案会随语言与改版变化，进了 URL 就等于把展示层
   * 绑进深链。合法值集合由**拥有该视图的 feature** 校验（见
   * `features/system/model/systemStatus.ts` 的 `resolveSystemTab`），路由边界不认识
   * 任何页面的具体 tab，因此只做「非空字符串」这一层解析。
   */
  readonly view?: string;
}

const CONTEXT_KEYS = Object.freeze({
  appId: "app",
  range: "range",
  accountId: "account",
  view: "view",
} as const);

/** 全局不限定应用的哨兵值。它是协议值，不是展示文案。 */
export const ALL_APPLICATIONS = "all";

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
    const value = context[field as keyof NavigationContext];
    if (typeof value === "string" && value.length > 0) search.set(key, value);
  }
  const query = search.toString();
  return query ? `${known.path}?${query}` : known.path;
}

/** {@link pathFor} 的解析结果。 */
export interface ParsedRoute {
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
  const [rawPath, rawQuery = ""] = withoutHash.split("?", 2);
  const route = (ROUTES.find((item) => item.id === rawPath)?.id ?? FALLBACK_ROUTE);

  const search = new URLSearchParams(rawQuery);
  const appId = search.get(CONTEXT_KEYS.appId);
  const range = search.get(CONTEXT_KEYS.range);
  const accountId = search.get(CONTEXT_KEYS.accountId);
  const view = search.get(CONTEXT_KEYS.view);

  return {
    route,
    context: {
      ...(appId ? { appId } : {}),
      ...(range && isTimeRange(range) ? { range } : {}),
      ...(accountId ? { accountId } : {}),
      // `view` 的合法值由拥有它的 feature 判定，这里只保证它是个非空字符串。
      ...(view ? { view } : {}),
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

/**
 * 依据当前状态解析实际应展示的路由。
 *
 * 中文
 * ----
 * 这是守卫的唯一决策点：未登录一律去登录页；setup 只在服务端报告未初始化时可达。
 * 守卫不做网络请求——会话与初始化状态由 `core/session` 提供快照。
 */
export function resolveAccessibleRoute(
  requested: RouteId,
  session: { readonly authenticated: boolean; readonly initialized: boolean },
): RouteId {
  const access = accessFor(requested);
  if (access === "none") return requested;
  if (access === "setup") {
    return session.initialized ? ROUTE.Login : requested;
  }
  return session.authenticated ? requested : ROUTE.Login;
}
