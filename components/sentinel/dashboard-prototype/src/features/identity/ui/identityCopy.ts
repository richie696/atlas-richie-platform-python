/**
 * 身份 feature 校验消息的界面文案表。
 *
 * 中文
 * ----
 * `model/` 里的校验只返回**消息键 + 插值参数**，翻译发生在 UI 层——这就是本文件存在
 * 的唯一理由。领域判断因此可以脱离语言单测，界面文案也可以在一处维护。
 *
 * 形状是 `Readonly<Record<全部消息键, 文案>>`：新增一条校验而忘记补文案，会在编译期
 * 报错，而不是在界面上漏出 `setup.adminRequired` 这样的协议键。
 *
 * 参数化文案用函数而不是 `{min}` 模板替换：`min` 来自 `PASSWORD_MIN_LENGTH`，页面
 * 文案不需要再写一遍「12」，策略变化时两处不会漂移。
 *
 * 归属说明：本 feature 目前没有自己的 i18n 层（`src/ruleI18n.ts` 由 rules feature
 * 拥有，identity 不共享它的消息空间）。阶段 1.3 落地 `core/i18n` 后，本表整体迁入
 * locale 资源，**消息键保持不变**，各调用点无需改动。
 */
import type { AccountDraftIssueKey, LoginIssueKey } from "../model/account";
import type { PasswordIssueKey } from "../model/passwordPolicy";
import type { SetupIssueKey } from "../model/setup";
import type { IdentityIssue } from "../model/passwordPolicy";

/** 身份 feature 全部校验消息键。 */
export type IdentityIssueTextKey = AccountDraftIssueKey | LoginIssueKey | PasswordIssueKey | SetupIssueKey;

type IssueParams = Readonly<Record<string, string | number>>;

/** 带参数文案工厂。 */
type IssueText = string | ((params: IssueParams) => string);

export const IDENTITY_ISSUE_TEXT: Readonly<Record<IdentityIssueTextKey, IssueText>> =
  Object.freeze({
    "account.credentialsRequired": "请填写账号名和密码。",
    "account.passwordTooShort": (params) =>
      `密码至少 ${params.min} 位，并应包含多种字符类型。`,
    "account.loginRequired": "请输入登录名和密码。",
    "password.tooShort": (params) => `新密码至少 ${params.min} 位，并应包含多种字符类型。`,
    "password.mismatch": "两次输入的新密码不一致。",
    "setup.adminRequired": (params) =>
      `请填写管理员信息，并设置至少 ${params.min} 位的密码。`,
    "setup.adminPasswordMismatch": "两次输入的管理员密码不一致。",
    "setup.credentialReferenceRequired": "请填写部署凭证引用，或选择直接填写凭证 / 不启用认证。",
    "setup.nacosCredentialsRequired": "请填写 Nacos 用户名和密码。",
    "setup.consulTokenRequired": "请填写 Consul ACL Token。",
  });

/** 把一条结构化校验问题翻译为界面文案。 */
export function identityIssueText(
  issue: IdentityIssue<IdentityIssueTextKey>,
): string {
  const entry = IDENTITY_ISSUE_TEXT[issue.key];
  return typeof entry === "function" ? entry(issue.params ?? {}) : entry;
}
