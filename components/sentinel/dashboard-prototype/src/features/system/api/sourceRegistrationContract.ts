import { RequestKeySchema } from "../../../core/api/protocol/common";
import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { SOURCE_REGISTRATION_ENDPOINTS } from "./sourceRegistrationHttp";
import { SourceCheckInputSchema, SourceMutationSchema } from "./sourceRegistrationWire";

const requestKeyPath = [{ name: "requestKey", schema: RequestKeySchema }] as const;
export const SOURCE_REGISTRATION_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readRegisteredSources",
    summary: "读取已登记的配置源及非秘密配置事实",
    tag: "system-sources",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: SOURCE_REGISTRATION_ENDPOINTS.Registry,
    input: null,
    pathParameters: [],
    semanticRules: [
      "Requires the admin role on every request.",
      "Credential values and credential-reference identifiers are write-only and never returned.",
      "The source registry is a server-persisted fact; it is not inferred from UI state.",
    ],
    examples: [
      {
        name: "admin_reads_safe_registry",
        summary: "管理员读取已登记的非秘密配置源事实",
        kind: "positive",
        request: {},
        response: {
          status: 200,
          body: {
            asOf: "2026-10-10T00:00:00.000Z",
            items: [
              {
                id: "source-prod-nacos",
                revision: "revision-12",
                name: "生产规则源",
                endpoint: "https://nacos.example.test:8848",
                authenticationMode: "credential-reference",
                credentialConfigured: true,
                provider: "nacos",
                namespace: "sentinel-prod",
              },
            ],
          },
        },
      },
      {
        name: "viewer_cannot_read_registry",
        summary: "查看者不能读取管理员专属的配置源登记表",
        kind: "negative",
        request: {},
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "source-example-denied" } },
        },
      },
    ],
  },
  {
    operationId: "checkRegisteredSource",
    summary: "无副作用地检查配置源连通性与规则写回能力",
    tag: "system-sources",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: SOURCE_REGISTRATION_ENDPOINTS.Check,
    input: SourceCheckInputSchema,
    pathParameters: [],
    semanticRules: [
      "Requires the admin role, exact Origin and CSRF; does not register, publish or mutate the source.",
      "sourceId and expectedRevision must either both be null for a new candidate or both identify the same registered revision.",
      "A 429 rate_limited rejection always includes bounded retryAfterMs; the client preserves the cooldown and never auto-replays the probe.",
      "The server enforces endpoint/SSRF policy and returns only bounded capability and failure classifications.",
      "Keep credentials resolve only on the server; direct credentials and references are write-only.",
    ],
    examples: [
      {
        name: "probe_reachable_source",
        summary: "连通性检查返回有时效的能力事实",
        kind: "positive",
        request: {
          body: {
            sourceId: null,
            expectedRevision: null,
            source: {
              provider: "nacos",
              endpoint: "https://nacos.example.test:8848",
              namespace: "sentinel-staging",
              authentication: { mode: "none" },
            },
          },
          bodyConforms: true,
        },
        response: {
          status: 200,
          body: {
            status: "reachable",
            checkedAt: "2026-10-10T00:00:00.000Z",
            expiresAt: "2026-10-10T00:01:00.000Z",
            capabilities: ["read", "conditional-write", "watch"],
          },
        },
      },
      {
        name: "probe_rejects_unpaired_source_revision",
        summary: "配置源 ID 与 revision 不能只提供其中一个",
        kind: "negative",
        request: {
          body: {
            sourceId: null,
            expectedRevision: "revision-12",
            source: {
              provider: "nacos",
              endpoint: "https://nacos.example.test:8848",
              namespace: "sentinel-staging",
              authentication: { mode: "none" },
            },
          },
          bodyConforms: false,
        },
        response: {
          status: 400,
          body: { error: { code: "invalid_request", requestId: "source-example-invalid" } },
        },
      },
      {
        name: "viewer_probe_forbidden",
        summary: "查看者不能发起配置源连通性检查",
        kind: "negative",
        request: {
          body: {
            sourceId: null,
            expectedRevision: null,
            source: {
              provider: "nacos",
              endpoint: "https://nacos.example.test:8848",
              namespace: "sentinel-staging",
              authentication: { mode: "none" },
            },
          },
          bodyConforms: true,
        },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "source-example-denied" } },
        },
      },
    ],
  },
  {
    operationId: "mutateRegisteredSource",
    summary: "登记、条件更新或删除 Nacos/Consul 配置源",
    tag: "system-sources",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: SOURCE_REGISTRATION_ENDPOINTS.Command,
    input: SourceMutationSchema,
    pathParameters: [],
    semanticRules: [
      "Requires the admin role, exact Origin and CSRF; Idempotency-Key must equal body requestKey.",
      "Update compares expectedRevision atomically; same key with different canonical input is rejected.",
      "Credential fields and reference identifiers are write-only, excluded from safe receipts/audit, and never logged or returned.",
      "A completed receipt must match the requested provider/name/location and return a new safe revision; rejected is a finite domain fact.",
      "Delete requires the exact current source revision; it is idempotent and never cascades into rule bindings or publications.",
      "A source referenced by any rule binding is rejected with source_in_use; the restrictive foreign key remains the final concurrency guard.",
      "Successful delete removes the online encrypted credential and probe in the same SQL transaction; its durable receipt contains only deletedSourceId, never endpoint or credential metadata.",
    ],
    examples: [
      {
        name: "register_source_pending",
        summary: "登记命令先返回可核查的 pending 操作事实",
        kind: "positive",
        request: {
          body: {
            kind: "register",
            requestKey: "source-register-example-1",
            name: "示例 Nacos",
            source: {
              provider: "nacos",
              endpoint: "https://nacos.example.test:8848",
              namespace: "sentinel-example",
              authentication: { mode: "none" },
            },
          },
          bodyConforms: true,
        },
        response: {
          status: 202,
          body: { status: "pending", requestKey: "source-register-example-1" },
        },
      },
      {
        name: "register_missing_name_rejected",
        summary: "缺少显示名称的登记请求在受理前以 validation_failed 拒绝",
        kind: "negative",
        request: {
          body: {
            kind: "register",
            requestKey: "source-register-invalid-1",
            source: {
              provider: "nacos",
              endpoint: "https://nacos.example.test:8848",
              namespace: "sentinel-example",
              authentication: { mode: "none" },
            },
          },
          bodyConforms: false,
        },
        response: {
          status: 422,
          body: {
            error: { code: "validation_failed", requestId: "source-example-invalid" },
          },
        },
      },
      {
        name: "delete_unreferenced_source",
        summary: "按 revision 删除未被规则引用的配置源，回执不包含连接或凭证事实",
        kind: "positive",
        request: {
          body: {
            kind: "delete",
            requestKey: "source-delete-example-1",
            sourceId: "source-prod-nacos",
            expectedRevision: "revision-12",
          },
          bodyConforms: true,
        },
        response: {
          status: 202,
          body: {
            status: "completed",
            requestKey: "source-delete-example-1",
            deletedSourceId: "source-prod-nacos",
          },
        },
      },
      {
        name: "delete_rejects_referenced_source",
        summary: "仍被规则绑定引用的配置源不允许删除，且不会级联删除规则",
        kind: "negative",
        request: {
          body: {
            kind: "delete",
            requestKey: "source-delete-example-2",
            sourceId: "source-prod-nacos",
            expectedRevision: "revision-12",
          },
          bodyConforms: true,
        },
        response: {
          status: 202,
          body: {
            status: "rejected",
            requestKey: "source-delete-example-2",
            reason: "source_in_use",
          },
        },
      },
    ],
  },
  {
    operationId: "readRegisteredSourceOperation",
    summary: "核查原操作者发起的配置源操作",
    tag: "system-sources",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: SOURCE_REGISTRATION_ENDPOINTS.Operation,
    input: null,
    pathParameters: requestKeyPath,
    semanticRules: [
      "Requires the current admin role and ownership of the original operation; a request key alone is not authorization.",
      "Not-found and pending do not prove rollback and cannot authorize replay.",
      "The safe observation contains no credentials, raw errors, or submitted source body.",
    ],
    examples: [
      {
        name: "lookup_missing_operation_is_an_observation",
        summary: "原操作未找到以 200 安全观察事实返回，不代表写请求从未提交",
        kind: "positive",
        request: { pathParameters: { requestKey: "source-operation-example-1" } },
        response: {
          status: 200,
          body: { status: "not_found", requestKey: "source-operation-example-1" },
        },
      },
      {
        name: "viewer_cannot_lookup_operation",
        summary: "查看者不能查询管理员操作回执",
        kind: "negative",
        request: { pathParameters: { requestKey: "source-operation-example-1" } },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "source-example-denied" } },
        },
      },
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
