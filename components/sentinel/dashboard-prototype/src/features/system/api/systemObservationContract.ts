import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { SYSTEM_OBSERVATION_ENDPOINTS } from "./systemObservationHttp";
import { AuditQueryParametersSchema } from "./systemObservationWire";

const systemObservationAsOf = "2026-10-09T01:02:03.456Z";
const connectionsExample = Object.freeze({
  asOf: systemObservationAsOf,
  items: [
    {
      id: "source-1",
      kind: "config-center",
      sourceId: "source-1",
      provider: "nacos",
      state: "available",
      checkedAt: "2026-10-09T01:02:01.456Z",
      expiresAt: "2026-10-09T01:02:33.456Z",
      latencyMs: 4.5,
      capabilities: ["read", "watch"],
      reason: null,
    },
    {
      id: "reporting-collector",
      kind: "reporting-collector",
      sourceId: null,
      provider: null,
      state: "unknown",
      checkedAt: null,
      expiresAt: null,
      latencyMs: null,
      capabilities: [],
      reason: "no-probe",
    },
  ],
});
const protocolsExample = Object.freeze({
  asOf: systemObservationAsOf,
  items: [
    {
      kind: "agent-reporting",
      supported: ["v1"],
      active: "v1",
      compatibility: "compatible",
      observedAt: "2026-10-09T01:02:02.456Z",
    },
    {
      kind: "rule-config",
      supported: [],
      active: null,
      compatibility: "unknown",
      observedAt: null,
    },
  ],
});
const auditQueryExample = Object.freeze({
  start: "2026-10-08T00:00:00.000Z",
  end: "2026-10-09T00:00:00.000Z",
  page: 1,
  pageSize: 20,
});

export const SYSTEM_OBSERVATION_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readSystemConnections",
    summary: "读取配置中心、指标后端和采集器连接探测事实",
    tag: "system-observation",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: SYSTEM_OBSERVATION_ENDPOINTS.Connections,
    input: null,
    pathParameters: [],
    semanticRules: [
      "Probe state is a server observation with an explicit expiry; it is not browser reachability.",
      "Missing categories, unconfigured sources, and expired probes are represented as partial/unknown facts, never synthesized success.",
      "No provider URL, credential, raw exception, or connection secret is returned.",
    ],
    examples: [
      {
        name: "connection_probe_includes_unknown_collector",
        summary: "配置源探测可用，同时明确未探测的 Collector 为 unknown",
        kind: "positive",
        request: {},
        response: { status: 200, body: connectionsExample },
      },
      {
        name: "connection_read_requires_session",
        summary: "匿名请求不能读取服务端连接探测事实",
        kind: "negative",
        request: {},
        response: {
          status: 401,
          body: { error: { code: "unauthenticated", requestId: "connections-anonymous" } },
        },
      },
    ],
  },
  {
    operationId: "readSystemProtocols",
    summary: "读取各协议边界的支持版本和实际协商事实",
    tag: "system-observation",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: SYSTEM_OBSERVATION_ENDPOINTS.Protocols,
    input: null,
    pathParameters: [],
    semanticRules: [
      "Supported capability is distinct from deployed active version; absent negotiation remains unknown.",
      "Missing independent protocol boundaries are partial observations, not inferred compatibility.",
    ],
    examples: [
      {
        name: "protocol_snapshot_preserves_unknown_boundary",
        summary: "报告协议实际协商为 v1，规则源协议未观测时保留 unknown",
        kind: "positive",
        request: {},
        response: { status: 200, body: protocolsExample },
      },
      {
        name: "protocol_read_requires_session",
        summary: "匿名请求不能读取部署协议协商事实",
        kind: "negative",
        request: {},
        response: {
          status: 401,
          body: { error: { code: "unauthenticated", requestId: "protocols-anonymous" } },
        },
      },
    ],
  },
  {
    operationId: "readSystemAudit",
    summary: "按操作者、操作、结果和 UTC 时间窗读取有界审计记录",
    tag: "system-observation",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: SYSTEM_OBSERVATION_ENDPOINTS.Audit,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(AuditQueryParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    semanticRules: [
      "Requires the admin role on every request.",
      "The query window is UTC and half-open; maximum span and page size are bounded by the runtime model.",
      "Audit response preserves query identity, server as-of time, stable order, and total independent of current page.",
      "A missing account actor is valid only for system-initialize, plan-activate, and plan-restore actions.",
      "No request body, secret, password, raw business log, or traceback is exposed.",
    ],
    examples: [
      {
        name: "admin_reads_bounded_audit_page",
        summary: "管理员按 UTC 半开时间窗读取安全审计事实",
        kind: "positive",
        request: { queryParameters: auditQueryExample },
        response: {
          status: 200,
          body: {
            query: {
              ...auditQueryExample,
              actorId: "",
              action: null,
              result: null,
            },
            asOf: systemObservationAsOf,
            total: 1,
            items: [
              {
                id: "event-1",
                occurredAt: "2026-10-08T12:00:00.000Z",
                actorId: "account-1",
                action: "account-create",
                targetId: "account-2",
                result: "success",
                requestId: "request-1",
                environmentId: null,
                appId: null,
                bindingId: null,
                publicationId: null,
              },
            ],
          },
        },
      },
      {
        name: "viewer_audit_access_forbidden",
        summary: "view 角色不可读取账号审计记录",
        kind: "negative",
        request: { queryParameters: auditQueryExample },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "audit-viewer-denied" } },
        },
      },
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
