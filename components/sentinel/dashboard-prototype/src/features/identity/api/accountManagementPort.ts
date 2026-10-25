import type { AccountDraft, AccountStatus, IdentityRoleId } from "../model/account";
import type { AccountListQuery, AccountPage, AccountRecord } from "../model/accountManagement";

/** Internal mutation contract; F6 freezes its wire projection after complete page behavior. */
export type AccountMutation =
  | { readonly kind: "create"; readonly requestKey: string; readonly input: AccountDraft }
  | {
      readonly kind: "status";
      readonly requestKey: string;
      readonly accountId: string;
      readonly revision: string;
      readonly status: AccountStatus;
    }
  | {
      readonly kind: "role";
      readonly requestKey: string;
      readonly accountId: string;
      readonly revision: string;
      readonly roleId: IdentityRoleId;
    }
  | {
      readonly kind: "reset_password";
      readonly requestKey: string;
      readonly accountId: string;
      readonly revision: string;
      readonly password: string;
    }
  | {
      readonly kind: "delete";
      readonly requestKey: string;
      readonly accountId: string;
      readonly revision: string;
    };
export type AccountRejection =
  | "username_taken"
  | "last_admin"
  | "built_in"
  | "self_operation"
  | "validation"
  | "conflict"
  | "not_found";
/** Safe operation fact. No credential or mutation body can be returned by lookup. */
export type AccountOperationObservation =
  | { readonly status: "not-found"; readonly requestKey: string }
  | { readonly status: "completed"; readonly requestKey: string; readonly account: AccountRecord }
  | { readonly status: "rejected"; readonly requestKey: string; readonly reason: AccountRejection };
/** Account command HTTP responses are final; `pending` belongs to local request lifecycle only. */
export type AccountCommandReceipt = Extract<
  AccountOperationObservation,
  { readonly status: "completed" | "rejected" }
>;

/** Caller-owned management effects; adapters enforce authorization, revision and durable request-key semantics. */
export interface AccountManagementPort {
  readonly listAccounts: (query: AccountListQuery, signal: AbortSignal) => Promise<AccountPage>;
  /** Missing target is null, never a fallback account. Permission failures throw. */
  readonly readAccount: (accountId: string, signal: AbortSignal) => Promise<AccountRecord | null>;
  readonly mutateAccount: (
    mutation: AccountMutation,
    signal: AbortSignal,
  ) => Promise<AccountCommandReceipt>;
  readonly readAccountOperation: (
    requestKey: string,
    signal: AbortSignal,
  ) => Promise<AccountOperationObservation>;
}
