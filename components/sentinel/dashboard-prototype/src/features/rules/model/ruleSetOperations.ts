import type { RuleKind } from "./ruleKinds";
import type { RuleRecord, RuleSetCandidate } from "./ruleSet";
import type { RuleSetVersion, RulePublication } from "./ruleDeployment";
import type { ActivationSchedule, RuleActivationPlan } from "./ruleActivation";
import type { VersionedRulePublicationTarget } from "./rulePublicationTarget";

/** Persisted mutable draft identity/revision is independent from active source and immutable versions. */
export interface StoredRuleDraft {
  readonly id: string;
  readonly bindingId: string;
  readonly revision: string;
  readonly kind: RuleKind;
  readonly profile: string;
  readonly baseVersionId: string | null;
  readonly baseChecksum: string;
  readonly sourceRevision: string | null;
  readonly updatedAtMs: number;
  readonly records: readonly RuleRecord[];
}
export const RULE_SERVER_ISSUE = Object.freeze({
  Validation: "validation",
  UnsupportedField: "unsupported_field",
  UnsupportedCapability: "unsupported_capability",
  UnknownField: "unknown_field",
  Conflict: "conflict",
} as const);
export interface RuleServerIssue {
  readonly code: (typeof RULE_SERVER_ISSUE)[keyof typeof RULE_SERVER_ISSUE];
  readonly recordIndex: number | null;
  readonly path: string;
}
/** A report/ticket is bound to the exact candidate and deployment profile, never a permanent green flag. */
export interface RuleValidationReport {
  readonly bindingId: string;
  readonly profile: string;
  readonly baseChecksum: string;
  readonly candidateChecksum: string;
  readonly validationId: string;
  readonly isPublishable: boolean;
  readonly issues: readonly RuleServerIssue[];
}
export interface RuleSetDiff {
  readonly bindingId: string;
  readonly baseChecksum: string;
  readonly candidateChecksum: string;
  readonly changes: readonly (
    | { readonly operation: "add"; readonly after: RuleRecord["rule"] }
    | {
        readonly operation: "remove";
        readonly recordId: string;
        readonly before: RuleRecord["rule"];
      }
    | {
        readonly operation: "replace";
        readonly recordId: string;
        readonly before: RuleRecord["rule"];
        readonly after: RuleRecord["rule"];
      }
  )[];
}
export const RULE_MUTATION = Object.freeze({
  SaveDraft: "save_draft",
  DeleteDraft: "delete_draft",
  FreezeVersion: "freeze_version",
  Publish: "publish",
  CreatePlan: "create_plan",
  CancelPlan: "cancel_plan",
  ConfigureTarget: "configure_target",
} as const);
export type RuleMutationInput =
  | {
      readonly kind: typeof RULE_MUTATION.SaveDraft;
      readonly draftId: string | null;
      readonly expectedRevision: string | null;
      readonly candidate: RuleSetCandidate;
    }
  | {
      readonly kind: typeof RULE_MUTATION.DeleteDraft;
      readonly draftId: string;
      readonly expectedRevision: string;
    }
  | {
      readonly kind: typeof RULE_MUTATION.FreezeVersion;
      readonly draftId: string;
      readonly expectedRevision: string;
      readonly validationId: string;
      readonly candidateChecksum: string;
      readonly name: string;
      readonly note: string;
    }
  | {
      readonly kind: typeof RULE_MUTATION.Publish;
      readonly versionId: string;
      readonly versionChecksum: string;
      readonly expectedVersionId: string | null;
      readonly expectedChecksum: string;
      readonly expectedSourceRevision: string | null;
      readonly reason: string;
    }
  | { readonly kind: typeof RULE_MUTATION.CreatePlan; readonly schedule: ActivationSchedule }
  | {
      readonly kind: typeof RULE_MUTATION.CancelPlan;
      readonly planId: string;
      readonly expectedRevision: string;
      readonly reason: string;
    }
  | {
      readonly kind: typeof RULE_MUTATION.ConfigureTarget;
      readonly expectedSourceRevision: string;
      readonly expectedTargetRevision: string | null;
      readonly target: RuleMutationTarget;
    };
export type RuleMutationTarget =
  | {
      readonly provider: "nacos";
      readonly sourceId: string;
      readonly namespace: string;
      readonly group: string;
      readonly dataId: string;
    }
  | {
      readonly provider: "consul";
      readonly sourceId: string;
      readonly key: string;
    };
export type RuleMutation = RuleMutationInput & {
  readonly bindingId: string;
  readonly requestKey: string;
};
export type RuleMutationResult =
  | { readonly kind: typeof RULE_MUTATION.SaveDraft; readonly draft: StoredRuleDraft }
  | { readonly kind: typeof RULE_MUTATION.DeleteDraft; readonly draftId: string }
  | {
      readonly kind: typeof RULE_MUTATION.FreezeVersion;
      readonly draftId: string;
      readonly draftRevision: string;
      readonly version: RuleSetVersion;
    }
  | { readonly kind: typeof RULE_MUTATION.Publish; readonly publication: RulePublication }
  | { readonly kind: typeof RULE_MUTATION.CreatePlan; readonly plan: RuleActivationPlan }
  | { readonly kind: typeof RULE_MUTATION.CancelPlan; readonly plan: RuleActivationPlan }
  | {
      readonly kind: typeof RULE_MUTATION.ConfigureTarget;
      readonly target: VersionedRulePublicationTarget;
    };
export const RULE_REJECTION = Object.freeze({
  Validation: "validation",
  Conflict: "conflict",
  NotFound: "not_found",
  Unsupported: "unsupported",
  Unavailable: "unavailable",
} as const);
export type RuleOperationObservation = {
  readonly requestKey: string;
  readonly bindingId: string;
} & (
  | { readonly status: "pending" | "not-found" }
  | { readonly status: "completed"; readonly result: RuleMutationResult }
  | {
      readonly status: "rejected";
      readonly reason: (typeof RULE_REJECTION)[keyof typeof RULE_REJECTION];
    }
);
