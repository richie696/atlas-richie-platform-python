import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  NON_BLANK_WIRE_CONTENT,
  PageSizeSchema,
  TotalCountSchema,
  UtcInstantSchema,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import {
  ObservationContextSchema,
  ObservationContextParametersSchema,
} from "../../../shared/api/observationWire";
import { INCIDENT_CATEGORY, INCIDENT_SEVERITY } from "../model/incident";
import { METRIC_ID, OBSERVATION_SCOPE } from "../../../shared/model/observation";
import {
  INCIDENT_FACT_CODE,
  MAX_INCIDENT_CURSOR_LENGTH,
  MAX_INCIDENT_EVIDENCE_ITEMS,
  MAX_INCIDENT_PAGE_SIZE,
} from "../model/incidentObservation";

export const IncidentSeveritySchema = z.enum(INCIDENT_SEVERITY);
export const IncidentCategorySchema = z.enum(INCIDENT_CATEGORY);
const IncidentScopeSchema = z.enum([
  OBSERVATION_SCOPE.Fleet,
  OBSERVATION_SCOPE.Application,
  OBSERVATION_SCOPE.Process,
]);
const IncidentObservationContextSchema = ObservationContextSchema.extend({
  resource: z.null(),
  scope: IncidentScopeSchema,
});
const IncidentObservationContextParametersSchema = ObservationContextParametersSchema.omit({
  resource: true,
}).extend({ scope: IncidentScopeSchema });
export const IncidentFactSchema = z.discriminatedUnion("code", [
  z.strictObject({
    code: z.literal(INCIDENT_FACT_CODE.ResourcePressure),
    metric: z.enum([METRIC_ID.CpuRatio, METRIC_ID.MemoryRatio]),
    value: z.number().min(0).max(1),
    threshold: z.number().min(0).max(1),
  }),
  z.strictObject({
    code: z.literal(INCIDENT_FACT_CODE.ResponseTime),
    valueMs: z.number().nonnegative(),
    thresholdMs: z.number().nonnegative(),
  }),
  z.strictObject({
    code: z.literal(INCIDENT_FACT_CODE.RulePublished),
    versionId: OpaqueIdentifierSchema,
  }),
  z.strictObject({
    code: z.literal(INCIDENT_FACT_CODE.RuleApplied),
    versionId: OpaqueIdentifierSchema,
  }),
]);
export const ObservedIncidentSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  instanceId: OpaqueIdentifierSchema.nullable(),
  processEpoch: OpaqueIdentifierSchema.nullable(),
  occurredAt: UtcInstantSchema,
  receivedAt: UtcInstantSchema,
  severity: IncidentSeveritySchema,
  category: IncidentCategorySchema,
  sourceEventId: OpaqueIdentifierSchema.nullable(),
  publicationId: OpaqueIdentifierSchema.nullable(),
  caption: IncidentFactSchema,
});
const cursorSchema = utf16BoundedString(MAX_INCIDENT_CURSOR_LENGTH)
  .min(1)
  .regex(NON_BLANK_WIRE_CONTENT)
  .nullable();
export const IncidentQuerySchema = z.strictObject({
  context: IncidentObservationContextSchema,
  severity: IncidentSeveritySchema.nullable(),
  category: IncidentCategorySchema.nullable(),
  cursor: cursorSchema,
  pageSize: PageSizeSchema.max(MAX_INCIDENT_PAGE_SIZE),
});
export const IncidentQueryParametersSchema = IncidentObservationContextParametersSchema.extend({
  severity: IncidentSeveritySchema.optional(),
  category: IncidentCategorySchema.optional(),
  cursor: utf16BoundedString(MAX_INCIDENT_CURSOR_LENGTH)
    .min(1)
    .regex(NON_BLANK_WIRE_CONTENT)
    .optional(),
  pageSize: PageSizeSchema.max(MAX_INCIDENT_PAGE_SIZE),
});
export const IncidentPageSchema = z.strictObject({
  query: IncidentQuerySchema,
  asOf: UtcInstantSchema,
  statistics: z.strictObject({
    total: TotalCountSchema,
    critical: TotalCountSchema,
    warning: TotalCountSchema,
    info: TotalCountSchema,
    ruleChanges: TotalCountSchema,
    affectedApplications: TotalCountSchema,
  }),
  items: z.array(ObservedIncidentSchema).max(MAX_INCIDENT_PAGE_SIZE),
  filteredTotal: TotalCountSchema,
  nextCursor: cursorSchema,
});
export const IncidentDetailQuerySchema = z.strictObject({
  context: IncidentObservationContextSchema,
  eventId: OpaqueIdentifierSchema,
  severity: IncidentSeveritySchema.nullable(),
  category: IncidentCategorySchema.nullable(),
});
export const IncidentDetailParametersSchema = IncidentObservationContextParametersSchema.extend({
  severity: IncidentSeveritySchema.optional(),
  category: IncidentCategorySchema.optional(),
});
export const IncidentEvidenceSchema = z.strictObject({
  query: IncidentDetailQuerySchema,
  asOf: UtcInstantSchema,
  event: ObservedIncidentSchema,
  facts: z
    .array(
      z.strictObject({
        id: OpaqueIdentifierSchema,
        source: OpaqueIdentifierSchema,
        at: UtcInstantSchema,
        fact: IncidentFactSchema,
      }),
    )
    .max(MAX_INCIDENT_EVIDENCE_ITEMS),
  completeness: z.enum(["complete", "partial", "unavailable"]),
  suggestedViews: z.array(z.enum(["instance", "metrics", "rules"])).max(3),
  relatedRule: z
    .strictObject({
      environmentId: OpaqueIdentifierSchema,
      appId: OpaqueIdentifierSchema,
      bindingId: OpaqueIdentifierSchema,
      versionId: OpaqueIdentifierSchema,
      publicationId: OpaqueIdentifierSchema,
    })
    .nullable(),
});
