/**
 * Demo-only identity contracts. The production API must return these shapes
 * without exposing password hashes, reset tokens, or other credentials.
 */
export type IdentityRoleId = "admin" | "view";
export type AccountStatus = "active" | "disabled";
export type IdentityRole = {
  id: IdentityRoleId;
  label: string;
  description: string;
  permissions: readonly string[];
};
export type AccountSummary = {
  id: string;
  username: string;
  displayName: string;
  roleId: IdentityRoleId;
  status: AccountStatus;
  builtIn: boolean;
  lastLoginAt: string;
};
export type ControlPlaneDatabaseKind = "postgresql" | "mysql" | "sqlite";
export type ControlPlaneDatabase = {
  id: ControlPlaneDatabaseKind;
  label: string;
  description: string;
  defaultPort: string;
  requiresNetworkConfiguration: boolean;
  usage: "production" | "local-development";
};

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
] satisfies readonly IdentityRole[]);

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
] satisfies readonly AccountSummary[]);

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

/**
 * Supported persistence choices for the Dashboard control plane.
 *
 * The active Sentinel rule snapshot remains in Nacos or Consul. These choices
 * only persist Dashboard-owned facts such as accounts, audits, drafts, rule
 * versions, and publishing plans. `id` is the API contract value; labels are
 * presentation data and must never be used as a protocol value.
 */
export const CONTROL_PLANE_DATABASES = Object.freeze([
  {
    id: "postgresql",
    label: "PostgreSQL",
    description: "生产环境支持，用于可靠的控制面持久化。",
    defaultPort: "5432",
    requiresNetworkConfiguration: true,
    usage: "production",
  },
  {
    id: "mysql",
    label: "MySQL",
    description: "生产环境支持，要求 MySQL 8.0+；MariaDB 需作为独立兼容项评估。",
    defaultPort: "3306",
    requiresNetworkConfiguration: true,
    usage: "production",
  },
  {
    id: "sqlite",
    label: "SQLite",
    description: "仅限本地体验或单机开发，不作为生产集群存储。",
    defaultPort: "",
    requiresNetworkConfiguration: false,
    usage: "local-development",
  },
] satisfies readonly ControlPlaneDatabase[]);

export function roleFor(roleId: IdentityRoleId): IdentityRole {
  return IDENTITY_ROLES.find((role) => role.id === roleId) ?? IDENTITY_ROLES[1];
}

/** Returns the supported database metadata for a stable API `kind` value. */
export function controlPlaneDatabaseFor(
  databaseKind: ControlPlaneDatabaseKind,
): ControlPlaneDatabase {
  return CONTROL_PLANE_DATABASES.find((database) => database.id === databaseKind)
    ?? CONTROL_PLANE_DATABASES[0];
}
