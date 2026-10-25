import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  TotalCountSchema,
  UtcInstantSchema,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import {
  ObservationContextSchema,
  ObservationContextParametersSchema,
  ObservationCoverageSchema,
  MetricReadingSchema,
  MetricBundleSchema,
  MetricQuerySchema,
  ObservationStepSchema,
} from "../../../shared/api/observationWire";
import {
  INSTANCE_LAYER,
  INSTANCE_HEALTH,
  RULE_RECEIPT,
  MAX_INSTANCE_PAGE_SIZE,
  MAX_INSTANCE_SEARCH_LENGTH,
} from "../model/instanceObservation";
import { OBSERVATION_SCOPE, OPERATIONAL_METRICS } from "../../../shared/model/observation";

const InstanceCatalogScopeSchema = z.enum([OBSERVATION_SCOPE.Fleet, OBSERVATION_SCOPE.Application]);
const InstanceCatalogContextSchema = ObservationContextSchema.extend({
  instanceId: z.null(),
  resource: z.null(),
  scope: InstanceCatalogScopeSchema,
});
const InstanceCatalogContextParametersSchema = ObservationContextParametersSchema.omit({
  instanceId: true,
  resource: true,
}).extend({ scope: InstanceCatalogScopeSchema });

export const InstanceCatalogQuerySchema = z.strictObject({
  context: InstanceCatalogContextSchema,
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_INSTANCE_PAGE_SIZE),
  search: utf16BoundedString(MAX_INSTANCE_SEARCH_LENGTH),
  attentionOnly: z.boolean(),
});
export const InstanceCatalogParametersSchema = InstanceCatalogContextParametersSchema.extend({
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_INSTANCE_PAGE_SIZE),
  search: utf16BoundedString(MAX_INSTANCE_SEARCH_LENGTH),
  attentionOnly: z.boolean(),
});
export const InstanceDetailQuerySchema = z.strictObject({
  context: ObservationContextSchema.extend({ scope: z.enum(INSTANCE_LAYER) }),
  processEpoch: OpaqueIdentifierSchema,
  stepMs: ObservationStepSchema,
});
const InstanceMetricBundleSchema = MetricBundleSchema.extend({
  query: MetricQuerySchema.extend({
    context: ObservationContextSchema.extend({ scope: z.enum(INSTANCE_LAYER) }),
  }),
});
export const InstanceDetailParametersSchema = ObservationContextParametersSchema.omit({
  instanceId: true,
}).extend({
  appId: OpaqueIdentifierSchema,
  scope: z.enum(INSTANCE_LAYER),
  processEpoch: OpaqueIdentifierSchema,
  stepMs: ObservationStepSchema,
});
export const InstanceRuleReceiptSchema = z.strictObject({
  state: z.enum(RULE_RECEIPT),
  desiredVersionId: OpaqueIdentifierSchema.nullable(),
  appliedVersionId: OpaqueIdentifierSchema.nullable(),
  processEpoch: OpaqueIdentifierSchema,
  receivedAt: UtcInstantSchema.nullable(),
});
export const ObservedInstanceSchema = z.strictObject({
  instanceId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  environmentId: OpaqueIdentifierSchema,
  hostId: OpaqueIdentifierSchema.nullable(),
  containerId: OpaqueIdentifierSchema.nullable(),
  processId: OpaqueIdentifierSchema.nullable(),
  processEpoch: OpaqueIdentifierSchema,
  health: z.enum(INSTANCE_HEALTH),
  lastReportAt: UtcInstantSchema.nullable(),
  supportedScopes: z.array(z.enum(INSTANCE_LAYER)).max(Object.keys(INSTANCE_LAYER).length),
  ruleReceipt: InstanceRuleReceiptSchema,
  processMetrics: z.array(MetricReadingSchema).length(OPERATIONAL_METRICS.length),
});
export const InstanceCatalogSchema = z.strictObject({
  query: InstanceCatalogQuerySchema,
  asOf: UtcInstantSchema,
  coverage: ObservationCoverageSchema,
  totalInstances: TotalCountSchema,
  attentionInstances: TotalCountSchema,
  filteredTotal: TotalCountSchema,
  items: z.array(ObservedInstanceSchema).max(MAX_INSTANCE_PAGE_SIZE),
});
export const InstanceObservationSchema = z.strictObject({
  query: InstanceDetailQuerySchema,
  asOf: UtcInstantSchema,
  instance: ObservedInstanceSchema,
  metrics: InstanceMetricBundleSchema.nullable(),
});
