import { AppError, AppErrorKind, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import { OpaqueIdentifierSchema, UtcInstantSchema } from "../../../core/api/protocol/common";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { ObservationStepSchema } from "../../../shared/api/observationWire";

const MAX_HOSTS = 200;
const MAX_POINTS = 1_000;
const HostMetricsQuerySchema = z.strictObject({
  from: UtcInstantSchema,
  to: UtcInstantSchema,
  stepMs: ObservationStepSchema,
});
const HostMetricKindSchema = z.enum([
  "host_cpu_busy_ratio",
  "host_memory_used_bytes",
  "host_memory_used_ratio",
  "host_load_1m",
]);
const HostMetricReasonSchema = z.enum([
  "source_disabled",
  "target_rejected",
  "authentication",
  "timeout",
  "transport",
  "invalid_response",
  "missing_samples",
  "stale_samples",
  "duplicate_series",
  "conflicting_identity",
]);
const HostMetricQualitySchema = z.enum([
  "available",
  "partial",
  "stale",
  "no_samples",
  "not_integrated",
  "unavailable",
]);
const MetricUnitSchema = z.enum(["ratio", "bytes", "tasks"]);
const HostMetricsSnapshotSchema = z.strictObject({
  sourceId: OpaqueIdentifierSchema,
  environmentId: OpaqueIdentifierSchema,
  query: z.strictObject(HostMetricsQuerySchema.shape),
  asOf: UtcInstantSchema,
  quality: HostMetricQualitySchema,
  reason: HostMetricReasonSchema.nullable(),
  hosts: z
    .array(
      z.strictObject({
        hostId: z.string().min(1).max(512),
        identity: z
          .array(
            z.strictObject({ name: z.string().min(1).max(128), value: z.string().min(1).max(256) }),
          )
          .min(1)
          .max(10),
        metrics: z
          .array(
            z.strictObject({
              metric: HostMetricKindSchema,
              unit: MetricUnitSchema,
              quality: HostMetricQualitySchema,
              reason: HostMetricReasonSchema.nullable(),
              samples: z
                .array(z.strictObject({ at: UtcInstantSchema, value: z.number().finite() }))
                .max(MAX_POINTS),
            }),
          )
          .length(4),
      }),
    )
    .max(MAX_HOSTS),
});

export type HostMetricsQuery = z.infer<typeof HostMetricsQuerySchema>;
export type HostMetricsSnapshot = z.infer<typeof HostMetricsSnapshotSchema>;

export const HOST_METRICS_ENDPOINT: ConsoleEndpoint<HostMetricsSnapshot> = Object.freeze({
  url: defineUrl("/api/v2/monitoring/sources/{sourceId}/host-metrics", { method: HttpMethod.GET }),
  response: HostMetricsSnapshotSchema,
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

export const HostMetricsParametersSchema = HostMetricsQuerySchema;

/** Read fixed-profile host samples from a previously registered source; no URL or PromQL crosses this boundary. */
export function createHostMetricsHttp(transport: ConsoleTransport) {
  return Object.freeze({
    async read(sourceId: string, query: HostMetricsQuery, signal: AbortSignal) {
      const request = parseConsoleInput(HostMetricsParametersSchema, query);
      const durationMs = Date.parse(request.to) - Date.parse(request.from);
      const count = Math.floor((durationMs - 1) / request.stepMs) + 1;
      if (durationMs < 1 || count > MAX_POINTS) {
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid host metrics query", {
          status: 400,
          code: "console_request_invalid",
        });
      }
      const value = await transport.send(HOST_METRICS_ENDPOINT, {
        signal,
        pathParams: [parseConsoleInput(OpaqueIdentifierSchema, sourceId)],
        query: request,
      });
      if (!matchesHostMetricsQuery(value, sourceId, request)) {
        throw new AppError(
          AppErrorKind.PROTOCOL,
          "Host metrics response does not match the requested source and window",
          { code: "console_response_invalid" },
        );
      }
      return value;
    },
  });
}

function matchesHostMetricsQuery(
  value: HostMetricsSnapshot,
  sourceId: string,
  query: HostMetricsQuery,
): boolean {
  if (
    value.sourceId !== sourceId ||
    value.query.from !== query.from ||
    value.query.to !== query.to ||
    value.query.stepMs !== query.stepMs
  )
    return false;
  const from = Date.parse(query.from);
  const to = Date.parse(query.to);
  const hostIds = new Set<string>();
  for (const host of value.hosts) {
    if (hostIds.has(host.hostId)) return false;
    hostIds.add(host.hostId);
    const identityKeys = new Set(host.identity.map(({ name }) => name));
    if (identityKeys.size !== host.identity.length) return false;
    const metrics = new Set(host.metrics.map(({ metric }) => metric));
    if (metrics.size !== 4) return false;
    for (const metric of host.metrics) {
      let previous = Number.NEGATIVE_INFINITY;
      for (const sample of metric.samples) {
        const at = Date.parse(sample.at);
        if (at < from || at >= to || at <= previous) return false;
        previous = at;
      }
    }
  }
  return true;
}

export const HOST_METRICS_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readHostMetrics",
    summary: "查询固定 node-exporter-v1 主机指标",
    tag: "host-metrics",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: HOST_METRICS_ENDPOINT,
    input: null,
    pathParameters: [{ name: "sourceId", schema: OpaqueIdentifierSchema }],
    queryParameters: Object.entries(HostMetricsParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    semanticRules: [
      "Reads only a previously persisted, enabled monitoring source; clients cannot supply an endpoint, credentials, label selector or PromQL.",
      "The request is a UTC half-open [from,to) interval and at most 1000 aligned points per series; provider evaluation end is inclusive and must remain below to.",
      "The response contains at most 200 stable host identities and exactly the four declared host metrics; missing values remain gaps, never zero-filled.",
      "Metric quality/reason distinguishes available, partial, stale, no_samples, not_integrated and unavailable; provider text and non-identity labels are never returned.",
      "HOST scope is independent from PROCESS Metrics V2 and never supplies process QPS/TPS or process resource values.",
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
