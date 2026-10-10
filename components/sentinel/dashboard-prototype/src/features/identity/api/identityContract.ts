import { RequestKeySchema } from "../../../core/api/protocol/common";
import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { ConfigurationSourceInputSchema } from "../../../shared/api/configurationSourceWire";
import { IDENTITY_ENDPOINTS } from "./identityEndpoints";
import {
  BootstrapAuthorizationInputSchema,
  LoginInputSchema,
  SetupStorageSchema,
  InitializeCommandSchema,
} from "./identityWire";

const noParameters = Object.freeze([]);
const adminSessionExample = Object.freeze({
  accountId: "account-admin-1",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "session-epoch-1",
});
/** Semantic rules are required backend obligations; structural JSON Schema alone cannot prove these conditions. */
export const IDENTITY_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readBootstrap",
    summary: "读取初始化及本请求引导授权状态",
    tag: "bootstrap",
    security: "optional-bootstrap",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.Bootstrap,
    input: null,
    pathParameters: noParameters,
    semanticRules: [
      "Completed initialization is never reopened by a database failure.",
      "An operator grant cannot exist while the setup window is closed.",
      "No connection credentials or operator code are returned.",
      "Bootstrap issues or reuses a __Host- HttpOnly SameSite=Strict CSRF cookie and returns its matching nonce header; the nonce grants no identity.",
    ],
    examples: [
      {
        name: "setup_window_open_without_grant",
        summary: "未初始化系统允许首次设置，但当前浏览器尚未取得 operator grant",
        kind: "positive",
        request: {},
        response: {
          status: 200,
          body: { initialized: false, setupAvailable: true, operatorAuthorized: false },
        },
      },
      {
        name: "bootstrap_authority_temporarily_unavailable",
        summary: "无法读取权威初始化状态时返回服务不可用，不伪装成首次安装",
        kind: "negative",
        request: {},
        response: {
          status: 503,
          body: { error: { code: "service_unavailable", requestId: "bootstrap-read-error" } },
        },
      },
    ],
  },
  {
    operationId: "authorizeBootstrap",
    summary: "交换启动授权码为有时限的引导会话",
    tag: "bootstrap",
    security: "public",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.AuthorizeBootstrap,
    input: BootstrapAuthorizationInputSchema,
    pathParameters: noParameters,
    semanticRules: [
      "Exact allowed Origin and operator code are verified before granting bootstrap authority.",
      "operatorCode uses 32-1024 URL-safe ASCII characters; malformed values are rejected before authority exchange.",
      "Grant does not authenticate an administrator.",
      "Code is never returned or logged; unknown exchange is investigated by readBootstrap.",
    ],
    examples: [
      {
        name: "operator_code_grants_setup_only",
        summary: "有效的一次性部署授权码只建立 bootstrap 权限",
        kind: "positive",
        request: { body: { operatorCode: "synthetic-operator-code-contract-0001" } },
        response: { status: 200, body: { authorized: true } },
      },
      {
        name: "invalid_operator_code_forbidden",
        summary: "无效部署授权码不创建 bootstrap grant",
        kind: "negative",
        request: {
          body: { operatorCode: "synthetic-invalid-operator-code-contract-0001" },
        },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "bootstrap-code-denied" } },
        },
      },
    ],
  },
  {
    operationId: "readSession",
    summary: "确认当前账户会话或匿名状态",
    tag: "authentication",
    security: "anonymous",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.Session,
    input: null,
    pathParameters: noParameters,
    semanticRules: [
      "A view account never has rules:write capability.",
      "Capabilities are unique; authorization is rechecked for every request.",
      "sessionEpoch is an opaque observation owner, never a credential.",
    ],
    examples: [
      {
        name: "read_authenticated_admin_session",
        summary: "有效会话只返回安全身份字段与有限能力",
        kind: "positive",
        request: {},
        response: { status: 200, body: adminSessionExample },
      },
      {
        name: "session_authority_unavailable",
        summary: "会话权威不可用与匿名会话区分，不降级为 null",
        kind: "negative",
        request: {},
        response: {
          status: 503,
          body: { error: { code: "service_unavailable", requestId: "session-read-error" } },
        },
      },
    ],
  },
  {
    operationId: "login",
    summary: "验证登录凭据并轮换账户会话",
    tag: "authentication",
    security: "anonymous",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.Login,
    input: LoginInputSchema,
    pathParameters: noParameters,
    semanticRules: [
      "CSRF is bound to the browser's anonymous session and exact Origin.",
      "The x-sentinel-csrf value must match the __Host-sentinel_csrf cookie before account lookup or password verification.",
      "Login username lookup uses the shared trim/NFKC/lowercase identity used by account creation and bootstrap initialization.",
      "Successful login rotates the HttpOnly cookie and CSRF nonce.",
      "Unknown login response is inspected through readSession, not automatically repeated.",
    ],
    examples: [
      {
        name: "login_rotates_to_admin_session",
        summary: "正确凭据建立服务端会话，响应只投影身份与能力",
        kind: "positive",
        request: {
          body: { username: "operator", password: "synthetic-login-password-012345" },
        },
        response: { status: 200, body: adminSessionExample },
      },
      {
        name: "login_rejects_invalid_credentials",
        summary: "未知账号、错误密码或停用账号统一拒绝，不泄漏账号存在性",
        kind: "negative",
        request: {
          body: { username: "unknown-operator", password: "synthetic-wrong-password-012345" },
        },
        response: {
          status: 401,
          body: { error: { code: "unauthenticated", requestId: "login-denied" } },
        },
      },
    ],
  },
  {
    operationId: "logout",
    summary: "撤销当前登录会话",
    tag: "authentication",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.Logout,
    input: null,
    pathParameters: noParameters,
    semanticRules: [
      "CSRF and exact Origin are checked before session revocation.",
      "The CSRF proof must match the current active session's server-stored digest; the session cookie is cleared only after confirmed revocation.",
      "204 contains no body; completion is separately inspected through bootstrap and readSession.",
    ],
    examples: [
      {
        name: "logout_revokes_current_session",
        summary: "通过当前会话 CSRF 校验后撤销 session，并以空 204 确认",
        kind: "positive",
        request: {},
        response: { status: 204 },
      },
      {
        name: "logout_rejects_stale_csrf_proof",
        summary: "CSRF 证明不匹配时不撤销任何会话",
        kind: "negative",
        request: {},
        response: {
          status: 403,
          body: { error: { code: "csrf_failed", requestId: "logout-csrf-denied" } },
        },
      },
    ],
  },
  {
    operationId: "checkBootstrapDatabase",
    summary: "只读检查控制面数据库连接",
    tag: "bootstrap",
    security: "bootstrap",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.CheckDatabase,
    input: SetupStorageSchema,
    pathParameters: noParameters,
    semanticRules: [
      "Requires the current bootstrap-operator grant, not knowledge of a request key.",
      "Target allowlist, DNS pinning, TLS and bounded timeout are enforced server-side.",
      "Does not migrate schema or persist database credentials.",
      "SQLite is local-only when explicitly enabled; PG/MySQL acceptance cannot be substituted.",
    ],
    examples: [
      {
        name: "local_sqlite_connection_reachable",
        summary: "显式启用本地 SQLite 后只验证连接能力，不触发迁移",
        kind: "positive",
        request: { body: { kind: "sqlite" } },
        response: { status: 200, body: { status: "reachable" } },
      },
      {
        name: "invalid_database_port_rejected",
        summary: "端口超出范围在建立连接前按无效请求拒绝",
        kind: "negative",
        request: {
          body: {
            kind: "postgresql",
            host: "db.example.test",
            port: 70000,
            database: "sentinel",
            username: "console",
            password: "synthetic-db-password-012345",
          },
          bodyConforms: false,
        },
        response: {
          status: 400,
          body: { error: { code: "invalid_request", requestId: "database-check-invalid" } },
        },
      },
    ],
  },
  {
    operationId: "checkBootstrapSource",
    summary: "只读检查首个规则配置中心",
    tag: "bootstrap",
    security: "bootstrap",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.CheckSource,
    input: ConfigurationSourceInputSchema,
    pathParameters: noParameters,
    semanticRules: [
      "Requires current bootstrap authority and exact Origin/CSRF.",
      "Nacos namespace and Consul datacenter are not interchangeable.",
      "None/reference/direct modes are supported; KMS is not mandatory.",
      "Server connector enforces SSRF/TLS/destination policies without persisting or writing rules.",
    ],
    examples: [
      {
        name: "nacos_no_auth_endpoint_reachable",
        summary: "内网 Nacos 可使用显式 none 认证模式检查连接",
        kind: "positive",
        request: {
          body: {
            provider: "nacos",
            endpoint: "https://nacos.example.test",
            namespace: "public",
            authentication: { mode: "none" },
          },
        },
        response: { status: 200, body: { status: "reachable" } },
      },
      {
        name: "unsafe_source_endpoint_rejected",
        summary: "非 HTTP(S) 配置源地址在连接前拒绝",
        kind: "negative",
        request: {
          body: {
            provider: "consul",
            endpoint: "file:///etc/passwd",
            datacenter: "dc1",
            authentication: { mode: "none" },
          },
          bodyConforms: false,
        },
        response: {
          status: 400,
          body: { error: { code: "invalid_request", requestId: "source-check-invalid" } },
        },
      },
    ],
  },
  {
    operationId: "initializeConsole",
    summary: "原子初始化数据库、内置管理员及规则源登记",
    tag: "bootstrap",
    security: "bootstrap",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.Initialize,
    input: InitializeCommandSchema,
    pathParameters: noParameters,
    semanticRules: [
      "Idempotency-Key equals requestKey and is bound to the original bootstrap operator and canonical input.",
      "Bootstrap administrator username uses the shared trim/NFKC/lowercase identity and the same unique lookup key as later accounts and login.",
      "Server protects stored credentials; read receipts never contain input values.",
      "A pending/completed/rejected receipt has the original requestKey; not-found is invalid for a command ACK.",
      "Initialization lock and completed marker survive worker concurrency/restarts/database outages.",
    ],
    examples: [
      {
        name: "first_run_initialization_accepted",
        summary: "首次初始化以幂等 requestKey 受理，长流程可返回待核查操作 ID",
        kind: "positive",
        request: {
          body: {
            requestKey: "bootstrap-init-example-1",
            input: {
              database: { kind: "sqlite" },
              admin: {
                username: "operator",
                password: "synthetic-admin-password-012345",
              },
              source: {
                provider: "nacos",
                endpoint: "https://nacos.example.test",
                namespace: "public",
                authentication: { mode: "none" },
              },
            },
          },
        },
        response: {
          status: 200,
          body: {
            status: "pending",
            requestKey: "bootstrap-init-example-1",
            operationId: "bootstrap-operation-1",
          },
        },
      },
      {
        name: "unsupported_database_rejected_before_acceptance",
        summary: "不支持的数据库类型在初始化受理前以 invalid_request 拒绝",
        kind: "negative",
        request: {
          body: {
            requestKey: "bootstrap-init-invalid-1",
            input: {
              database: { kind: "oracle" },
              admin: {
                username: "operator",
                password: "synthetic-admin-password-012345",
              },
              source: {
                provider: "nacos",
                endpoint: "https://nacos.example.test",
                namespace: "public",
                authentication: { mode: "none" },
              },
            },
          },
          bodyConforms: false,
        },
        response: {
          status: 400,
          body: { error: { code: "invalid_request", requestId: "bootstrap-init-invalid" } },
        },
      },
    ],
  },
  {
    operationId: "readInitialization",
    summary: "核查原操作者的首次初始化命令",
    tag: "bootstrap",
    security: "bootstrap",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: IDENTITY_ENDPOINTS.Initialization,
    input: null,
    pathParameters: [{ name: "requestKey", schema: RequestKeySchema }],
    semanticRules: [
      "Knowing the key never grants lookup authority.",
      "Bounded post-completion recovery may read only the original safe operation fact.",
      "not-found/pending is not proof of rollback and cannot authorize replay.",
    ],
    examples: [
      {
        name: "initialization_lookup_completed",
        summary: "原 operator 可核查安全完成回执，不包含提交的凭证",
        kind: "positive",
        request: { pathParameters: { requestKey: "bootstrap-init-example-1" } },
        response: {
          status: 200,
          body: {
            status: "completed",
            requestKey: "bootstrap-init-example-1",
            operationId: "bootstrap-operation-1",
          },
        },
      },
      {
        name: "initialization_lookup_not_found",
        summary: "当前暂未观察到该初始化操作；not-found 不证明原请求已回滚",
        kind: "negative",
        request: { pathParameters: { requestKey: "bootstrap-init-example-2" } },
        response: {
          status: 200,
          body: { status: "not-found", requestKey: "bootstrap-init-example-2" },
        },
      },
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
