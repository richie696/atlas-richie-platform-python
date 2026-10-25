import { instantToMilliseconds, millisecondsToInstant } from "../../../core/api/protocol/common";
import type { z } from "zod";
import type {
  BindingPage,
  BindingQuery,
  RuleCatalogPage,
  RuleCatalogRefreshResult,
} from "../model/ruleDirectory";
import type {
  RuleBindingRegistration,
  RuleBindingRegistrationReceipt,
} from "../model/ruleBindingRegistration";
import type { RuleSetCandidate, RuleSetCollection, RuleSetSnapshot } from "../model/ruleSet";
import type {
  PublicationReceiptPage,
  RulePublication,
  RuleSetVersion,
} from "../model/ruleDeployment";
import type { RuleActivationPlan } from "../model/ruleActivation";
import type {
  RuleMutation,
  RuleMutationResult,
  RuleOperationObservation,
  RuleSetDiff,
  RuleValidationReport,
  StoredRuleDraft,
} from "../model/ruleSetOperations";
import type { TypedRuleValue } from "../model/ruleValue";
import {
  ActivationPlanSchema,
  PublicationReceiptPageSchema,
  RuleBindingPageSchema,
  RuleCatalogPageSchema,
  RuleCatalogRefreshResultSchema,
  RuleValueSchema,
  RuleBindingRegistrationReceiptSchema,
  RuleOperationObservationSchema,
  RulePublicationSchema,
  RuleSetCandidateSchema,
  RuleSetCollectionSchema,
  RuleSetDiffSchema,
  RuleSetSnapshotSchema,
  RuleSetVersionSchema,
  RuleValidationReportSchema,
  StoredRuleDraftSchema,
} from "./ruleSetWire";

export function bindingQueryToWire(query: BindingQuery) {
  return {
    environmentId: query.environmentId,
    appId: query.appId,
    kind: query.kind,
    search: query.search,
    page: query.page,
    pageSize: query.pageSize,
  };
}

export function bindingParametersToWire(query: BindingQuery) {
  return {
    environmentId: query.environmentId,
    ...(query.appId === null ? {} : { appId: query.appId }),
    ...(query.kind === null ? {} : { kind: query.kind }),
    ...(query.search === "" ? {} : { search: query.search }),
    page: query.page,
    pageSize: query.pageSize,
  };
}

export function bindingPageFromWire(input: unknown): BindingPage {
  const value = RuleBindingPageSchema.parse(input);
  return {
    query: value.query,
    total: value.total,
    items: value.items,
  };
}

/** Validate the catalog response and construct the feature-owned read model. */
export function ruleCatalogPageFromWire(input: unknown): RuleCatalogPage {
  const value = RuleCatalogPageSchema.parse(input);
  return {
    query: { ...value.query },
    asOf: value.asOf,
    coverage: value.coverage,
    bindings: { ...value.bindings },
    total: value.total,
    hasMore: value.hasMore,
    items: value.items.map((item) => ({
      binding: { ...item.binding },
      record: {
        id: item.record.id,
        rule: typedRuleValueFromWire(item.record.rule),
      },
      snapshot: { ...item.snapshot },
      read: { ...item.read },
    })),
    issues: value.issues.map((issue) => ({
      binding: { ...issue.binding },
      reason: issue.reason,
      lastAttemptAt: issue.lastAttemptAt,
      stale: issue.stale,
    })),
  };
}

/** Preserve the discriminator/value relationship when mapping rule values. */
function typedRuleValueFromWire(value: z.infer<typeof RuleValueSchema>): TypedRuleValue {
  switch (value.kind) {
    case "flow":
      return { kind: value.kind, value: { ...value.value } };
    case "degrade":
      return { kind: value.kind, value: { ...value.value } };
    case "system":
      return { kind: value.kind, value: { ...value.value } };
    case "authority":
      return { kind: value.kind, value: { ...value.value } };
    case "param":
      return {
        kind: value.kind,
        value: {
          ...value.value,
          paramFlowItemList: value.value.paramFlowItemList.map((item) => ({ ...item })),
        },
      };
    default: {
      const unreachable: never = value;
      return unreachable;
    }
  }
}

/** Validate and copy the refresh receipt into its feature-owned model. */
export function ruleCatalogRefreshFromWire(input: unknown): RuleCatalogRefreshResult {
  const value = RuleCatalogRefreshResultSchema.parse(input);
  return {
    scope: { ...value.scope },
    asOf: value.asOf,
    coverage: value.coverage,
    bindings: { ...value.bindings },
  };
}

/** Converts the feature-owned registration command to its strict Console wire body. */
export function bindingRegistrationToWire(command: RuleBindingRegistration) {
  return {
    requestKey: command.requestKey,
    bindingId: command.bindingId,
    environmentId: command.environmentId,
    appId: command.appId,
    kind: command.kind,
    profile: command.profile,
    sourceId: command.sourceId,
    sourceRevision: command.sourceRevision,
    target: { ...command.target },
  };
}

/** Parses the narrow safe receipt used to resolve an unknown binding-create outcome. */
export function bindingRegistrationReceiptFromWire(input: unknown): RuleBindingRegistrationReceipt {
  return RuleBindingRegistrationReceiptSchema.parse(input);
}

export function ruleSetSnapshotFromWire(input: unknown): RuleSetSnapshot {
  const value = RuleSetSnapshotSchema.parse(input);
  return {
    binding: value.binding,
    versionId: value.versionId,
    checksum: value.checksum,
    sourceRevision: value.sourceRevision,
    asOfMs: instantToMilliseconds(value.asOf),
    records: value.records,
  };
}

export function ruleSetCandidateToWire(candidate: RuleSetCandidate) {
  return RuleSetCandidateSchema.parse(candidate);
}

export function ruleCollectionFromWire<T>(
  input: unknown,
  itemSchema: z.ZodType<unknown>,
  map: (item: unknown) => T,
): RuleSetCollection<T> {
  const value = RuleSetCollectionSchema(itemSchema).parse(input);
  return {
    bindingId: value.bindingId,
    asOfMs: instantToMilliseconds(value.asOf),
    items: value.items.map(map),
  };
}

export function storedDraftFromWire(input: unknown): StoredRuleDraft {
  const value = StoredRuleDraftSchema.parse(input);
  return {
    id: value.id,
    bindingId: value.bindingId,
    revision: value.revision,
    kind: value.kind,
    profile: value.profile,
    baseVersionId: value.baseVersionId,
    baseChecksum: value.baseChecksum,
    sourceRevision: value.sourceRevision,
    updatedAtMs: instantToMilliseconds(value.updatedAt),
    records: value.records,
  };
}

export function versionFromWire(input: unknown): RuleSetVersion {
  const value = RuleSetVersionSchema.parse(input);
  return {
    id: value.id,
    bindingId: value.bindingId,
    kind: value.kind,
    profile: value.profile,
    baseVersionId: value.baseVersionId,
    checksum: value.checksum,
    name: value.name,
    note: value.note,
    createdAtMs: instantToMilliseconds(value.createdAt),
    createdById: value.createdById,
    records: value.records,
  };
}

export function publicationFromWire(input: unknown): RulePublication {
  const value = RulePublicationSchema.parse(input);
  const phase = (item: (typeof value)["validation"]) => ({
    state: item.state,
    observedAtMs: item.observedAt === null ? null : instantToMilliseconds(item.observedAt),
    reason: item.reason,
  });
  return {
    id: value.id,
    bindingId: value.bindingId,
    targetVersionId: value.targetVersionId,
    targetChecksum: value.targetChecksum,
    baseVersionId: value.baseVersionId,
    createdAtMs: instantToMilliseconds(value.createdAt),
    validation: phase(value.validation),
    configurationWrite: phase(value.configurationWrite),
    readBack: phase(value.readBack),
  };
}

export function receiptsFromWire(input: unknown): PublicationReceiptPage {
  const value = PublicationReceiptPageSchema.parse(input);
  return {
    publicationId: value.publicationId,
    bindingId: value.bindingId,
    page: value.page,
    pageSize: value.pageSize,
    asOfMs: instantToMilliseconds(value.asOf),
    total: value.total,
    expected: value.expected,
    inventorySource: value.inventorySource,
    applied: value.applied,
    pending: value.pending,
    failed: value.failed,
    unknown: value.unknown,
    restartRequired: value.restartRequired,
    items: value.items.map((item) => ({
      instanceId: item.instanceId,
      processEpoch: item.processEpoch,
      loadedProcessEpoch: item.loadedProcessEpoch,
      targetVersionId: item.targetVersionId,
      loadedVersionId: item.loadedVersionId,
      loadedChecksum: item.loadedChecksum,
      appliedAtMs: item.appliedAt === null ? null : instantToMilliseconds(item.appliedAt),
      lastReportAtMs: item.lastReportAt === null ? null : instantToMilliseconds(item.lastReportAt),
      state: item.state,
    })),
  };
}

export function planFromWire(input: unknown): RuleActivationPlan {
  const value = ActivationPlanSchema.parse(input);
  return {
    id: value.id,
    revision: value.revision,
    bindingId: value.bindingId,
    versionId: value.versionId,
    restoreVersionId: value.restoreVersionId,
    activateAtMs: instantToMilliseconds(value.activateAt),
    deactivateAtMs: instantToMilliseconds(value.deactivateAt),
    timeZone: value.timeZone,
    state: value.state,
    activationPublicationId: value.activationPublicationId,
    restorePublicationId: value.restorePublicationId,
  };
}

export function candidateToWire(candidate: RuleSetCandidate) {
  return RuleSetCandidateSchema.parse(candidate);
}

export function mutationToWire(mutation: RuleMutation) {
  if (mutation.kind === "create_plan") {
    const { activateAtMs, deactivateAtMs, ...restSchedule } = mutation.schedule;
    return {
      bindingId: mutation.bindingId,
      requestKey: mutation.requestKey,
      mutation: {
        kind: mutation.kind,
        schedule: {
          ...restSchedule,
          activateAt: millisecondsToInstant(activateAtMs),
          deactivateAt: millisecondsToInstant(deactivateAtMs),
        },
      },
    };
  }
  const { bindingId, requestKey, kind, ...payload } = mutation;
  return { bindingId, requestKey, mutation: { kind, ...payload } };
}

export function ruleValidationFromWire(input: unknown): RuleValidationReport {
  return RuleValidationReportSchema.parse(input);
}

export function diffFromWire(input: unknown): RuleSetDiff {
  return RuleSetDiffSchema.parse(input);
}

export function operationFromWire(input: unknown): RuleOperationObservation {
  const value = RuleOperationObservationSchema.parse(input);
  if (value.status !== "completed") return value;
  const result = value.result;
  const mapResult = (item: typeof result): RuleMutationResult => {
    switch (item.kind) {
      case "save_draft":
        return { ...item, draft: storedDraftFromWire(item.draft) };
      case "delete_draft":
        return item;
      case "freeze_version":
        return { ...item, version: versionFromWire(item.version) };
      case "publish":
        return { ...item, publication: publicationFromWire(item.publication) };
      case "create_plan":
      case "cancel_plan":
        return { ...item, plan: planFromWire(item.plan) };
      case "configure_target":
        return {
          kind: item.kind,
          target: {
            bindingId: item.bindingId,
            targetRevision: item.targetRevision,
            sourceRevision: item.sourceRevision,
            target: item.target,
          },
        };
    }
  };
  return { ...value, result: mapResult(result) };
}
