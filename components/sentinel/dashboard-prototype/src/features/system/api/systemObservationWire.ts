import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  TotalCountSchema,
  UtcInstantSchema,
} from "../../../core/api/protocol/common";
import {
  AUDIT_ACTION,
  AUDIT_MAX_PAGE_SIZE,
  AUDIT_MAX_WINDOW_MS,
  AUDIT_RESULT,
} from "../model/systemObservation";
import {
  CONFIG_PROVIDER,
  HEALTH_CAPABILITY,
  HEALTH_REASON,
  HEALTH_STATE,
} from "../model/connectionObservation";
import { CONNECTION_KIND } from "../model/systemStatus";
import {
  PROTOCOL_BOUNDARY_COUNT,
  PROTOCOL_BOUNDARY_IDS,
  PROTOCOL_COMPATIBILITY,
  MAX_SUPPORTED_PROTOCOL_VERSIONS,
} from "../model/protocolObservation";
import { SYSTEM_COLLECTION_LIMIT } from "../model/systemReadGuards";
import { validAuditActor } from "../model/auditObservation";
import {
  AGENT_REPORTING_BOUNDARY,
  MAX_PROTOCOL_OBSERVATIONS_PAGE,
} from "../model/agentReportingObservation";
import { INCIDENT_EVENT_BOUNDARY } from "../model/incidentEventObservation";

const boundedIdentifier = OpaqueIdentifierSchema;
const nullableIdentifier = boundedIdentifier.nullable();
const AuditActorFilterSchema = z.union([z.literal(""), OpaqueIdentifierSchema]);
export const ConnectionObservationSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  kind: z.enum(CONNECTION_KIND),
  sourceId: nullableIdentifier,
  provider: z.enum(CONFIG_PROVIDER).nullable(),
  state: z.enum(HEALTH_STATE),
  checkedAt: UtcInstantSchema.nullable(),
  expiresAt: UtcInstantSchema.nullable(),
  latencyMs: z.number().nonnegative().nullable(),
  capabilities: z.array(z.enum(HEALTH_CAPABILITY)).max(5),
  reason: z.enum(HEALTH_REASON).nullable(),
});
export const SystemConnectionsSchema = z.strictObject({
  asOf: UtcInstantSchema,
  items: z.array(ConnectionObservationSchema).max(SYSTEM_COLLECTION_LIMIT),
});
export const DeploymentGuidesSchema = z.strictObject({
  catalogRevision: OpaqueIdentifierSchema,
  runtimeCollector: z.strictObject({
    state: z.enum(["configured", "not_configured"]),
    endpoint: z.string().url().max(512).nullable(),
  }),
  paths: z
    .array(
      z.strictObject({
        id: z.enum(["existing", "linux", "kubernetes"]),
        readiness: z.enum(["configuration-required", "guide-only"]),
        profileRevision: OpaqueIdentifierSchema.nullable(),
      }),
    )
    .length(3),
});
export const ProtocolObservationSchema = z.strictObject({
  kind: z.enum(PROTOCOL_BOUNDARY_IDS),
  supported: z.array(boundedIdentifier).max(MAX_SUPPORTED_PROTOCOL_VERSIONS),
  active: nullableIdentifier,
  compatibility: z.enum(PROTOCOL_COMPATIBILITY),
  observedAt: UtcInstantSchema.nullable(),
});
export const SystemProtocolsSchema = z.strictObject({
  asOf: UtcInstantSchema,
  items: z.array(ProtocolObservationSchema).max(PROTOCOL_BOUNDARY_COUNT),
});
function protocolObservationPageSchema<Boundary extends string>(boundary: Boundary) {
  return z.strictObject({
    asOf: UtcInstantSchema,
    page: PageNumberSchema.max(MAX_PROTOCOL_OBSERVATIONS_PAGE),
    pageSize: PageSizeSchema.max(100),
    total: TotalCountSchema,
    items: z
      .array(
        z.strictObject({
          environmentId: OpaqueIdentifierSchema,
          appId: OpaqueIdentifierSchema,
          instanceId: OpaqueIdentifierSchema,
          processId: OpaqueIdentifierSchema,
          reporterId: OpaqueIdentifierSchema,
          boundary: z.literal(boundary),
          collectorSupported: z.array(boundedIdentifier).max(MAX_SUPPORTED_PROTOCOL_VERSIONS),
          runtimeVersion: nullableIdentifier,
          compatibility: z.enum(PROTOCOL_COMPATIBILITY),
          observedAt: UtcInstantSchema.nullable(),
        }),
      )
      .max(100),
  });
}
export const AgentReportingObservationPageSchema =
  protocolObservationPageSchema(AGENT_REPORTING_BOUNDARY);
export const IncidentEventObservationPageSchema =
  protocolObservationPageSchema(INCIDENT_EVENT_BOUNDARY);
export const AuditQuerySchema = z.strictObject({
  start: UtcInstantSchema,
  end: UtcInstantSchema,
  actorId: AuditActorFilterSchema,
  action: z.enum(AUDIT_ACTION).nullable(),
  result: z.enum(AUDIT_RESULT).nullable(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(AUDIT_MAX_PAGE_SIZE),
});
export const AuditQueryParametersSchema = z.strictObject({
  start: UtcInstantSchema,
  end: UtcInstantSchema,
  actorId: AuditActorFilterSchema.optional(),
  action: z.enum(AUDIT_ACTION).optional(),
  result: z.enum(AUDIT_RESULT).optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(AUDIT_MAX_PAGE_SIZE),
});
export const AuditRecordSchema = z
  .strictObject({
    id: OpaqueIdentifierSchema,
    occurredAt: UtcInstantSchema,
    actorId: nullableIdentifier,
    action: z.enum(AUDIT_ACTION),
    targetId: boundedIdentifier,
    result: z.enum(AUDIT_RESULT),
    requestId: boundedIdentifier,
    environmentId: nullableIdentifier,
    appId: nullableIdentifier,
    bindingId: nullableIdentifier,
    publicationId: nullableIdentifier,
  })
  .superRefine((value, context) => {
    if (!validAuditActor(value.action, value.actorId)) {
      context.addIssue({
        code: "custom",
        path: ["actorId"],
        message: "This audit action requires an account actor",
      });
    }
  });
export const AuditPageSchema = z.strictObject({
  query: AuditQuerySchema,
  asOf: UtcInstantSchema,
  total: TotalCountSchema,
  items: z.array(AuditRecordSchema).max(AUDIT_MAX_PAGE_SIZE),
});
export const MAX_AUDIT_WINDOW_MS = AUDIT_MAX_WINDOW_MS;
