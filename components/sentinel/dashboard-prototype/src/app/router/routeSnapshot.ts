import {
  ALL_APPLICATIONS,
  TIME_RANGE,
  resolveAppIdForRoute,
  routeFromPath,
  type NavigationContext,
  type RouteId,
  type TimeRangeId,
} from "./route.constants";

/** URL state is authoritative; this value contains no credentials or session permissions. */
export interface RouteSnapshot {
  readonly notFound: boolean;
  readonly route: RouteId;
  readonly appId: string;
  readonly range: TimeRangeId;
  readonly accountId: string;
  readonly view: string;
  readonly context: NavigationContext;
}

/** Defaults come from the assembly owner, not a module-global account identity. */
export interface RouteSnapshotOptions {
  /** Optional catalog for a future single-application route; never filled with demo IDs. */
  readonly applicationScopeIds?: readonly string[];
  readonly defaultAccountId: string;
}

/**
 * One bounded cache per routing owner. Hash AND semantic defaults are part of
 * its identity, so changing session/catalog without changing the URL cannot
 * return another owner's stale account/application. Equal inputs preserve the
 * snapshot reference required by useSyncExternalStore.
 */
export function createRouteSnapshotReader(): (
  hash: string,
  options: RouteSnapshotOptions,
) => RouteSnapshot {
  let previousKey: string | undefined;
  let previous: RouteSnapshot | undefined;
  return (hash, options) => {
    const applicationScopeIds = options.applicationScopeIds ?? [];
    const key = JSON.stringify([hash, options.defaultAccountId, applicationScopeIds]);
    if (key === previousKey && previous) return previous;
    const parsed = routeFromPath(hash);
    const requestedApp = parsed.context.appId ?? ALL_APPLICATIONS;
    const appId =
      resolveAppIdForRoute(parsed.route, requestedApp, applicationScopeIds) ?? ALL_APPLICATIONS;
    previousKey = key;
    previous = Object.freeze({
      route: parsed.route,
      notFound: parsed.notFound,
      appId,
      range: parsed.context.range ?? TIME_RANGE.Last1Hour,
      accountId: parsed.context.accountId ?? options.defaultAccountId,
      view: parsed.context.view ?? "",
      context: Object.freeze(parsed.context),
    });
    return previous;
  };
}
