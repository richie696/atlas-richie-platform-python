import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import { OpaqueIdentifierSchema } from "../../../core/api/protocol/common";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import {
  observationContextParameters,
  observationContextToWire,
} from "../../../shared/api/observationMapper";
import {
  validInstanceCatalog,
  validInstanceCatalogQuery,
  validInstanceDetailQuery,
  validInstanceObservation,
} from "../model/instanceObservation";
import type { InstancePort } from "./instancePort";
import {
  InstanceCatalogParametersSchema,
  InstanceCatalogQuerySchema,
  InstanceCatalogSchema,
  InstanceDetailParametersSchema,
  InstanceDetailQuerySchema,
  InstanceObservationSchema,
} from "./instanceWire";
import { instanceCatalogFromWire, instanceObservationFromWire } from "./instanceMapper";

export const INSTANCE_ENDPOINTS = Object.freeze({
  Catalog: {
    url: defineUrl("/api/v1/instances"),
    response: InstanceCatalogSchema,
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
  } satisfies ConsoleEndpoint<z.infer<typeof InstanceCatalogSchema>>,
  Detail: {
    url: defineUrl("/api/v1/instances/{instanceId}"),
    response: InstanceObservationSchema,
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
      "target_retired",
      "rate_limited",
      "service_unavailable",
    ],
  } satisfies ConsoleEndpoint<z.infer<typeof InstanceObservationSchema>>,
});
export function createInstanceHttp(transport: ConsoleTransport): InstancePort {
  return Object.freeze({
    async readCatalog(query, signal) {
      if (!validInstanceCatalogQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid instance query", {
          status: 400,
          code: "console_request_invalid",
        });
      parseConsoleInput(InstanceCatalogQuerySchema, {
        ...query,
        context: observationContextToWire(query.context),
      });
      const contextParameters = observationContextParameters(query.context);
      const value = await transport.send(
        {
          ...INSTANCE_ENDPOINTS.Catalog,
          accept: (wire) => validInstanceCatalog(instanceCatalogFromWire(wire), query),
        },
        {
          signal,
          query: parseConsoleInput(InstanceCatalogParametersSchema, {
            environmentId: contextParameters.environmentId,
            ...(contextParameters.appId === undefined ? {} : { appId: contextParameters.appId }),
            scope: contextParameters.scope,
            from: contextParameters.from,
            to: contextParameters.to,
            page: query.page,
            pageSize: query.pageSize,
            search: query.search,
            attentionOnly: query.attentionOnly,
          }),
        },
      );
      return instanceCatalogFromWire(value);
    },
    async readInstance(query, signal) {
      if (!validInstanceDetailQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid instance detail query", {
          status: 400,
          code: "console_request_invalid",
        });
      parseConsoleInput(InstanceDetailQuerySchema, {
        ...query,
        context: observationContextToWire(query.context),
      });
      const { instanceId: pathIdentity, ...contextParameters } = observationContextParameters(
        query.context,
      );
      const target = parseConsoleInput(OpaqueIdentifierSchema, pathIdentity);
      const requestQuery = parseConsoleInput(InstanceDetailParametersSchema, {
        ...contextParameters,
        appId: query.context.appId,
        processEpoch: query.processEpoch,
        stepMs: query.stepMs,
      });
      try {
        const value = await transport.send(
          {
            ...INSTANCE_ENDPOINTS.Detail,
            accept: (wire) => validInstanceObservation(instanceObservationFromWire(wire), query),
          },
          { signal, pathParams: [target], query: requestQuery },
        );
        return instanceObservationFromWire(value);
      } catch (cause) {
        if (cause instanceof AppError && cause.code === "target_retired")
          throw new AppError(AppErrorKind.SERVER, "Instance process incarnation changed", {
            status: 409,
            code: "instance_incarnation_changed",
            requestId: cause.requestId,
          });
        throw cause;
      }
    },
  } satisfies InstancePort);
}
