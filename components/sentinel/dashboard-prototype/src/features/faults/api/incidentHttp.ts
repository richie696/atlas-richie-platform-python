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
import { METRIC_ID } from "../../../shared/model/observation";
import {
  validIncidentQuery,
  validIncidentPage,
  validIncidentDetailQuery,
  validIncidentEvidence,
} from "../model/incidentObservation";
import type { IncidentPort } from "./incidentPort";
import {
  IncidentDetailParametersSchema,
  IncidentDetailQuerySchema,
  IncidentEvidenceSchema,
  IncidentPageSchema,
  IncidentQueryParametersSchema,
  IncidentQuerySchema,
} from "./incidentWire";
import { incidentEvidenceFromWire, incidentPageFromWire } from "./incidentMapper";

export const INCIDENT_ENDPOINTS = Object.freeze({
  Timeline: {
    url: defineUrl("/api/v1/incidents"),
    response: IncidentPageSchema,
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
  } satisfies ConsoleEndpoint<z.infer<typeof IncidentPageSchema>>,
  Evidence: {
    url: defineUrl("/api/v1/incidents/{incidentId}/evidence"),
    response: IncidentEvidenceSchema,
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
  } satisfies ConsoleEndpoint<z.infer<typeof IncidentEvidenceSchema>>,
});
function listContextParameters(context: Parameters<typeof observationContextParameters>[0]) {
  const parameters = observationContextParameters(context);
  return {
    environmentId: parameters.environmentId,
    appId: parameters.appId ?? undefined,
    instanceId: parameters.instanceId ?? undefined,
    scope: parameters.scope,
    from: parameters.from,
    to: parameters.to,
  };
}
export function createIncidentHttp(transport: ConsoleTransport): IncidentPort {
  return Object.freeze({
    async readTimeline(query, signal) {
      if (!validIncidentQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid incident query", {
          status: 400,
          code: "console_request_invalid",
        });
      parseConsoleInput(IncidentQuerySchema, {
        ...query,
        context: observationContextToWire(query.context),
      });
      const value = await transport.send(
        {
          ...INCIDENT_ENDPOINTS.Timeline,
          accept: (wire) => validIncidentPage(incidentPageFromWire(wire), query),
        },
        {
          signal,
          query: parseConsoleInput(IncidentQueryParametersSchema, {
            ...listContextParameters(query.context),
            severity: query.severity ?? undefined,
            category: query.category ?? undefined,
            cursor: query.cursor ?? undefined,
            pageSize: query.pageSize,
          }),
        },
      );
      return incidentPageFromWire(value);
    },
    async readEvidence(query, signal) {
      if (!validIncidentDetailQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid incident evidence query", {
          status: 400,
          code: "console_request_invalid",
        });
      parseConsoleInput(IncidentDetailQuerySchema, {
        ...query,
        context: observationContextToWire(query.context),
      });
      const value = await transport.send(
        {
          ...INCIDENT_ENDPOINTS.Evidence,
          accept: (wire) => validIncidentEvidence(incidentEvidenceFromWire(wire), query),
        },
        {
          signal,
          pathParams: [parseConsoleInput(OpaqueIdentifierSchema, query.eventId)],
          query: parseConsoleInput(IncidentDetailParametersSchema, {
            ...listContextParameters(query.context),
            severity: query.severity ?? undefined,
            category: query.category ?? undefined,
          }),
        },
      );
      return incidentEvidenceFromWire(value);
    },
  } satisfies IncidentPort);
}
