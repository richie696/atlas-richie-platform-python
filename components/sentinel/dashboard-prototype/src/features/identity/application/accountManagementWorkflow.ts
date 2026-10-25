import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createQueryResource, type QuerySnapshot } from "../../../shared/state/queryResource";
import { createCommandResource, type CommandSnapshot } from "../../../shared/state/commandResource";
import type {
  AccountManagementPort,
  AccountMutation,
  AccountCommandReceipt,
  AccountOperationObservation,
  AccountRejection,
} from "../api/accountManagementPort";
import type { IdentitySessionOwner } from "../api/identityAccessPort";
import { IDENTITY_ROLE, type AccountDraft, type AccountStatus } from "../model/account";
import type { SessionIdentity } from "../model/controlPlaneAccess";
import { PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH } from "../model/passwordPolicy";
import {
  accountRoleIssue,
  accountStatusIssue,
  prepareAccountCreation,
  validateAccountQuery,
  type AccountListQuery,
  type AccountPage,
  type AccountRecord,
  type RoleDraft,
} from "../model/accountManagement";

/** Safe lookup identity; never retain the write body/password in public state. */
export interface AccountOperationIdentity {
  readonly requestKey: string;
  readonly kind: AccountMutation["kind"];
  readonly accountId?: string;
}
export interface AccountManagementSnapshot {
  readonly authorized: boolean;
  readonly directory: QuerySnapshot<AccountPage>;
  readonly detail: QuerySnapshot<AccountRecord | null>;
  readonly mutation: CommandSnapshot<AccountRecord>;
  readonly operation: AccountOperationIdentity | null;
  readonly inspecting: boolean;
}
export interface AccountManagementWorkflow {
  readonly ownerAccountId: string;
  readonly resetPassword: (
    record: AccountRecord,
    password: string,
  ) => Promise<AccountCommandReceipt>;
  readonly deleteAccount: (record: AccountRecord) => Promise<AccountCommandReceipt>;
  readonly getSnapshot: () => AccountManagementSnapshot;
  readonly subscribe: (listener: () => void) => () => void;
  readonly list: (query: AccountListQuery) => Promise<AccountPage>;
  readonly select: (accountId: string) => Promise<AccountRecord | null>;
  readonly create: (draft: AccountDraft) => Promise<AccountCommandReceipt>;
  readonly setStatus: (
    record: AccountRecord | null,
    status: AccountStatus,
  ) => Promise<AccountCommandReceipt>;
  readonly setRole: (
    record: AccountRecord | null,
    draft: RoleDraft,
  ) => Promise<AccountCommandReceipt>;
  /** Read the original operation. Not-found is NOT proof of rollback and cannot unlock another write. */
  readonly inspect: () => Promise<AccountOperationObservation>;
  /** Cancel only the directory read owned by account-list query effects. */
  readonly cancelDirectory: () => void;
  readonly cancel: () => void;
  readonly dispose: () => void;
}

const REJECTION_STATUS: Readonly<Record<AccountRejection, number>> = Object.freeze({
  username_taken: 409,
  last_admin: 409,
  built_in: 409,
  self_operation: 409,
  validation: 422,
  conflict: 409,
  not_found: 404,
});
const FINALIZED_MUTATION_STATUSES: ReadonlySet<string> = new Set(["success", "conflict", "error"]);
function rejection(reason: AccountRejection): CommandSnapshot<AccountRecord> {
  const status = REJECTION_STATUS[reason];
  const error = new AppError(AppErrorKind.PROTOCOL, "Account operation rejected", {
    status,
    code: `account_${reason}`,
  });
  return { status: status === 409 ? "conflict" : "error", error };
}
function redact(error: AppError): AppError {
  return new AppError(error.kind, "Account operation failed", {
    status: error.status,
    code: error.code,
  });
}

/**
 * One session-bound management owner for directory, detail and mutations. Compose
 * shared query/command mechanics; don't optimistically invent accounts/revisions.
 * Confirmed writes invalidate/refetch current reads; refresh failure is not a
 * failed transaction. Unknown writes require correlated durable operation lookup.
 * UI hints never replace server authorization/last-admin/revision transactions.
 */
export function createAccountManagementWorkflow(
  port: AccountManagementPort,
  owner: SessionIdentity,
  session: IdentitySessionOwner,
  newRequestKey: () => string,
  options: { readonly timeoutMs?: number } = {},
): AccountManagementWorkflow {
  const accountId = owner.accountId,
    epoch = owner.sessionEpoch;
  let disposed = false,
    activeQuery: AccountListQuery | undefined,
    selectedId: string | undefined;
  let operation: AccountOperationIdentity | null = null,
    verified: CommandSnapshot<AccountRecord> | undefined,
    verifiedAccountId: string | undefined;
  let inspecting = false,
    inspectGeneration = 0;
  // Keep only non-secret confirmation facts for a later operation lookup.
  let expected:
    | {
        readonly username?: string;
        readonly roleId?: string;
        readonly status?: AccountStatus;
        readonly builtIn?: boolean;
        readonly lastLoginAt?: string | null;
      }
    | undefined;
  const idle = Object.freeze({ status: "idle" } as const);
  function authorized() {
    const access = session.read();
    return (
      !disposed &&
      access.phase === "resolved" &&
      access.facts.kind === "authenticated" &&
      access.facts.identity.accountId === accountId &&
      access.facts.identity.sessionEpoch === epoch &&
      access.facts.identity.roleId === IDENTITY_ROLE.Admin
    );
  }
  function assertOwner() {
    if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Account owner disposed");
    if (!authorized())
      throw new AppError(
        AppErrorKind.FORBIDDEN,
        "Account management requires current administrator",
        { status: 403 },
      );
  }
  const directory = createQueryResource<AccountListQuery, AccountPage>({
    keyOf: (query) =>
      JSON.stringify([
        accountId,
        epoch,
        query.page,
        query.pageSize,
        query.search,
        query.status ?? null,
      ]),
    read: (query, signal) => {
      assertOwner();
      return port.listAccounts(query, signal);
    },
    classify: (page) =>
      page.items.length
        ? "ready"
        : activeQuery?.search || activeQuery?.status
          ? "filtered-empty"
          : "empty",
  });
  const detail = createQueryResource<string, AccountRecord | null>({
    keyOf: (id) => JSON.stringify([accountId, epoch, id]),
    read: (id, signal) => {
      assertOwner();
      return port.readAccount(id, signal);
    },
    classify: (record) => (record ? "ready" : "empty"),
  });
  const inspection = createQueryResource<string, AccountOperationObservation>({
    keyOf: (key) => JSON.stringify([accountId, epoch, key]),
    timeoutMs: options.timeoutMs,
    read: (key, signal) => {
      assertOwner();
      return port.readAccountOperation(key, signal);
    },
    classify: () => "ready",
  });
  function checkObservation(value: AccountOperationObservation, key: string, isLookup: boolean) {
    const validStatus =
      value?.status === "completed" ||
      value?.status === "rejected" ||
      (isLookup && value?.status === "not-found");
    if (!value || value.requestKey !== key || !validStatus)
      throw new AppError(AppErrorKind.SERVER, "Invalid account operation receipt", {
        status: 502,
        code: "account_receipt_invalid",
      });
    if (
      value.status === "completed" &&
      (!value.account?.id ||
        !value.account.revision ||
        (operation?.accountId && value.account.id !== operation.accountId))
    )
      throw new AppError(AppErrorKind.SERVER, "Mismatched account target", {
        status: 502,
        code: "account_receipt_invalid",
      });
    if (value.status === "rejected" && !Object.hasOwn(REJECTION_STATUS, value.reason))
      throw new AppError(AppErrorKind.SERVER, "Invalid account rejection", {
        status: 502,
        code: "account_receipt_invalid",
      });
    if (
      value.status === "completed" &&
      expected &&
      ((expected.username !== undefined && value.account.username !== expected.username) ||
        (expected.roleId !== undefined && value.account.roleId !== expected.roleId) ||
        (expected.status !== undefined && value.account.status !== expected.status) ||
        (expected.builtIn !== undefined && value.account.builtIn !== expected.builtIn) ||
        (expected.lastLoginAt !== undefined && value.account.lastLoginAt !== expected.lastLoginAt))
    )
      throw new AppError(AppErrorKind.SERVER, "Account receipt does not confirm mutation", {
        status: 502,
        code: "account_receipt_invalid",
      });
  }
  const command = createCommandResource<AccountMutation, AccountCommandReceipt>(
    async (input, signal) => {
      assertOwner();
      const receipt = await port.mutateAccount(input, signal);
      if (!authorized() || signal.aborted)
        throw new AppError(AppErrorKind.CANCELLED, "Account observation cancelled");
      checkObservation(receipt, input.requestKey, false);
      return receipt;
    },
  );
  function mutationSnapshot(): CommandSnapshot<AccountRecord> {
    if (verified) return verified;
    const current = command.getSnapshot();
    if (current.status !== "success")
      return "error" in current ? { ...current, error: redact(current.error) } : current;
    const receipt = current.result;
    if (receipt.status === "completed") return { status: "success", result: receipt.account };
    return rejection(receipt.reason);
  }
  const state = new StateStore<AccountManagementSnapshot>({
    authorized: authorized(),
    directory: idle,
    detail: idle,
    mutation: idle,
    operation: null,
    inspecting: false,
  });
  function publish() {
    if (disposed) return;
    const allowed = authorized();
    state.set({
      authorized: allowed,
      directory: allowed ? directory.getSnapshot() : idle,
      detail: allowed ? detail.getSnapshot() : idle,
      mutation: allowed ? mutationSnapshot() : idle,
      operation: allowed ? operation : null,
      inspecting: allowed && inspecting,
    });
  }
  const stops = [
    directory.subscribe(publish),
    detail.subscribe(publish),
    command.subscribe(publish),
  ];
  function cancelInspection() {
    inspectGeneration++;
    inspection.reset();
    inspecting = false;
  }
  function cancelDirectory() {
    directory.cancel();
    publish();
  }
  stops.push(
    session.subscribe(() => {
      if (!authorized()) {
        cancelInspection();
        activeQuery = undefined;
        selectedId = undefined;
        directory.reset();
        detail.reset();
        command.cancel();
      }
      publish();
    }),
  );
  function assertAvailable() {
    assertOwner();
    if (inspecting || ["pending", "result-unknown"].includes(mutationSnapshot().status))
      throw new AppError(AppErrorKind.DUPLICATE, "Account mutation requires confirmation");
  }
  function invalid(code: string, status = 400, targetAccountId?: string): never {
    const error = new AppError(AppErrorKind.PROTOCOL, "Invalid account command", { status, code });
    verified = { status: status === 409 ? "conflict" : "error", error };
    verifiedAccountId = targetAccountId;
    operation = null;
    publish();
    throw error;
  }
  async function refreshConfirmed() {
    if (!authorized()) return;
    const query = activeQuery,
      id = selectedId;
    // Reset first: prior revision cannot be reused as a trusted post-write value.
    directory.reset();
    detail.reset();
    await Promise.allSettled([
      ...(query ? [directory.load(query)] : []),
      ...(id ? [detail.load(id)] : []),
    ]);
    // A failed refresh is visible on its read resource; the confirmed write remains success.
  }
  async function reconcileConfirmedMutation() {
    const confirmed = operation;
    // A self-reset revokes this session in the same server transaction. Avoid
    // follow-up reads with a session that is already known to be invalid.
    if (confirmed?.kind === "reset_password" && confirmed.accountId === accountId) return;
    if (
      confirmed &&
      confirmed.accountId === accountId &&
      (confirmed.kind === "role" || confirmed.kind === "status")
    ) {
      // Changing or disabling the signed-in account can change its server-owned
      // authority. Preserve the confirmed mutation outcome if the follow-up read
      // fails; AuthenticationWorkflow publishes that read failure as unavailable.
      await session.revalidateAccess().catch(() => undefined);
    }
    await refreshConfirmed();
  }
  async function run(input: AccountMutation) {
    operation = Object.freeze({
      requestKey: input.requestKey,
      kind: input.kind,
      ...(input.kind === "create" ? {} : { accountId: input.accountId }),
    });
    verified = undefined;
    verifiedAccountId = undefined;
    expected = Object.freeze(
      input.kind === "create"
        ? {
            username: input.input.username,
            roleId: input.input.roleId,
            status: "active",
            builtIn: false,
            lastLoginAt: null,
          }
        : input.kind === "role"
          ? { roleId: input.roleId }
          : input.kind === "status"
            ? { status: input.status }
            : input.kind === "delete"
              ? { status: "disabled" }
              : {},
    );
    let receipt: AccountCommandReceipt;
    try {
      receipt = await command.run(input);
    } catch (cause) {
      // A server-side role change can race the in-memory administrator projection.
      // A definitive authorization denial is a reason to refresh authority before
      // retaining any account-directory data; CSRF failures are not role changes.
      if (
        cause instanceof AppError &&
        cause.kind === AppErrorKind.FORBIDDEN &&
        cause.status === 403 &&
        cause.code === "forbidden"
      )
        await session.revalidateAccess().catch(() => undefined);
      throw cause;
    }
    if (receipt.status === "completed") await reconcileConfirmedMutation();
    return receipt;
  }
  function requestKey() {
    const key = newRequestKey();
    if (!key.trim()) return invalid("account_request_key_invalid");
    return key;
  }
  return Object.freeze({
    ownerAccountId: accountId,
    async resetPassword(record: AccountRecord, password: string) {
      assertAvailable();
      if (record.builtIn && record.id !== accountId)
        return invalid("account_built_in", 409, record.id);
      if (password.length < PASSWORD_MIN_LENGTH || password.length > PASSWORD_MAX_LENGTH)
        return invalid("account_form_invalid");
      return run({
        kind: "reset_password",
        requestKey: requestKey(),
        accountId: record.id,
        revision: record.revision,
        password,
      });
    },
    async deleteAccount(record: AccountRecord) {
      assertAvailable();
      if (record.builtIn) return invalid("account_built_in", 409, record.id);
      if (record.id === accountId) return invalid("account_self_operation", 409, record.id);
      if (record.lastActiveAdmin) return invalid("account_last_admin", 409, record.id);
      return run({
        kind: "delete",
        requestKey: requestKey(),
        accountId: record.id,
        revision: record.revision,
      });
    },
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async list(query: AccountListQuery) {
      assertOwner();
      if (validateAccountQuery(query).length)
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid account query", {
          status: 400,
          code: "account_query_invalid",
        });
      activeQuery = Object.freeze({ ...query, search: query.search.trim() });
      return directory.load(activeQuery);
    },
    async select(id: string) {
      assertOwner();
      if (!id)
        throw new AppError(AppErrorKind.PROTOCOL, "Account target required", {
          status: 400,
          code: "account_target_required",
        });
      selectedId = id;
      const record = await detail.load(id);
      if (
        (operation?.accountId ?? verifiedAccountId) &&
        FINALIZED_MUTATION_STATUSES.has(mutationSnapshot().status)
      ) {
        // A completed authoritative reread makes a previous terminal role/status
        // outcome obsolete for the editor. Keep unknown outcomes until their
        // original request key is explicitly inspected; never infer rollback.
        operation = null;
        verified = undefined;
        verifiedAccountId = undefined;
        expected = undefined;
        command.reset();
        publish();
      }
      return record;
    },
    async create(draft: AccountDraft) {
      assertAvailable();
      const result = prepareAccountCreation(draft);
      if (result.status === "invalid") return invalid("account_form_invalid");
      return run({ kind: "create", requestKey: requestKey(), input: result.input });
    },
    async setStatus(record: AccountRecord | null, status: AccountStatus) {
      assertAvailable();
      const issue = accountStatusIssue(record, status);
      if (issue || !record)
        return invalid(
          `account_${issue ?? "not_found"}`,
          issue === "built_in" || issue === "last_admin" ? 409 : 400,
          record?.id,
        );
      return run({
        kind: "status",
        requestKey: requestKey(),
        accountId: record.id,
        revision: record.revision,
        status,
      });
    },
    async setRole(record: AccountRecord | null, draft: RoleDraft) {
      assertAvailable();
      if (!record || record.id !== draft.accountId)
        return invalid("account_not_found", 404, record?.id);
      if (record.revision !== draft.revision)
        return invalid("account_revision_conflict", 409, record.id);
      const issue = accountRoleIssue(record, draft.roleId);
      if (issue)
        return invalid(
          `account_${issue}`,
          issue === "built_in" || issue === "last_admin" ? 409 : 400,
          record.id,
        );
      return run({
        kind: "role",
        requestKey: requestKey(),
        accountId: record.id,
        revision: draft.revision,
        roleId: draft.roleId,
      });
    },
    async inspect() {
      assertOwner();
      if (inspecting || command.getSnapshot().status === "pending")
        throw new AppError(AppErrorKind.DUPLICATE, "Account observation pending");
      if (!operation)
        throw new AppError(AppErrorKind.PROTOCOL, "Account operation missing", { status: 400 });
      const current = operation,
        ticket = ++inspectGeneration;
      inspecting = true;
      publish();
      try {
        const receipt = await inspection.load(current.requestKey);
        if (ticket !== inspectGeneration || !authorized())
          throw new AppError(AppErrorKind.CANCELLED, "Account inspection owner changed");
        checkObservation(receipt, current.requestKey, true);
        if (receipt.status === "completed" || receipt.status === "rejected") {
          verified =
            receipt.status === "completed"
              ? { status: "success", result: receipt.account }
              : rejection(receipt.reason);
          verifiedAccountId =
            receipt.status === "completed" ? receipt.account.id : current.accountId;
          command.reset();
          publish();
          if (receipt.status === "completed") await reconcileConfirmedMutation();
        }
        return receipt;
      } finally {
        if (ticket === inspectGeneration) {
          inspecting = false;
          publish();
        }
      }
    },
    cancelDirectory,
    cancel() {
      cancelInspection();
      directory.cancel();
      detail.cancel();
      command.cancel();
      publish();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelInspection();
      stops.forEach((stop) => stop());
      directory.dispose();
      detail.dispose();
      command.dispose();
      inspection.dispose();
      activeQuery = undefined;
      selectedId = undefined;
      operation = null;
      verified = undefined;
      verifiedAccountId = undefined;
      expected = undefined;
      state.set({
        authorized: false,
        directory: idle,
        detail: idle,
        mutation: idle,
        operation: null,
        inspecting: false,
      });
      state.complete();
    },
  });
}
