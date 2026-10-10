import type {
  SystemConnections,
  SystemProtocols,
  AuditPage,
  AuditQuery,
} from "../model/systemObservation";
/** Consumer read contracts only. Transport decoding/schema freeze belongs to F6. */
export interface SystemHealthPort {
  readConnections(signal: AbortSignal): Promise<SystemConnections>;
}
export interface SystemProtocolPort {
  readProtocols(signal: AbortSignal): Promise<SystemProtocols>;
}
export interface SystemAuditPort {
  readAudit(query: AuditQuery, signal: AbortSignal): Promise<AuditPage>;
}

/** Complete read capability required by the system-observation page. */
export interface SystemObservationPorts {
  readonly health: SystemHealthPort;
  readonly protocols: SystemProtocolPort;
  readonly audit: SystemAuditPort;
}
