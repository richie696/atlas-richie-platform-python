/** Explicit local Mock profile API; production routes must use HTTP adapters. */
import type { AccountStatus, IdentityRoleId } from "./model/account";

/** Immutable app-supplied facts/configuration consumed by identity Mock handlers. */
export interface IdentityMockScenario {
  readonly bootstrap: Readonly<{
    readonly initializedByDefault: boolean;
    readonly operatorAuthorizedByDefault: boolean;
  }>;
  readonly accounts: readonly {
    readonly id: string;
    readonly username: string;
    readonly roleId: IdentityRoleId;
    readonly status: AccountStatus;
    readonly builtIn: boolean;
    readonly lastLoginOffsetMs: number;
  }[];
  readonly password: string;
  readonly failureMode: Readonly<{ failOnce: string }>;
  readonly storageKeys: Readonly<{
    initialized: string;
    operatorAuthorized: string;
    principal: string;
    databaseCheckFailure: string;
    sourceCheckFailure: string;
  }>;
}

export { createIdentityMockHandlers } from "./fixtures/identityMockHandlers";
export { createAccountManagementMockHandlers } from "./fixtures/accountManagementMockHandlers";
