import type { RouteId } from "./route.constants";

/**
 * Build the React page-owner identity from the route and the server-confirmed session.
 *
 * A session change must remount page-owned query resources even when the user remains
 * authorized for the same route. `sessionEpoch` is an opaque, non-secret server fact;
 * `null` represents routes rendered without an authenticated identity.
 */
export function routePageOwnerKey(route: RouteId, sessionEpoch: string | null): string {
  return JSON.stringify([route, sessionEpoch]);
}
