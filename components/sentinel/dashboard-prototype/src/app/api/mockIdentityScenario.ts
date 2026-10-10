/** Canonical local-only identity facts and controls for the explicit Mock profile. */
import {
  IDENTITY_ROLE,
  ACCOUNT_STATUS,
  type AccountStatus,
  type IdentityRoleId,
} from "../../features/identity";
import type { IdentityMockScenario } from "../../features/identity/mock";

/** Supported initial bootstrap states for isolated local Mock runs. */
export const MOCK_BOOTSTRAP_PROFILE = Object.freeze({
  Initialized: "initialized",
  FirstRun: "first-run",
} as const);

export type MockBootstrapProfile =
  (typeof MOCK_BOOTSTRAP_PROFILE)[keyof typeof MOCK_BOOTSTRAP_PROFILE];

/** Create app-owned synthetic identities and setup controls for one local Mock run. */
export function createMockIdentityScenario(
  profile: string | undefined = MOCK_BOOTSTRAP_PROFILE.Initialized,
) {
  if (
    profile !== MOCK_BOOTSTRAP_PROFILE.Initialized &&
    profile !== MOCK_BOOTSTRAP_PROFILE.FirstRun
  ) {
    throw new Error("VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE must be 'initialized' or 'first-run'");
  }
  const initializedByDefault = profile === MOCK_BOOTSTRAP_PROFILE.Initialized;
  return Object.freeze({
    bootstrap: Object.freeze({ initializedByDefault, operatorAuthorizedByDefault: false }),
    accounts: Object.freeze([
      Object.freeze({
        id: "account-admin",
        username: "admin",
        roleId: IDENTITY_ROLE.Admin,
        status: ACCOUNT_STATUS.Active,
        builtIn: true,
        lastLoginOffsetMs: -60_000,
      }),
      Object.freeze({
        id: "account-view",
        username: "viewer",
        roleId: IDENTITY_ROLE.View,
        status: ACCOUNT_STATUS.Active,
        builtIn: false,
        lastLoginOffsetMs: -120_000,
      }),
    ] satisfies readonly {
      readonly id: string;
      readonly username: string;
      readonly roleId: IdentityRoleId;
      readonly status: AccountStatus;
      readonly builtIn: boolean;
      readonly lastLoginOffsetMs: number;
    }[]),
    password: "synthetic-password",
    failureMode: Object.freeze({ failOnce: "fail-once" }),
    storageKeys: Object.freeze({
      initialized: "sentinel.mock.initialized",
      operatorAuthorized: "sentinel.mock.operator-authorized",
      principal: "sentinel.mock.role",
      databaseCheckFailure: "sentinel.mock.setup.database-check-failure",
      sourceCheckFailure: "sentinel.mock.setup.source-check-failure",
    }),
  } satisfies IdentityMockScenario);
}

/** Default synthetic scenario retained for focused feature-contract tests. */
export const MOCK_IDENTITY_SCENARIO = createMockIdentityScenario();
