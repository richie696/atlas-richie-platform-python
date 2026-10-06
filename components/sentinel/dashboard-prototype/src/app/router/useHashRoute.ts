/**
 * 把 hash 路由解析成一个受控快照，供应用壳与页面共享。
 *
 * 中文
 * ----
 * 旧实现在 `App.tsx` 里用五个 `useState`（`route` / `appId` / `range` / `accountId` /
 * `view`）保存导航状态，再用一个 `hashchange` effect 把 URL 同步进来，并用
 * `navigate()` 手动再同步一次。问题不在于多写了几行，而在于**同一事实有两份**：
 *
 * - URL（可分享、可刷新恢复、深链可直达）
 * - 组件 state（刷新即失真、与 URL 之间靠 effect 双向搬运）
 *
 * 两份副本必然漂移。可分享的导航上下文只有一个合法来源，就是 URL——`route.constants.ts`
 * 已经提供了 `routeFromPath`（纯函数）承担全部解析与校验。因此这里不再复制状态，
 * 而是**订阅** URL：hash 变了就重新解析，没变就返回同一个快照引用。
 *
 * ## 为什么用 `useSyncExternalStore`
 *
 * hash 是 React 之外的可变外部状态。`useState` + `useEffect` 需要一份 state 副本来
 * 承接变化，而副本正是要消除的东西。`useSyncExternalStore` 直接读外部快照，不在
 * 组件里留第二份；它还保证并发渲染下读到的是同一份数据。
 *
 * ## 快照必须引用稳定
 *
 * `getSnapshot` 在每次渲染都会被调用。若每次都新建对象，React 会认为快照一直在变，
 * 触发无限重渲染。这里按 hash 字符串缓存解析结果，hash 不变就返回同一个引用。
 * 这与 `features/identity` 的 `accountStore.getSnapshot` 是同一条纪律：未变化时
 * 返回同一引用，否则订阅方无法判断「是否真的变了」。
 *
 * ## 页面级 setter 的语义变化
 *
 * 页面过去收到 `setAppId` / `setRange`，直接改本地 state。现在它们是**命令**：
 * 写回 URL，由订阅机制把新值送回。页面调用方式不变，行为契约变成「筛选状态可分享、
 * 刷新可恢复」——这本来就是这些值应有的性质。
 */
import { useCallback, useSyncExternalStore } from "react";

import {
  ALL_APPLICATIONS,
  pathFor,
  resolveAppIdForRoute,
  routeFromPath,
  TIME_RANGE,
  type NavigationContext,
  type RouteId,
  type TimeRangeId,
} from "./route.constants";

/** 解析后的导航快照：已校验、可直接下发给页面。 */
export interface RouteSnapshot {
  readonly route: RouteId;
  /** 已按路由粒度收敛过的应用 id。 */
  readonly appId: string;
  readonly range: TimeRangeId;
  readonly accountId: string;
  /** 路由内子视图；无子视图时为空串。 */
  readonly view: string;
  /** 原始 query 上下文，写回 URL 时作为基线。 */
  readonly context: NavigationContext;
}

export interface UseHashRouteOptions {
  /** 全部合法应用 id；`single` 路由从「全部应用」回落时取第一个。 */
  readonly applicationScopeIds: readonly string[];
  /** 无账号上下文时的默认账号。 */
  readonly defaultAccountId: string;
}

/** 未知/缺失时使用的缺省值。集中在这里，避免散落到调用点各自决定。 */
const DEFAULTS = Object.freeze({
  appId: ALL_APPLICATIONS,
  range: TIME_RANGE.Last1Hour,
  accountId: "account-admin",
  view: "",
} as const);

let cachedHash: string | null = null;
let cachedSnapshot: RouteSnapshot | null = null;

/**
 * 按当前 hash 解析快照，并在 hash 未变时复用上次结果。
 *
 * 中文
 * ----
 * 纯函数式依赖之外只保留「上一次解析结果」这一个可变的缓存格——它的键是完整的
 * hash 字符串，命中率判定与真值无关，因此不会成为第二份事实：只要 hash 变了，
 * 缓存立即失效并重新解析。
 */
function readSnapshot(options: UseHashRouteOptions): RouteSnapshot {
  const hash = typeof window === "undefined" ? "" : window.location.hash;
  if (hash === cachedHash && cachedSnapshot) return cachedSnapshot;

  const parsed = routeFromPath(hash);
  const appId =
    (parsed.context.appId
      ? resolveAppIdForRoute(parsed.route, parsed.context.appId, options.applicationScopeIds)
      : undefined) ?? DEFAULTS.appId;

  cachedHash = hash;
  cachedSnapshot = Object.freeze({
    route: parsed.route,
    appId,
    range: parsed.context.range ?? DEFAULTS.range,
    accountId: parsed.context.accountId ?? DEFAULTS.accountId,
    view: parsed.context.view ?? DEFAULTS.view,
    context: parsed.context,
  });
  return cachedSnapshot;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** 仅供测试重置模块级缓存；生产代码不应调用。 */
export function __resetRouteCache(): void {
  cachedHash = null;
  cachedSnapshot = null;
}

export interface HashRouteBinding extends RouteSnapshot {
  /** 写入新的 hash。唯一的状态变更入口。 */
  readonly navigate: (route: RouteId, context?: NavigationContext) => void;
  /** 页面级筛选命令：只改对应字段，其余上下文原样保留。 */
  readonly setAppId: (appId: string) => void;
  readonly setRange: (range: TimeRangeId) => void;
  readonly setView: (view: string) => void;
}

export function useHashRoute(options: UseHashRouteOptions): HashRouteBinding {
  const snapshot = useSyncExternalStore(subscribe, () => readSnapshot(options));

  const write = useCallback(
    (nextRoute: RouteId, nextContext: NavigationContext) => {
      const target = pathFor(nextRoute, nextContext);
      if (target === window.location.hash) return;
      window.location.hash = target;
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [],
  );

  const navigate = useCallback(
    (route: RouteId, context?: NavigationContext) => {
      const nextAppId = context?.appId ?? snapshot.appId;
      // 关键：区分「本次调用没提 view」和「本次调用要求清空 view」。
      //
      // 旧实现用 `context?.view ?? snapshot.view`，于是 `view: undefined` 被当成
      // 「不修改」——`RulesPage` 切回「全部类型」时正好传 `undefined`，结果旧的
      // `view=degrade` 原样留在 URL，下拉框和目录都不变，该选项彻底失效。
      //
      // 这里用 `'view' in context` 判定：键存在就以此为准（空串 = 清空），
      // 键不存在才沿用当前值。调用方想「保持不变」就整个省略这个键。
      const nextView =
        context && "view" in context ? context.view : snapshot.view;
      write(
        route,
        resolveNavigationContext({
          ...snapshot.context,
          ...context,
          // single 路由不接受「全部应用」：收敛到一个真实应用，避免下拉框无匹配项。
          appId:
            resolveAppIdForRoute(route, nextAppId, options.applicationScopeIds) ??
            DEFAULTS.appId,
          accountId: context?.accountId ?? snapshot.accountId,
          range: context?.range ?? snapshot.range,
          view: nextView,
        }),
      );
    },
    [options.applicationScopeIds, snapshot, write],
  );

  const setAppId = useCallback(
    (appId: string) => navigate(snapshot.route, { appId }),
    [navigate, snapshot.route],
  );
  const setRange = useCallback(
    (range: TimeRangeId) => navigate(snapshot.route, { range }),
    [navigate, snapshot.route],
  );
  const setView = useCallback(
    (view: string) => navigate(snapshot.route, { view }),
    [navigate, snapshot.route],
  );

  return { ...snapshot, navigate, setAppId, setRange, setView };
}

/**
 * 丢掉空值后再序列化。
 *
 * 中文
 * ----
 * `view` 为空串时必须省略，否则 URL 会出现 `view=` 这种空参数，与旧实现
 * （`...(nextView ? { view: nextView } : {})`）行为一致。
 */
function resolveNavigationContext(context: NavigationContext): NavigationContext {
  return {
    ...(context.appId ? { appId: context.appId } : {}),
    ...(context.range ? { range: context.range } : {}),
    ...(context.accountId ? { accountId: context.accountId } : {}),
    ...(context.view ? { view: context.view } : {}),
  };
}
