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
