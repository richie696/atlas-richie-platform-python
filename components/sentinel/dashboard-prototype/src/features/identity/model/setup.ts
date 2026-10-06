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
import { PASSWORD_MIN_LENGTH, type IdentityIssue } from "./passwordPolicy";

/** 控制面持久化数据库的协议值。 */
export const CONTROL_PLANE_DATABASE = Object.freeze({
  PostgreSql: "postgresql",
  MySql: "mysql",
  Sqlite: "sqlite",
} as const);

/** {@link CONTROL_PLANE_DATABASE} 的值联合。 */
export type ControlPlaneDatabaseKind =
  (typeof CONTROL_PLANE_DATABASE)[keyof typeof CONTROL_PLANE_DATABASE];

/**
 * 单个数据库选项的元数据。
 *
 * `id` 是 API 契约值；`label` 是展示文案，永远不能反过来当协议值使用。`usage` 说明
 * 该选项是否允许用于生产集群。
 */
export interface ControlPlaneDatabase {
  readonly id: ControlPlaneDatabaseKind;
  /** 产品名（PostgreSQL / MySQL / SQLite），是**数据**不翻译。 */
  readonly label: string;
  /** 说明的语言键。 */
  readonly descriptionKey: string;
  readonly defaultPort: string;
  /** SQLite 为 false：它不需要主机、端口和账号。 */
  readonly requiresNetworkConfiguration: boolean;
  readonly usage: "production" | "local-development";
}

/** 控制面可持久化的内容：账号、角色、审计、草稿、规则版本与发布计划。 */
export const CONTROL_PLANE_DATABASES: readonly ControlPlaneDatabase[] = Object.freeze([
  {
    id: CONTROL_PLANE_DATABASE.PostgreSql,
    label: "PostgreSQL",
    descriptionKey: "setup.option.postgres.description",
    defaultPort: "5432",
    requiresNetworkConfiguration: true,
    usage: "production",
  },
  {
    id: CONTROL_PLANE_DATABASE.MySql,
    label: "MySQL",
    descriptionKey: "setup.option.mysql.description",
    defaultPort: "3306",
    requiresNetworkConfiguration: true,
    usage: "production",
  },
  {
    id: CONTROL_PLANE_DATABASE.Sqlite,
    label: "SQLite",
    descriptionKey: "setup.option.sqlite.description",
    defaultPort: "",
    requiresNetworkConfiguration: false,
    usage: "local-development",
  },
] satisfies readonly ControlPlaneDatabase[]);

/** 规则来源（配置中心）的协议值。 */
export const RULE_SOURCE = Object.freeze({
  Nacos: "nacos",
  Consul: "consul",
} as const);

/** {@link RULE_SOURCE} 的值联合。 */
export type RuleSourceKind = (typeof RULE_SOURCE)[keyof typeof RULE_SOURCE];

/** 规则来源的展示文案。`id` 是协议值，`label` 只用于界面。 */
export interface RuleSourceOption {
  readonly id: RuleSourceKind;
  /** 产品名（Nacos / Consul），是**数据**不翻译。 */
  readonly label: string;
  readonly descriptionKey: string;
}

/**
 * 可登记的规则来源。
 *
 * 两者同为**规则事实来源**，都不是账户或审计存储。选项文案原先内联在页面 JSX 的
 * `options` 数组里，与数据库选项的写法不一致；提到这里后「支持哪些来源」成为一处
 * 可枚举的领域事实。
 */
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

/** 后台在初始化时取得规则来源凭证的方式。 */
export const RULE_SOURCE_AUTHENTICATION = Object.freeze({
  CredentialReference: "credential-reference",
  Direct: "direct",
  None: "none",
} as const);

/** {@link RULE_SOURCE_AUTHENTICATION} 的值联合。 */
export type RuleSourceAuthenticationMode =
  (typeof RULE_SOURCE_AUTHENTICATION)[keyof typeof RULE_SOURCE_AUTHENTICATION];

/** 单个认证方式的展示契约。 */
export interface RuleSourceAuthenticationOption {
  readonly id: RuleSourceAuthenticationMode;
  /** 功能名的语言键（「使用部署凭证引用」是界面措辞，不是协议值）。 */
  readonly labelKey: string;
  readonly descriptionKey: string;
}

/**
 * 规则来源的认证方式选项。
 *
 * `direct` 是有意保留的：受控内网部署确实需要。浏览器只能通过 TLS 提交一次这些值，
 * 后台必须脱敏并只持久化受保护的配置——它不是浏览器侧的密钥仓库。
 */
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

/** 初始化步骤的协议值。顺序即向导推进顺序。 */
export const SETUP_STEP = Object.freeze({
  Storage: "storage",
  Admin: "admin",
  Sources: "sources",
  Complete: "complete",
} as const);

/** {@link SETUP_STEP} 的值联合。 */
export type SetupStepId = (typeof SETUP_STEP)[keyof typeof SETUP_STEP];

/** 单个初始化步骤的元数据。 */
export interface SetupStep {
  readonly id: SetupStepId;
  /** 步骤名的语言键。 */
  readonly labelKey: string;
  readonly descriptionKey: string;
}

/** 一次性初始化的检查点。这些是引导阶段，不是规则来源状态。 */
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

/**
 * 直接填写模式下的规则来源凭证。
 *
 * 全部字段都是**写入式**：页面不回显、不写入浏览器存储，提交后由后台脱敏保存。字段
 * 集合覆盖两种来源，因此同时存在 `username`/`password` 与 `consulToken`。
 */
export interface RuleSourceCredentials {
  readonly reference: string;
  readonly username: string;
  readonly password: string;
  readonly consulToken: string;
}

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
  | "setup.adminRequired"
  | "setup.adminPasswordMismatch"
  | "setup.credentialReferenceRequired"
  | "setup.nacosCredentialsRequired"
  | "setup.consulTokenRequired";

/** 一条初始化问题。 */
export type SetupIssue = IdentityIssue<SetupIssueKey>;

/** 返回数据库种类的元数据；未知值回落到首个生产选项。 */
export function controlPlaneDatabaseFor(
  databaseKind: ControlPlaneDatabaseKind,
): ControlPlaneDatabase {
  return (
    CONTROL_PLANE_DATABASES.find((database) => database.id === databaseKind) ??
    CONTROL_PLANE_DATABASES[0]
  );
}

/** 返回规则来源的展示文案；未知值回落到 Nacos。 */
export function ruleSourceFor(sourceKind: RuleSourceKind): RuleSourceOption {
  return (
    RULE_SOURCE_OPTIONS.find((source) => source.id === sourceKind) ?? RULE_SOURCE_OPTIONS[0]
  );
}

/** 收窄任意字符串为受支持的数据库种类。替代旧实现的 `value as ControlPlaneDatabaseKind`。 */
export function isControlPlaneDatabaseKind(
  value: string,
): value is ControlPlaneDatabaseKind {
  return (CONTROL_PLANE_DATABASES as readonly { id: string }[]).some(
    (database) => database.id === value,
  );
}

/** 收窄任意字符串为受支持的规则来源。替代旧实现的 `value as RuleSourceKind`。 */
export function isRuleSourceKind(value: string): value is RuleSourceKind {
  return (RULE_SOURCE_OPTIONS as readonly { id: string }[]).some(
    (source) => source.id === value,
  );
}

/** 收窄任意字符串为受支持的认证方式。替代 `value as RuleSourceAuthenticationMode`。 */
export function isRuleSourceAuthenticationMode(
  value: string,
): value is RuleSourceAuthenticationMode {
  return (RULE_SOURCE_AUTHENTICATION_OPTIONS as readonly { id: string }[]).some(
    (option) => option.id === value,
  );
}

/**
 * 校验当前步骤能否推进到下一步。
 *
 * 只检查**本地可判断**的必填项：管理员账号名与密码长度、两次密码是否一致、规则来源
 * 凭证是否齐备。连接可达性、端口占用、来源连通性和内置管理员唯一性由服务端在真正
 * 执行初始化时判定。
 *
 * 步骤本身没有可校验字段（`complete` 只是确认页），因此返回空问题列表。
 */
export function validateSetupStep(
  stepId: SetupStepId,
  draft: SetupDraft,
): readonly SetupIssue[] {
  if (stepId === SETUP_STEP.Admin) {
    if (!draft.admin.username.trim() || draft.admin.password.length < PASSWORD_MIN_LENGTH) {
      return [
        {
          key: "setup.adminRequired",
          params: { min: PASSWORD_MIN_LENGTH },
        },
      ];
    }
    if (draft.admin.password !== draft.admin.confirm) {
      return [{ key: "setup.adminPasswordMismatch" }];
    }
  }

  if (stepId === SETUP_STEP.Sources) {
    if (
      draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.CredentialReference &&
      !draft.sourceCredentials.reference.trim()
    ) {
      return [{ key: "setup.credentialReferenceRequired" }];
    }
    if (draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.Direct) {
      const hasCredentials =
        draft.sourceKind === RULE_SOURCE.Nacos
          ? Boolean(draft.sourceCredentials.username.trim() && draft.sourceCredentials.password)
          : Boolean(draft.sourceCredentials.consulToken);
      if (!hasCredentials) {
        return [
          draft.sourceKind === RULE_SOURCE.Nacos
            ? { key: "setup.nacosCredentialsRequired" }
            : { key: "setup.consulTokenRequired" },
        ];
      }
    }
  }

  return [];
}
