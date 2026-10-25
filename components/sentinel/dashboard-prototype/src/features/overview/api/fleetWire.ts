import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  TotalCountSchema,
  UtcInstantSchema,
  CONSOLE_WIRE_LIMIT,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import {
  ObservationContextSchema,
  ObservationContextParametersSchema,
  ObservationCoverageSchema,
  MetricReadingSchema,
  MetricBundleSchema,
  ObservationStepSchema,
} from "../../../shared/api/observationWire";
import { OBSERVATION_SCOPE, OPERATIONAL_METRICS } from "../../../shared/model/observation";

export const FleetQuerySchema = z.strictObject({
  context: ObservationContextSchema,
  page: PageNumberSchema,
  pageSize: PageSizeSchema,
  search: utf16BoundedString(200),
  stepMs: ObservationStepSchema,
});
export const FleetParametersSchema = ObservationContextParametersSchema.omit({
  instanceId: true,
  resource: true,
}).extend({
  scope: z.enum([OBSERVATION_SCOPE.Fleet, OBSERVATION_SCOPE.Application]),
  page: PageNumberSchema,
  pageSize: PageSizeSchema,
  search: FleetQuerySchema.shape.search,
  stepMs: ObservationStepSchema,
});
export const FleetApplicationSchema = z.strictObject({
  appId: OpaqueIdentifierSchema,
  name: OpaqueIdentifierSchema,
  health: z.enum(["healthy", "attention", "unknown"]),
  instanceCoverage: ObservationCoverageSchema,
  ruleCoverage: ObservationCoverageSchema,
  metrics: z.array(MetricReadingSchema).length(OPERATIONAL_METRICS.length),
});
export const FleetSnapshotSchema = z.strictObject({
  query: FleetQuerySchema,
  asOf: UtcInstantSchema,
  coverage: ObservationCoverageSchema,
  totalApplications: TotalCountSchema,
  attentionApplications: TotalCountSchema,
  attentionTargets: z.array(OpaqueIdentifierSchema).max(CONSOLE_WIRE_LIMIT.PageSize),
  applications: z.strictObject({
    items: z.array(FleetApplicationSchema).max(CONSOLE_WIRE_LIMIT.PageSize),
    total: TotalCountSchema,
    page: PageNumberSchema,
    pageSize: PageSizeSchema,
  }),
  metrics: MetricBundleSchema,
  connections: z
    .array(
      z.strictObject({
        id: OpaqueIdentifierSchema,
        provider: z.enum(["nacos", "consul", "collector"]),
        state: z.enum(["available", "unavailable", "not_configured", "unknown"]),
        checkedAt: UtcInstantSchema.nullable(),
        latencyMs: z.number().nonnegative().nullable(),
      }),
    )
    .max(CONSOLE_WIRE_LIMIT.PageSize),
});
