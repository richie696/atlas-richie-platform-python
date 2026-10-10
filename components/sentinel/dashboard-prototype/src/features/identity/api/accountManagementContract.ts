import { OpaqueIdentifierSchema, RequestKeySchema } from "../../../core/api/protocol/common";
import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { ACCOUNT_ENDPOINTS } from "./accountManagementEndpoints";
import { AccountListQuerySchema, AccountMutationSchema } from "./accountManagementWire";

/** Durable directory/command obligations. Server transactions, not UI hints, protect the built-in/last administrator. */
export const ACCOUNT_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "listAccounts",
    summary: "分页查询账号目录",
    tag: "accounts",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: ACCOUNT_ENDPOINTS.List,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(AccountListQuerySchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    semanticRules: [
      "Requires admin on each request; view cannot enumerate account management data.",
      "Page identity, unique IDs and total/items belong to one consistent directory read.",
      "No password, hash, reset token or display name is returned.",
    ],
    examples: [
      {
        name: "admin_lists_safe_accounts",
        summary: "管理员分页读取安全账号字段，不包含密码或密码摘要",
        kind: "positive",
        request: { queryParameters: { page: 1, pageSize: 20, search: "admin" } },
        response: {
          status: 200,
          body: {
            items: [
              {
                id: "account-1",
                username: "admin",
                roleId: "admin",
                status: "active",
                builtIn: true,
                lastLoginAt: "2026-10-08T00:00:00.000Z",
                revision: "3",
                lastActiveAdmin: true,
              },
            ],
            page: 1,
            pageSize: 20,
            total: 1,
          },
        },
      },
      {
        name: "viewer_account_list_forbidden",
        summary: "查看者无权枚举账号管理目录",
        kind: "negative",
        request: { queryParameters: { page: 1, pageSize: 20, search: "admin" } },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "account-example-denied" } },
        },
      },
    ],
  },
  {
    operationId: "readAccount",
    summary: "读取指定账号的当前修订",
    tag: "accounts",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: ACCOUNT_ENDPOINTS.Read,
    input: null,
    pathParameters: [{ name: "accountId", schema: OpaqueIdentifierSchema }],
    semanticRules: [
      "Requires admin; absence is null, never a substitute account.",
      "Built-in account is an active administrator; lastActiveAdmin is a server hint, not mutation authorization.",
    ],
    examples: [
      {
        name: "read_account_detail",
        summary: "按精确账号 ID 返回账号安全事实",
        kind: "positive",
        request: { pathParameters: { accountId: "account-1" } },
        response: {
          status: 200,
          body: {
            id: "account-1",
            username: "admin",
            roleId: "admin",
            status: "active",
            builtIn: true,
            lastLoginAt: "2026-10-08T00:00:00.000Z",
            revision: "3",
            lastActiveAdmin: true,
          },
        },
      },
      {
        name: "unknown_account_is_null",
        summary: "不存在的账号用 null 表示，不回退到其他账号",
        kind: "negative",
        request: { pathParameters: { accountId: "unknown-account" } },
        response: { status: 200, body: null },
      },
    ],
  },
  {
    operationId: "mutateAccount",
    summary: "创建账号、修改状态或绑定角色",
    tag: "accounts",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: ACCOUNT_ENDPOINTS.Command,
    input: AccountMutationSchema,
    pathParameters: [],
    semanticRules: [
      "Requires current admin session, exact Origin and CSRF; idempotency header equals body requestKey.",
      "Account commands are synchronous in V1: a completed HTTP response contains only a final completed/rejected receipt; pending describes an in-flight local request, not a wire status.",
      "Original actor, canonical input and key are bound durably; same key with different input is rejected.",
      "Username validation and lookup use the shared trim/NFKC/lowercase identity; a unique SHA-256 username_key rejects case and compatibility variants.",
      "Status/role require the target's current revision; check and update are one transaction.",
      "Built-in admin cannot be disabled/demoted, nor can the last active admin; concurrent mutations cannot bypass this invariant.",
      "Completed receipt matches the requested target/effect and has a new revision. Domain rejection is a safe operation fact; not-found is invalid as command acknowledgement.",
      "Password is write-only; safe operation lookup never includes the input or credential digest.",
    ],
    examples: [
      {
        name: "create_account_completed_receipt",
        summary: "新建账号命令同步返回最终回执；密码只在请求体中出现",
        kind: "positive",
        request: {
          body: {
            kind: "create",
            requestKey: "account-create-example-1",
            input: {
              username: "new-operator",
              password: "sample-only-credential-1234",
              roleId: "view",
            },
          },
          bodyConforms: true,
        },
        response: {
          status: 200,
          body: {
            status: "completed",
            requestKey: "account-create-example-1",
            account: {
              id: "account-2",
              username: "new-operator",
              roleId: "view",
              status: "active",
              builtIn: false,
              lastLoginAt: null,
              revision: "1",
              lastActiveAdmin: false,
            },
          },
        },
      },
      {
        name: "duplicate_account_has_final_domain_rejection",
        summary: "账号名冲突是 HTTP 200 的已知业务拒绝，不返回凭证或等待中状态",
        kind: "positive",
        request: {
          body: {
            kind: "create",
            requestKey: "account-create-example-2",
            input: {
              username: "admin",
              password: "sample-only-credential-2345",
              roleId: "view",
            },
          },
          bodyConforms: true,
        },
        response: {
          status: 200,
          body: {
            status: "rejected",
            requestKey: "account-create-example-2",
            reason: "username_taken",
          },
        },
      },
      {
        name: "unsupported_role_rejected_before_acceptance",
        summary: "不支持的角色编码在命令受理前以 invalid_request 拒绝",
        kind: "negative",
        request: {
          body: {
            kind: "role",
            requestKey: "account-role-invalid-1",
            accountId: "account-1",
            revision: "3",
            roleId: "owner",
          },
          bodyConforms: false,
        },
        response: {
          status: 400,
          body: {
            error: { code: "invalid_request", requestId: "account-example-invalid" },
          },
        },
      },
    ],
  },
  {
    operationId: "readAccountOperation",
    summary: "核查原操作者的账号命令",
    tag: "accounts",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: ACCOUNT_ENDPOINTS.Operation,
    input: null,
    pathParameters: [{ name: "requestKey", schema: RequestKeySchema }],
    semanticRules: [
      "Requires current admin and original operation ownership, not knowledge of the key.",
      "Not-found does not prove rollback and cannot authorize replay.",
    ],
    examples: [
      {
        name: "missing_account_operation_is_observation",
        summary: "未找到原操作以 200 not-found 观察返回，不授权写请求重放",
        kind: "positive",
        request: { pathParameters: { requestKey: "account-operation-example-1" } },
        response: {
          status: 200,
          body: { status: "not-found", requestKey: "account-operation-example-1" },
        },
      },
      {
        name: "viewer_account_operation_forbidden",
        summary: "查看者不能查询账号变更操作",
        kind: "negative",
        request: { pathParameters: { requestKey: "account-operation-example-1" } },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "account-example-denied" } },
        },
      },
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
