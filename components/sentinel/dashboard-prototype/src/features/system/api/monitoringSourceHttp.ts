import { defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type { ConsoleEndpoint } from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type { ConsoleTransport } from "../../../core/api/transport/consoleEndpoint";
import type { MonitoringSourcePort } from "./monitoringSourcePort";

const IdentityPreviewSchema = z.strictObject({
  observed: z.number().int().min(0).max(10_000),
  unique: z.number().int().min(0).max(10_000),
  missing: z.number().int().min(0).max(10_000),
  conflicting: z.number().int().min(0).max(10_000),
});
const ProbeResultSchema = z.strictObject({
  connection: z.enum(["reachable", "unreachable"]),
  queryApi: z.enum(["available", "denied", "unsupported", "unknown"]),
  profile: z.enum(["supported", "missing_samples", "unsupported", "unknown"]),
  identity: IdentityPreviewSchema,
  failure: z
    .enum(["target_rejected", "authentication", "timeout", "transport", "invalid_response"])
    .nullable(),
});
export const MonitoringSourceCheckReceiptSchema = z.strictObject({
  checkId: z.string().uuid(),
  sourceId: z.string().min(1).max(200),
  sourceRevision: z.string().min(1).max(200),
  checkedAt: z.string().datetime({ offset: true }),
  expiresAt: z.string().datetime({ offset: true }),
  candidateFingerprint: z.string().regex(/^[0-9a-f]{64}$/),
  result: ProbeResultSchema,
});
const MonitoringSourceSchema = z.strictObject({
  sourceId: z.string().min(1).max(200),
  revision: z.string().min(1).max(200),
  displayName: z.string().min(1).max(200),
  environmentId: z.string().min(1).max(200),
  endpoint: z.string().url().max(2048),
  provider: z.literal("prometheus-compatible"),
  profile: z.literal("node-exporter-v1"),
  authenticationMode: z.enum(["none", "direct-basic", "direct-bearer", "credential-reference"]),
  credentialConfigured: z.boolean(),
  enabled: z.boolean(),
  identityLabels: z
    .array(
      z
        .string()
        .regex(/^[A-Za-z_][A-Za-z0-9_]*$/)
        .max(128),
    )
    .min(1)
    .max(10),
  selectorLabels: z
    .array(
      z.strictObject({
        name: z
          .string()
          .regex(/^[A-Za-z_][A-Za-z0-9_]*$/)
          .max(128),
        value: z.string().min(1).max(256),
      }),
    )
    .max(20),
  scrapeIntervalSeconds: z.number().int().min(1).max(300),
  staleAfterSeconds: z.number().int().min(2).max(3600),
});
const MonitoringSourceMutationReceiptSchema = z.strictObject({
  status: z.enum(["completed", "rejected", "not_found"]),
  requestKey: z.string().min(1).max(128),
  sourceId: z.string().min(1).max(200).optional(),
  sourceRevision: z.string().min(1).max(200).optional(),
  enabled: z.boolean().optional(),
  verified: z.boolean().optional(),
  reason: z
    .enum(["conflict", "not_found", "check_required", "check_mismatch", "source_in_use"])
    .optional(),
});
const MonitoringSourceMutationFields = {
  requestKey: z.string().min(1).max(128),
  source: MonitoringSourceSchema,
  credentials: z.union([
    z.null(),
    z.strictObject({
      username: z.string().min(1).max(4096),
      password: z.string().min(1).max(4096),
    }),
    z.strictObject({ bearerToken: z.string().min(1).max(4096) }),
    z.strictObject({ reference: z.string().min(1).max(4096) }),
  ]),
  credentialUpdate: z.enum(["keep", "replace", "clear"]),
  checkId: z.string().uuid().nullable(),
  skipCheck: z.boolean(),
};
export const MonitoringSourceMutationInputSchema = z.union([
  z.strictObject({
    kind: z.literal("set-enabled"),
    requestKey: z.string().min(1).max(128),
    sourceId: z.string().min(1).max(200),
    expectedRevision: z.string().min(1).max(200),
    enabled: z.boolean(),
  }),
  z.strictObject({ kind: z.literal("create"), ...MonitoringSourceMutationFields }),
  z.strictObject({
    kind: z.literal("update"),
    ...MonitoringSourceMutationFields,
    expectedRevision: z.string().min(1).max(200),
  }),
  z.strictObject({
    kind: z.literal("delete"),
    requestKey: z.string().min(1).max(128),
    sourceId: z.string().min(1).max(200),
    expectedRevision: z.string().min(1).max(200),
  }),
]);
const MonitoringSourceDirectoryItemSchema = z.strictObject({
  id: z.string().min(1).max(200),
  revision: z.string().min(1).max(200),
  displayName: z.string().min(1).max(200),
  environmentId: z.string().min(1).max(200),
  provider: z.literal("prometheus-compatible"),
  profile: z.literal("node-exporter-v1"),
  enabled: z.boolean(),
  authenticationMode: z.enum(["none", "direct-basic", "direct-bearer", "credential-reference"]),
  credentialConfigured: z.boolean(),
});
export const MonitoringSourcesDirectorySchema = z.strictObject({
  asOf: z.string().datetime({ offset: true }),
  items: z.array(MonitoringSourceDirectoryItemSchema).max(500),
});
export const MonitoringSourceDetailSchema = MonitoringSourceDirectoryItemSchema.extend({
  endpointOrigin: z.string().url().max(2048),
  identityLabels: z.array(z.string().min(1).max(128)).min(1).max(10),
  selectorLabels: z
    .array(z.strictObject({ name: z.string().min(1).max(128), value: z.string().min(1).max(256) }))
    .max(20),
  scrapeIntervalSeconds: z.number().int().min(1).max(300),
  staleAfterSeconds: z.number().int().min(2).max(3600),
});
export const MonitoringSourceCheckInputSchema = z.strictObject({
  source: MonitoringSourceSchema,
  credentials: z.union([
    z.null(),
    z.strictObject({
      username: z.string().min(1).max(4096),
      password: z.string().min(1).max(4096),
    }),
    z.strictObject({ bearerToken: z.string().min(1).max(4096) }),
    z.strictObject({ reference: z.string().min(1).max(256) }),
  ]),
});

export const MONITORING_SOURCE_CHECK_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof MonitoringSourceCheckReceiptSchema>
> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources/check", { method: HttpMethod.POST }),
  response: MonitoringSourceCheckReceiptSchema,
  successStatus: 200,
  command: true,
  idempotency: "none",
  csrf: true,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "csrf_failed",
    "validation_failed",
    "service_unavailable",
  ] as const,
});

export const MONITORING_SOURCE_CHECK_READ_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof MonitoringSourceCheckReceiptSchema>
> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources/checks/{checkId}"),
  response: MonitoringSourceCheckReceiptSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "not_found", "service_unavailable"] as const,
});

export const MONITORING_SOURCES_READ_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof MonitoringSourcesDirectorySchema>
> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources"),
  response: MonitoringSourcesDirectorySchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "service_unavailable"] as const,
});

export const MONITORING_SOURCE_DETAIL_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof MonitoringSourceDetailSchema>
> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources/{sourceId}"),
  response: MonitoringSourceDetailSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "not_found",
    "service_unavailable",
  ] as const,
});
export const MONITORING_SOURCE_COMMAND_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof MonitoringSourceMutationReceiptSchema>
> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources/commands", { method: HttpMethod.POST }),
  response: MonitoringSourceMutationReceiptSchema,
  successStatus: 202,
  command: true,
  idempotency: "required",
  csrf: true,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "csrf_failed",
    "idempotency_conflict",
    "validation_failed",
    "service_unavailable",
  ] as const,
});
export const MONITORING_SOURCE_OPERATION_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof MonitoringSourceMutationReceiptSchema>
> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources/operations/{requestKey}"),
  response: MonitoringSourceMutationReceiptSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "forbidden", "service_unavailable"] as const,
});

export function createMonitoringSourceHttp(transport: ConsoleTransport): MonitoringSourcePort {
  return Object.freeze({
    async readSources(signal) {
      return transport.send(MONITORING_SOURCES_READ_ENDPOINT, { signal });
    },
    async readSource(sourceId, signal) {
      return transport.send(MONITORING_SOURCE_DETAIL_ENDPOINT, {
        signal,
        pathParams: [sourceId],
      });
    },
    async checkCandidate(source, credentials, signal) {
      return transport.send(MONITORING_SOURCE_CHECK_ENDPOINT, {
        signal,
        body: parseConsoleInput(MonitoringSourceCheckInputSchema, { source, credentials }),
      });
    },
    async mutate(input, signal) {
      const body = parseConsoleInput(MonitoringSourceMutationInputSchema, input);
      return transport.send(MONITORING_SOURCE_COMMAND_ENDPOINT, {
        signal,
        body,
        requestKey: body.requestKey,
      });
    },
    async readOperation(requestKey, signal) {
      return transport.send(MONITORING_SOURCE_OPERATION_ENDPOINT, {
        signal,
        pathParams: [requestKey],
      });
    },
  } satisfies MonitoringSourcePort);
}

export const MONITORING_SOURCE_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "mutateMonitoringSource",
    summary: "创建、更新、启停或删除监控源",
    tag: "monitoring-sources",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: MONITORING_SOURCE_COMMAND_ENDPOINT,
    input: MonitoringSourceMutationInputSchema,
    pathParameters: [],
    semanticRules: [
      "Source changes, consumed candidate check and actor/session-owned idempotency receipt commit atomically.",
      "The Idempotency-Key header must equal the body requestKey.",
      "Credential material is write-only and encrypted; operation receipts never contain endpoint or credentials.",
      "Deleting a source referenced by a persisted host association is durably rejected with reason source_in_use.",
      "An explicit skipCheck is accepted but the durable result marks verified=false.",
      "Reusing a request key with different input conflicts; readback is restricted to the originating account and session.",
    ],
    examples: [],
  },
  {
    operationId: "readMonitoringSourceOperation",
    summary: "读取当前账号与会话所属的监控源操作回执",
    tag: "monitoring-sources",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: MONITORING_SOURCE_OPERATION_ENDPOINT,
    input: null,
    pathParameters: [{ name: "requestKey", schema: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/) }],
    semanticRules: [
      "Operation readback requires the exact initiating account and browser session.",
      "A missing or foreign operation is not_found; secrets and provider errors are never returned.",
    ],
    examples: [],
  },
  {
    operationId: "readMonitoringSources",
    summary: "读取监控源脱敏目录",
    tag: "monitoring-sources",
    security: "session",
    requiredAccess: { role: null, capabilities: [] },
    endpoint: MONITORING_SOURCES_READ_ENDPOINT,
    input: null,
    pathParameters: [],
    semanticRules: [
      "Directory reads are bounded and contain only safe metadata, never endpoint URLs or authentication material.",
      "A missing monitoring backend does not erase the system page; an empty directory is authoritative and normal.",
    ],
  },
  {
    operationId: "readMonitoringSource",
    summary: "读取监控源安全配置详情",
    tag: "monitoring-sources",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: MONITORING_SOURCE_DETAIL_ENDPOINT,
    input: null,
    pathParameters: [
      {
        name: "sourceId",
        description: "Stable monitoring source identity",
        schema: z.string().min(1).max(200),
      },
    ],
    semanticRules: [
      "Only administrators may read configuration details.",
      "The response contains only scheme and authority for the endpoint; path, credentials, and deployment reference values are never returned.",
    ],
  },
  {
    operationId: "checkMonitoringSource",
    summary: "校验 Prometheus 兼容监控源候选配置",
    tag: "monitoring-sources",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: MONITORING_SOURCE_CHECK_ENDPOINT,
    input: MonitoringSourceCheckInputSchema,
    pathParameters: [],
    semanticRules: [
      "The probe is read-only, bounded, and does not mutate source configuration.",
      "Only finite probe facts and a short-lived candidate fingerprint are returned; credentials and raw provider responses are never returned.",
      "Direct credentials are write-only input. Credential references are resolved by deployment-owned infrastructure and are never sent to Prometheus as the reference string.",
      "The endpoint accepts only the fixed Node Exporter V1 profile; caller-supplied PromQL is forbidden.",
    ],
    examples: [
      {
        name: "check_monitoring_source_safe_receipt",
        summary: "探测成功返回有时限、无凭证的身份统计回执",
        kind: "positive",
        request: {
          body: {
            source: {
              sourceId: "prom-primary",
              revision: "candidate-1",
              displayName: "Prometheus",
              environmentId: "production",
              endpoint: "https://prometheus.example.test",
              provider: "prometheus-compatible",
              profile: "node-exporter-v1",
              authenticationMode: "none",
              credentialConfigured: false,
              enabled: true,
              identityLabels: ["instance"],
              selectorLabels: [],
              scrapeIntervalSeconds: 15,
              staleAfterSeconds: 90,
            },
            credentials: null,
          },
        },
        response: {
          status: 200,
          body: {
            checkId: "a53e010f-f850-4b8b-8680-a4cff8d2e6e2",
            sourceId: "prom-primary",
            sourceRevision: "candidate-1",
            checkedAt: "2026-10-17T01:02:03.000Z",
            expiresAt: "2026-10-17T01:12:03.000Z",
            candidateFingerprint:
              "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            result: {
              connection: "reachable",
              queryApi: "available",
              profile: "supported",
              identity: { observed: 3, unique: 3, missing: 0, conflicting: 0 },
              failure: null,
            },
          },
        },
      },
      {
        name: "check_monitoring_source_requires_admin",
        summary: "查看者不能探测监控源或使用提交的凭证",
        kind: "negative",
        request: {
          body: {
            source: {
              sourceId: "prom-primary",
              revision: "candidate-1",
              displayName: "Prometheus",
              environmentId: "production",
              endpoint: "https://prometheus.example.test",
              provider: "prometheus-compatible",
              profile: "node-exporter-v1",
              authenticationMode: "none",
              credentialConfigured: false,
              enabled: true,
              identityLabels: ["instance"],
              selectorLabels: [],
              scrapeIntervalSeconds: 15,
              staleAfterSeconds: 90,
            },
            credentials: null,
          },
        },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "monitor-check-view" } },
        },
      },
    ],
  },
  {
    operationId: "readMonitoringSourceCheck",
    summary: "读取当前账号和会话所属的监控源探测回执",
    tag: "monitoring-sources",
    security: "session",
    requiredAccess: { role: null, capabilities: [] },
    endpoint: MONITORING_SOURCE_CHECK_READ_ENDPOINT,
    input: null,
    pathParameters: [{ name: "checkId", schema: z.string().uuid() }],
    semanticRules: [
      "A check receipt is visible only to the exact account and browser session that created it, until its ten-minute expiry.",
      "Expired, missing, or foreign-session receipts return not_found; no source credentials or endpoint are included.",
    ],
    examples: [],
  },
] as const);

export function monitoringSourceCheckPayload(value: unknown) {
  return parseConsoleInput(MonitoringSourceCheckInputSchema, value);
}
export function monitoringSourceCheckTransport(transport: ConsoleTransport) {
  return Object.freeze({
    check: (input: unknown, signal: AbortSignal) =>
      transport.send(MONITORING_SOURCE_CHECK_ENDPOINT, {
        signal,
        body: monitoringSourceCheckPayload(input),
      }),
    read: (checkId: string, signal: AbortSignal) =>
      transport.send(MONITORING_SOURCE_CHECK_READ_ENDPOINT, {
        signal,
        pathParams: [checkId],
      }),
  });
}

export function monitoringSourceCommandTransport(transport: ConsoleTransport) {
  return Object.freeze({
    mutate: (input: unknown, signal: AbortSignal) =>
      transport.send(MONITORING_SOURCE_COMMAND_ENDPOINT, {
        signal,
        body: parseConsoleInput(MonitoringSourceMutationInputSchema, input),
      }),
    readOperation: (requestKey: string, signal: AbortSignal) =>
      transport.send(MONITORING_SOURCE_OPERATION_ENDPOINT, {
        signal,
        pathParams: [requestKey],
      }),
  });
}
