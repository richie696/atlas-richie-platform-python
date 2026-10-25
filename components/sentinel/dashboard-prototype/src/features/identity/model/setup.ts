import {
  RULE_SOURCE,
  RULE_SOURCES,
  RULE_SOURCE_AUTHENTICATION,
  RULE_SOURCE_AUTHENTICATION_MODES,
  validateConfigurationSource,
  type RuleSourceKind,
  type RuleSourceAuthenticationMode,
  type RuleSourceCredentials,
  type ConfigurationSourceDraft,
  type SourceConfigurationIssue,
} from "../../../shared/model/configurationSource";
export {
  RULE_SOURCE,
  RULE_SOURCES,
  RULE_SOURCE_AUTHENTICATION,
  RULE_SOURCE_AUTHENTICATION_MODES,
  isRuleSourceEndpoint,
} from "../../../shared/model/configurationSource";
export type {
  RuleSourceKind,
  RuleSourceAuthenticationMode,
  RuleSourceCredentials,
} from "../../../shared/model/configurationSource";
/**
 * 首次初始化的协议值、步骤定义与每步校验。
 *
 * 中文
 * ----
 * 本模块不依赖 React、语言包和网络。它拥有三件事：有哪些**受支持的数据库种类**、
 * **规则来源与认证方式**、以及**四个初始化步骤的本地校验**。
 *
 * 旧实现把这些内容内联在 `SystemInitializationPage` 的 8 个 `useState` 和 onChange
 * 处理器里：`value as ControlPlaneDatabaseKind` 断言不检查值域，向导的合法迁移与
 * 「这一步允许提交什么」也只存在于事件函数里，无法单测。
 *
 * 边界说明（来自 `REWRITE_PLAN` §4.7）：setup 是**服务端治理的一次性窗口**。初始化
 * 成功后服务端关闭该窗口、重复访问拒绝，客户端把 `#/setup` 深链重定向到登录页。
 * 前端校验只是提前给出反馈，不构成任何授权判断。
 */
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, type IdentityIssue } from "./passwordPolicy";

/** 控制面持久化数据库的协议值。 */
export const CONTROL_PLANE_DATABASE = Object.freeze({
  PostgreSql: "postgresql",
  MySql: "mysql",
  Sqlite: "sqlite",
} as const);

/** {@link CONTROL_PLANE_DATABASE} 的值联合。 */
export type ControlPlaneDatabaseKind =
  (typeof CONTROL_PLANE_DATABASE)[keyof typeof CONTROL_PLANE_DATABASE];

/** Supported storage semantics; visual labels live in presentation/setupPresentation. */
export interface ControlPlaneDatabase {
  readonly id: ControlPlaneDatabaseKind;
  readonly defaultPort: string;
  readonly requiresNetworkConfiguration: boolean;
  readonly usage: "production" | "local-development";
}

/** 控制面可持久化的内容：账号、角色、审计、草稿、规则版本与发布计划。 */
export const CONTROL_PLANE_DATABASES: readonly ControlPlaneDatabase[] = Object.freeze([
  {
    id: CONTROL_PLANE_DATABASE.PostgreSql,
    defaultPort: "5432",
    requiresNetworkConfiguration: true,
    usage: "production",
  },
  {
    id: CONTROL_PLANE_DATABASE.MySql,
    defaultPort: "3306",
    requiresNetworkConfiguration: true,
    usage: "production",
  },
  {
    id: CONTROL_PLANE_DATABASE.Sqlite,
    defaultPort: "",
    requiresNetworkConfiguration: false,
    usage: "local-development",
  },
]);

/** 初始化步骤的协议值。顺序即向导推进顺序。 */
export const SETUP_STEP = Object.freeze({
  Storage: "storage",
  Admin: "admin",
  Sources: "sources",
  Complete: "complete",
} as const);

/** {@link SETUP_STEP} 的值联合。 */
export type SetupStepId = (typeof SETUP_STEP)[keyof typeof SETUP_STEP];

/** 一次性初始化的检查点。这些是引导阶段，不是规则来源状态。 */
export const SETUP_STEPS: readonly SetupStepId[] = Object.freeze(Object.values(SETUP_STEP));

/** Independent connection checks whose results are invalidated by their own inputs. */
export const SETUP_CONNECTION_CHECK = Object.freeze({
  Database: "database",
  Source: "source",
} as const);

/** One independently confirmed setup dependency. */
export type SetupConnectionCheckTarget =
  (typeof SETUP_CONNECTION_CHECK)[keyof typeof SETUP_CONNECTION_CHECK];

/** 内置管理员表单。初始账号名固定为 `admin`，密码由用户设置。 */
export interface SetupAdminDraft {
  readonly username: string;
  readonly password: string;
  readonly confirm: string;
}

/** 数据库连接表单。SQLite 不会用到 host / port / username / password。 */
export interface SetupDatabaseDraft {
  readonly host: string;
  readonly name: string;
  readonly username: string;
  readonly password: string;
}

/** 规则来源连接表单。 */
export interface SetupRuleSourceDraft {
  readonly address: string;
  readonly namespace: string;
}

/** 整个初始化向导的草稿快照。 */
export interface SetupDraft {
  readonly databaseKind: ControlPlaneDatabaseKind;
  readonly databasePort: string;
  readonly database: SetupDatabaseDraft;
  readonly sourceKind: RuleSourceKind;
  readonly source: SetupRuleSourceDraft;
  readonly sourceAuthenticationMode: RuleSourceAuthenticationMode;
  readonly sourceCredentials: RuleSourceCredentials;
  readonly admin: SetupAdminDraft;
}

/** 初始化的全空草稿。数据库名与管理员账号名有协议默认值。 */
export const INITIAL_SETUP_DRAFT: SetupDraft = Object.freeze({
  databaseKind: CONTROL_PLANE_DATABASE.PostgreSql,
  databasePort: CONTROL_PLANE_DATABASES[0].defaultPort,
  database: Object.freeze({
    host: "",
    name: "sentinel_control",
    username: "",
    password: "",
  }),
  sourceKind: RULE_SOURCE.Nacos,
  source: Object.freeze({ address: "", namespace: "" }),
  sourceAuthenticationMode: RULE_SOURCE_AUTHENTICATION.CredentialReference,
  sourceCredentials: Object.freeze({
    reference: "",
    username: "",
    password: "",
    consulToken: "",
  }),
  admin: Object.freeze({ username: "admin", password: "", confirm: "" }),
});

/** 初始化校验的消息键。翻译发生在 UI 层。 */
export type SetupIssueKey =
  | "setup.required"
  | "setup.databaseRequired"
  | "setup.databasePortInvalid"
  | "setup.sourceAddressInvalid"
  | "setup.adminRequired"
  | "setup.adminPasswordMismatch"
  | "setup.credentialReferenceRequired"
  | "setup.nacosCredentialsRequired"
  | "setup.consulTokenRequired";

/** Setup form field owners used to connect pure validation results to accessible inputs. */
export const SETUP_FIELD = Object.freeze({
  DatabaseHost: "database.host",
  DatabaseName: "database.name",
  DatabaseUsername: "database.username",
  DatabasePassword: "database.password",
  DatabasePort: "database.port",
  AdminUsername: "admin.username",
  AdminPassword: "admin.password",
  AdminConfirm: "admin.confirm",
  SourceAddress: "source.address",
  CredentialReference: "source.credentials.reference",
  NacosUsername: "source.credentials.nacosUsername",
  NacosPassword: "source.credentials.nacosPassword",
  ConsulToken: "source.credentials.consulToken",
} as const);

export type SetupField = (typeof SETUP_FIELD)[keyof typeof SETUP_FIELD];

/** A local validation issue with an optional field owner for inline feedback. */
export type SetupIssue = IdentityIssue<SetupIssueKey> & { readonly field?: SetupField };

/** Resolve a setup field to its owning wizard step; fields without an owner stay on the current step. */
export function setupStepForField(field: SetupField): SetupStepId {
  switch (field) {
    case SETUP_FIELD.DatabaseHost:
    case SETUP_FIELD.DatabaseName:
    case SETUP_FIELD.DatabaseUsername:
    case SETUP_FIELD.DatabasePassword:
    case SETUP_FIELD.DatabasePort:
      return SETUP_STEP.Storage;
    case SETUP_FIELD.AdminUsername:
    case SETUP_FIELD.AdminPassword:
    case SETUP_FIELD.AdminConfirm:
      return SETUP_STEP.Admin;
    case SETUP_FIELD.SourceAddress:
    case SETUP_FIELD.CredentialReference:
    case SETUP_FIELD.NacosUsername:
    case SETUP_FIELD.NacosPassword:
    case SETUP_FIELD.ConsulToken:
      return SETUP_STEP.Sources;
  }
}

/** Network storage uses an explicit TCP port, not a URL/DSN or permissive numeric coercion. */
export const DATABASE_PORT_RANGE = Object.freeze({ min: 1, max: 65535 });

/** 返回数据库种类的元数据；未知值回落到首个生产选项。 */
export function controlPlaneDatabaseFor(
  databaseKind: ControlPlaneDatabaseKind,
): ControlPlaneDatabase {
  return (
    CONTROL_PLANE_DATABASES.find((database) => database.id === databaseKind) ??
    CONTROL_PLANE_DATABASES[0]
  );
}

/** 收窄任意字符串为受支持的数据库种类。替代旧实现的 `value as ControlPlaneDatabaseKind`。 */
export function isControlPlaneDatabaseKind(value: string): value is ControlPlaneDatabaseKind {
  return CONTROL_PLANE_DATABASES.some((database) => database.id === value);
}

/** 收窄任意字符串为受支持的规则来源。替代旧实现的 `value as RuleSourceKind`。 */
export function isRuleSourceKind(value: string): value is RuleSourceKind {
  return RULE_SOURCES.some((source) => source === value);
}

/** 收窄任意字符串为受支持的认证方式。替代 `value as RuleSourceAuthenticationMode`。 */
export function isRuleSourceAuthenticationMode(
  value: string,
): value is RuleSourceAuthenticationMode {
  return RULE_SOURCE_AUTHENTICATION_MODES.some((mode) => mode === value);
}

/**
 * 校验当前步骤能否推进到下一步。
 *
 * 只检查**本地可判断**的必填项：管理员账号名与密码长度、两次密码是否一致、规则来源
 * 凭证是否齐备。连接可达性、端口占用、来源连通性和内置管理员唯一性由服务端在真正
 * 执行初始化时判定。
 *
 * `complete` 重新检查全部步骤，不让从旧状态或其它入口到达确认页绕过校验。
 */
export function validateSetupStep(stepId: SetupStepId, draft: SetupDraft): readonly SetupIssue[] {
  if (stepId === SETUP_STEP.Complete)
    return [SETUP_STEP.Storage, SETUP_STEP.Admin, SETUP_STEP.Sources].flatMap((step) =>
      validateSetupStep(step, draft),
    );
  if (
    stepId === SETUP_STEP.Storage &&
    controlPlaneDatabaseFor(draft.databaseKind).requiresNetworkConfiguration
  ) {
    const requiredIssues: SetupIssue[] = [];
    if (!draft.database.host.trim())
      requiredIssues.push({ key: "setup.required", field: SETUP_FIELD.DatabaseHost });
    if (!draft.database.name.trim())
      requiredIssues.push({ key: "setup.required", field: SETUP_FIELD.DatabaseName });
    if (!draft.database.username.trim())
      requiredIssues.push({ key: "setup.required", field: SETUP_FIELD.DatabaseUsername });
    if (!draft.database.password)
      requiredIssues.push({ key: "setup.required", field: SETUP_FIELD.DatabasePassword });
    if (requiredIssues.length > 0) return requiredIssues;
    const port = Number(draft.databasePort);
    if (
      !/^\d+$/.test(draft.databasePort) ||
      !Number.isSafeInteger(port) ||
      port < DATABASE_PORT_RANGE.min ||
      port > DATABASE_PORT_RANGE.max
    )
      return [
        {
          key: "setup.databasePortInvalid",
          params: DATABASE_PORT_RANGE,
          field: SETUP_FIELD.DatabasePort,
        },
      ];
  }
  if (stepId === SETUP_STEP.Admin) {
    const issues: SetupIssue[] = [];
    if (!draft.admin.username.trim())
      issues.push({ key: "setup.required", field: SETUP_FIELD.AdminUsername });
    if (
      draft.admin.password.length < PASSWORD_MIN_LENGTH ||
      draft.admin.password.length > PASSWORD_MAX_LENGTH
    )
      issues.push({
        key: "setup.adminRequired",
        params: { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH },
        field: SETUP_FIELD.AdminPassword,
      });
    if (draft.admin.password !== draft.admin.confirm)
      issues.push({ key: "setup.adminPasswordMismatch", field: SETUP_FIELD.AdminConfirm });
    if (issues.length > 0) return issues;
  }

  if (stepId === SETUP_STEP.Sources) {
    const issues = validateConfigurationSource(setupConfigurationSource(draft));
    return issues.flatMap((issue): SetupIssue[] => {
      if (issue === "endpoint-invalid")
        return [{ key: SOURCE_ISSUE_TO_SETUP_ISSUE[issue], field: SETUP_FIELD.SourceAddress }];
      if (issue === "reference-required")
        return [
          { key: SOURCE_ISSUE_TO_SETUP_ISSUE[issue], field: SETUP_FIELD.CredentialReference },
        ];
      if (issue === "nacos-credentials-required")
        return [
          ...(!draft.sourceCredentials.username.trim()
            ? [{ key: "setup.required" as const, field: SETUP_FIELD.NacosUsername }]
            : []),
          ...(!draft.sourceCredentials.password
            ? [{ key: "setup.required" as const, field: SETUP_FIELD.NacosPassword }]
            : []),
        ];
      if (issue === "consul-token-required")
        return [{ key: SOURCE_ISSUE_TO_SETUP_ISSUE[issue], field: SETUP_FIELD.ConsulToken }];
      return [{ key: SOURCE_ISSUE_TO_SETUP_ISSUE[issue] }];
    });
  }

  return [];
}

/**
 * Return a new setup draft with submitted/credential material removed.
 *
 * The account name, database location, provider and namespace remain available
 * for harmless UI context; database login name/password, source credentials,
 * and administrator password/confirmation are cleared. The input snapshot is
 * never mutated.
 */
export function clearSetupSecrets(draft: SetupDraft): SetupDraft {
  return {
    ...draft,
    database: { ...draft.database, username: "", password: "" },
    sourceCredentials: INITIAL_SETUP_DRAFT.sourceCredentials,
    admin: { ...draft.admin, password: "", confirm: "" },
  };
}

/** Translate setup's form shape to the shared pure source capability, not a second validation implementation. */
export function setupConfigurationSource(draft: SetupDraft): ConfigurationSourceDraft {
  return {
    provider: draft.sourceKind,
    endpoint: draft.source.address,
    location: draft.source.namespace,
    authentication: draft.sourceAuthenticationMode,
    credentials: draft.sourceCredentials,
  };
}
const SOURCE_ISSUE_TO_SETUP_ISSUE: Readonly<Record<SourceConfigurationIssue, SetupIssueKey>> = {
  "endpoint-invalid": "setup.sourceAddressInvalid",
  "reference-required": "setup.credentialReferenceRequired",
  "nacos-credentials-required": "setup.nacosCredentialsRequired",
  "consul-token-required": "setup.consulTokenRequired",
  "unsupported-configuration": "setup.sourceAddressInvalid",
};
