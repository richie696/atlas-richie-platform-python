import { useCallback, useMemo, useSyncExternalStore } from "react";
import { ALL_APPLICATIONS, pathFor, resolveAppIdForRoute } from "./route.constants";
import {
  createRouteSnapshotReader,
  type RouteSnapshot,
  type RouteSnapshotOptions,
} from "./routeSnapshot";
import { writeHashHistory } from "./hashHistory";
import { useHashNavigationController } from "./HashNavigationContext";
import type { Navigate, NavigationContext, TimeRangeId } from "../../shared/types/navigation";
export type { RouteSnapshot } from "./routeSnapshot";
export type UseHashRouteOptions = RouteSnapshotOptions;

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** URL is the state owner; no duplicate filter state or global account/default cache. */
export interface HashRouteBinding extends RouteSnapshot {
  readonly navigate: Navigate;
  readonly setAppId: (appId: string) => void;
  readonly setRange: (range: TimeRangeId) => void;
  readonly setView: (view: string) => void;
}

/**
 * Bind a per-owner snapshot reader to native hash history. Explicit undefined
 * clears a field; omitted fields keep observation context. A page's private
 * view does not leak into a different page. Secrets/permissions are never
 * accepted by the typed/whitelisted serializer.
 */
export function useHashRoute(options: UseHashRouteOptions): HashRouteBinding {
  const controller = useHashNavigationController();
  const read = useMemo(() => createRouteSnapshotReader(), []);
  const getSnapshot = useCallback(
    () =>
      read(
        controller?.getSnapshot().location.hash ??
          (typeof window === "undefined" ? "" : window.location.hash),
        options,
      ),
    [read, options, controller],
  );
  const subscribeRoute = useCallback(
    (listener: () => void) => (controller ? controller.subscribe(listener) : subscribe(listener)),
    [controller],
  );
  const snapshot = useSyncExternalStore(subscribeRoute, getSnapshot, () => read("", options));
  const navigate = useCallback<Navigate>(
    (route, context, historyOptions) => {
      const next: NavigationContext = {
        ...snapshot.context,
        appId: snapshot.appId,
        range: snapshot.range,
        accountId: snapshot.accountId,
        view: route === snapshot.route ? snapshot.view : undefined,
        ...context,
      };
      const target = pathFor(route, {
        ...next,
        appId:
          resolveAppIdForRoute(
            route,
            next.appId ?? ALL_APPLICATIONS,
            options.applicationScopeIds ?? [],
          ) ?? ALL_APPLICATIONS,
      });
      if (controller) controller.request(target, historyOptions);
      else writeHashHistory(target, historyOptions);
    },
    [options.applicationScopeIds, snapshot, controller],
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
