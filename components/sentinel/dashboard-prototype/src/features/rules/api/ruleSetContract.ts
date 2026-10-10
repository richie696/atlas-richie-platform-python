import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { OpaqueIdentifierSchema, RequestKeySchema } from "../../../core/api/protocol/common";
import {
  PublicationReceiptParametersSchema,
  RuleBindingParametersSchema,
  RuleBindingRegistrationRequestSchema,
  RuleCommandRequestSchema,
  RuleSetCandidateSchema,
} from "./ruleSetWire";
import { RULE_SET_ENDPOINTS } from "./ruleSetHttp";
import {
  RULE_EXAMPLE_BINDING,
  RULE_EXAMPLE_CANDIDATE,
  RULE_EXAMPLE_DRAFT,
  RULE_EXAMPLE_OPERATION,
  RULE_EXAMPLE_PLAN,
  RULE_EXAMPLE_PUBLICATION,
  RULE_EXAMPLE_PREVIOUS_DRAFT_REVISION,
  RULE_EXAMPLE_RECORD,
  RULE_EXAMPLE_RESTORE_VERSION,
  RULE_EXAMPLE_TARGET,
  RULE_EXAMPLE_TIME,
  RULE_EXAMPLE_VERSION,
  RULE_EXAMPLE_RECEIPT_STATE,
  ruleErrorExample,
} from "./ruleContractExamples";
import { RULE_MUTATION } from "../model/ruleSetOperations";

const binding = [{ name: "bindingId", schema: OpaqueIdentifierSchema }] as const;
const item = (name: string) => [{ name, schema: OpaqueIdentifierSchema }] as const;
const operationKey = [{ name: "requestKey", schema: RequestKeySchema }] as const;
const bindingQueryParameters: Readonly<Record<string, string | number | boolean>> = {
  environmentId: "prod",
  appId: RULE_EXAMPLE_BINDING.appId,
  kind: RULE_EXAMPLE_BINDING.kind,
  search: "checkout",
  page: 1,
  pageSize: 20,
};
const bindingRead = (
  operationId: string,
  summary: string,
  endpoint: ConsoleOperationContract["endpoint"],
) => ({
  operationId,
  summary,
  tag: "rulesets",
  security: "session" as const,
  requiredAccess: CONSOLE_ACCESS.None,
  endpoint,
  input: null,
  pathParameters: binding,
  semanticRules: [
    "Requires current session authorization for this exact binding on every request.",
    "Rule bodies and profile data are complete typed records; secret material is never exposed by the API.",
  ],
});

export const RULE_SET_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "createRuleBinding",
    summary: "创建规则集绑定及其精确配置源目标",
    tag: "rulesets",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.AdminRulesWrite,
    endpoint: RULE_SET_ENDPOINTS.RegisterBinding,
    input: RuleBindingRegistrationRequestSchema,
    pathParameters: [],
    semanticRules: [
      "Creates Console binding metadata and its exact Nacos/Consul target in one SQL transaction; it never writes a rule array or calls the provider.",
      "The registered source provider, label, and revision are authoritative server facts; the request supplies only sourceId and expected sourceRevision.",
      "The command is idempotent for the same actor, browser session, request key, and payload. Reusing the key with another payload is rejected.",
      "An identical retry returns the original binding; provider target and binding metadata are never partially visible.",
    ],
    examples: [
      {
        name: "create-nacos-binding",
        summary: "创建 Nacos flow binding，但不写入规则正文",
        kind: "positive",
        request: {
          body: {
            requestKey: "binding-create-1",
            bindingId: "checkout-prod-flow",
            environmentId: "prod",
            appId: "checkout",
            kind: "flow",
            profile: "sentinel-flow-v1",
            sourceId: "nacos-main",
            sourceRevision: "source-revision-1",
            target: {
              provider: "nacos",
              namespace: "prod-namespace",
              group: "DEFAULT_GROUP",
              dataId: "flow-rules.json",
            },
          },
        },
        response: {
          status: 201,
          body: {
            id: "checkout-prod-flow",
            environmentId: "prod",
            appId: "checkout",
            kind: "flow",
            profile: "sentinel-flow-v1",
            sourceId: "nacos-main",
            sourceLabel: "Operations Nacos",
            location: "nacos://prod-namespace/DEFAULT_GROUP/flow-rules.json",
          },
        },
      },
      {
        name: "binding-registration-admin-required",
        summary: "viewer 不能创建规则绑定",
        kind: "negative",
        request: { body: { requestKey: "binding-create-1" }, bodyConforms: false },
        response: { status: 403, body: ruleErrorExample("forbidden") },
      },
    ],
  },
  {
    operationId: "readRuleBindings",
    summary: "按环境、应用、类型和关键词分页查询规则绑定",
    tag: "rulesets",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: RULE_SET_ENDPOINTS.Bindings,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(RuleBindingParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    examples: [
      {
        name: "flow-binding-page",
        summary: "返回与筛选查询一致的 flow 规则绑定页",
        kind: "positive",
        request: {
          queryParameters: bindingQueryParameters,
        },
        response: {
          status: 200,
          body: {
            query: {
              environmentId: RULE_EXAMPLE_BINDING.environmentId,
              appId: RULE_EXAMPLE_BINDING.appId,
              kind: RULE_EXAMPLE_BINDING.kind,
              search: "checkout",
              page: 1,
              pageSize: 20,
            },
            total: 1,
            items: [RULE_EXAMPLE_BINDING],
          },
        },
      },
      {
        name: "session-required",
        summary: "未认证请求不能读取规则绑定目录",
        kind: "negative",
        request: { queryParameters: bindingQueryParameters },
        response: { status: 401, body: ruleErrorExample("unauthenticated") },
      },
    ],
    semanticRules: [
      "Requires current session authorization; every filter and page is explicit.",
      "The response query exactly echoes the effective query; total is the filtered total and never implies a first binding selection.",
      "Binding locations are redacted display facts; provider credentials and raw connection options are forbidden.",
    ],
  },
  {
    ...bindingRead("readRuleSetSnapshot", "读取规则源的完整权威快照", RULE_SET_ENDPOINTS.Snapshot),
    examples: [
      {
        name: "authoritative-empty-snapshot",
        summary: "权威快照保留 source revision 与 checksum，即使当前无规则",
        kind: "positive",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: {
          status: 200,
          body: {
            binding: RULE_EXAMPLE_BINDING,
            versionId: RULE_EXAMPLE_VERSION.id,
            checksum: RULE_EXAMPLE_VERSION.checksum,
            sourceRevision: "source-revision-7",
            asOf: RULE_EXAMPLE_TIME.asOf,
            records: [RULE_EXAMPLE_RECORD],
          },
        },
      },
      {
        name: "binding-not-found",
        summary: "绑定已删除或当前会话无权访问时不返回其他绑定快照",
        kind: "negative",
        request: { pathParameters: { bindingId: "missing-binding" } },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead("readRuleDrafts", "读取当前绑定的全部持久草稿", RULE_SET_ENDPOINTS.Drafts),
    security: "session" as const,
    requiredAccess: CONSOLE_ACCESS.RulesWrite,
    semanticRules: [
      "Requires rules:write authorization; draft content and revisions are isolated by binding.",
    ],
    examples: [
      {
        name: "draft-collection",
        summary: "读取绑定下独立持久的草稿修订",
        kind: "positive",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: {
          status: 200,
          body: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            asOf: RULE_EXAMPLE_TIME.asOf,
            items: [RULE_EXAMPLE_DRAFT],
          },
        },
      },
      {
        name: "rules-write-required",
        summary: "没有 rules:write 时拒绝读取编辑草稿",
        kind: "negative",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: { status: 403, body: ruleErrorExample("forbidden") },
      },
    ],
  },
  {
    ...bindingRead("readRuleDraft", "读取指定草稿及其完整修订", RULE_SET_ENDPOINTS.Draft),
    requiredAccess: CONSOLE_ACCESS.RulesWrite,
    pathParameters: [...binding, ...item("draftId")],
    semanticRules: [
      "Requires rules:write authorization; path bindingId and draftId must match response identity.",
    ],
    examples: [
      {
        name: "draft-revision",
        summary: "草稿响应回显精确绑定、基线与 revision",
        kind: "positive",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            draftId: RULE_EXAMPLE_DRAFT.id,
          },
        },
        response: { status: 200, body: RULE_EXAMPLE_DRAFT },
      },
      {
        name: "draft-not-found",
        summary: "草稿不存在时返回 not_found",
        kind: "negative",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id, draftId: "missing-draft" },
        },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead(
      "validateRuleCandidate",
      "校验完整规则候选集但不持久写入",
      RULE_SET_ENDPOINTS.Validate,
    ),
    security: "session" as const,
    requiredAccess: CONSOLE_ACCESS.RulesWrite,
    input: RuleSetCandidateSchema,
    semanticRules: [
      "Requires rules:write authorization; validation never mutates source or draft state.",
      "Report binds exact binding, profile, base checksum and candidate checksum; any changed candidate invalidates the ticket.",
    ],
    examples: [
      {
        name: "candidate-publishable",
        summary: "返回绑定精确 candidate checksum 的可发布校验票据",
        kind: "positive",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id },
          body: RULE_EXAMPLE_CANDIDATE,
        },
        response: {
          status: 200,
          body: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            profile: RULE_EXAMPLE_BINDING.profile,
            baseChecksum: RULE_EXAMPLE_CANDIDATE.baseChecksum,
            candidateChecksum: "checksum-candidate-1",
            validationId: "validation-ticket-1",
            isPublishable: true,
            issues: [],
          },
        },
      },
      {
        name: "candidate-base-conflict",
        summary: "候选基线已变化时要求重新读取权威快照",
        kind: "negative",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id },
          body: RULE_EXAMPLE_CANDIDATE,
        },
        response: { status: 409, body: ruleErrorExample("conflict") },
      },
    ],
  },
  {
    ...bindingRead("compareRuleCandidate", "比较权威基线与完整候选规则集", RULE_SET_ENDPOINTS.Diff),
    security: "session" as const,
    requiredAccess: CONSOLE_ACCESS.RulesWrite,
    input: RuleSetCandidateSchema,
    semanticRules: [
      "Requires rules:write authorization; diff is complete and bound to base and candidate checksums.",
    ],
    examples: [
      {
        name: "candidate-diff",
        summary: "当前候选与基线一致时返回空差异",
        kind: "positive",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id },
          body: RULE_EXAMPLE_CANDIDATE,
        },
        response: {
          status: 200,
          body: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            baseChecksum: RULE_EXAMPLE_CANDIDATE.baseChecksum,
            candidateChecksum: RULE_EXAMPLE_CANDIDATE.baseChecksum,
            changes: [],
          },
        },
      },
      {
        name: "candidate-base-conflict",
        summary: "差异计算发现权威基线变化时拒绝返回过期比较",
        kind: "negative",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id },
          body: RULE_EXAMPLE_CANDIDATE,
        },
        response: { status: 409, body: ruleErrorExample("conflict") },
      },
    ],
  },
  {
    ...bindingRead("readRuleVersions", "读取不可变规则版本集合", RULE_SET_ENDPOINTS.Versions),
    examples: [
      {
        name: "immutable-version-list",
        summary: "返回不可变版本记录，激活状态不混入版本内容",
        kind: "positive",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: {
          status: 200,
          body: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            asOf: RULE_EXAMPLE_TIME.asOf,
            items: [RULE_EXAMPLE_VERSION, RULE_EXAMPLE_RESTORE_VERSION],
          },
        },
      },
      {
        name: "binding-not-found",
        summary: "绑定不存在时不能读取其他规则版本",
        kind: "negative",
        request: { pathParameters: { bindingId: "missing-binding" } },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead("readRuleVersion", "读取指定不可变规则版本", RULE_SET_ENDPOINTS.Version),
    pathParameters: [...binding, ...item("versionId")],
    examples: [
      {
        name: "immutable-version",
        summary: "返回指定绑定下的不可变版本内容与创建者",
        kind: "positive",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            versionId: RULE_EXAMPLE_VERSION.id,
          },
        },
        response: { status: 200, body: RULE_EXAMPLE_VERSION },
      },
      {
        name: "version-not-found",
        summary: "版本不属于此绑定或不存在时返回 not_found",
        kind: "negative",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id, versionId: "missing-version" },
        },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead(
      "readRulePublications",
      "读取发布阶段与回读事实",
      RULE_SET_ENDPOINTS.Publications,
    ),
    examples: [
      {
        name: "publication-in-progress",
        summary: "校验完成、配置写入尚未结束时保持阶段事实分离",
        kind: "positive",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: {
          status: 200,
          body: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            asOf: RULE_EXAMPLE_TIME.asOf,
            items: [RULE_EXAMPLE_PUBLICATION],
          },
        },
      },
      {
        name: "binding-not-found",
        summary: "绑定不存在时不泄漏发布记录",
        kind: "negative",
        request: { pathParameters: { bindingId: "missing-binding" } },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead(
      "readRulePublication",
      "读取单次规则发布的独立阶段事实",
      RULE_SET_ENDPOINTS.Publication,
    ),
    pathParameters: [...binding, ...item("publicationId")],
    examples: [
      {
        name: "publication-phases",
        summary: "发布回读仍待执行时不能推断配置已生效",
        kind: "positive",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            publicationId: RULE_EXAMPLE_PUBLICATION.id,
          },
        },
        response: { status: 200, body: RULE_EXAMPLE_PUBLICATION },
      },
      {
        name: "publication-not-found",
        summary: "发布记录不属于此绑定或不存在时返回 not_found",
        kind: "negative",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            publicationId: "missing-publication",
          },
        },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead(
      "readRulePublicationReceipts",
      "分页读取实例加载回执与完整性分母",
      RULE_SET_ENDPOINTS.Receipts,
    ),
    pathParameters: [...binding, ...item("publicationId")],
    queryParameters: Object.entries(PublicationReceiptParametersSchema.shape).map(
      ([name, schema]) => ({
        name,
        schema,
      }),
    ),
    semanticRules: [
      "A null processEpoch is permitted only for an unknown receipt with all loaded-process, version, checksum, and report-time facts null.",
      "Applied requires matching current process incarnation, target version and target checksum, plus non-null appliedAt and lastReportAt.",
      "Inventory expected/source are both known or both null; when known, expected equals the receipt population total.",
      "The five full-population status counters sum to total; page rows fit the requested page, have unique instance IDs, and never exceed their status counters.",
      "Restart-required never counts as applied.",
    ],
    examples: [
      {
        name: "unknown-instance-population",
        summary: "未建立权威实例分母时保留 null 分母，不把空页解释为全部生效",
        kind: "positive",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            publicationId: "publication-checkout-flow-1",
          },
          queryParameters: { page: 1, pageSize: 50 },
        },
        response: {
          status: 200,
          body: {
            publicationId: "publication-checkout-flow-1",
            bindingId: RULE_EXAMPLE_BINDING.id,
            page: 1,
            pageSize: 50,
            asOf: RULE_EXAMPLE_TIME.asOf,
            total: 1,
            expected: null,
            inventorySource: null,
            applied: 0,
            pending: 0,
            failed: 0,
            unknown: 1,
            restartRequired: 0,
            items: [
              {
                instanceId: "checkout-1",
                processEpoch: "process-epoch-1",
                loadedProcessEpoch: null,
                targetVersionId: RULE_EXAMPLE_VERSION.id,
                loadedVersionId: null,
                loadedChecksum: null,
                appliedAt: null,
                lastReportAt: RULE_EXAMPLE_TIME.asOf,
                state: RULE_EXAMPLE_RECEIPT_STATE,
              },
            ],
          },
        },
      },
      {
        name: "publication-not-found",
        summary: "发布不存在时不返回实例加载回执",
        kind: "negative",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            publicationId: "missing-publication",
          },
          queryParameters: { page: 1, pageSize: 50 },
        },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead(
      "readRuleActivationPlans",
      "读取服务端持久计划与调度事实",
      RULE_SET_ENDPOINTS.Plans,
    ),
    examples: [
      {
        name: "scheduled-activation",
        summary: "返回由服务端持久化并负责执行的 future activation plan",
        kind: "positive",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: {
          status: 200,
          body: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            asOf: RULE_EXAMPLE_TIME.asOf,
            items: [RULE_EXAMPLE_PLAN],
          },
        },
      },
      {
        name: "binding-not-found",
        summary: "绑定不存在时不能读取或猜测计划",
        kind: "negative",
        request: { pathParameters: { bindingId: "missing-binding" } },
        response: { status: 404, body: ruleErrorExample("not_found") },
      },
    ],
  },
  {
    ...bindingRead(
      "readRulePublicationTarget",
      "读取规则绑定的精确配置中心发布目标",
      RULE_SET_ENDPOINTS.PublicationTarget,
    ),
    examples: [
      {
        name: "configured-target",
        summary: "返回绑定的精确 Nacos 发布目标，但不暴露凭证或原始连接参数",
        kind: "positive",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: { status: 200, body: RULE_EXAMPLE_TARGET },
      },
      {
        name: "target-authority-unavailable",
        summary: "目标权威存储不可用时明确返回不可用错误",
        kind: "negative",
        request: { pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id } },
        response: { status: 503, body: ruleErrorExample("service_unavailable") },
      },
    ],
  },
  {
    ...bindingRead("mutateRuleSet", "执行一个带版本条件的规则命令", RULE_SET_ENDPOINTS.Command),
    security: "session" as const,
    requiredAccess: CONSOLE_ACCESS.AdminRulesWrite,
    input: RuleCommandRequestSchema,
    semanticRules: [
      "Requires admin and rules:write; server rechecks source/base revisions transactionally.",
      "Exactly one of save_draft/delete_draft/freeze_version/publish/create_plan/cancel_plan/configure_target is accepted.",
      "Idempotency-Key equals body requestKey. An unverifiable outcome is queried only via the original operation route, never replayed.",
      "Publication phases, instance receipt, scheduling and configuration-source effects are distinct facts.",
    ],
    examples: [
      {
        name: "save-draft-pending",
        summary: "受理保存草稿命令后返回原 requestKey 的 pending receipt",
        kind: "positive",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id },
          body: {
            requestKey: RULE_EXAMPLE_OPERATION.requestKey,
            mutation: {
              kind: RULE_MUTATION.SaveDraft,
              draftId: RULE_EXAMPLE_DRAFT.id,
              expectedRevision: RULE_EXAMPLE_PREVIOUS_DRAFT_REVISION,
              candidate: RULE_EXAMPLE_CANDIDATE,
            },
          },
        },
        response: { status: 202, body: RULE_EXAMPLE_OPERATION.pending },
      },
      {
        name: "business-rejected",
        summary: "基线/校验冲突通过已受理 operation 的 rejected 状态表达，不伪装成 HTTP 重放许可",
        kind: "negative",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id },
          body: {
            requestKey: "rule-save-draft-20261010-2",
            mutation: {
              kind: RULE_MUTATION.SaveDraft,
              draftId: RULE_EXAMPLE_DRAFT.id,
              expectedRevision: "stale-revision",
              candidate: RULE_EXAMPLE_CANDIDATE,
            },
          },
        },
        response: { status: 202, body: RULE_EXAMPLE_OPERATION.rejected },
      },
    ],
  },
  {
    ...bindingRead(
      "readRuleOperation",
      "核查当前授权主体的原始规则操作",
      RULE_SET_ENDPOINTS.Operation,
    ),
    security: "session" as const,
    requiredAccess: CONSOLE_ACCESS.Admin,
    pathParameters: [...binding, ...operationKey],
    semanticRules: [
      "Lookup is scoped to actor, current authorization, exact binding and original request key.",
      "Pending or not-found does not prove rollback and never authorizes command replay.",
    ],
    examples: [
      {
        name: "command-completed",
        summary: "按原 binding 与 requestKey 读取已完成保存草稿命令",
        kind: "positive",
        request: {
          pathParameters: {
            bindingId: RULE_EXAMPLE_BINDING.id,
            requestKey: RULE_EXAMPLE_OPERATION.requestKey,
          },
        },
        response: { status: 200, body: RULE_EXAMPLE_OPERATION.completed },
      },
      {
        name: "operation-not-found",
        summary: "not-found 只表示当前授权主体下未找到原操作，不证明副作用回滚",
        kind: "negative",
        request: {
          pathParameters: { bindingId: RULE_EXAMPLE_BINDING.id, requestKey: "unknown-request-1" },
        },
        response: {
          status: 200,
          body: {
            requestKey: "unknown-request-1",
            bindingId: RULE_EXAMPLE_BINDING.id,
            status: "not-found",
          },
        },
      },
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
