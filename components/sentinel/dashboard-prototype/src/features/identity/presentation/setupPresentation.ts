import {
  CONTROL_PLANE_DATABASE,
  CONTROL_PLANE_DATABASES,
  controlPlaneDatabaseFor,
  RULE_SOURCE,
  RULE_SOURCE_AUTHENTICATION,
  SETUP_STEP,
  type ControlPlaneDatabase,
  type ControlPlaneDatabaseKind,
  type RuleSourceKind,
  type RuleSourceAuthenticationMode,
  type SetupStepId,
} from "../model/setup";
import type { TranslationKey } from "../../../shared/types/translation";

/** Setup labels/options are UI projections; storage/source/auth facts stay in model. */
export interface SetupDatabasePresentation extends ControlPlaneDatabase {
  readonly label: string;
  readonly descriptionKey: TranslationKey;
}
const DATABASE_COPY = Object.freeze({
  [CONTROL_PLANE_DATABASE.PostgreSql]: {
    label: "PostgreSQL",
    descriptionKey: "setup.option.postgres.description",
  },
  [CONTROL_PLANE_DATABASE.MySql]: {
    label: "MySQL",
    descriptionKey: "setup.option.mysql.description",
  },
  [CONTROL_PLANE_DATABASE.Sqlite]: {
    label: "SQLite",
    descriptionKey: "setup.option.sqlite.description",
  },
} satisfies Record<
  ControlPlaneDatabaseKind,
  { readonly label: string; readonly descriptionKey: TranslationKey }
>);

export const SETUP_DATABASE_OPTIONS: readonly SetupDatabasePresentation[] = Object.freeze(
  CONTROL_PLANE_DATABASES.map((database) =>
    Object.freeze({ ...database, ...DATABASE_COPY[database.id] }),
  ),
);

/** The chosen database's UI metadata without copying defaults/driver rules. */
export function setupDatabasePresentationFor(
  kind: ControlPlaneDatabaseKind,
): SetupDatabasePresentation {
  const database = controlPlaneDatabaseFor(kind);
  return { ...database, ...DATABASE_COPY[database.id] };
}

export interface RuleSourceOption {
  readonly id: RuleSourceKind;
  /** 产品名（Nacos / Consul），是**数据**不翻译。 */
  readonly label: string;
  readonly descriptionKey: TranslationKey;
}

export const RULE_SOURCE_OPTIONS: readonly RuleSourceOption[] = Object.freeze([
  {
    id: RULE_SOURCE.Nacos,
    label: "Nacos",
    descriptionKey: "setup.option.nacos.description",
  },
  {
    id: RULE_SOURCE.Consul,
    label: "Consul",
    descriptionKey: "setup.option.consul.description",
  },
] satisfies readonly RuleSourceOption[]);

export interface RuleSourceAuthenticationOption {
  readonly id: RuleSourceAuthenticationMode;
  /** 功能名的语言键（「使用部署凭证引用」是界面措辞，不是协议值）。 */
  readonly labelKey: TranslationKey;
  readonly descriptionKey: TranslationKey;
}

export const RULE_SOURCE_AUTHENTICATION_OPTIONS: readonly RuleSourceAuthenticationOption[] =
  Object.freeze([
    {
      id: RULE_SOURCE_AUTHENTICATION.CredentialReference,
      labelKey: "setup.option.credentialReference.label",
      descriptionKey: "setup.option.credentialReference.description",
    },
    {
      id: RULE_SOURCE_AUTHENTICATION.Direct,
      labelKey: "setup.option.direct.label",
      descriptionKey: "setup.option.direct.description",
    },
    {
      id: RULE_SOURCE_AUTHENTICATION.None,
      labelKey: "setup.option.none.label",
      descriptionKey: "setup.option.none.description",
    },
  ] satisfies readonly RuleSourceAuthenticationOption[]);

export interface SetupStep {
  readonly id: SetupStepId;
  /** 步骤名的语言键。 */
  readonly labelKey: TranslationKey;
  readonly descriptionKey: TranslationKey;
}

export const INITIALIZATION_STEPS: readonly SetupStep[] = Object.freeze([
  {
    id: SETUP_STEP.Storage,
    labelKey: "setup.step.database.label",
    descriptionKey: "setup.step.database.description",
  },
  {
    id: SETUP_STEP.Admin,
    labelKey: "setup.step.admin.label",
    descriptionKey: "setup.step.admin.description",
  },
  {
    id: SETUP_STEP.Sources,
    labelKey: "setup.step.source.label",
    descriptionKey: "setup.step.source.description",
  },
  {
    id: SETUP_STEP.Complete,
    labelKey: "setup.step.finish.label",
    descriptionKey: "setup.step.finish.description",
  },
] satisfies readonly SetupStep[]);
