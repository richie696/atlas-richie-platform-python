import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  TotalCountSchema,
  UtcInstantSchema,
} from "../../../core/api/protocol/common";
import { RuleBindingSchema } from "./ruleSetWire";
import { RULE_KINDS } from "../model/ruleKinds";

const RuleKindSchema = z.enum(RULE_KINDS);
const NullableIdentifierSchema = OpaqueIdentifierSchema.nullable();
const DigestSchema = z.string().regex(/^[0-9a-f]{64}$/);
const RuleBindingObservedStateSchema = z.enum([
  "current_with_rules",
  "configured_empty",
  "target_missing",
  "content_invalid",
  "unsupported_profile",
  "source_unavailable",
  "not_read",
]);
const RuleLoadStateSchema = z.enum([
  "applied",
  "failed_keeps_last_known_good",
  "failed_before_first_load",
  "not_observed",
]);
export const RuleBindingStatesParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema.optional(),
  kind: RuleKindSchema.optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(100),
});
const RuleBindingStatesQuerySchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: NullableIdentifierSchema,
  kind: RuleKindSchema.nullable(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(100),
});
const RuleBindingObservedStateItemSchema = z.strictObject({
  binding: RuleBindingSchema,
  state: RuleBindingObservedStateSchema,
  ruleCount: TotalCountSchema.nullable(),
  sourceRevision: NullableIdentifierSchema,
  lastAttemptAt: UtcInstantSchema.nullable(),
  freshness: z.enum(["current", "stale", "not_read"]),
  hasLastKnownGood: z.boolean(),
});
export const RuleBindingStatesPageSchema = z.strictObject({
  query: RuleBindingStatesQuerySchema,
  asOf: UtcInstantSchema,
  coverage: z.enum(["complete", "partial"]),
  total: TotalCountSchema.nullable(),
  hasMore: z.boolean(),
  items: z.array(RuleBindingObservedStateItemSchema).max(100),
});

export const RuleLoadObservationParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  bindingId: OpaqueIdentifierSchema.optional(),
  instanceId: OpaqueIdentifierSchema.optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(100),
});
const RuleLoadObservationQuerySchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  bindingId: NullableIdentifierSchema,
  instanceId: NullableIdentifierSchema,
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(100),
});
const RuleLoadMemberSchema = z.strictObject({
  ruleKind: RuleKindSchema,
  fingerprintSha256: DigestSchema,
});
const RuleLoadSnapshotSchema = z.strictObject({
  sourceRevision: NullableIdentifierSchema,
  canonicalRulesSha256: DigestSchema,
  membershipComplete: z.boolean(),
  members: z.array(RuleLoadMemberSchema).max(8192),
});
const RuleLoadAttemptSchema = z.strictObject({
  sourceRevision: NullableIdentifierSchema,
  canonicalRulesSha256: DigestSchema.nullable(),
  failureReason: z.enum([
    "source_unavailable",
    "content_invalid",
    "unsupported_profile",
    "unknown",
  ]),
});
const RuleLoadObservationItemSchema = z.strictObject({
  bindingId: OpaqueIdentifierSchema,
  instanceId: OpaqueIdentifierSchema,
  processId: OpaqueIdentifierSchema,
  processEpoch: NullableIdentifierSchema,
  profileId: NullableIdentifierSchema,
  loadState: RuleLoadStateSchema,
  eventKind: z.enum(["snapshot_applied", "snapshot_failed", "heartbeat"]).nullable(),
  activeSnapshot: RuleLoadSnapshotSchema.nullable(),
  attempt: RuleLoadAttemptSchema.nullable(),
  observedAt: UtcInstantSchema.nullable(),
  receivedAt: UtcInstantSchema.nullable(),
  freshness: z.enum(["current", "stale", "unknown"]),
});
export const RuleLoadObservationPageSchema = z.strictObject({
  query: RuleLoadObservationQuerySchema,
  asOf: UtcInstantSchema,
  coverage: z.enum(["complete", "partial"]),
  targets: z.strictObject({
    source: z.literal("active_reporter_enrollment"),
    expected: TotalCountSchema.nullable(),
    observed: TotalCountSchema.nullable(),
    stale: TotalCountSchema.nullable(),
    notObserved: TotalCountSchema.nullable(),
  }),
  total: TotalCountSchema.nullable(),
  hasMore: z.boolean(),
  items: z.array(RuleLoadObservationItemSchema).max(100),
});
export const RuleLoadObservationHistoryParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  bindingId: OpaqueIdentifierSchema,
  instanceId: OpaqueIdentifierSchema.optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(100),
});
export const RuleLoadObservationHistoryPageSchema = z.strictObject({
  query: z.strictObject({
    environmentId: OpaqueIdentifierSchema,
    appId: OpaqueIdentifierSchema,
    bindingId: OpaqueIdentifierSchema,
    instanceId: NullableIdentifierSchema,
    page: PageNumberSchema,
    pageSize: PageSizeSchema.max(100),
  }),
  asOf: UtcInstantSchema,
  coverage: z.enum(["complete", "partial"]),
  total: TotalCountSchema.nullable(),
  hasMore: z.boolean(),
  items: z
    .array(
      z.strictObject({
        observationId: OpaqueIdentifierSchema,
        epochStatus: z.enum(["superseded", "revoked", "no_current_epoch"]),
        observation: RuleLoadObservationItemSchema,
      }),
    )
    .max(100),
});

export type RuleBindingStatesWire = z.infer<typeof RuleBindingStatesPageSchema>;
export type RuleLoadObservationsWire = z.infer<typeof RuleLoadObservationPageSchema>;
