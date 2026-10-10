/** Formal internal system read entry; no prototype fixture or synchronous gateway. */
export { createSystemObservationResources } from "./application/systemObservationResources";
export { ObservedConnectionsPanel } from "./ui/ObservedConnectionsPanel";
export { ObservedProtocolsPanel } from "./ui/ObservedProtocolsPanel";
export { ObservedAuditPanel } from "./ui/ObservedAuditPanel";
export { ObservedPermissionsPanel } from "./ui/ObservedPermissionsPanel";
export type {
  SystemHealthPort,
  SystemProtocolPort,
  SystemAuditPort,
} from "./api/systemObservationPort";
export type {
  SystemConnections,
  SystemProtocols,
  AuditQuery,
  AuditPage,
} from "./model/systemObservation";
