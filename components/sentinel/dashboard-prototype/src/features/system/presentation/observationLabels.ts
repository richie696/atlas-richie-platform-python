import type { ConnectionKind, ProtocolBoundaryId } from "../model/systemStatus";
import type {
  HealthState,
  HealthReason,
  HealthCapability,
  ProtocolCompatibility,
  AuditAction,
  AuditResult,
} from "../model/systemObservation";
import type { TranslationKey } from "../../../shared/types/translation";
/** Exhaustive formal labels only. Status decisions remain in the pure models/resources. */
export const CONNECTION_LABEL_KEY: Readonly<Record<ConnectionKind, TranslationKey>> = {
  "config-center": "system.observed.kind.configuration",
  "metrics-backend": "system.observed.kind.metrics",
  "reporting-collector": "system.observed.kind.collector",
};
export const HEALTH_LABEL_KEY: Readonly<Record<HealthState, TranslationKey>> = {
  available: "system.observed.health.available",
  unavailable: "system.observed.health.unavailable",
  unconfigured: "system.observed.health.unconfigured",
  unknown: "system.observed.health.unknown",
};
export const HEALTH_REASON_LABEL_KEY: Readonly<Record<HealthReason, TranslationKey>> = {
  network: "system.observed.reason.network",
  authentication: "system.observed.reason.authentication",
  unsupported: "system.observed.reason.unsupported",
  "not-configured": "system.observed.reason.unconfigured",
  "no-probe": "system.observed.reason.noProbe",
};
export const CAPABILITY_LABEL_KEY: Readonly<Record<HealthCapability, TranslationKey>> = {
  read: "system.observed.capability.read",
  "conditional-write": "system.observed.capability.conditionalWrite",
  watch: "system.observed.capability.watch",
  "query-metrics": "system.observed.capability.metrics",
  ingest: "system.observed.capability.ingest",
};
export const PROTOCOL_LABEL_KEY: Readonly<Record<ProtocolBoundaryId, TranslationKey>> = {
  "rule-config": "system.observed.protocol.rules",
  "agent-reporting": "system.observed.protocol.reporting",
  "cluster-token": "system.observed.protocol.token",
};
export const COMPATIBILITY_LABEL_KEY: Readonly<Record<ProtocolCompatibility, TranslationKey>> = {
  compatible: "system.observed.compatibility.compatible",
  incompatible: "system.observed.compatibility.incompatible",
  unknown: "system.observed.compatibility.unknown",
};
export const AUDIT_ACTION_LABEL_KEY: Readonly<Record<AuditAction, TranslationKey>> = {
  "account-create": "system.audit.action.accountCreate",
  "account-role": "system.audit.action.accountRole",
  "account-status": "system.audit.action.accountStatus",
  "password-change": "system.audit.action.passwordChange",
  "system-initialize": "system.audit.action.systemInitialize",
  "rule-validate": "system.audit.action.ruleValidate",
  "source-register": "system.audit.action.sourceRegister",
  "source-update": "system.audit.action.sourceUpdate",
  "draft-save": "system.audit.action.draftSave",
  "draft-delete": "system.audit.action.draftDelete",
  "version-freeze": "system.audit.action.versionFreeze",
  "rule-publish": "system.audit.action.rulePublish",
  "plan-create": "system.audit.action.planCreate",
  "plan-cancel": "system.audit.action.planCancel",
  "plan-activate": "system.audit.action.planActivate",
  "plan-restore": "system.audit.action.planRestore",
  "rule-binding-create": "system.audit.action.ruleBindingCreate",
};
export const AUDIT_RESULT_LABEL_KEY: Readonly<Record<AuditResult, TranslationKey>> = {
  success: "system.audit.result.success",
  rejected: "system.audit.result.rejected",
  unknown: "system.audit.result.unknown",
};
