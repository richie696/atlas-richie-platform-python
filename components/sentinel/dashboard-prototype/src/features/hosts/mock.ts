import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER, parseIdempotencyKeyHeader } from "../../core/api/protocol/common";
import { readMockPrincipal } from "../../core/api/mock/mockRole";
import { HOST_ASSOCIATION_WIRE_SCHEMAS } from "./api/hostAssociationHttp";

type Association = ReturnType<typeof HOST_ASSOCIATION_WIRE_SCHEMAS.association.parse>;
type MutationResult = Association | { readonly removed: true };

const BASE_PATH = "*/api/v2/monitoring/host-associations";
const CSRF = "M".repeat(48);

function response(request: Request, body: unknown, status = 200) {
  const headers = new Headers({ "content-type": "application/json" });
  const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  headers.set(CONSOLE_HEADER.Csrf, CSRF);
  return new HttpResponse(JSON.stringify(body), { status, headers });
}

function error(request: Request, code: string, status: number) {
  return response(
    request,
    { error: { code, requestId: request.headers.get(CONSOLE_HEADER.RequestId) } },
    status,
  );
}

async function sessionOwner(request: Request): Promise<string> {
  const identity = `${readMockPrincipal() ?? "anonymous"}\n${request.headers.get("cookie") ?? ""}`;
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function commandFingerprint(value: unknown): Promise<string> {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(value)),
  );
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Stateful synthetic projection for explicit Mock mode; it makes no runtime-observation claim. */
export function createHostAssociationMockHandlers(now: () => number = Date.now) {
  const associations = new Map<string, Association>();
  const operations = new Map<
    string,
    { readonly owner: string; readonly fingerprint: string; readonly result: MutationResult }
  >();
  const associationKey = (environmentId: string, appId: string, instanceId: string) =>
    `${environmentId}\n${appId}\n${instanceId}`;
  const operationKey = (owner: string, requestKey: string) => `${owner}\n${requestKey}`;

  const handlers = [
    http.get(BASE_PATH, ({ request }) => {
      if (!readMockPrincipal()) return error(request, "unauthenticated", 401);
      const query = new URL(request.url).searchParams;
      const environmentId = query.get("environmentId");
      const pageValue = query.get("page") ?? "1";
      const pageSizeValue = query.get("pageSize") ?? "25";
      if (
        !environmentId ||
        !/^[1-9]\d*$/.test(pageValue) ||
        !/^[1-9]\d*$/.test(pageSizeValue) ||
        Number(pageSizeValue) > 100
      )
        return error(request, "invalid_request", 400);
      const page = Number(pageValue);
      const pageSize = Number(pageSizeValue);
      const filtered = [...associations.values()].filter(
        (item) =>
          item.environmentId === environmentId &&
          (!query.has("sourceId") || item.sourceId === query.get("sourceId")) &&
          (!query.has("appId") || item.appId === query.get("appId")) &&
          (!query.has("instanceId") || item.instanceId === query.get("instanceId")),
      );
      const directory = HOST_ASSOCIATION_WIRE_SCHEMAS.directory.parse({
        environmentId,
        asOf: new Date(now()).toISOString(),
        page,
        pageSize,
        total: filtered.length,
        associatedHostIds: [...new Set(filtered.map((item) => item.hostId))].slice(0, 200),
        hostIdsComplete: true,
        items: filtered.slice((page - 1) * pageSize, page * pageSize),
      });
      return response(request, directory);
    }),
    http.put(BASE_PATH, async ({ request }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return error(request, "csrf_failed", 403);
      const input = HOST_ASSOCIATION_WIRE_SCHEMAS.associateInput.safeParse(
        await request.json().catch(() => null),
      );
      const headerKey = parseIdempotencyKeyHeader(request.headers);
      if (!input.success || headerKey.kind !== "valid")
        return error(request, "validation_failed", 422);
      if (headerKey.requestKey !== input.data.requestKey)
        return error(request, "idempotency_conflict", 409);
      const owner = await sessionOwner(request);
      const digest = await commandFingerprint(input.data);
      const id = operationKey(owner, input.data.requestKey);
      const previous = operations.get(id);
      if (previous) {
        if (previous.fingerprint !== digest) return error(request, "idempotency_conflict", 409);
        if (!("sourceId" in previous.result)) return error(request, "idempotency_conflict", 409);
        return response(request, previous.result);
      }
      const key = associationKey(input.data.environmentId, input.data.appId, input.data.instanceId);
      const current = associations.get(key);
      if (
        (input.data.expectedRevision === null && current) ||
        (input.data.expectedRevision !== null &&
          (!current || current.revision !== input.data.expectedRevision))
      )
        return error(request, "conflict", 409);
      const value = HOST_ASSOCIATION_WIRE_SCHEMAS.association.parse({
        sourceId: input.data.sourceId,
        environmentId: input.data.environmentId,
        hostId: input.data.hostId,
        appId: input.data.appId,
        instanceId: input.data.instanceId,
        processId: `mock-process-${input.data.instanceId}`,
        revision: crypto.randomUUID(),
        provenance: "operator_confirmed",
        currentEpoch: null,
        lastReceivedAt: null,
        reporterActive: false,
        createdAt: new Date(now()).toISOString(),
      });
      associations.set(key, value);
      operations.set(id, { owner, fingerprint: digest, result: value });
      return response(request, value);
    }),
    http.delete(BASE_PATH, async ({ request }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return error(request, "csrf_failed", 403);
      const input = HOST_ASSOCIATION_WIRE_SCHEMAS.removeInput.safeParse(
        await request.json().catch(() => null),
      );
      const headerKey = parseIdempotencyKeyHeader(request.headers);
      if (!input.success || headerKey.kind !== "valid")
        return error(request, "validation_failed", 422);
      if (headerKey.requestKey !== input.data.requestKey)
        return error(request, "idempotency_conflict", 409);
      const owner = await sessionOwner(request);
      const digest = await commandFingerprint(input.data);
      const id = operationKey(owner, input.data.requestKey);
      const previous = operations.get(id);
      if (previous) {
        if (previous.fingerprint !== digest) return error(request, "idempotency_conflict", 409);
        if ("sourceId" in previous.result) return error(request, "idempotency_conflict", 409);
        return response(request, previous.result);
      }
      const key = associationKey(input.data.environmentId, input.data.appId, input.data.instanceId);
      const current = associations.get(key);
      if (!current || current.revision !== input.data.expectedRevision)
        return error(request, current ? "conflict" : "not_found", current ? 409 : 404);
      associations.delete(key);
      const value = { removed: true as const };
      operations.set(id, { owner, fingerprint: digest, result: value });
      return response(request, value);
    }),
    http.get(`${BASE_PATH}/operations/:requestKey`, async ({ request, params }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      const requestKey = String(params.requestKey);
      const owner = await sessionOwner(request);
      const operation = operations.get(operationKey(owner, requestKey));
      const value = operation
        ? { status: "completed" as const, requestKey, result: operation.result }
        : { status: "not_found" as const, requestKey };
      return response(request, HOST_ASSOCIATION_WIRE_SCHEMAS.operation.parse(value));
    }),
  ];

  return Object.freeze({
    handlers: Object.freeze(handlers),
    reset: () => {
      associations.clear();
      operations.clear();
    },
  });
}
