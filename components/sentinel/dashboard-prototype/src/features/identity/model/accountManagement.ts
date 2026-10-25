import {
  ACCOUNT_STATUS,
  IDENTITY_ROLE,
  isIdentityRoleId,
  validateAccountDraft,
  type AccountDraft,
  type AccountDraftIssue,
  type AccountStatus,
  type AccountSummary,
  type IdentityRoleId,
} from "./account";

/** Raw management record. UTC/null replaces legacy formatted demo last-login text. */
export interface AccountRecord extends Omit<AccountSummary, "lastLoginAt"> {
  readonly lastLoginAt: string | null;
  readonly revision: string;
  /** Server hint, not a substitute for atomic last-admin protection on every mutation. */
  readonly lastActiveAdmin: boolean;
}

export const ACCOUNT_PAGE_SIZE_LIMIT = 100;
/** Maximum account-directory search size in UTF-16 code units, matching the Console wire contract. */
export const ACCOUNT_SEARCH_MAX_LENGTH = 200;

/**
 * Keep interactive account search within its wire bound without cutting a
 * supplementary Unicode character in half.
 */
export function boundAccountSearch(value: string): string {
  if (value.length <= ACCOUNT_SEARCH_MAX_LENGTH) return value;
  let end = 0;
  for (const character of value) {
    if (end + character.length > ACCOUNT_SEARCH_MAX_LENGTH) break;
    end += character.length;
  }
  return value.slice(0, end);
}

/** Directory filters contain no secrets or local role-based authentication assumptions. */
export interface AccountListQuery {
  readonly page: number;
  readonly pageSize: number;
  readonly search: string;
  readonly status?: AccountStatus;
}
export interface AccountPage {
  readonly items: readonly AccountRecord[];
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
}

/** Reject malformed queries instead of silently issuing a different page/filter. */
export function validateAccountQuery(
  query: AccountListQuery,
): readonly ("page" | "pageSize" | "search" | "status")[] {
  const issues: ("page" | "pageSize" | "search" | "status")[] = [];
  if (!Number.isSafeInteger(query.page) || query.page < 1) issues.push("page");
  if (
    !Number.isSafeInteger(query.pageSize) ||
    query.pageSize < 1 ||
    query.pageSize > ACCOUNT_PAGE_SIZE_LIMIT
  )
    issues.push("pageSize");
  if (query.search.length > ACCOUNT_SEARCH_MAX_LENGTH) issues.push("search");
  if (
    query.status !== undefined &&
    query.status !== ACCOUNT_STATUS.Active &&
    query.status !== ACCOUNT_STATUS.Disabled
  )
    issues.push("status");
  return issues;
}

/** Write-only projection: no ID generation, display name or confirmation fields. */
export function prepareAccountCreation(
  draft: AccountDraft,
):
  | { readonly status: "invalid"; readonly issues: readonly AccountDraftIssue[] }
  | { readonly status: "valid"; readonly input: AccountDraft } {
  const issues = validateAccountDraft(draft);
  return issues.length
    ? { status: "invalid", issues }
    : {
        status: "valid",
        input: Object.freeze({
          username: draft.username.trim(),
          password: draft.password,
          roleId: draft.roleId,
        }),
      };
}

export type AccountChangeIssue =
  | "not_found"
  | "built_in"
  | "last_admin"
  | "inactive"
  | "unchanged"
  | "invalid_status"
  | "invalid_role";
/** Conservative UI protection. The server must recheck against the complete directory in a transaction. */
export function accountStatusIssue(
  record: AccountRecord | null,
  status: string,
): AccountChangeIssue | null {
  if (!record) return "not_found";
  if (status !== ACCOUNT_STATUS.Active && status !== ACCOUNT_STATUS.Disabled)
    return "invalid_status";
  if (record.status === status) return "unchanged";
  if (status === ACCOUNT_STATUS.Disabled && record.builtIn) return "built_in";
  if (status === ACCOUNT_STATUS.Disabled && record.lastActiveAdmin) return "last_admin";
  return null;
}
/** Disabled/protected accounts cannot be edited through a stale role form. */
export function accountRoleIssue(
  record: AccountRecord | null,
  roleId: string,
): AccountChangeIssue | null {
  if (!record) return "not_found";
  if (!isIdentityRoleId(roleId)) return "invalid_role";
  if (record.status === ACCOUNT_STATUS.Disabled) return "inactive";
  if (record.roleId === roleId) return "unchanged";
  if (roleId !== IDENTITY_ROLE.Admin && record.builtIn) return "built_in";
  if (roleId !== IDENTITY_ROLE.Admin && record.lastActiveAdmin) return "last_admin";
  return null;
}

/** Local edit buffer, not persisted role facts. Its baseline never follows a refresh silently. */
export interface RoleDraft {
  readonly accountId: string;
  readonly revision: string;
  readonly baseRoleId: IdentityRoleId;
  readonly roleId: IdentityRoleId;
}
export const ROLE_DRAFT_SNAPSHOT_SCHEMA_VERSION = 1;
/** Versioned, non-sensitive role edit payload persisted only for the current browser tab. */
export interface RoleDraftSnapshot extends RoleDraft {
  readonly schemaVersion: typeof ROLE_DRAFT_SNAPSHOT_SCHEMA_VERSION;
}
export function createRoleDraft(record: AccountRecord): RoleDraft {
  return Object.freeze({
    accountId: record.id,
    revision: record.revision,
    baseRoleId: record.roleId,
    roleId: record.roleId,
  });
}
/** Create the non-sensitive, versioned snapshot used to restore an unsaved role edit in this tab. */
export function createRoleDraftSnapshot(draft: RoleDraft): RoleDraftSnapshot {
  return Object.freeze({ schemaVersion: ROLE_DRAFT_SNAPSHOT_SCHEMA_VERSION, ...draft });
}
/**
 * Validate an untrusted browser-storage value for one authoritative target.
 * Stored role changes are never allowed to change the account or revision they
 * were originally based on.
 */
export function restoreRoleDraftSnapshot(accountId: string, value: unknown): RoleDraft | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const snapshot = value as Record<string, unknown>,
    expectedKeys = ["accountId", "baseRoleId", "revision", "roleId", "schemaVersion"];
  const keys = Object.keys(snapshot).sort();
  if (
    keys.length !== expectedKeys.length ||
    keys.some((key, index) => key !== expectedKeys[index]) ||
    snapshot.schemaVersion !== ROLE_DRAFT_SNAPSHOT_SCHEMA_VERSION ||
    snapshot.accountId !== accountId ||
    typeof snapshot.revision !== "string" ||
    snapshot.revision.length === 0 ||
    typeof snapshot.baseRoleId !== "string" ||
    typeof snapshot.roleId !== "string" ||
    !isIdentityRoleId(snapshot.baseRoleId) ||
    !isIdentityRoleId(snapshot.roleId) ||
    snapshot.baseRoleId === snapshot.roleId
  )
    return null;
  return Object.freeze({
    accountId: snapshot.accountId,
    revision: snapshot.revision,
    baseRoleId: snapshot.baseRoleId,
    roleId: snapshot.roleId,
  });
}
/** True when the local role differs from the baseline the user began editing. */
export function roleDraftIsDirty(draft: RoleDraft): boolean {
  return draft.roleId !== draft.baseRoleId;
}
/**
 * Reconcile a local edit buffer with a newly read record for the same account.
 * A clean buffer follows the authoritative revision. A dirty buffer remains
 * anchored to its original revision unless the authoritative role already
 * equals the user's requested role, in which case no local change remains.
 */
export function reconcileRoleDraft(record: AccountRecord, draft: RoleDraft): RoleDraft {
  if (draft.accountId !== record.id) return createRoleDraft(record);
  if (draft.revision === record.revision) return draft;
  if (roleDraftIsDirty(draft) && draft.roleId !== record.roleId) return draft;
  return createRoleDraft(record);
}
/** Unknown or unchanged radio values cannot mutate the draft or baseline. */
export function changeRoleDraft(draft: RoleDraft, roleId: string): RoleDraft {
  return !isIdentityRoleId(roleId) || draft.roleId === roleId
    ? draft
    : Object.freeze({ ...draft, roleId });
}
