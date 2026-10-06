/**
 * 身份 feature 的演示数据。
 *
 * 中文
 * ----
 * fixture 只用于装配演示页面与测试；接入 Console API 后本文件整体删除，账号列表改由
 * `identity.gateway` 装载（`REACT_PROJECT_SKELETON` §2：`fixtures/` 是显式测试/演示
 * 数据）。因此这里的值是**示例**，不代表任何真实部署。
 *
 * 迁移说明：原 `model/identityData.ts` 把这份列表和协议类型放在一起，看起来像正式
 * 目录，实际只是首屏示例。协议类型与角色目录已留在 `model/account.ts`。
 */
import { ACCOUNT_STATUS, IDENTITY_ROLE } from "../model/account";
import type { AccountSummary } from "../model/account";

/**
 * 首屏示例账号。
 *
 * 刻意不包含密码哈希、重置令牌或任何凭证——线上契约里也没有这些字段。两个账号分别
 * 覆盖内置管理员与普通账号两条展示分支。
 */
export const INITIAL_ACCOUNTS: readonly AccountSummary[] = Object.freeze([
  {
    id: "account-admin",
    username: "admin",
    roleId: IDENTITY_ROLE.Admin,
    status: ACCOUNT_STATUS.Active,
    builtIn: true,
    lastLoginAt: "2026-09-14 14:21",
  },
  {
    id: "account-view",
    username: "viewer",
    roleId: IDENTITY_ROLE.View,
    status: ACCOUNT_STATUS.Active,
    builtIn: false,
    lastLoginAt: "2026-09-14 13:58",
  },
] satisfies readonly AccountSummary[]);

/** 新建账号的「最近登录」占位文案。真实实现由服务端在创建后返回。 */
export const NEW_ACCOUNT_LAST_LOGIN = "从未登录";
