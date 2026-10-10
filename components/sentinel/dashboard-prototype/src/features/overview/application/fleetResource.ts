import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import {
  createQueryResource,
  type QueryResourceOptions,
} from "../../../shared/state/queryResource";
import { OBSERVATION_QUALITY } from "../../../shared/model/observation";
import type { FleetPort } from "../api/fleetPort";
import {
  fleetQueryKey,
  validFleetQuery,
  validFleetSnapshot,
  type FleetQuery,
  type FleetSnapshot,
} from "../model/fleet";

/** One read owner for cards, table, trends and dependency probes; no independently invented summary values. */
export function createFleetResource(
  port: FleetPort,
  access?: QueryAccessObserver,
  options: { readonly timeoutMs?: number } = {},
) {
  const resourceOptions: QueryResourceOptions<FleetQuery, FleetSnapshot> = {
    keyOf: fleetQueryKey,
    timeoutMs: options.timeoutMs,
    async read(query, signal) {
      if (!validFleetQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid fleet query", {
          status: 400,
          code: "invalid_observation_query",
        });
      const value = await port.readFleet(query, signal);
      if (!validFleetSnapshot(value, query))
        throw new AppError(AppErrorKind.PROTOCOL, "Inconsistent fleet observation", {
          status: 502,
          code: "invalid_observation",
        });
      return value;
    },
    classify: (value) =>
      value.totalApplications === 0
        ? "empty"
        : value.applications.items.length === 0 && !!value.query.search
          ? "filtered-empty"
          : value.coverage.expected === null ||
              value.coverage.reporting < value.coverage.expected ||
              value.metrics.summary.some((item) => item.quality !== OBSERVATION_QUALITY.Available)
            ? "partial"
            : "ready",
  };
  // The optional observer is only a UI data-retention guard. Server authorization
  // remains authoritative; callers without a session owner still use the same
  // cancellable HTTP resource and must not infer access from this client state.
  return access
    ? createOwnedQueryResource<FleetQuery, FleetSnapshot>(access, resourceOptions)
    : createQueryResource<FleetQuery, FleetSnapshot>(resourceOptions);
}
