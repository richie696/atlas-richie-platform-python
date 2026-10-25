import type { RuleKind } from "./ruleKinds";
import type { RuleBinding } from "./ruleSet";

export type RuleBindingObservedState =
  | "current_with_rules"
  | "configured_empty"
  | "target_missing"
  | "content_invalid"
  | "unsupported_profile"
  | "source_unavailable"
  | "not_read";
export type RuleLoadState =
  "applied" | "failed_keeps_last_known_good" | "failed_before_first_load" | "not_observed";
export type RuleLoadFreshness = "current" | "stale" | "unknown";
export type RuleLoadEventKind = "snapshot_applied" | "snapshot_failed" | "heartbeat";

export interface RuleBindingStatesQuery {
  readonly environmentId: string;
  readonly appId: string | null;
  readonly kind: RuleKind | null;
  readonly page: number;
  readonly pageSize: number;
}
export interface RuleBindingObservedStateItem {
  readonly binding: RuleBinding;
  readonly state: RuleBindingObservedState;
  readonly ruleCount: number | null;
  readonly sourceRevision: string | null;
  readonly lastAttemptAt: string | null;
  readonly freshness: "current" | "stale" | "not_read";
  readonly hasLastKnownGood: boolean;
}
export interface RuleBindingStatesPage {
  readonly query: RuleBindingStatesQuery;
  readonly asOf: string;
  readonly coverage: "complete" | "partial";
  readonly total: number | null;
  readonly hasMore: boolean;
  readonly items: readonly RuleBindingObservedStateItem[];
}

export interface RuleLoadObservationQuery {
  readonly environmentId: string;
  readonly appId: string;
  readonly bindingId: string | null;
  readonly instanceId: string | null;
  readonly page: number;
  readonly pageSize: number;
}
export interface RuleLoadObservationItem {
  readonly bindingId: string;
  readonly instanceId: string;
  readonly processId: string;
  readonly processEpoch: string | null;
  readonly profileId: string | null;
  readonly loadState: RuleLoadState;
  readonly eventKind: RuleLoadEventKind | null;
  readonly activeSnapshot: {
    readonly sourceRevision: string | null;
    readonly canonicalRulesSha256: string;
    readonly membershipComplete: boolean;
    readonly members: readonly {
      readonly ruleKind: RuleKind;
      readonly fingerprintSha256: string;
    }[];
  } | null;
  readonly attempt: {
    readonly sourceRevision: string | null;
    readonly canonicalRulesSha256: string | null;
    readonly failureReason:
      "source_unavailable" | "content_invalid" | "unsupported_profile" | "unknown";
  } | null;
  readonly observedAt: string | null;
  readonly receivedAt: string | null;
  readonly freshness: RuleLoadFreshness;
}
export interface RuleLoadObservationPage {
  readonly query: RuleLoadObservationQuery;
  readonly asOf: string;
  readonly coverage: "complete" | "partial";
  readonly targets: {
    readonly source: "active_reporter_enrollment";
    readonly expected: number | null;
    readonly observed: number | null;
    readonly stale: number | null;
    readonly notObserved: number | null;
  };
  readonly total: number | null;
  readonly hasMore: boolean;
  readonly items: readonly RuleLoadObservationItem[];
}
export interface RuleLoadObservationHistoryQuery {
  readonly environmentId: string;
  readonly appId: string;
  readonly bindingId: string;
  readonly instanceId: string | null;
  readonly page: number;
  readonly pageSize: number;
}
export interface RuleLoadObservationHistoryItem {
  readonly observationId: string;
  readonly epochStatus: "superseded" | "revoked" | "no_current_epoch";
  readonly observation: RuleLoadObservationItem;
}
export interface RuleLoadObservationHistoryPage {
  readonly query: RuleLoadObservationHistoryQuery;
  readonly asOf: string;
  readonly coverage: "complete" | "partial";
  readonly total: number | null;
  readonly hasMore: boolean;
  readonly items: readonly RuleLoadObservationHistoryItem[];
}

/** Bounded per-application runtime reads used to correlate visible catalog rows. */
export interface RuleCatalogUsageQuery {
  readonly environmentId: string;
  readonly bindings: readonly { readonly bindingId: string; readonly appId: string }[];
}
export interface RuleCatalogUsagePage {
  readonly query: RuleCatalogUsageQuery;
  readonly bindings: Readonly<Record<string, RuleLoadObservationPage>>;
}
