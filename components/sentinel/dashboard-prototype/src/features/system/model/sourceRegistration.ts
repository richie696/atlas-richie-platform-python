import {
  RULE_SOURCE,
  RULE_SOURCE_AUTHENTICATION,
  RULE_SOURCE_AUTHENTICATION_MODES,
  isRuleSourceEndpoint,
  prepareConfigurationSource,
  type ConfigurationSourceDraft,
  type ConfigurationSourceInput,
  type RuleSourceAuthenticationMode,
} from "../../../shared/model/configurationSource";
import { identifier, timestamp, unique } from "./systemReadGuards";
export const SOURCE_CREDENTIAL_ACTION = Object.freeze({
  Keep: "keep",
  Replace: "replace",
} as const);
type SourceLocation =
  | { readonly provider: "nacos"; readonly namespace: string }
  | { readonly provider: "consul"; readonly datacenter: string };
/** Read-only identity/revision and non-secret configuration. Existing credentials or reference values are never returned. */
export type RegisteredSource = SourceLocation & {
  readonly id: string;
  readonly revision: string;
  readonly name: string;
  readonly endpoint: string;
  readonly authenticationMode: RuleSourceAuthenticationMode;
  readonly credentialConfigured: boolean;
};
export interface SourceRegistrySnapshot {
  readonly asOfMs: number;
  readonly items: readonly RegisteredSource[];
}
export type SourceUpdateInput =
  | ConfigurationSourceInput
  | (SourceLocation & {
      readonly endpoint: string;
      readonly authentication: { readonly mode: "keep" };
    });
export interface SourceRegistrationDraft {
  readonly name: string;
  readonly connection: ConfigurationSourceDraft;
  readonly credentialAction: (typeof SOURCE_CREDENTIAL_ACTION)[keyof typeof SOURCE_CREDENTIAL_ACTION];
}
export type SourceMutationInput =
  | { readonly kind: "register"; readonly name: string; readonly source: ConfigurationSourceInput }
  | {
      readonly kind: "update";
      readonly sourceId: string;
      readonly expectedRevision: string;
      readonly name: string;
      readonly source: SourceUpdateInput;
    }
  | { readonly kind: "delete"; readonly sourceId: string; readonly expectedRevision: string };
export type SourceMutation = SourceMutationInput & { readonly requestKey: string };
export interface SourceCheckInput {
  readonly sourceId: string | null;
  readonly expectedRevision: string | null;
  readonly source: SourceUpdateInput;
}
export const SOURCE_CHECK_CAPABILITY = Object.freeze({
  Read: "read",
  ConditionalWrite: "conditional-write",
  Watch: "watch",
} as const);
export type SourceCheckCapability =
  (typeof SOURCE_CHECK_CAPABILITY)[keyof typeof SOURCE_CHECK_CAPABILITY];
export type SourceCheckResult = { readonly checkedAtMs: number; readonly expiresAtMs: number } & (
  | { readonly status: "reachable"; readonly capabilities: readonly SourceCheckCapability[] }
  | {
      readonly status: "unreachable";
      readonly reason: "connection" | "authentication" | "unsupported";
    }
);
export type SourceOperationObservation =
  | { readonly requestKey: string; readonly status: "pending" | "not-found" }
  | { readonly requestKey: string; readonly status: "completed"; readonly record: RegisteredSource }
  | { readonly requestKey: string; readonly status: "completed"; readonly deletedSourceId: string }
  | {
      readonly requestKey: string;
      readonly status: "rejected";
      readonly reason: "validation" | "conflict" | "not-found" | "unavailable" | "source_in_use";
    };
/** Safe private expectation for register/update, never a retained source credential body. */
export interface SourceMutationOutcomeExpectation {
  readonly requestKey: string;
  readonly kind: "register" | "update";
  readonly sourceId: string | null;
  readonly name: string;
  readonly provider: "nacos" | "consul";
  readonly endpoint: string;
  readonly location: string;
  readonly authenticationMode: RuleSourceAuthenticationMode;
  readonly credentialConfigured: boolean;
}
/** Delete expectation deliberately retains only source identity/revision and request key. */
export interface SourceDeletionOutcomeExpectation {
  readonly requestKey: string;
  readonly kind: "delete";
  readonly sourceId: string;
  readonly expectedRevision: string;
}
export type SourceOutcomeExpectation =
  SourceMutationOutcomeExpectation | SourceDeletionOutcomeExpectation;
export type SourceCommandResult = RegisteredSource | { readonly deletedSourceId: string };
const EMPTY_CREDENTIALS = Object.freeze({
  reference: "",
  username: "",
  password: "",
  consulToken: "",
});
export function validRegisteredSource(record: RegisteredSource): boolean {
  return (
    [record.id, record.revision, record.name].every(identifier) &&
    isRuleSourceEndpoint(record.endpoint) &&
    RULE_SOURCE_AUTHENTICATION_MODES.includes(record.authenticationMode) &&
    (record.authenticationMode !== RULE_SOURCE_AUTHENTICATION.None ||
      !record.credentialConfigured) &&
    (record.provider === RULE_SOURCE.Nacos
      ? record.namespace.length <= 200
      : record.provider === RULE_SOURCE.Consul && record.datacenter.length <= 200)
  );
}
export function validSourceRegistry(value: SourceRegistrySnapshot): boolean {
  return (
    timestamp(value.asOfMs) &&
    unique(value.items, (record) => record.id) &&
    value.items.every(validRegisteredSource)
  );
}
/** Editing defaults to keep without inventing a username/reference. Adding starts explicitly unauthenticated, not mandatory KMS. */
export function sourceRegistrationDraft(record: RegisteredSource | null): SourceRegistrationDraft {
  return record
    ? {
        name: record.name,
        credentialAction: SOURCE_CREDENTIAL_ACTION.Keep,
        connection: {
          provider: record.provider,
          endpoint: record.endpoint,
          location: record.provider === RULE_SOURCE.Nacos ? record.namespace : record.datacenter,
          authentication: record.authenticationMode,
          credentials: EMPTY_CREDENTIALS,
        },
      }
    : {
        name: "",
        credentialAction: SOURCE_CREDENTIAL_ACTION.Replace,
        connection: {
          provider: RULE_SOURCE.Nacos,
          endpoint: "",
          location: "",
          authentication: RULE_SOURCE_AUTHENTICATION.None,
          credentials: EMPTY_CREDENTIALS,
        },
      };
}
export function clearSourceCredentials(draft: SourceRegistrationDraft): SourceRegistrationDraft {
  return { ...draft, connection: { ...draft.connection, credentials: EMPTY_CREDENTIALS } };
}
/** Provider/authentication-policy transitions cannot carry a hidden credential branch into another source. */
export function changeSourceRegistration(
  draft: SourceRegistrationDraft,
  next: SourceRegistrationDraft,
): SourceRegistrationDraft {
  const providerChanged = next.connection.provider !== draft.connection.provider;
  return providerChanged ||
    next.connection.authentication !== draft.connection.authentication ||
    next.credentialAction !== draft.credentialAction
    ? clearSourceCredentials({
        ...next,
        connection: providerChanged
          ? { ...next.connection, endpoint: "", location: "" }
          : next.connection,
        credentialAction:
          next.connection.provider !== draft.connection.provider
            ? SOURCE_CREDENTIAL_ACTION.Replace
            : next.credentialAction,
      })
    : next;
}
/** Canonical non-secret read identity, independent of JSON object insertion order. */
export function sourceRecordKey(record: RegisteredSource): string {
  return JSON.stringify([
    record.id,
    record.revision,
    record.name,
    record.provider,
    record.endpoint,
    record.provider === RULE_SOURCE.Nacos ? record.namespace : record.datacenter,
    record.authenticationMode,
    record.credentialConfigured,
  ]);
}
export function prepareSourceMutation(
  draft: SourceRegistrationDraft,
  record: RegisteredSource | null,
): SourceMutationInput | null {
  if (
    !identifier(draft.name) ||
    !isRuleSourceEndpoint(draft.connection.endpoint) ||
    draft.connection.location.length > 200
  )
    return null;
  if (record && !validRegisteredSource(record)) return null;
  if (draft.credentialAction === SOURCE_CREDENTIAL_ACTION.Keep) {
    if (!record || record.provider !== draft.connection.provider) return null;
    const source: SourceUpdateInput =
      record.provider === RULE_SOURCE.Nacos
        ? {
            provider: RULE_SOURCE.Nacos,
            endpoint: draft.connection.endpoint.trim(),
            namespace: draft.connection.location.trim(),
            authentication: { mode: "keep" },
          }
        : {
            provider: RULE_SOURCE.Consul,
            endpoint: draft.connection.endpoint.trim(),
            datacenter: draft.connection.location.trim(),
            authentication: { mode: "keep" },
          };
    return {
      kind: "update",
      sourceId: record.id,
      expectedRevision: record.revision,
      name: draft.name.trim(),
      source,
    };
  }
  if (draft.credentialAction !== SOURCE_CREDENTIAL_ACTION.Replace) return null;
  const source = prepareConfigurationSource(draft.connection);
  if (!source) return null;
  return record
    ? {
        kind: "update",
        sourceId: record.id,
        expectedRevision: record.revision,
        name: draft.name.trim(),
        source,
      }
    : { kind: "register", name: draft.name.trim(), source };
}
export function sourceCheckInput(
  input: SourceMutationInput & { readonly kind: "register" | "update" },
): SourceCheckInput {
  return {
    sourceId: input.kind === "update" ? input.sourceId : null,
    expectedRevision: input.kind === "update" ? input.expectedRevision : null,
    source: input.source,
  };
}
export function sourceOutcomeExpectation(
  mutation: SourceMutation & { readonly kind: "register" | "update" },
  record: RegisteredSource | null,
): SourceOutcomeExpectation {
  const keep = mutation.source.authentication.mode === "keep";
  if (keep && !record) throw new Error("Existing source required for credential preservation");
  return {
    requestKey: mutation.requestKey,
    kind: mutation.kind,
    sourceId: mutation.kind === "update" ? mutation.sourceId : null,
    name: mutation.name,
    provider: mutation.source.provider,
    endpoint: mutation.source.endpoint,
    location:
      mutation.source.provider === RULE_SOURCE.Nacos
        ? mutation.source.namespace
        : mutation.source.datacenter,
    authenticationMode: keep ? record!.authenticationMode : mutation.source.authentication.mode,
    credentialConfigured: keep
      ? record!.credentialConfigured
      : mutation.source.authentication.mode !== RULE_SOURCE_AUTHENTICATION.None,
  };
}
export function sourceDeletionExpectation(
  requestKey: string,
  record: RegisteredSource,
): SourceDeletionOutcomeExpectation {
  if (!validRegisteredSource(record)) throw new Error("Valid source required for deletion");
  return {
    requestKey,
    kind: "delete",
    sourceId: record.id,
    expectedRevision: record.revision,
  };
}
export function validSourceCheck(value: SourceCheckResult): boolean {
  return (
    timestamp(value.checkedAtMs) &&
    timestamp(value.expiresAtMs) &&
    value.expiresAtMs > value.checkedAtMs &&
    (value.status === "reachable"
      ? value.capabilities.length <= Object.values(SOURCE_CHECK_CAPABILITY).length &&
        new Set(value.capabilities).size === value.capabilities.length &&
        value.capabilities.every((capability) =>
          Object.values(SOURCE_CHECK_CAPABILITY).includes(capability),
        )
      : value.status === "unreachable" &&
        ["connection", "authentication", "unsupported"].includes(value.reason))
  );
}
/** Completed receipt is matched to the actual safe intent; pending/not-found never prove rollback. */
export function validSourceObservation(
  value: SourceOperationObservation,
  expected: SourceOutcomeExpectation,
): boolean {
  if (value.requestKey !== expected.requestKey) return false;
  if (value.status === "pending" || value.status === "not-found") return true;
  if (value.status === "rejected" && "reason" in value)
    return ["validation", "conflict", "not-found", "unavailable", "source_in_use"].includes(
      value.reason,
    );
  if (expected.kind === "delete")
    return (
      value.status === "completed" &&
      "deletedSourceId" in value &&
      value.deletedSourceId === expected.sourceId
    );
  if (value.status !== "completed" || !("record" in value) || !validRegisteredSource(value.record))
    return false;
  const record = value.record;
  return (
    (expected.sourceId === null || record.id === expected.sourceId) &&
    record.name === expected.name &&
    record.provider === expected.provider &&
    record.endpoint === expected.endpoint &&
    (record.provider === RULE_SOURCE.Nacos ? record.namespace : record.datacenter) ===
      expected.location &&
    record.authenticationMode === expected.authenticationMode &&
    record.credentialConfigured === expected.credentialConfigured
  );
}
