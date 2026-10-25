import {
  prepareConfigurationSource,
  type ConfigurationSourceInput,
} from "../../../shared/model/configurationSource";
import {
  CONTROL_PLANE_DATABASE,
  INITIAL_SETUP_DRAFT,
  RULE_SOURCE,
  RULE_SOURCE_AUTHENTICATION,
  SETUP_STEP,
  controlPlaneDatabaseFor,
  validateSetupStep,
  setupConfigurationSource,
  type ControlPlaneDatabaseKind,
  type RuleSourceAuthenticationMode,
  type RuleSourceKind,
  type SetupDraft,
  type SetupIssue,
} from "./setup";

/** Internal write-only command input, NOT a frozen HTTP DTO. SQLite has no network credentials. */
export type SetupStorageInput =
  | { readonly kind: "sqlite" }
  | {
      readonly kind: "postgresql" | "mysql";
      readonly host: string;
      readonly port: number;
      readonly database: string;
      readonly username: string;
      readonly password: string;
    };
/** Shared write-only source input, retained under the setup consumer's existing type name. */
export type SetupSourceInput = ConfigurationSourceInput;
export interface SetupSubmission {
  readonly database: SetupStorageInput;
  readonly admin: { readonly username: string; readonly password: string };
  readonly source: SetupSourceInput;
}
export type SetupPreparation =
  | { readonly status: "invalid"; readonly issues: readonly SetupIssue[] }
  | { readonly status: "valid"; readonly submission: SetupSubmission };

type ConnectionPreparation<Input> =
  | { readonly status: "invalid"; readonly issues: readonly SetupIssue[] }
  | { readonly status: "valid"; readonly input: Input };

function projectDatabase(draft: SetupDraft): SetupStorageInput {
  return draft.databaseKind === CONTROL_PLANE_DATABASE.Sqlite
    ? { kind: CONTROL_PLANE_DATABASE.Sqlite }
    : {
        kind: draft.databaseKind,
        host: draft.database.host.trim(),
        port: Number(draft.databasePort),
        database: draft.database.name.trim(),
        username: draft.database.username.trim(),
        password: draft.database.password,
      };
}
function projectSource(draft: SetupDraft): SetupSourceInput {
  const input = prepareConfigurationSource(setupConfigurationSource(draft));
  if (!input) throw new Error("Source was not validated");
  return input;
}
/** Validate only storage for a side-effect-free connectivity check; no administrator/source credentials are required. */
export function prepareSetupDatabase(draft: SetupDraft): ConnectionPreparation<SetupStorageInput> {
  const issues = validateSetupStep(SETUP_STEP.Storage, draft);
  return issues.length
    ? { status: "invalid", issues }
    : { status: "valid", input: projectDatabase(draft) };
}
/** Validate only the selected source/authentication branch for a connectivity check. */
export function prepareSetupSource(draft: SetupDraft): ConnectionPreparation<SetupSourceInput> {
  const issues = validateSetupStep(SETUP_STEP.Sources, draft);
  return issues.length
    ? { status: "invalid", issues }
    : { status: "valid", input: projectSource(draft) };
}
/** Validate every step and omit inactive credentials/confirmation. Never mutate the form. */
export function prepareSetupSubmission(draft: SetupDraft): SetupPreparation {
  const issues = validateSetupStep(SETUP_STEP.Complete, draft);
  if (issues.length) return { status: "invalid", issues };
  return {
    status: "valid",
    submission: {
      database: projectDatabase(draft),
      source: projectSource(draft),
      admin: { username: draft.admin.username.trim(), password: draft.admin.password },
    },
  };
}

/** A network driver switch preserves connection location, but never carries the previous database identity. */
export function changeSetupDatabase(draft: SetupDraft, kind: ControlPlaneDatabaseKind): SetupDraft {
  if (draft.databaseKind === kind) return draft;
  return {
    ...draft,
    databaseKind: kind,
    databasePort: controlPlaneDatabaseFor(kind).defaultPort,
    database:
      kind === CONTROL_PLANE_DATABASE.Sqlite
        ? INITIAL_SETUP_DRAFT.database
        : { ...draft.database, username: "", password: "" },
  };
}

/** Provider locations and credentials are not transferable. Returning to the old provider cannot revive them. */
export function changeSetupSource(draft: SetupDraft, kind: RuleSourceKind): SetupDraft {
  if (draft.sourceKind === kind) return draft;
  return {
    ...draft,
    sourceKind: kind,
    source: INITIAL_SETUP_DRAFT.source,
    sourceCredentials: INITIAL_SETUP_DRAFT.sourceCredentials,
  };
}

/** Clear every credential branch on an actual mode change; repeat clicks preserve current input. */
export function changeSetupAuthentication(
  draft: SetupDraft,
  mode: RuleSourceAuthenticationMode,
): SetupDraft {
  if (draft.sourceAuthenticationMode === mode) return draft;
  return {
    ...draft,
    sourceAuthenticationMode: mode,
    sourceCredentials: INITIAL_SETUP_DRAFT.sourceCredentials,
  };
}
