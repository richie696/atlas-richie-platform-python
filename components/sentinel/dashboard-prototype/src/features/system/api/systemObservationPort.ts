import type {
  SystemConnections,
  SystemProtocols,
  AgentReportingObservationPage,
  IncidentEventObservationPage,
  AuditPage,
  AuditQuery,
} from "../model/systemObservation";
import type { DeploymentGuidesSnapshot } from "../model/deploymentGuide";
/** Consumer read contracts only. Transport decoding/schema freeze belongs to F6. */
export interface SystemHealthPort {
  readConnections(signal: AbortSignal): Promise<SystemConnections>;
}
export interface DeploymentGuidesPort {
  readDeploymentGuides(signal: AbortSignal): Promise<DeploymentGuidesSnapshot>;
}
export interface SystemProtocolPort {
  readProtocols(signal: AbortSignal): Promise<SystemProtocols>;
  readAgentReportingObservations(
    page: number,
    pageSize: number,
    signal: AbortSignal,
  ): Promise<AgentReportingObservationPage>;
  readIncidentEventObservations(
    page: number,
    pageSize: number,
    signal: AbortSignal,
  ): Promise<IncidentEventObservationPage>;
}
export interface SystemAuditPort {
  readAudit(query: AuditQuery, signal: AbortSignal): Promise<AuditPage>;
}

/** Complete read capability required by the system-observation page. */
export interface SystemObservationPorts {
  readonly health: SystemHealthPort;
  readonly deploymentGuides: DeploymentGuidesPort;
  readonly protocols: SystemProtocolPort;
  readonly audit: SystemAuditPort;
}
