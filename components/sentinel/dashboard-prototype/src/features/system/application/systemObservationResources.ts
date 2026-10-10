import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type {
  SystemHealthPort,
  SystemProtocolPort,
  SystemAuditPort,
} from "../api/systemObservationPort";
import {
  validSystemConnections,
  connectionProbeExpired,
  connectionCoverageComplete,
  validSystemProtocols,
  protocolCoverageComplete,
  validAuditQuery,
  validAuditPage,
  auditQueryKey,
  HEALTH_STATE,
  PROTOCOL_COMPATIBILITY,
  type SystemConnections,
  type SystemProtocols,
  type AuditQuery,
  type AuditPage,
} from "../model/systemObservation";
const invalid = (status: number) =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid system observation", {
    status,
    code: "system_read_invalid",
  });
/** Independent keys/failures: unavailable Collector never makes a Nacos probe or audit query unavailable. */
export function createSystemObservationResources(
  ports: {
    readonly health: SystemHealthPort;
    readonly protocols: SystemProtocolPort;
    readonly audit: SystemAuditPort;
  },
  access: { readonly system: QueryAccessObserver; readonly audit: QueryAccessObserver },
) {
  const connections = createOwnedQueryResource<null, SystemConnections>(access.system, {
    keyOf: () => "connections",
    async read(_query, signal) {
      const value = await ports.health.readConnections(signal);
      if (!validSystemConnections(value)) throw invalid(502);
      return value;
    },
    classify: (value) =>
      value.items.length === 0
        ? "empty"
        : !connectionCoverageComplete(value) ||
            value.items.some(
              (item) =>
                item.state !== HEALTH_STATE.Available ||
                item.expiresAtMs === null ||
                connectionProbeExpired(item, value.asOfMs),
            )
          ? "partial"
          : "ready",
  });
  const protocols = createOwnedQueryResource<null, SystemProtocols>(access.system, {
    keyOf: () => "protocols",
    async read(_query, signal) {
      const value = await ports.protocols.readProtocols(signal);
      if (!validSystemProtocols(value)) throw invalid(502);
      return value;
    },
    classify: (value) =>
      value.items.length === 0
        ? "empty"
        : !protocolCoverageComplete(value) ||
            value.items.some((item) => item.compatibility !== PROTOCOL_COMPATIBILITY.Compatible)
          ? "partial"
          : "ready",
  });
  const audit = createOwnedQueryResource<AuditQuery, AuditPage>(access.audit, {
    keyOf: auditQueryKey,
    async read(query, signal) {
      if (!validAuditQuery(query)) throw invalid(422);
      const value = await ports.audit.readAudit(query, signal);
      if (!validAuditPage(value, query)) throw invalid(502);
      return value;
    },
    classify: (value) =>
      value.items.length
        ? "ready"
        : value.total || value.query.actorId || value.query.action || value.query.result
          ? "filtered-empty"
          : "empty",
  });
  return Object.freeze({
    connections,
    protocols,
    audit,
    dispose() {
      connections.dispose();
      protocols.dispose();
      audit.dispose();
    },
  });
}
