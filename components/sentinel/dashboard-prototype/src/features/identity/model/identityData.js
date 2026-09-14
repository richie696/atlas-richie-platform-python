/**
 * Demo-only identity contracts. The production API must return these shapes
 * without exposing password hashes, reset tokens, or other credentials.
 */
export const IDENTITY_ROLES = Object.freeze([
  {
    id: "admin",
    label: "管理员",
    description: "查看全部运行数据，并创建、修改、发布和回滚流控规则。",
    permissions: ["metrics:view", "rules:write"],
  },
  {
    id: "view",
    label: "查看者",
    description: "查看总览、实例、监控和故障分析，不具备任何编辑能力。",
    permissions: ["metrics:view"],
  },
]);

export const INITIAL_ACCOUNTS = Object.freeze([
  {
    id: "account-admin",
    username: "admin",
    displayName: "系统管理员",
    roleId: "admin",
    status: "active",
    builtIn: true,
    lastLoginAt: "2026-09-14 14:21",
  },
  {
    id: "account-view",
    username: "viewer",
    displayName: "运维查看",
    roleId: "view",
    status: "active",
    builtIn: false,
    lastLoginAt: "2026-09-14 13:58",
  },
]);

/** Ordered, persisted bootstrap checkpoints; these are not rule-source states. */
export const INITIALIZATION_STEPS = Object.freeze([
  {
    id: "storage",
    label: "系统存储",
    description: "验证数据库连接并创建控制面数据结构。",
  },
  {
    id: "admin",
    label: "内置管理员",
    description: "创建唯一的首个 admin；系统不提供默认密码。",
  },
  {
    id: "sources",
    label: "规则来源",
    description: "登记 Nacos 或 Consul，规则仍由配置中心权威持有。",
  },
  {
    id: "complete",
    label: "完成初始化",
    description: "记录初始化结果，开放登录与控制台 API。",
  },
]);

export function roleFor(roleId) {
  return IDENTITY_ROLES.find((role) => role.id === roleId) ?? IDENTITY_ROLES[1];
}
