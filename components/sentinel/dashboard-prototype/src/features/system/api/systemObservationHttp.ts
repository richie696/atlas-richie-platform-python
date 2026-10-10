import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import {
  validAuditPage,
  validAuditQuery,
  validSystemConnections,
  validSystemProtocols,
} from "../model/systemObservation";
import type {
  SystemAuditPort,
  SystemHealthPort,
  SystemProtocolPort,
} from "./systemObservationPort";
import {
  AuditPageSchema,
  AuditQueryParametersSchema,
  SystemConnectionsSchema,
  SystemProtocolsSchema,
} from "./systemObservationWire";
import {
  auditPageFromWire,
  auditQueryToWire,
  systemConnectionsFromWire,
  systemProtocolsFromWire,
} from "./systemObservationMapper";

const sessionReadErrors = ["invalid_request", "unauthenticated", "service_unavailable"] as const;
const adminReadErrors = [...sessionReadErrors, "forbidden"] as const;
export const SYSTEM_OBSERVATION_ENDPOINTS = Object.freeze({
  Connections: {
    url: defineUrl("/api/v1/system/connections"),
    response: SystemConnectionsSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: sessionReadErrors,
  } satisfies ConsoleEndpoint<z.infer<typeof SystemConnectionsSchema>>,
  Protocols: {
    url: defineUrl("/api/v1/system/protocols"),
    response: SystemProtocolsSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: sessionReadErrors,
  } satisfies ConsoleEndpoint<z.infer<typeof SystemProtocolsSchema>>,
  Audit: {
    url: defineUrl("/api/v1/system/audit"),
    response: AuditPageSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: adminReadErrors,
  } satisfies ConsoleEndpoint<z.infer<typeof AuditPageSchema>>,
});
const invalidInput = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid system observation query", {
    status: 400,
    code: "console_request_invalid",
  });
export function createSystemObservationHttp(transport: ConsoleTransport): {
  readonly health: SystemHealthPort;
  readonly protocols: SystemProtocolPort;
  readonly audit: SystemAuditPort;
} {
  return Object.freeze({
    health: Object.freeze({
      async readConnections(signal: AbortSignal) {
        const wire = await transport.send(SYSTEM_OBSERVATION_ENDPOINTS.Connections, { signal });
        const value = systemConnectionsFromWire(wire);
        if (!validSystemConnections(value))
          throw new AppError(AppErrorKind.PROTOCOL, "Invalid system connections", {
            status: 502,
            code: "console_response_invalid",
          });
        return value;
      },
    }),
    protocols: Object.freeze({
      async readProtocols(signal: AbortSignal) {
        const wire = await transport.send(SYSTEM_OBSERVATION_ENDPOINTS.Protocols, { signal });
        const value = systemProtocolsFromWire(wire);
        if (!validSystemProtocols(value))
          throw new AppError(AppErrorKind.PROTOCOL, "Invalid system protocols", {
            status: 502,
            code: "console_response_invalid",
          });
        return value;
      },
    }),
    audit: Object.freeze({
      async readAudit(query: Parameters<SystemAuditPort["readAudit"]>[0], signal: AbortSignal) {
        if (!validAuditQuery(query)) throw invalidInput();
        const wireQuery = parseConsoleInput(AuditQueryParametersSchema, auditQueryToWire(query));
        const wire = await transport.send(
          {
            ...SYSTEM_OBSERVATION_ENDPOINTS.Audit,
            accept: (response) => validAuditPage(auditPageFromWire(response), query),
          },
          { signal, query: wireQuery },
        );
        return auditPageFromWire(wire);
      },
    }),
  });
}
