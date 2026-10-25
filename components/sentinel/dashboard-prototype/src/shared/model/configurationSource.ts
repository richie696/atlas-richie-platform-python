/** Shared pure configuration-source semantics for bootstrap and normal administration. No UI, persistence, KMS or transport. */
import { isSupportedConfigurationSourceEndpoint } from "../protocol/configurationSourceEndpoint";

export const RULE_SOURCE = Object.freeze({ Nacos: "nacos", Consul: "consul" } as const);
export type RuleSourceKind = (typeof RULE_SOURCE)[keyof typeof RULE_SOURCE];
export const RULE_SOURCES: readonly RuleSourceKind[] = Object.freeze(Object.values(RULE_SOURCE));
export const RULE_SOURCE_AUTHENTICATION = Object.freeze({
  CredentialReference: "credential-reference",
  Direct: "direct",
  None: "none",
} as const);
export type RuleSourceAuthenticationMode =
  (typeof RULE_SOURCE_AUTHENTICATION)[keyof typeof RULE_SOURCE_AUTHENTICATION];
export const RULE_SOURCE_AUTHENTICATION_MODES: readonly RuleSourceAuthenticationMode[] =
  Object.freeze(Object.values(RULE_SOURCE_AUTHENTICATION));
/** Transient write-only inputs. Switching provider/authentication clears all inactive branches in the owning form. */
export interface RuleSourceCredentials {
  readonly reference: string;
  readonly username: string;
  readonly password: string;
  readonly consulToken: string;
}
export interface ConfigurationSourceDraft {
  readonly provider: RuleSourceKind;
  readonly endpoint: string;
  readonly location: string;
  readonly authentication: RuleSourceAuthenticationMode;
  readonly credentials: RuleSourceCredentials;
}
type NonDirectAuthentication =
  { readonly mode: "none" } | { readonly mode: "credential-reference"; readonly reference: string };
export type ConfigurationSourceInput =
  | {
      readonly provider: "nacos";
      readonly endpoint: string;
      readonly namespace: string;
      readonly authentication:
        | NonDirectAuthentication
        | { readonly mode: "direct"; readonly username: string; readonly password: string };
    }
  | {
      readonly provider: "consul";
      readonly endpoint: string;
      readonly datacenter: string;
      readonly authentication:
        NonDirectAuthentication | { readonly mode: "direct"; readonly aclToken: string };
    };
export const SOURCE_CONFIGURATION_ISSUE = Object.freeze({
  Endpoint: "endpoint-invalid",
  Reference: "reference-required",
  NacosCredentials: "nacos-credentials-required",
  ConsulToken: "consul-token-required",
  Unsupported: "unsupported-configuration",
} as const);
export type SourceConfigurationIssue =
  (typeof SOURCE_CONFIGURATION_ISSUE)[keyof typeof SOURCE_CONFIGURATION_ISSUE];
/** Local URL syntax only. The Python connector independently enforces SSRF, TLS and destination policies. */
export function isRuleSourceEndpoint(value: string): boolean {
  return isSupportedConfigurationSourceEndpoint(value);
}
export function validateConfigurationSource(
  draft: ConfigurationSourceDraft,
): readonly SourceConfigurationIssue[] {
  if (
    !RULE_SOURCES.includes(draft.provider) ||
    !RULE_SOURCE_AUTHENTICATION_MODES.includes(draft.authentication)
  )
    return [SOURCE_CONFIGURATION_ISSUE.Unsupported];
  if (!isRuleSourceEndpoint(draft.endpoint)) return [SOURCE_CONFIGURATION_ISSUE.Endpoint];
  if (
    draft.authentication === RULE_SOURCE_AUTHENTICATION.CredentialReference &&
    !draft.credentials.reference.trim()
  )
    return [SOURCE_CONFIGURATION_ISSUE.Reference];
  if (draft.authentication === RULE_SOURCE_AUTHENTICATION.Direct) {
    if (
      draft.provider === RULE_SOURCE.Nacos &&
      !(draft.credentials.username.trim() && draft.credentials.password)
    )
      return [SOURCE_CONFIGURATION_ISSUE.NacosCredentials];
    if (draft.provider === RULE_SOURCE.Consul && !draft.credentials.consulToken)
      return [SOURCE_CONFIGURATION_ISSUE.ConsulToken];
  }
  return [];
}
/** Project only the selected provider/authentication. Secret whitespace is preserved, irrelevant credentials are omitted. */
export function prepareConfigurationSource(
  draft: ConfigurationSourceDraft,
): ConfigurationSourceInput | null {
  if (validateConfigurationSource(draft).length) return null;
  const shared: NonDirectAuthentication =
    draft.authentication === RULE_SOURCE_AUTHENTICATION.CredentialReference
      ? {
          mode: RULE_SOURCE_AUTHENTICATION.CredentialReference,
          reference: draft.credentials.reference.trim(),
        }
      : { mode: RULE_SOURCE_AUTHENTICATION.None };
  return draft.provider === RULE_SOURCE.Nacos
    ? {
        provider: RULE_SOURCE.Nacos,
        endpoint: draft.endpoint.trim(),
        namespace: draft.location.trim(),
        authentication:
          draft.authentication === RULE_SOURCE_AUTHENTICATION.Direct
            ? {
                mode: RULE_SOURCE_AUTHENTICATION.Direct,
                username: draft.credentials.username.trim(),
                password: draft.credentials.password,
              }
            : shared,
      }
    : {
        provider: RULE_SOURCE.Consul,
        endpoint: draft.endpoint.trim(),
        datacenter: draft.location.trim(),
        authentication:
          draft.authentication === RULE_SOURCE_AUTHENTICATION.Direct
            ? { mode: RULE_SOURCE_AUTHENTICATION.Direct, aclToken: draft.credentials.consulToken }
            : shared,
      };
}
