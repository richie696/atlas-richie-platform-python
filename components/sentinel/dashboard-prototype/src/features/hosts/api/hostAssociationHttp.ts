import { AppError, AppErrorKind, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import { OpaqueIdentifierSchema, UtcInstantSchema } from "../../../core/api/protocol/common";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import type { ConsoleOperationContract } from "../../../core/api/protocol/operationContract";
import type {
  HostAssociation,
  HostAssociationDirectory,
  HostAssociationInput,
  HostAssociationOperation,
  HostAssociationPort,
} from "../application/hostAssociationPort";

const AssociationSchema = z.strictObject({
  sourceId: OpaqueIdentifierSchema,
  environmentId: OpaqueIdentifierSchema,
  hostId: z.string().min(1).max(512),
  appId: OpaqueIdentifierSchema,
  instanceId: OpaqueIdentifierSchema,
  processId: z.string().max(200),
  revision: z.string().uuid(),
  provenance: z.literal("operator_confirmed"),
  currentEpoch: z.string().uuid().nullable(),
  lastReceivedAt: UtcInstantSchema.nullable(),
  reporterActive: z.boolean(),
  createdAt: UtcInstantSchema,
});
const DirectorySchema = z
  .strictObject({
    environmentId: OpaqueIdentifierSchema,
    asOf: UtcInstantSchema,
    page: z.number().int().min(1).max(10_000),
    pageSize: z.number().int().min(1).max(100),
    total: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
    associatedHostIds: z.array(z.string().min(1).max(512)).max(200),
    hostIdsComplete: z.boolean(),
    items: z.array(AssociationSchema).max(100),
  })
  .superRefine((value, context) => {
    if (value.items.length > value.pageSize) {
      context.addIssue({ code: "custom", path: ["items"], message: "page size exceeded" });
    }
    if (new Set(value.associatedHostIds).size !== value.associatedHostIds.length) {
      context.addIssue({
        code: "custom",
        path: ["associatedHostIds"],
        message: "duplicate host id",
      });
    }
    if ((value.page - 1) * value.pageSize + value.items.length > value.total) {
      context.addIssue({ code: "custom", path: ["total"], message: "total contradicts page" });
    }
  });
const AssociateInputSchema = z.strictObject({
  requestKey: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
  environmentId: OpaqueIdentifierSchema,
  sourceId: OpaqueIdentifierSchema,
  hostId: z.string().min(1).max(512),
  appId: OpaqueIdentifierSchema,
  instanceId: OpaqueIdentifierSchema,
  expectedRevision: z.string().uuid().nullable(),
});
const RemoveInputSchema = z.strictObject({
  requestKey: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
  environmentId: OpaqueIdentifierSchema,
  appId: OpaqueIdentifierSchema,
  instanceId: OpaqueIdentifierSchema,
  expectedRevision: z.string().uuid(),
});
const RemovedSchema = z.strictObject({ removed: z.literal(true) });
const OperationSchema = z.discriminatedUnion("status", [
  z.strictObject({
    status: z.literal("completed"),
    requestKey: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
    result: z.union([AssociationSchema, RemovedSchema]),
  }),
  z.strictObject({
    status: z.literal("not_found"),
    requestKey: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
  }),
]);

const readEndpoint = Object.freeze({
  url: defineUrl("/api/v2/monitoring/host-associations"),
  response: DirectorySchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "forbidden", "service_unavailable"] as const,
}) satisfies ConsoleEndpoint<z.infer<typeof DirectorySchema>>;
const putEndpoint = Object.freeze({
  url: defineUrl("/api/v2/monitoring/host-associations", { method: HttpMethod.PUT }),
  response: AssociationSchema,
  successStatus: 200,
  command: true,
  idempotency: "required",
  csrf: true,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "csrf_failed",
    "validation_failed",
    "not_found",
    "conflict",
    "idempotency_conflict",
    "service_unavailable",
  ] as const,
}) satisfies ConsoleEndpoint<z.infer<typeof AssociationSchema>>;
const deleteEndpoint = Object.freeze({
  url: defineUrl("/api/v2/monitoring/host-associations", { method: HttpMethod.DELETE }),
  response: RemovedSchema,
  successStatus: 200,
  command: true,
  idempotency: "required",
  csrf: true,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "csrf_failed",
    "not_found",
    "conflict",
    "idempotency_conflict",
    "service_unavailable",
  ] as const,
}) satisfies ConsoleEndpoint<z.infer<typeof RemovedSchema>>;
const operationEndpoint = Object.freeze({
  url: defineUrl("/api/v2/monitoring/host-associations/operations/{requestKey}"),
  response: OperationSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "forbidden", "service_unavailable"] as const,
}) satisfies ConsoleEndpoint<z.infer<typeof OperationSchema>>;

/** Shared by this feature's HTTP adapter and its explicit browser-only mock projection. */
export const HOST_ASSOCIATION_WIRE_SCHEMAS = Object.freeze({
  association: AssociationSchema,
  directory: DirectorySchema,
  associateInput: AssociateInputSchema,
  removeInput: RemoveInputSchema,
  operation: OperationSchema,
});

/** Narrow API adapter for viewer reads and administrator-only association mutations. */
export function createHostAssociationHttp(transport: ConsoleTransport): HostAssociationPort {
  return Object.freeze({
    async read(
      environmentId: string,
      filters: {
        sourceId?: string;
        appId?: string;
        instanceId?: string;
        page: number;
        pageSize: number;
      },
      signal: AbortSignal,
    ) {
      const result = await transport.send(readEndpoint, {
        signal,
        query: {
          environmentId: parseConsoleInput(OpaqueIdentifierSchema, environmentId),
          ...(filters.sourceId
            ? { sourceId: parseConsoleInput(OpaqueIdentifierSchema, filters.sourceId) }
            : {}),
          ...(filters.appId
            ? { appId: parseConsoleInput(OpaqueIdentifierSchema, filters.appId) }
            : {}),
          ...(filters.instanceId
            ? { instanceId: parseConsoleInput(OpaqueIdentifierSchema, filters.instanceId) }
            : {}),
          page: parseConsoleInput(z.number().int().min(1).max(10_000), filters.page),
          pageSize: parseConsoleInput(z.number().int().min(1).max(100), filters.pageSize),
        },
      });
      if (result.environmentId !== environmentId)
        throw new AppError(AppErrorKind.PROTOCOL, "Host association scope mismatch", {
          code: "console_response_invalid",
        });
      return result;
    },
    async associate(input: HostAssociationInput, signal: AbortSignal) {
      return transport.send(putEndpoint, {
        signal,
        body: parseConsoleInput(AssociateInputSchema, input),
        requestKey: input.requestKey,
      });
    },
    async remove(input: z.input<typeof RemoveInputSchema>, signal: AbortSignal) {
      return transport.send(deleteEndpoint, {
        signal,
        body: parseConsoleInput(RemoveInputSchema, input),
        requestKey: input.requestKey,
      });
    },
    async readOperation(requestKey: string, signal: AbortSignal) {
      const key = parseConsoleInput(z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/), requestKey);
      return transport.send(operationEndpoint, { signal, pathParams: [key] });
    },
  });
}

export type {
  HostAssociation,
  HostAssociationDirectory,
  HostAssociationInput,
  HostAssociationOperation,
} from "../application/hostAssociationPort";

export const HOST_ASSOCIATION_HTTP_CONTRACT: readonly ConsoleOperationContract[] = Object.freeze([
  {
    operationId: "readHostAssociations",
    summary: "读取环境内显式配置的主机与运行实例关联",
    tag: "host-associations",
    security: "session",
    requiredAccess: { role: null, capabilities: [] },
    endpoint: readEndpoint,
    input: null,
    pathParameters: [],
    queryParameters: [
      { name: "environmentId", schema: OpaqueIdentifierSchema },
      { name: "sourceId", schema: OpaqueIdentifierSchema.optional() },
      { name: "appId", schema: OpaqueIdentifierSchema.optional() },
      { name: "instanceId", schema: OpaqueIdentifierSchema.optional() },
      { name: "page", schema: z.number().int().min(1).max(10_000).optional() },
      { name: "pageSize", schema: z.number().int().min(1).max(100).optional() },
    ],
    semanticRules: [
      "Returns one page of at most 100 worker associations, plus a bounded distinct host-id summary for host filtering; the summary is complete when hostIdsComplete is true. An exact instance filter requires appId and resolves the operator-entered app/instance target without scanning client-side pages.",
      "Only operator-managed links are returned; host/application identity is never inferred from scrape labels.",
      "A revoked or missing Reporter enrollment remains visible as reporterActive=false for audit and is not treated as a live worker.",
      "Returns live process epoch and last accepted heartbeat when known; these values are not pinned into the association.",
      "The mapping is scoped by environment and each app/instance worker has at most one associated host.",
    ],
    examples: [],
  },
  {
    operationId: "putHostAssociation",
    summary: "显式关联已观测主机与已注册运行实例",
    tag: "host-associations",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: putEndpoint,
    input: AssociateInputSchema,
    pathParameters: [],
    semanticRules: [
      "Requires an enabled monitoring source in the same environment, a currently enrolled non-revoked Reporter, and a host present in a fresh fixed-profile query.",
      "Creation/update uses exact expectedRevision compare-and-swap; reassigning requires the revision previously read by the operator.",
      "One host may be linked to multiple workers and applications.",
      "The Idempotency-Key header equals the body requestKey; replay is bound to the original account, browser session and exact command fingerprint.",
      "A successful command and its credential-free audit fact are committed atomically; operation readback is limited to the originating account and session.",
    ],
    examples: [],
  },
  {
    operationId: "deleteHostAssociation",
    summary: "解除运行实例与主机的显式关联",
    tag: "host-associations",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: deleteEndpoint,
    input: RemoveInputSchema,
    pathParameters: [],
    semanticRules: [
      "Removes only the explicit environment/app/instance mapping; host metrics remain in the source directory.",
      "The Idempotency-Key header equals the body requestKey; successful deletion is replayable and durably audited.",
    ],
    examples: [],
  },
  {
    operationId: "readHostAssociationOperation",
    summary: "读取当前管理员会话所属的主机关联操作回执",
    tag: "host-associations",
    security: "session",
    requiredAccess: { role: "admin", capabilities: [] },
    endpoint: operationEndpoint,
    input: null,
    pathParameters: [{ name: "requestKey", schema: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/) }],
    semanticRules: [
      "Operation results are visible only to the exact account and browser session that submitted them.",
      "The result contains only safe association identifiers, revision and status; it never includes Prometheus credentials or query text.",
    ],
    examples: [],
  },
]);
