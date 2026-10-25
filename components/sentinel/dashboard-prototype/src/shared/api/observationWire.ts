import { z } from "zod";
import {
  InventoryCoverageSchema,
  OpaqueIdentifierSchema,
  TotalCountSchema,
  UtcInstantSchema,
} from "../../core/api/protocol/common";
import {
  OBSERVATION_SCOPE,
  METRIC_ID,
  METRIC_UNIT,
  METRIC_BASIS,
  OBSERVATION_QUALITY,
  MAX_OBSERVATION_POINTS,
  MAX_OBSERVATION_WINDOW_MS,
} from "../model/observation";

export const ObservationWindowSchema = z.strictObject({
  from: UtcInstantSchema,
  to: UtcInstantSchema,
});
export const ObservationContextSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema.nullable(),
  instanceId: OpaqueIdentifierSchema.nullable(),
  resource: OpaqueIdentifierSchema.nullable(),
  scope: z.enum(OBSERVATION_SCOPE),
  window: ObservationWindowSchema,
});
export const ObservationCoverageSchema = z.union([
  InventoryCoverageSchema.options[0].extend({ reporting: TotalCountSchema }),
  InventoryCoverageSchema.options[1].extend({ reporting: TotalCountSchema }),
]);
export const ObservationStepSchema = z.int().min(1).max(MAX_OBSERVATION_WINDOW_MS);
export const MetricSelectionSchema = z
  .array(z.enum(METRIC_ID))
  .min(1)
  .max(Object.keys(METRIC_ID).length);
const Metadata = {
  source: OpaqueIdentifierSchema,
  denominator: z.enum(METRIC_BASIS),
  coverage: ObservationCoverageSchema,
  quality: z.enum(OBSERVATION_QUALITY),
};
const MetricIdentity = { metric: z.enum(METRIC_ID), unit: z.enum(METRIC_UNIT) };
const ValueSchema = z.number().nonnegative().nullable();
export const MetricReadingSchema = z.strictObject({
  ...Metadata,
  ...MetricIdentity,
  value: ValueSchema,
  sampledAt: UtcInstantSchema.nullable(),
});
export const MetricSeriesSchema = z.strictObject({
  ...Metadata,
  ...MetricIdentity,
  samples: z
    .array(z.strictObject({ at: UtcInstantSchema, value: ValueSchema }))
    .max(MAX_OBSERVATION_POINTS),
});
export const ObservationAnnotationSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  kind: z.enum(["publication", "source_activation", "incident"]),
  at: UtcInstantSchema,
  versionId: OpaqueIdentifierSchema.optional(),
  publicationId: OpaqueIdentifierSchema.optional(),
  incidentId: OpaqueIdentifierSchema.optional(),
});
export const MetricQuerySchema = z.strictObject({
  context: ObservationContextSchema,
  metrics: MetricSelectionSchema,
  stepMs: ObservationStepSchema,
});
/** UTC instants have dedicated names; durations/ratios are never converted by a field-name suffix heuristic. */
export const MetricBundleSchema = z.strictObject({
  query: MetricQuerySchema,
  asOf: UtcInstantSchema,
  summary: z.array(MetricReadingSchema).max(Object.keys(METRIC_ID).length),
  series: z.array(MetricSeriesSchema).max(Object.keys(METRIC_ID).length),
  annotations: z.array(ObservationAnnotationSchema).max(MAX_OBSERVATION_POINTS),
});
/** Shared flat GET projection. Null optional identities are omitted, not the literal string "null". */
export const ObservationContextParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema.optional(),
  instanceId: OpaqueIdentifierSchema.optional(),
  resource: OpaqueIdentifierSchema.optional(),
  scope: z.enum(OBSERVATION_SCOPE),
  from: UtcInstantSchema,
  to: UtcInstantSchema,
});
export type ObservationContextWire = z.infer<typeof ObservationContextSchema>;
export type MetricQueryWire = z.infer<typeof MetricQuerySchema>;
export type MetricBundleWire = z.infer<typeof MetricBundleSchema>;
