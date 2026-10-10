import type { BindingQuery, BindingPage } from "../model/ruleDirectory";
import type { RuleBindingRegistration } from "../model/ruleBindingRegistration";
import type { RuleBinding } from "../model/ruleSet";
import type { RuleSetSnapshot, RuleSetCandidate, RuleSetCollection } from "../model/ruleSet";
import type {
  RuleSetVersion,
  RulePublication,
  PublicationReceiptPage,
} from "../model/ruleDeployment";
import type { RuleActivationPlan } from "../model/ruleActivation";
import type { RulePublicationTargetSnapshot } from "../model/rulePublicationTarget";
import type {
  StoredRuleDraft,
  RuleValidationReport,
  RuleSetDiff,
  RuleMutation,
  RuleOperationObservation,
} from "../model/ruleSetOperations";

export interface PublicationReceiptQuery {
  readonly bindingId: string;
  readonly publicationId: string;
  readonly page: number;
  readonly pageSize: number;
}

/** Consumer effects, not frozen JSON endpoints. Same future HTTP adapter serves mock and live. */
export interface RuleSetPort {
  readonly readBindings: (query: BindingQuery, signal: AbortSignal) => Promise<BindingPage>;
  readonly registerBinding: (
    command: RuleBindingRegistration,
    signal: AbortSignal,
  ) => Promise<RuleBinding>;
  readonly readSnapshot: (bindingId: string, signal: AbortSignal) => Promise<RuleSetSnapshot>;
  readonly readDrafts: (
    bindingId: string,
    signal: AbortSignal,
  ) => Promise<RuleSetCollection<StoredRuleDraft>>;
  readonly readDraft: (
    bindingId: string,
    draftId: string,
    signal: AbortSignal,
  ) => Promise<StoredRuleDraft>;
  readonly validateCandidate: (
    candidate: RuleSetCandidate,
    signal: AbortSignal,
  ) => Promise<RuleValidationReport>;
  readonly compareCandidate: (
    candidate: RuleSetCandidate,
    signal: AbortSignal,
  ) => Promise<RuleSetDiff>;
  readonly readVersions: (
    bindingId: string,
    signal: AbortSignal,
  ) => Promise<RuleSetCollection<RuleSetVersion>>;
  readonly readVersion: (
    bindingId: string,
    versionId: string,
    signal: AbortSignal,
  ) => Promise<RuleSetVersion>;
  readonly readPublications: (
    bindingId: string,
    signal: AbortSignal,
  ) => Promise<RuleSetCollection<RulePublication>>;
  readonly readPublication: (
    bindingId: string,
    publicationId: string,
    signal: AbortSignal,
  ) => Promise<RulePublication>;
  readonly readReceipts: (
    query: PublicationReceiptQuery,
    signal: AbortSignal,
  ) => Promise<PublicationReceiptPage>;
  readonly readPlans: (
    bindingId: string,
    signal: AbortSignal,
  ) => Promise<RuleSetCollection<RuleActivationPlan>>;
  readonly readPublicationTarget: (
    bindingId: string,
    signal: AbortSignal,
  ) => Promise<RulePublicationTargetSnapshot>;
  /** Durable command acceptance is not source write/readback/application success. No browser scheduling. */
  readonly mutateRuleSet: (
    mutation: RuleMutation,
    signal: AbortSignal,
  ) => Promise<RuleOperationObservation>;
  /** Not-found/pending does not prove rollback and must not unlock a second mutation. */
  readonly readRuleOperation: (
    bindingId: string,
    requestKey: string,
    signal: AbortSignal,
  ) => Promise<RuleOperationObservation>;
}
