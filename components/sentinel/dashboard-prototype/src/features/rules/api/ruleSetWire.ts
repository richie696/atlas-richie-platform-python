import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  RequestKeySchema,
  TotalCountSchema,
  UtcInstantSchema,
  NON_BLANK_WIRE_CONTENT,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import { RULE_KINDS, RULE_KIND } from "../model/ruleKinds";
import { MAX_BINDING_PAGE_SIZE, MAX_BINDING_SEARCH_LENGTH } from "../model/ruleDirectory";
import { RECEIPT_PAGE_SIZE_LIMIT } from "../model/ruleDeployment";
import { ACTIVATION_STATE } from "../model/ruleActivation";
import { PUBLICATION_REASON, PUBLICATION_STAGE, RECEIPT_STATE } from "../model/ruleDeployment";
import { RULE_MUTATION, RULE_REJECTION, RULE_SERVER_ISSUE } from "../model/ruleSetOperations";
import type { RulePublicationTargetSnapshot } from "../model/rulePublicationTarget";

const SafeIntegerSchema = z.int().min(-Number.MAX_SAFE_INTEGER).max(Number.MAX_SAFE_INTEGER);
const RuleNumberSchema = z
  .number()
  .finite()
  .min(-Number.MAX_SAFE_INTEGER)
  .max(Number.MAX_SAFE_INTEGER);
const RuleKindSchema = z.enum(RULE_KINDS);
const NullableIdentifierSchema = OpaqueIdentifierSchema.nullable();
const noWireControlCharacters = /^[^\u0000-\u001f\u007f]*$/;
const publicationTargetIdentifier = OpaqueIdentifierSchema.regex(noWireControlCharacters);
const nonBlankRuleText = (maximum: number) =>
  utf16BoundedString(maximum).min(1).regex(NON_BLANK_WIRE_CONTENT);
const boundedPublicationTargetText = utf16BoundedString(512).regex(noWireControlCharacters);
const nonBlankPublicationTargetText = boundedPublicationTargetText
  .min(1)
  .regex(NON_BLANK_WIRE_CONTENT);
const validConsulRuleTargetKey = nonBlankPublicationTargetText.refine(
  (value) =>
    !value.startsWith("/") &&
    !value.endsWith("/") &&
    !value.includes("\\") &&
    !value.includes("?") &&
    !value.includes("#") &&
    value.split("/").every((segment) => segment !== "" && segment !== "." && segment !== ".."),
);

export const RuleValueSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal(RULE_KIND.Flow),
    value: z.strictObject({
      resource: nonBlankRuleText(512),
      limitApp: nonBlankRuleText(200),
      grade: SafeIntegerSchema,
      count: RuleNumberSchema,
      strategy: SafeIntegerSchema,
      controlBehavior: SafeIntegerSchema,
      clusterMode: z.boolean(),
      refResource: nonBlankRuleText(512).optional(),
      warmUpPeriodSec: SafeIntegerSchema.optional(),
      maxQueueingTimeMs: SafeIntegerSchema.optional(),
      clusterConfig: z
        .strictObject({
          thresholdType: SafeIntegerSchema,
          fallbackToLocalWhenFail: z.boolean(),
          sampleCount: SafeIntegerSchema,
          windowIntervalMs: SafeIntegerSchema,
        })
        .optional(),
    }),
  }),
  z.strictObject({
    kind: z.literal(RULE_KIND.Degrade),
    value: z.strictObject({
      resource: nonBlankRuleText(512),
      grade: SafeIntegerSchema,
      count: RuleNumberSchema,
      timeWindow: SafeIntegerSchema,
      minRequestAmount: SafeIntegerSchema,
      statIntervalMs: SafeIntegerSchema,
      slowRatioThreshold: RuleNumberSchema.optional(),
    }),
  }),
  z.strictObject({
    kind: z.literal(RULE_KIND.System),
    value: z.strictObject({
      highestSystemLoad: RuleNumberSchema,
      avgRt: RuleNumberSchema,
      maxThread: SafeIntegerSchema,
      qps: RuleNumberSchema,
      highestCpuUsage: RuleNumberSchema,
    }),
  }),
  z.strictObject({
    kind: z.literal(RULE_KIND.Authority),
    value: z.strictObject({
      resource: nonBlankRuleText(512),
      limitApp: nonBlankRuleText(200),
      strategy: SafeIntegerSchema,
    }),
  }),
  z.strictObject({
    kind: z.literal(RULE_KIND.ParamFlow),
    value: z.strictObject({
      resource: nonBlankRuleText(512),
      grade: SafeIntegerSchema,
      count: RuleNumberSchema,
      durationInSec: SafeIntegerSchema,
      paramIdx: SafeIntegerSchema,
      paramFlowItemList: z
        .array(
          z.strictObject({
            classType: nonBlankRuleText(512),
            object: nonBlankRuleText(512),
            count: RuleNumberSchema,
          }),
        )
        .max(100),
    }),
  }),
]);

export const RuleRecordSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  rule: RuleValueSchema,
});
export const RuleBindingSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  kind: RuleKindSchema,
  profile: OpaqueIdentifierSchema,
  sourceId: OpaqueIdentifierSchema,
  sourceLabel: nonBlankRuleText(200),
  location: nonBlankRuleText(512),
});
export const RuleBindingQuerySchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: NullableIdentifierSchema,
  kind: RuleKindSchema.nullable(),
  search: utf16BoundedString(MAX_BINDING_SEARCH_LENGTH),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_BINDING_PAGE_SIZE),
});
export const RuleBindingParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema.optional(),
  kind: RuleKindSchema.optional(),
  search: utf16BoundedString(MAX_BINDING_SEARCH_LENGTH).optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_BINDING_PAGE_SIZE),
});
export const RuleBindingPageSchema = z.strictObject({
  query: RuleBindingQuerySchema,
  total: TotalCountSchema,
  items: z.array(RuleBindingSchema).max(MAX_BINDING_PAGE_SIZE),
});
const RuleCatalogCoverageSchema = z.enum(["complete", "partial"]);
const RuleCatalogFreshnessSchema = z.enum(["current", "stale"]);
const RuleCatalogIssueReasonSchema = z.enum(["source_unavailable", "content_invalid", "not_read"]);
const RuleCatalogBindingCoverageSchema = z.strictObject({
  total: TotalCountSchema,
  current: TotalCountSchema,
  stale: TotalCountSchema,
  notRead: TotalCountSchema,
});
const RuleCatalogEntrySchema = z.strictObject({
  binding: RuleBindingSchema,
  record: RuleRecordSchema,
  snapshot: z.strictObject({
    checksum: OpaqueIdentifierSchema,
    sourceRevision: NullableIdentifierSchema,
    versionId: NullableIdentifierSchema,
    asOf: UtcInstantSchema,
  }),
  read: z.strictObject({
    freshness: RuleCatalogFreshnessSchema,
    lastAttemptAt: UtcInstantSchema,
  }),
});
const RuleCatalogIssueSchema = z.strictObject({
  binding: RuleBindingSchema,
  reason: RuleCatalogIssueReasonSchema,
  lastAttemptAt: UtcInstantSchema.nullable(),
  stale: z.boolean(),
});
export const RuleCatalogQuerySchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: NullableIdentifierSchema,
  kind: RuleKindSchema.nullable(),
  search: utf16BoundedString(MAX_BINDING_SEARCH_LENGTH),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_BINDING_PAGE_SIZE),
});
export const RuleCatalogParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema.optional(),
  kind: RuleKindSchema.optional(),
  search: utf16BoundedString(MAX_BINDING_SEARCH_LENGTH).optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_BINDING_PAGE_SIZE),
});
export const RuleCatalogPageSchema = z
  .strictObject({
    query: RuleCatalogQuerySchema,
    asOf: UtcInstantSchema,
    coverage: RuleCatalogCoverageSchema,
    bindings: RuleCatalogBindingCoverageSchema,
    total: TotalCountSchema.nullable(),
    hasMore: z.boolean(),
    items: z.array(RuleCatalogEntrySchema).max(MAX_BINDING_PAGE_SIZE),
    issues: z.array(RuleCatalogIssueSchema).max(100),
  })
  .superRefine((value, context) => {
    if (
      value.bindings.current + value.bindings.stale + value.bindings.notRead !==
      value.bindings.total
    ) {
      context.addIssue({ code: "custom", message: "inconsistent rule catalog coverage" });
    }
    if ((value.coverage === "complete") !== (value.total !== null)) {
      context.addIssue({ code: "custom", message: "inconsistent rule catalog total" });
    }
    if (
      value.coverage === "complete" &&
      value.total !== null &&
      value.hasMore !==
        (value.query.page - 1) * value.query.pageSize + value.items.length < value.total
    ) {
      context.addIssue({ code: "custom", message: "inconsistent rule catalog pagination" });
    }
  });
export const RuleCatalogRefreshRequestSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: NullableIdentifierSchema.optional(),
});
export const RuleCatalogRefreshResultSchema = z
  .strictObject({
    scope: z.strictObject({
      environmentId: OpaqueIdentifierSchema,
      appId: NullableIdentifierSchema,
    }),
    asOf: UtcInstantSchema,
    coverage: RuleCatalogCoverageSchema,
    bindings: z.strictObject({
      total: TotalCountSchema,
      attempted: TotalCountSchema.max(24),
      current: TotalCountSchema,
      stale: TotalCountSchema,
      notRead: TotalCountSchema,
    }),
  })
  .superRefine((value, context) => {
    if (
      value.bindings.current + value.bindings.stale + value.bindings.notRead !==
      value.bindings.total
    ) {
      context.addIssue({ code: "custom", message: "inconsistent rule catalog refresh counts" });
    }
  });
export const RuleBindingRegistrationTargetSchema = z.discriminatedUnion("provider", [
  z.strictObject({
    provider: z.literal("nacos"),
    namespace: nonBlankPublicationTargetText,
    group: nonBlankPublicationTargetText,
    dataId: nonBlankPublicationTargetText,
  }),
  z.strictObject({
    provider: z.literal("consul"),
    datacenter: boundedPublicationTargetText.nullable(),
    key: validConsulRuleTargetKey,
  }),
]);
export const RuleBindingRegistrationRequestSchema = z.strictObject({
  requestKey: RequestKeySchema,
  bindingId: OpaqueIdentifierSchema,
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  kind: RuleKindSchema,
  profile: OpaqueIdentifierSchema,
  sourceId: OpaqueIdentifierSchema,
  sourceRevision: OpaqueIdentifierSchema,
  target: RuleBindingRegistrationTargetSchema,
});
export const RuleBindingRegistrationReceiptSchema = z.discriminatedUnion("status", [
  z.strictObject({
    requestKey: RequestKeySchema,
    bindingId: OpaqueIdentifierSchema,
    status: z.literal("completed"),
    binding: RuleBindingSchema,
  }),
  z.strictObject({
    requestKey: RequestKeySchema,
    bindingId: OpaqueIdentifierSchema,
    status: z.literal("not_found"),
    binding: z.null(),
  }),
]);
export const RuleSetSnapshotSchema = z.strictObject({
  binding: RuleBindingSchema,
  versionId: NullableIdentifierSchema,
  checksum: OpaqueIdentifierSchema,
  sourceRevision: NullableIdentifierSchema,
  asOf: UtcInstantSchema,
  records: z.array(RuleRecordSchema).max(1000),
});
export const RuleSetCollectionQuerySchema = z.strictObject({ bindingId: OpaqueIdentifierSchema });
export const CandidateRuleSchema = z.strictObject({
  recordId: NullableIdentifierSchema,
  rule: RuleValueSchema,
});
export const RuleSetCandidateSchema = z.strictObject({
  bindingId: OpaqueIdentifierSchema,
  profile: OpaqueIdentifierSchema,
  kind: RuleKindSchema,
  baseVersionId: NullableIdentifierSchema,
  baseChecksum: OpaqueIdentifierSchema,
  sourceRevision: NullableIdentifierSchema,
  rules: z.array(CandidateRuleSchema).max(1000),
});
export const StoredRuleDraftSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  bindingId: OpaqueIdentifierSchema,
  revision: OpaqueIdentifierSchema,
  kind: RuleKindSchema,
  profile: OpaqueIdentifierSchema,
  baseVersionId: NullableIdentifierSchema,
  baseChecksum: OpaqueIdentifierSchema,
  sourceRevision: NullableIdentifierSchema,
  updatedAt: UtcInstantSchema,
  records: z.array(RuleRecordSchema).max(1000),
});
export const RuleSetVersionSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  bindingId: OpaqueIdentifierSchema,
  kind: RuleKindSchema,
  profile: OpaqueIdentifierSchema,
  baseVersionId: NullableIdentifierSchema,
  checksum: OpaqueIdentifierSchema,
  name: utf16BoundedString(200).min(1).regex(NON_BLANK_WIRE_CONTENT),
  note: utf16BoundedString(2000),
  createdAt: UtcInstantSchema,
  createdById: OpaqueIdentifierSchema,
  records: z.array(RuleRecordSchema).max(1000),
});
export const PublicationPhaseSchema = z.strictObject({
  state: z.enum(PUBLICATION_STAGE),
  observedAt: UtcInstantSchema.nullable(),
  reason: z.enum(PUBLICATION_REASON).nullable(),
});
export const RulePublicationSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  bindingId: OpaqueIdentifierSchema,
  targetVersionId: OpaqueIdentifierSchema,
  targetChecksum: OpaqueIdentifierSchema,
  baseVersionId: NullableIdentifierSchema,
  createdAt: UtcInstantSchema,
  validation: PublicationPhaseSchema,
  configurationWrite: PublicationPhaseSchema,
  readBack: PublicationPhaseSchema,
});
export const PublicationReceiptSchema = z
  .strictObject({
    instanceId: OpaqueIdentifierSchema,
    processEpoch: NullableIdentifierSchema,
    loadedProcessEpoch: NullableIdentifierSchema,
    targetVersionId: OpaqueIdentifierSchema,
    loadedVersionId: NullableIdentifierSchema,
    loadedChecksum: NullableIdentifierSchema,
    appliedAt: UtcInstantSchema.nullable(),
    lastReportAt: UtcInstantSchema.nullable(),
    state: z.enum(RECEIPT_STATE),
  })
  .superRefine((value, context) => {
    if (
      value.processEpoch === null &&
      (value.state !== RECEIPT_STATE.Unknown ||
        value.loadedProcessEpoch !== null ||
        value.loadedVersionId !== null ||
        value.loadedChecksum !== null ||
        value.appliedAt !== null ||
        value.lastReportAt !== null)
    ) {
      context.addIssue({
        code: "custom",
        path: ["processEpoch"],
        message: "An unknown incarnation cannot claim a loaded receipt",
      });
    }
    if (
      value.state === RECEIPT_STATE.Applied &&
      (value.processEpoch === null ||
        value.loadedProcessEpoch !== value.processEpoch ||
        value.loadedVersionId !== value.targetVersionId ||
        value.loadedChecksum === null ||
        value.appliedAt === null ||
        value.lastReportAt === null)
    ) {
      context.addIssue({
        code: "custom",
        path: ["state"],
        message: "Applied receipts must confirm their current incarnation and target version",
      });
    }
  });
export const PublicationReceiptQuerySchema = z.strictObject({
  bindingId: OpaqueIdentifierSchema,
  publicationId: OpaqueIdentifierSchema,
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(RECEIPT_PAGE_SIZE_LIMIT),
});
export const PublicationReceiptParametersSchema = PublicationReceiptQuerySchema.omit({
  bindingId: true,
  publicationId: true,
});
export const PublicationReceiptPageSchema = z
  .strictObject({
    publicationId: OpaqueIdentifierSchema,
    bindingId: OpaqueIdentifierSchema,
    page: PageNumberSchema,
    pageSize: PageSizeSchema.max(RECEIPT_PAGE_SIZE_LIMIT),
    asOf: UtcInstantSchema,
    total: TotalCountSchema,
    expected: TotalCountSchema.nullable(),
    inventorySource: OpaqueIdentifierSchema.nullable(),
    applied: TotalCountSchema,
    pending: TotalCountSchema,
    failed: TotalCountSchema,
    unknown: TotalCountSchema,
    restartRequired: TotalCountSchema,
    items: z.array(PublicationReceiptSchema).max(RECEIPT_PAGE_SIZE_LIMIT),
  })
  .refine(
    (value) => (value.expected === null) === (value.inventorySource === null),
    "Inventory denominator and source must be known or unknown together",
  )
  .superRefine((value, context) => {
    const statusTotal =
      value.applied + value.pending + value.failed + value.unknown + value.restartRequired;
    if (value.expected !== null && value.expected !== value.total) {
      context.addIssue({
        code: "custom",
        path: ["expected"],
        message: "Expected inventory population must match the receipt population",
      });
    }
    if (value.total !== statusTotal) {
      context.addIssue({
        code: "custom",
        path: ["total"],
        message: "Receipt status counts must cover the full population",
      });
    }
    if (
      value.items.length > value.pageSize ||
      (value.page - 1) * value.pageSize + value.items.length > value.total
    ) {
      context.addIssue({
        code: "custom",
        path: ["items"],
        message: "Receipt items must fit within the requested page and population",
      });
    }
    const instanceIds = value.items.map((item) => item.instanceId);
    if (new Set(instanceIds).size !== instanceIds.length) {
      context.addIssue({
        code: "custom",
        path: ["items"],
        message: "Instance identities must be unique within a receipt page",
      });
    }
    const pageCounts = new Map<string, number>();
    for (const item of value.items) {
      pageCounts.set(item.state, (pageCounts.get(item.state) ?? 0) + 1);
    }
    const populationCounts = new Map([
      ["applied", value.applied],
      ["pending", value.pending],
      ["failed", value.failed],
      ["unknown", value.unknown],
      ["restart_required", value.restartRequired],
    ]);
    if ([...pageCounts].some(([state, count]) => count > (populationCounts.get(state) ?? -1))) {
      context.addIssue({
        code: "custom",
        path: ["items"],
        message: "Page receipt states must not exceed full-population counters",
      });
    }
  });
export const ActivationPlanSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  revision: OpaqueIdentifierSchema,
  bindingId: OpaqueIdentifierSchema,
  versionId: OpaqueIdentifierSchema,
  restoreVersionId: OpaqueIdentifierSchema,
  activateAt: UtcInstantSchema,
  deactivateAt: UtcInstantSchema,
  timeZone: utf16BoundedString(128).min(1).regex(NON_BLANK_WIRE_CONTENT),
  state: z.enum(ACTIVATION_STATE),
  activationPublicationId: NullableIdentifierSchema,
  restorePublicationId: NullableIdentifierSchema,
});
export const RuleSetCollectionSchema = <T extends z.ZodType>(item: T) =>
  z.strictObject({
    bindingId: OpaqueIdentifierSchema,
    asOf: UtcInstantSchema,
    items: z.array(item).max(1000),
  });
export const RuleValidationReportSchema = z
  .strictObject({
    bindingId: OpaqueIdentifierSchema,
    profile: OpaqueIdentifierSchema,
    baseChecksum: OpaqueIdentifierSchema,
    candidateChecksum: OpaqueIdentifierSchema,
    validationId: OpaqueIdentifierSchema,
    isPublishable: z.boolean(),
    issues: z
      .array(
        z.strictObject({
          code: z.enum(RULE_SERVER_ISSUE),
          recordIndex: SafeIntegerSchema.min(0).max(999).nullable(),
          path: utf16BoundedString(512)
            .min(1)
            .regex(
              /^(?:rules\[\d+\](?:\.[A-Za-z][A-Za-z0-9]*)*|bindingId|profile|kind|baseChecksum)$/,
            ),
        }),
      )
      .max(32),
  })
  .refine(
    (report) => report.isPublishable === (report.issues.length === 0),
    "Publishability must agree with the validation issues",
  );
export const RuleSetDiffSchema = z.strictObject({
  bindingId: OpaqueIdentifierSchema,
  baseChecksum: OpaqueIdentifierSchema,
  candidateChecksum: OpaqueIdentifierSchema,
  changes: z
    .array(
      z.discriminatedUnion("operation", [
        z.strictObject({ operation: z.literal("add"), after: RuleValueSchema }),
        z.strictObject({
          operation: z.literal("remove"),
          recordId: OpaqueIdentifierSchema,
          before: RuleValueSchema,
        }),
        z.strictObject({
          operation: z.literal("replace"),
          recordId: OpaqueIdentifierSchema,
          before: RuleValueSchema,
          after: RuleValueSchema,
        }),
      ]),
    )
    .max(2000),
});
const ScheduleSchema = z.strictObject({
  bindingId: OpaqueIdentifierSchema,
  versionId: OpaqueIdentifierSchema,
  restoreVersionId: OpaqueIdentifierSchema,
  activateAt: UtcInstantSchema,
  deactivateAt: UtcInstantSchema,
  timeZone: utf16BoundedString(128).min(1).regex(NON_BLANK_WIRE_CONTENT),
});
export const RuleMutationSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal(RULE_MUTATION.SaveDraft),
    draftId: NullableIdentifierSchema,
    expectedRevision: NullableIdentifierSchema,
    candidate: RuleSetCandidateSchema,
  }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.DeleteDraft),
    draftId: OpaqueIdentifierSchema,
    expectedRevision: OpaqueIdentifierSchema,
  }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.FreezeVersion),
    draftId: OpaqueIdentifierSchema,
    expectedRevision: OpaqueIdentifierSchema,
    validationId: OpaqueIdentifierSchema,
    candidateChecksum: OpaqueIdentifierSchema,
    name: utf16BoundedString(200).min(1).regex(NON_BLANK_WIRE_CONTENT),
    note: utf16BoundedString(2000),
  }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.Publish),
    versionId: OpaqueIdentifierSchema,
    versionChecksum: OpaqueIdentifierSchema,
    expectedVersionId: NullableIdentifierSchema,
    expectedChecksum: OpaqueIdentifierSchema,
    expectedSourceRevision: NullableIdentifierSchema,
    reason: utf16BoundedString(2000).min(1).regex(NON_BLANK_WIRE_CONTENT),
  }),
  z.strictObject({ kind: z.literal(RULE_MUTATION.CreatePlan), schedule: ScheduleSchema }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.CancelPlan),
    planId: OpaqueIdentifierSchema,
    expectedRevision: OpaqueIdentifierSchema,
    reason: utf16BoundedString(2000).min(1).regex(NON_BLANK_WIRE_CONTENT),
  }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.ConfigureTarget),
    expectedSourceRevision: OpaqueIdentifierSchema,
    expectedTargetRevision: NullableIdentifierSchema,
    target: z.discriminatedUnion("provider", [
      z.strictObject({
        provider: z.literal("nacos"),
        sourceId: publicationTargetIdentifier,
        namespace: nonBlankPublicationTargetText,
        group: nonBlankPublicationTargetText,
        dataId: nonBlankPublicationTargetText,
      }),
      z.strictObject({
        provider: z.literal("consul"),
        sourceId: publicationTargetIdentifier,
        key: nonBlankPublicationTargetText,
      }),
    ]),
  }),
]);
const PublicationTargetValueSchema = z.discriminatedUnion("provider", [
  z.strictObject({
    provider: z.literal("nacos"),
    sourceId: publicationTargetIdentifier,
    namespace: nonBlankPublicationTargetText,
    group: nonBlankPublicationTargetText,
    dataId: nonBlankPublicationTargetText,
  }),
  z.strictObject({
    provider: z.literal("consul"),
    sourceId: publicationTargetIdentifier,
    key: nonBlankPublicationTargetText,
    datacenter: boundedPublicationTargetText.nullable(),
  }),
]);
export const RulePublicationTargetSnapshotSchema: z.ZodType<RulePublicationTargetSnapshot> =
  z.union([
    z.strictObject({ bindingId: publicationTargetIdentifier, target: z.null() }),
    z.strictObject({
      bindingId: publicationTargetIdentifier,
      targetRevision: OpaqueIdentifierSchema,
      sourceRevision: OpaqueIdentifierSchema,
      target: PublicationTargetValueSchema,
    }),
  ]) as z.ZodType<RulePublicationTargetSnapshot>;
export const RuleCommandSchema = z.strictObject({
  bindingId: OpaqueIdentifierSchema,
  requestKey: RequestKeySchema,
  mutation: RuleMutationSchema,
});
export const RuleMutationResultSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal(RULE_MUTATION.SaveDraft), draft: StoredRuleDraftSchema }),
  z.strictObject({ kind: z.literal(RULE_MUTATION.DeleteDraft), draftId: OpaqueIdentifierSchema }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.FreezeVersion),
    draftId: OpaqueIdentifierSchema,
    draftRevision: OpaqueIdentifierSchema,
    version: RuleSetVersionSchema,
  }),
  z.strictObject({ kind: z.literal(RULE_MUTATION.Publish), publication: RulePublicationSchema }),
  z.strictObject({ kind: z.literal(RULE_MUTATION.CreatePlan), plan: ActivationPlanSchema }),
  z.strictObject({ kind: z.literal(RULE_MUTATION.CancelPlan), plan: ActivationPlanSchema }),
  z.strictObject({
    kind: z.literal(RULE_MUTATION.ConfigureTarget),
    bindingId: OpaqueIdentifierSchema,
    targetRevision: OpaqueIdentifierSchema,
    sourceRevision: OpaqueIdentifierSchema,
    target: z.discriminatedUnion("provider", [
      z.strictObject({
        provider: z.literal("nacos"),
        sourceId: OpaqueIdentifierSchema,
        namespace: OpaqueIdentifierSchema,
        group: OpaqueIdentifierSchema,
        dataId: OpaqueIdentifierSchema,
      }),
      z.strictObject({
        provider: z.literal("consul"),
        sourceId: OpaqueIdentifierSchema,
        key: OpaqueIdentifierSchema,
        datacenter: z.string().nullable(),
      }),
    ]),
  }),
]);
export const RuleOperationObservationSchema = z.discriminatedUnion("status", [
  z.strictObject({
    requestKey: RequestKeySchema,
    bindingId: OpaqueIdentifierSchema,
    status: z.literal("pending"),
  }),
  z.strictObject({
    requestKey: RequestKeySchema,
    bindingId: OpaqueIdentifierSchema,
    status: z.literal("not-found"),
  }),
  z.strictObject({
    requestKey: RequestKeySchema,
    bindingId: OpaqueIdentifierSchema,
    status: z.literal("completed"),
    result: RuleMutationResultSchema,
  }),
  z.strictObject({
    requestKey: RequestKeySchema,
    bindingId: OpaqueIdentifierSchema,
    status: z.literal("rejected"),
    reason: z.enum(RULE_REJECTION),
  }),
]);
export const RuleValidationRequestSchema = z.strictObject({ candidate: RuleSetCandidateSchema });
export const RuleDiffRequestSchema = z.strictObject({ candidate: RuleSetCandidateSchema });
export const RuleCommandRequestSchema = z.strictObject({
  requestKey: RequestKeySchema,
  mutation: RuleMutationSchema,
});
export const RuleOperationParametersSchema = z.strictObject({ requestKey: RequestKeySchema });
export const RulePageParametersSchema = z.strictObject({
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema.optional(),
  kind: RuleKindSchema.optional(),
  search: utf16BoundedString(MAX_BINDING_SEARCH_LENGTH).optional(),
  page: PageNumberSchema,
  pageSize: PageSizeSchema.max(MAX_BINDING_PAGE_SIZE),
});
