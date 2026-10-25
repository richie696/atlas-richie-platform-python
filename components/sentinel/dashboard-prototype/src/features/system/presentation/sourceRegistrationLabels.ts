import type { RuleSourceAuthenticationMode } from "../../../shared/model/configurationSource";
import type { SourceCheckCapability, SourceCheckResult } from "../model/sourceRegistration";
import type { TranslationKey } from "../../../shared/types/translation";
/** Finite presentation vocabulary; wire values never become field captions. */
export const SOURCE_AUTH_LABEL: Readonly<Record<RuleSourceAuthenticationMode, TranslationKey>> =
  Object.freeze({
    "credential-reference": "system.source.authReference",
    direct: "system.source.authDirect",
    none: "system.source.authNone",
  });
export const SOURCE_CHECK_LABEL: Readonly<Record<SourceCheckCapability, TranslationKey>> =
  Object.freeze({
    read: "system.observed.capability.read",
    "conditional-write": "system.observed.capability.conditionalWrite",
    watch: "system.observed.capability.watch",
  });
export const SOURCE_CHECK_REASON_LABEL: Readonly<
  Record<Extract<SourceCheckResult, { status: "unreachable" }>["reason"], TranslationKey>
> = Object.freeze({
  connection: "system.source.reason.connection",
  authentication: "system.source.reason.authentication",
  unsupported: "system.source.reason.unsupported",
});
