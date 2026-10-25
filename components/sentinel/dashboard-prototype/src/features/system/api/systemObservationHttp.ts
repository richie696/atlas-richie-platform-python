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
  validAgentReportingObservationPage,
  validIncidentEventObservationPage,
} from "../model/systemObservation";
import { validDeploymentGuides } from "../model/deploymentGuide";
import type {
  SystemAuditPort,
  DeploymentGuidesPort,
  SystemHealthPort,
  SystemProtocolPort,
} from "./systemObservationPort";
import type { AgentReportingObservationPage } from "../model/agentReportingObservation";
import type { IncidentEventObservationPage } from "../model/incidentEventObservation";
import {
  AuditPageSchema,
  AuditQueryParametersSchema,
  SystemConnectionsSchema,
  DeploymentGuidesSchema,
  SystemProtocolsSchema,
  AgentReportingObservationPageSchema,
  IncidentEventObservationPageSchema,
} from "./systemObservationWire";
import {
  auditPageFromWire,
  auditQueryToWire,
  systemConnectionsFromWire,
  deploymentGuidesFromWire,
  systemProtocolsFromWire,
  agentReportingObservationsFromWire,
  incidentEventObservationsFromWire,
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
  DeploymentGuides: {
    url: defineUrl("/api/v1/system/deployment-guides"),
    response: DeploymentGuidesSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: sessionReadErrors,
  } satisfies ConsoleEndpoint<z.infer<typeof DeploymentGuidesSchema>>,
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
  AgentReporting: {
    url: defineUrl("/api/v2/system/protocol-observations/agent-reporting"),
    response: AgentReportingObservationPageSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: sessionReadErrors,
  } satisfies ConsoleEndpoint<z.infer<typeof AgentReportingObservationPageSchema>>,
  IncidentEvents: {
    url: defineUrl("/api/v2/system/protocol-observations/incident-events"),
    response: IncidentEventObservationPageSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: sessionReadErrors,
  } satisfies ConsoleEndpoint<z.infer<typeof IncidentEventObservationPageSchema>>,
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
function assertProtocolObservationPage(page: number, pageSize: number): void {
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    !Number.isSafeInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100
  )
    throw invalidInput();
}
export function createSystemObservationHttp(transport: ConsoleTransport): {
  readonly health: SystemHealthPort;
  readonly deploymentGuides: DeploymentGuidesPort;
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
    deploymentGuides: Object.freeze({
      async readDeploymentGuides(signal: AbortSignal) {
        const wire = await transport.send(SYSTEM_OBSERVATION_ENDPOINTS.DeploymentGuides, {
          signal,
        });
        const value = deploymentGuidesFromWire(wire);
        if (!validDeploymentGuides(value))
          throw new AppError(AppErrorKind.PROTOCOL, "Invalid deployment guide facts", {
            status: 502,
            code: "deployment_guide_read_invalid",
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
      async readAgentReportingObservations(
        page: number,
        pageSize: number,
        signal: AbortSignal,
      ): Promise<AgentReportingObservationPage> {
        assertProtocolObservationPage(page, pageSize);
        const wire = await transport.send(SYSTEM_OBSERVATION_ENDPOINTS.AgentReporting, {
          signal,
          query: { page, pageSize },
        });
        const value = agentReportingObservationsFromWire(wire);
        if (!validAgentReportingObservationPage(value))
          throw new AppError(AppErrorKind.PROTOCOL, "Invalid worker protocol observations", {
            status: 502,
            code: "console_response_invalid",
          });
        return value;
      },
      async readIncidentEventObservations(
        page: number,
        pageSize: number,
        signal: AbortSignal,
      ): Promise<IncidentEventObservationPage> {
        assertProtocolObservationPage(page, pageSize);
        const wire = await transport.send(SYSTEM_OBSERVATION_ENDPOINTS.IncidentEvents, {
          signal,
          query: { page, pageSize },
        });
        const value = incidentEventObservationsFromWire(wire);
        if (!validIncidentEventObservationPage(value))
          throw new AppError(AppErrorKind.PROTOCOL, "Invalid Incident Event observations", {
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
