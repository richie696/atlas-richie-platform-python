/**
 * 账号领域的协议类型、角色目录与凭据表单校验。
 *
 * 中文
 * ----
 * 本模块不依赖 React、语言包和网络，只描述「账号与角色是什么」以及「凭据表单是否
 * 完整」。它替代旧的 `model/identityData.ts`：旧文件把**协议类型**、**角色目录**、
 * **演示数据**和**校验规则**混在同一个文件里，于是 `INITIAL_ACCOUNTS` 这类示例数据
 * 看起来像正式目录，而页面里的 `value as IdentityRoleId` 断言也没有任何一层检查。
 *
 * 划分原则：
 *
 * - 协议值（角色 id、账号状态、能力名）在这里定义成常量对象，值即 API 契约值。
 * - 角色目录属于领域常量（授权只有两种角色），因此留在 model；**账号列表是示例数据**，
 *   已迁到 `features/identity/fixtures/identityFixtures.ts`。
 * - 校验返回**结构化问题**（消息键 + 参数），翻译由 UI 层完成；这样「管理员密码是否
 *   够长」这种领域判断不再被绑死在界面语言上。
 */
import { PASSWORD_MIN_LENGTH, type IdentityIssue } from "./passwordPolicy";
import { SESSION_CAPABILITY, type SessionCapability } from "../../../core/session/capabilities";

/** 授权角色。值即 API 契约里的 `roleId`，不是展示文案。 */
export const IDENTITY_ROLE = Object.freeze({
  Admin: "admin",
  View: "view",
} as const);

/** {@link IDENTITY_ROLE} 的值联合。 */
export type IdentityRoleId = (typeof IDENTITY_ROLE)[keyof typeof IDENTITY_ROLE];

/** 账号状态。停用会立即拒绝新的登录请求。 */
export const ACCOUNT_STATUS = Object.freeze({
  Active: "active",
  Disabled: "disabled",
} as const);

/** {@link ACCOUNT_STATUS} 的值联合。 */
export type AccountStatus = (typeof ACCOUNT_STATUS)[keyof typeof ACCOUNT_STATUS];

/**
 * 控制台承认的两项能力。
 *
 * 授权只有这两个维度：能看运行数据（`metrics:view`）与能写规则（`rules:write`）。
 * 服务端在**每次请求**上重新判定，客户端持有的能力快照只用于导航和展示。
 */
export const IDENTITY_CAPABILITY = SESSION_CAPABILITY;

/** {@link IDENTITY_CAPABILITY} 的值联合。 */
export type IdentityCapability = SessionCapability;

/** 单个角色的定义。`permissions` 是 {@link IDENTITY_CAPABILITY} 的子集。 */
export interface IdentityRole {
  readonly id: IdentityRoleId;
  /** 名称与说明的**语言键**。译文在 `features/identity/i18n/locales.ts`。 */
  readonly labelKey: string;
  readonly descriptionKey: string;
  /** 能力码（协议值，不翻译）。 */
  readonly permissions: readonly string[];
}

/**
 * 账号列表行。
 *
 * 线上契约里**没有**密码哈希、重置令牌或任何凭证：密码只在写入式提交时经过前端，
 * 从不进入这份只读摘要。
 */
export interface AccountSummary {
  readonly id: string;
  readonly username: string;
  readonly roleId: IdentityRoleId;
  readonly status: AccountStatus;
  /** 内置管理员账号不可删除。 */
  readonly builtIn: boolean;
  readonly lastLoginAt: string;
}

/**
 * 新建账号的写入式凭据。
 *
 * `password` 只存在于表单与提交载荷中；提交后必须从 UI 状态清除，不写进
 * {@link AccountSummary}，也不进入 URL、日志或浏览器存储。
 */
export interface AccountDraft {
  readonly username: string;
  /** Write-only credential; never store it in AccountSummary or UI state after submit. */
  readonly password: string;
  readonly roleId: IdentityRoleId;
}

/** 登录表单的凭据字段。 */
export interface LoginCredentials {
  readonly username: string;
  readonly password: string;
}

/** 角色目录。顺序即界面选项顺序。 */
export const IDENTITY_ROLES: readonly IdentityRole[] = Object.freeze([
  {
    id: IDENTITY_ROLE.Admin,
    labelKey: "roles.role.admin.title",
    descriptionKey: "roles.role.admin.description",
    permissions: [IDENTITY_CAPABILITY.MetricsView, IDENTITY_CAPABILITY.RulesWrite],
  },
  {
    id: IDENTITY_ROLE.View,
    labelKey: "roles.role.view.title",
    descriptionKey: "roles.role.view.description",
    permissions: [IDENTITY_CAPABILITY.MetricsView],
  },
] satisfies readonly IdentityRole[]);

/** 未知角色 id 的回落角色。宁可展示只读角色，也不把非法值当成 admin。 */
export function roleFor(roleId: IdentityRoleId): IdentityRole {
  return IDENTITY_ROLES.find((role) => role.id === roleId) ?? IDENTITY_ROLES[1];
}

/**
 * 把任意来源的字符串收窄为角色 id。
 *
 * `RadioGroup` / `Selector` 的值域是 `string`，旧实现在 onChange 里写
 * `value as IdentityRoleId`：断言不检查值域，配置中心或 DOM 里出现一个未知字符串时，
 * 它会静默变成一个不存在的角色。守卫让「不是协议值」这件事在类型层显式失败，调用方
 * 只需决定如何处理非法值（本 feature 一律保持原状态）。
 */
export function isIdentityRoleId(value: string): value is IdentityRoleId {
  return (IDENTITY_ROLES as readonly { id: string }[]).some((role) => role.id === value);
}

/** 状态切换命令的纯计算：启用 ⇄ 停用。 */
export function nextAccountStatus(status: AccountStatus): AccountStatus {
  return status === ACCOUNT_STATUS.Active ? ACCOUNT_STATUS.Disabled : ACCOUNT_STATUS.Active;
}

/** 从写入式草稿构造账号摘要。`id` 由调用方（未来的 gateway）提供。 */
export function toAccountSummary(
  id: string,
  draft: AccountDraft,
  lastLoginAt: string,
): AccountSummary {
  return {
    id,
    username: draft.username,
    roleId: draft.roleId,
    status: ACCOUNT_STATUS.Active,
    builtIn: false,
    lastLoginAt,
  };
}

/** 新建账号表单校验的消息键。翻译发生在 UI 层。 */
export type AccountDraftIssueKey = "account.credentialsRequired" | "account.passwordTooShort";

/** 登录表单校验的消息键。 */
export type LoginIssueKey = "account.loginRequired";

/** 凭据表单校验的全部消息键。 */
export type AccountIssueKey = AccountDraftIssueKey | LoginIssueKey;

/** 一条新建账号问题。UI 层把 `key` 与 `params` 翻译为文案。 */
export type AccountDraftIssue = IdentityIssue<AccountDraftIssueKey>;

/** 一条登录问题。 */
export type LoginIssue = IdentityIssue<LoginIssueKey>;

/** 新建账号的本地必填校验。跨字段唯一性、密码强度与审计由服务端判定。 */
export function validateAccountDraft(draft: AccountDraft): readonly AccountDraftIssue[] {
  if (!draft.username.trim() || !draft.password) {
    return [{ key: "account.credentialsRequired" }];
  }
  if (draft.password.length < PASSWORD_MIN_LENGTH) {
    return [{ key: "account.passwordTooShort", params: { min: PASSWORD_MIN_LENGTH } }];
  }
  return [];
}

/** 登录表单的本地必填校验。凭证正确性只能由服务端判断。 */
export function validateLoginCredentials(
  credentials: LoginCredentials,
): readonly LoginIssue[] {
  if (!credentials.username || !credentials.password) {
    return [{ key: "account.loginRequired" }];
  }
  return [];
}
