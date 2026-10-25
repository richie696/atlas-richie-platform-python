import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER, parseIdempotencyKeyHeader } from "../../../core/api/protocol/common";
import { readMockPrincipal } from "../../../core/api/mock/mockRole";
import {
  MonitoringSourceCheckInputSchema,
  MonitoringSourceMutationInputSchema,
} from "../api/monitoringSourceHttp";
import type { MonitoringSourceCandidate } from "../model/monitoringSource";

type StoredSource = {
  source: MonitoringSourceCandidate;
  authenticationMode: MonitoringSourceCandidate["authenticationMode"];
  credentialConfigured: boolean;
  enabled: boolean;
  revision: string;
};
type Operation = {
  readonly status: "completed" | "rejected";
  readonly requestKey: string;
  readonly sourceId?: string;
  readonly sourceRevision?: string;
  readonly enabled?: boolean;
  readonly verified?: boolean;
  readonly reason?:
    "conflict" | "not_found" | "check_required" | "check_mismatch" | "source_in_use";
};

const csrf = "M".repeat(48);
const json = (request: Request, body: unknown, status = 200) => {
  const headers = new Headers({ "content-type": "application/json" });
  const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  headers.set(CONSOLE_HEADER.Csrf, csrf);
  return new HttpResponse(JSON.stringify(body), { status, headers });
};
const error = (request: Request, code: string, status: number) =>
  json(
    request,
    { error: { code, requestId: request.headers.get(CONSOLE_HEADER.RequestId) } },
    status,
  );
const owner = async (request: Request) => {
  const value = `${readMockPrincipal() ?? "anonymous"}\n${request.headers.get("cookie") ?? ""}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
};
const fingerprint = async (source: unknown, credentials: unknown) => {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify({ source, credentials })),
  );
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
};
const endpointOrigin = (endpoint: string) => {
  const value = new URL(endpoint);
  return value.origin;
};

/** Stateful HTTP fixtures keep the same command/readback path as live mode without storing secrets. */
export function createMonitoringSourceMockHandlers(now: () => number = Date.now) {
  const sources = new Map<string, StoredSource>();
  const receipts = new Map<
    string,
    { owner: string; sourceId: string; revision: string; fingerprint: string; expiresAt: number }
  >();
  const checkReceipts = new Map<string, { owner: string; value: Record<string, unknown> }>();
  const operations = new Map<string, { owner: string; fingerprint: string; result: Operation }>();
  const inUseSourceIds = new Set<string>();
  let revision = 0;

  const handlers = [
    http.get("*/api/v2/monitoring/sources", ({ request }) => {
      if (!readMockPrincipal()) return error(request, "unauthenticated", 401);
      return json(request, {
        asOf: new Date(now()).toISOString(),
        items: [...sources.values()].map((item) => ({
          id: item.source.sourceId,
          revision: item.revision,
          displayName: item.source.displayName,
          environmentId: item.source.environmentId,
          provider: item.source.provider,
          profile: item.source.profile,
          enabled: item.enabled,
          authenticationMode: item.authenticationMode,
          credentialConfigured: item.credentialConfigured,
        })),
      });
    }),
    http.get("*/api/v2/monitoring/sources/:sourceId", ({ request, params }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      const item = sources.get(String(params.sourceId));
      if (!item) return error(request, "not_found", 404);
      return json(request, {
        id: item.source.sourceId,
        revision: item.revision,
        displayName: item.source.displayName,
        environmentId: item.source.environmentId,
        provider: item.source.provider,
        profile: item.source.profile,
        enabled: item.enabled,
        authenticationMode: item.authenticationMode,
        credentialConfigured: item.credentialConfigured,
        endpointOrigin: endpointOrigin(item.source.endpoint),
        identityLabels: item.source.identityLabels,
        selectorLabels: item.source.selectorLabels,
        scrapeIntervalSeconds: item.source.scrapeIntervalSeconds,
        staleAfterSeconds: item.source.staleAfterSeconds,
      });
    }),
    http.post("*/api/v2/monitoring/sources/check", async ({ request }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return error(request, "csrf_failed", 403);
      const parsed = MonitoringSourceCheckInputSchema.safeParse(
        await request.json().catch(() => null),
      );
      if (!parsed.success) return error(request, "validation_failed", 422);
      const id = crypto.randomUUID();
      const ownerId = await owner(request);
      const digest = await fingerprint(parsed.data.source, parsed.data.credentials);
      const checkedAt = now();
      const receipt = {
        owner: ownerId,
        sourceId: parsed.data.source.sourceId,
        revision: parsed.data.source.revision,
        fingerprint: digest,
        expiresAt: checkedAt + 10 * 60_000,
      };
      receipts.set(id, receipt);
      const value = {
        checkId: id,
        sourceId: parsed.data.source.sourceId,
        sourceRevision: parsed.data.source.revision,
        checkedAt: new Date(checkedAt).toISOString(),
        expiresAt: new Date(checkedAt + 10 * 60_000).toISOString(),
        candidateFingerprint: digest,
        result: {
          connection: "reachable",
          queryApi: "available",
          profile: "supported",
          identity: { observed: 3, unique: 3, missing: 0, conflicting: 0 },
          failure: null,
        },
      };
      checkReceipts.set(id, { owner: ownerId, value });
      return json(request, value);
    }),
    http.get("*/api/v2/monitoring/sources/checks/:checkId", async ({ request, params }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      const receipt = checkReceipts.get(String(params.checkId));
      if (!receipt || receipt.owner !== (await owner(request)))
        return error(request, "not_found", 404);
      return json(request, receipt.value);
    }),
    http.post("*/api/v2/monitoring/sources/commands", async ({ request }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return error(request, "csrf_failed", 403);
      const parsed = MonitoringSourceMutationInputSchema.safeParse(
        await request.json().catch(() => null),
      );
      const keyHeader = parseIdempotencyKeyHeader(request.headers);
      if (!parsed.success || keyHeader.kind !== "valid")
        return error(request, "validation_failed", 422);
      if (keyHeader.requestKey !== parsed.data.requestKey)
        return error(request, "idempotency_conflict", 409);
      const ownerId = await owner(request);
      const digest = await fingerprint(parsed.data, null);
      const previous = operations.get(parsed.data.requestKey);
      if (previous) {
        if (previous.owner !== ownerId) return error(request, "forbidden", 403);
        if (previous.fingerprint !== digest) return error(request, "idempotency_conflict", 409);
        return json(request, previous.result, 202);
      }

      const input = parsed.data;
      let result: Operation;
      if (input.kind === "delete") {
        const current = sources.get(input.sourceId);
        if (!current)
          result = { status: "rejected", requestKey: input.requestKey, reason: "not_found" };
        else if (current.revision !== input.expectedRevision)
          result = { status: "rejected", requestKey: input.requestKey, reason: "conflict" };
        else if (inUseSourceIds.has(input.sourceId))
          result = {
            status: "rejected",
            requestKey: input.requestKey,
            reason: "source_in_use",
          };
        else {
          sources.delete(input.sourceId);
          result = {
            status: "completed",
            requestKey: input.requestKey,
            sourceId: input.sourceId,
            sourceRevision: current.revision,
            enabled: false,
          };
        }
      } else if (input.kind === "set-enabled") {
        const current = sources.get(input.sourceId);
        if (!current)
          result = { status: "rejected", requestKey: input.requestKey, reason: "not_found" };
        else if (current.revision !== input.expectedRevision)
          result = { status: "rejected", requestKey: input.requestKey, reason: "conflict" };
        else {
          const nextRevision = `mock-revision-${++revision}`;
          sources.set(input.sourceId, {
            ...current,
            revision: nextRevision,
            enabled: input.enabled,
            source: { ...current.source, enabled: input.enabled },
          });
          result = {
            status: "completed",
            requestKey: input.requestKey,
            sourceId: input.sourceId,
            sourceRevision: nextRevision,
            enabled: input.enabled,
          };
        }
      } else {
        const current = sources.get(input.source.sourceId);
        if (
          (input.kind === "create" && current) ||
          (input.kind === "update" && (!current || current.revision !== input.expectedRevision))
        ) {
          result = {
            status: "rejected",
            requestKey: input.requestKey,
            reason: current ? "conflict" : "not_found",
          };
        } else {
          let verified = false;
          if (input.checkId) {
            const checked = receipts.get(input.checkId);
            const candidateDigest = await fingerprint(input.source, input.credentials);
            if (
              !checked ||
              checked.owner !== ownerId ||
              checked.sourceId !== input.source.sourceId ||
              checked.revision !== input.source.revision ||
              checked.expiresAt <= now() ||
              checked.fingerprint !== candidateDigest
            ) {
              result = {
                status: "rejected",
                requestKey: input.requestKey,
                reason: "check_mismatch",
              };
            } else {
              receipts.delete(input.checkId);
              verified = true;
              result = applySource(input, current, verified);
            }
          } else if (!input.skipCheck) {
            result = { status: "rejected", requestKey: input.requestKey, reason: "check_required" };
          } else result = applySource(input, current, false);
        }
      }
      operations.set(input.requestKey, { owner: ownerId, fingerprint: digest, result });
      return json(request, result, 202);
    }),
    http.get("*/api/v2/monitoring/sources/operations/:requestKey", async ({ request, params }) => {
      if (readMockPrincipal() !== "admin") return error(request, "forbidden", 403);
      const key = String(params.requestKey);
      const operation = operations.get(key);
      if (!operation || operation.owner !== (await owner(request)))
        return json(request, { status: "not_found", requestKey: key });
      return json(request, operation.result);
    }),
  ];

  function applySource(
    input: Extract<
      ReturnType<typeof MonitoringSourceMutationInputSchema.parse>,
      { kind: "create" | "update" }
    >,
    current: StoredSource | undefined,
    verified: boolean,
  ): Operation {
    const nextRevision = `mock-revision-${++revision}`;
    const authenticationMode =
      input.credentialUpdate === "keep" && current
        ? current.authenticationMode
        : input.source.authenticationMode;
    const credentialConfigured =
      input.credentialUpdate === "keep" && current
        ? current.credentialConfigured
        : input.source.credentialConfigured;
    const enabled = input.source.enabled;
    sources.set(input.source.sourceId, {
      source: { ...input.source, revision: nextRevision },
      authenticationMode,
      credentialConfigured,
      enabled,
      revision: nextRevision,
    });
    return {
      status: "completed",
      requestKey: input.requestKey,
      sourceId: input.source.sourceId,
      sourceRevision: nextRevision,
      enabled,
      verified,
    };
  }

  return Object.freeze({
    handlers: Object.freeze(handlers),
    reset: () => {
      sources.clear();
      receipts.clear();
      checkReceipts.clear();
      operations.clear();
      inUseSourceIds.clear();
      revision = 0;
    },
    markSourceInUse: (sourceId: string) => inUseSourceIds.add(sourceId),
  });
}
