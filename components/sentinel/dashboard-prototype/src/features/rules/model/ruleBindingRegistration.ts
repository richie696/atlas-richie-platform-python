import type { RuleKind } from "./ruleKinds";
import type { RuleBinding } from "./ruleSet";

/** Safe rule-source facts needed to register a binding; credentials never cross this contract. */
export type RuleSourceOption =
  | {
      readonly id: string;
      readonly revision: string;
      readonly name: string;
      readonly provider: "nacos";
      readonly namespace: string;
    }
  | {
      readonly id: string;
      readonly revision: string;
      readonly name: string;
      readonly provider: "consul";
      readonly datacenter: string;
    };

/** Current registered-source facts are authoritative for provider and revision selection. */
export interface RuleSourceCatalog {
  readonly asOfMs: number;
  readonly items: readonly RuleSourceOption[];
}

/** The rules feature consumes only this safe source catalog, not the system feature's write API. */
export interface RuleSourceCatalogPort {
  readonly readSources: (signal: AbortSignal) => Promise<RuleSourceCatalog>;
}

/** Inputs shown by the registration form. The adapter adds the exact source revision at submit. */
export interface RuleBindingRegistrationDraft {
  readonly bindingId: string;
  readonly environmentId: string;
  readonly appId: string;
  readonly kind: RuleKind;
  readonly profile: string;
  readonly sourceId: string;
  readonly namespace: string;
  readonly group: string;
  readonly dataId: string;
  readonly datacenter: string;
  readonly key: string;
}

/** A common profile already used by all five Sentinel-compatible demo bindings. */
export const DEFAULT_SENTINEL_RULE_PROFILE = "sentinel-python-v1";

/** Nacos' documented default group is a form suggestion, not an unlabelled protocol fallback. */
export const DEFAULT_NACOS_RULE_GROUP = "DEFAULT_GROUP";

const hasIdentity = (value: string) => value.trim().length > 0;

/** Reject an incomplete or malformed safe source catalog before it reaches a form. */
export function validRuleSourceCatalog(value: RuleSourceCatalog): boolean {
  return (
    Number.isSafeInteger(value.asOfMs) &&
    value.asOfMs >= 0 &&
    new Set(value.items.map((source) => source.id)).size === value.items.length &&
    value.items.every(
      (source) =>
        [source.id, source.revision, source.name].every(hasIdentity) &&
        (source.provider === "nacos"
          ? typeof source.namespace === "string" && source.namespace.length <= 200
          : source.provider === "consul" &&
            typeof source.datacenter === "string" &&
            source.datacenter.length <= 200),
    )
  );
}

/** Build an exact registration command from the selected authoritative source revision. */
export function prepareRuleBindingRegistration(
  draft: RuleBindingRegistrationDraft,
  source: RuleSourceOption | undefined,
  requestKey: string,
): RuleBindingRegistration | null {
  if (
    !source ||
    ![
      draft.bindingId,
      draft.environmentId,
      draft.appId,
      draft.profile,
      source.id,
      source.revision,
      requestKey,
    ].every(hasIdentity)
  )
    return null;
  const target: RuleBindingRegistrationTarget | null =
    source.provider === "nacos"
      ? [draft.namespace, draft.group, draft.dataId].every(hasIdentity)
        ? {
            provider: "nacos",
            namespace: draft.namespace.trim(),
            group: draft.group.trim(),
            dataId: draft.dataId.trim(),
          }
        : null
      : hasIdentity(draft.key)
        ? {
            provider: "consul",
            datacenter: draft.datacenter.trim() || null,
            key: draft.key.trim(),
          }
        : null;
  return target
    ? {
        requestKey,
        bindingId: draft.bindingId.trim(),
        environmentId: draft.environmentId.trim(),
        appId: draft.appId.trim(),
        kind: draft.kind,
        profile: draft.profile.trim(),
        sourceId: source.id,
        sourceRevision: source.revision,
        target,
      }
    : null;
}

/** Exact provider destination captured when an administrator registers a ruleset binding. */
export type RuleBindingRegistrationTarget =
  | {
      readonly provider: "nacos";
      readonly namespace: string;
      readonly group: string;
      readonly dataId: string;
    }
  | {
      readonly provider: "consul";
      readonly datacenter: string | null;
      readonly key: string;
    };

/** Credential-free Console command. It registers metadata and a target; it never writes rule content. */
export interface RuleBindingRegistration {
  readonly requestKey: string;
  readonly bindingId: string;
  readonly environmentId: string;
  readonly appId: string;
  readonly kind: RuleKind;
  readonly profile: string;
  readonly sourceId: string;
  readonly sourceRevision: string;
  readonly target: RuleBindingRegistrationTarget;
}

/** Safe read-only outcome of inspecting the exact original binding-create request. */
export type RuleBindingRegistrationReceipt =
  | {
      readonly requestKey: string;
      readonly bindingId: string;
      readonly status: "completed";
      readonly binding: RuleBinding;
    }
  | {
      readonly requestKey: string;
      readonly bindingId: string;
      readonly status: "not_found";
      readonly binding: null;
    };

/** Reject malformed or cross-request receipt facts before they can resolve an unknown command. */
export function validRuleBindingRegistrationReceipt(
  value: RuleBindingRegistrationReceipt,
  requestKey: string,
  bindingId: string,
): boolean {
  return (
    !!value &&
    value.requestKey === requestKey &&
    value.bindingId === bindingId &&
    (value.status === "completed"
      ? !!value.binding && value.binding.id === bindingId
      : value.status === "not_found" && value.binding === null)
  );
}
