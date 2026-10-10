import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import {
  observationContextToWire,
  observationContextParameters,
} from "../../../shared/api/observationMapper";
import { validFleetQuery, validFleetSnapshot } from "../model/fleet";
import type { FleetPort } from "./fleetPort";
import { FleetSnapshotSchema, FleetQuerySchema, FleetParametersSchema } from "./fleetWire";
import { fleetSnapshotFromWire } from "./fleetMapper";

export const FLEET_ENDPOINT: ConsoleEndpoint<z.infer<typeof FleetSnapshotSchema>> = {
  url: defineUrl("/api/v1/fleet/overview"),
  response: FleetSnapshotSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "not_found",
    "rate_limited",
    "service_unavailable",
  ],
};
/** Whole-scope totals are server facts. Never aggregate a page or turn absent readings into zero. */
export function createFleetHttp(transport: ConsoleTransport): FleetPort {
  return Object.freeze({
    async readFleet(query, signal) {
      if (!validFleetQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid fleet query", {
          status: 400,
          code: "console_request_invalid",
        });
      parseConsoleInput(FleetQuerySchema, {
        ...query,
        context: observationContextToWire(query.context),
      });
      const { environmentId, appId, scope, from, to } = observationContextParameters(query.context);
      const value = await transport.send(
        {
          ...FLEET_ENDPOINT,
          accept: (wire) => validFleetSnapshot(fleetSnapshotFromWire(wire), query),
        },
        {
          signal,
          query: parseConsoleInput(FleetParametersSchema, {
            environmentId,
            appId,
            scope,
            from,
            to,
            page: query.page,
            pageSize: query.pageSize,
            search: query.search,
            stepMs: query.stepMs,
          }),
        },
      );
      return fleetSnapshotFromWire(value);
    },
  } satisfies FleetPort);
}
