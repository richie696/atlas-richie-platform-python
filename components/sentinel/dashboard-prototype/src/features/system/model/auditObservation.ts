import { identifier, timestamp, unique, SYSTEM_IDENTIFIER_LIMIT } from "./systemReadGuards";
import { compareScalarText } from "../../../shared/model/scalarTextOrder";
export const AUDIT_ACTION = Object.freeze({
  AccountCreate: "account-create",
  AccountRole: "account-role",
  AccountStatus: "account-status",
  AccountPasswordReset: "account-password-reset",
  LocalAdminPasswordRecovery: "local-admin-password-recovery",
  AccountDelete: "account-delete",
  PasswordChange: "password-change",
  SystemInitialize: "system-initialize",
  RuleValidate: "rule-validate",
  SourceRegister: "source-register",
  SourceUpdate: "source-update",
  SourceDelete: "source-delete",
  DeploymentDependenciesMigrated: "deployment-dependencies-migrated",
  ReporterCertificateRotated: "reporter-certificate-rotated",
  MonitoringSourceCreate: "monitoring-source-create",
  MonitoringSourceUpdate: "monitoring-source-update",
  MonitoringSourceDelete: "monitoring-source-delete",
  MonitoringSourceEnable: "monitoring-source-enable",
  MonitoringSourceDisable: "monitoring-source-disable",
  HostAssociationCreate: "host-association-create",
  HostAssociationDelete: "host-association-delete",
  DraftSave: "draft-save",
  DraftDelete: "draft-delete",
  VersionFreeze: "version-freeze",
  RulePublish: "rule-publish",
  PlanCreate: "plan-create",
  PlanCancel: "plan-cancel",
  PlanActivate: "plan-activate",
  PlanRestore: "plan-restore",
  TargetConfigure: "target-configure",
  RuleBindingCreate: "rule-binding-create",
} as const);
export type AuditAction = (typeof AUDIT_ACTION)[keyof typeof AUDIT_ACTION];
export const AUDIT_RESULT = Object.freeze({
  Success: "success",
  Rejected: "rejected",
  Unknown: "unknown",
} as const);
export type AuditResult = (typeof AUDIT_RESULT)[keyof typeof AUDIT_RESULT];
const ANONYMOUS_AUDIT_ACTIONS: readonly AuditAction[] = [
  AUDIT_ACTION.SystemInitialize,
  AUDIT_ACTION.LocalAdminPasswordRecovery,
  AUDIT_ACTION.PlanActivate,
  AUDIT_ACTION.PlanRestore,
];
export interface AuditQuery {
  readonly startMs: number;
  readonly endMs: number;
  readonly actorId: string;
  readonly action: AuditAction | null;
  readonly result: AuditResult | null;
  readonly page: number;
  readonly pageSize: number;
}
/** Bounded audit projection. No body, credentials, tracebacks, free-form business logs or impersonation identity. */
export interface AuditRecord {
  readonly id: string;
  readonly occurredAtMs: number;
  readonly actorId: string | null;
  readonly action: AuditAction;
  readonly targetId: string;
  readonly result: AuditResult;
  /** Original server-recorded HTTP correlation ID; distinct from an idempotency key. */
  readonly requestId: string;
  /** Safe navigation context for an associated ruleset; null for non-application actions. */
  readonly environmentId: string | null;
  readonly appId: string | null;
  readonly bindingId: string | null;
  readonly publicationId: string | null;
}
export interface AuditPage {
  readonly query: AuditQuery;
  readonly asOfMs: number;
  readonly total: number;
  readonly items: readonly AuditRecord[];
}
export const AUDIT_MAX_WINDOW_MS = 31 * 24 * 60 * 60 * 1000;
export const AUDIT_MAX_PAGE_SIZE = 100;
/** The UTC half-open audit range is independent from chart windows; all filter dimensions own cache identity. */
export function auditQueryKey(query: AuditQuery): string {
  return JSON.stringify([
    query.startMs,
    query.endMs,
    query.actorId,
    query.action,
    query.result,
    query.page,
    query.pageSize,
  ]);
}
export function validAuditQuery(query: AuditQuery): boolean {
  return (
    timestamp(query.startMs) &&
    timestamp(query.endMs) &&
    query.endMs > query.startMs &&
    query.endMs - query.startMs <= AUDIT_MAX_WINDOW_MS &&
    query.actorId.length <= SYSTEM_IDENTIFIER_LIMIT &&
    (query.actorId === "" || identifier(query.actorId)) &&
    (query.action === null || Object.values(AUDIT_ACTION).includes(query.action)) &&
    (query.result === null || Object.values(AUDIT_RESULT).includes(query.result)) &&
    Number.isSafeInteger(query.page) &&
    query.page > 0 &&
    Number.isSafeInteger(query.pageSize) &&
    query.pageSize > 0 &&
    query.pageSize <= AUDIT_MAX_PAGE_SIZE
  );
}
/** Only system initialization and scheduled activation/restoration may lack an account actor. */
export function validAuditActor(action: AuditAction, actorId: string | null): boolean {
  return actorId === null ? ANONYMOUS_AUDIT_ACTIONS.includes(action) : identifier(actorId);
}
export function validAuditPage(value: AuditPage, query: AuditQuery): boolean {
  return (
    validAuditQuery(query) &&
    auditQueryKey(value.query) === auditQueryKey(query) &&
    timestamp(value.asOfMs) &&
    Number.isSafeInteger(value.total) &&
    value.total >= 0 &&
    value.items.length <= query.pageSize &&
    value.items.length <= Math.max(0, value.total - (query.page - 1) * query.pageSize) &&
    unique(value.items, (item) => item.id) &&
    value.items.every(
      (item) =>
        identifier(item.id) &&
        validAuditActor(item.action, item.actorId) &&
        identifier(item.targetId) &&
        identifier(item.requestId) &&
        timestamp(item.occurredAtMs) &&
        item.occurredAtMs >= query.startMs &&
        item.occurredAtMs < query.endMs &&
        item.occurredAtMs <= value.asOfMs &&
        Object.values(AUDIT_ACTION).includes(item.action) &&
        Object.values(AUDIT_RESULT).includes(item.result) &&
        (!query.actorId || item.actorId === query.actorId) &&
        (!query.action || item.action === query.action) &&
        (!query.result || item.result === query.result) &&
        (item.bindingId === null || identifier(item.bindingId)) &&
        (item.environmentId === null || identifier(item.environmentId)) &&
        (item.appId === null || identifier(item.appId)) &&
        (item.publicationId === null ||
          (identifier(item.publicationId) &&
            item.bindingId !== null &&
            item.environmentId !== null &&
            item.appId !== null)),
    ) &&
    value.items.every(
      (item, index) =>
        index === 0 ||
        value.items[index - 1].occurredAtMs > item.occurredAtMs ||
        (value.items[index - 1].occurredAtMs === item.occurredAtMs &&
          compareScalarText(value.items[index - 1].id, item.id) > 0),
    )
  );
}
