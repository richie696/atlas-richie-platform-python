import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER } from "../../../core/api/protocol/common";
import { readMockPrincipal } from "../../../core/api/mock/mockRole";
import {
  SourceCheckInputSchema,
  SourceCheckResultSchema,
  SourceMutationSchema,
  SourceOperationObservationSchema,
  SourceRegistrySchema,
} from "../api/sourceRegistrationWire";
import type { z } from "zod";

type Mutation = z.infer<typeof SourceMutationSchema>;
type SafeSource = z.infer<typeof SourceRegistrySchema>["items"][number];
type ReachableCapability = Extract<
  z.infer<typeof SourceCheckResultSchema>,
  { status: "reachable" }
>["capabilities"][number];
export type SourceCheckMockScenario = {
  readonly unavailableHostname: string;
  readonly validForMs: number;
  readonly capabilities: readonly ReachableCapability[];
};
type Operation =
  | { readonly status: "completed"; readonly requestKey: string; readonly record: SafeSource }
  | {
      readonly status: "rejected";
      readonly requestKey: string;
      readonly reason: "validation" | "conflict" | "not_found" | "unavailable";
    };
interface StoredOperation {
  readonly fingerprint: string;
  readonly result: Operation;
}

interface MockState {
  readonly sources: Map<string, SafeSource>;
  readonly operations: Map<string, StoredOperation>;
  generation: number;
  sequence: number;
}

const createState = (initialSources: readonly SafeSource[]): MockState => ({
  sources: new Map(initialSources.map((source) => [source.id, Object.freeze({ ...source })])),
  operations: new Map<string, StoredOperation>(),
  generation: 1,
  sequence: 0,
});
const csrfNonce = "M".repeat(48);

const headers = (requestId: string | null, withCsrf = true) => {
  const value = new Headers({ "Content-Type": "application/json" });
  if (requestId) value.set(CONSOLE_HEADER.RequestId, requestId);
  if (withCsrf) value.set(CONSOLE_HEADER.Csrf, csrfNonce);
  return value;
};
const json = (requestId: string | null, body: unknown, status = 200) =>
  new HttpResponse(JSON.stringify(body), { status, headers: headers(requestId) });
const problem = (requestId: string | null, code: string, status: number) =>
  json(requestId, { error: { code, requestId } }, status);
const requestIdOf = (request: Request) => request.headers.get(CONSOLE_HEADER.RequestId);
const authorized = () => readMockPrincipal() === "admin";
const forbidden = (requestId: string | null) => problem(requestId, "forbidden", 403);
const instant = (milliseconds: number) => new Date(milliseconds).toISOString();

let fingerprintKey: Promise<CryptoKey> | undefined;
async function fingerprint(input: Mutation): Promise<string> {
  // Keep only an ephemeral keyed digest so replays can be compared without retaining credentials.
  fingerprintKey ??= crypto.subtle.generateKey({ name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign(
    "HMAC",
    await fingerprintKey,
    new TextEncoder().encode(JSON.stringify(input)),
  );
  return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

function safeRecord(
  input: Mutation,
  current: SafeSource | undefined,
  state: MockState,
): SafeSource {
  const source = input.source;
  const authentication = source.authentication;
  const authenticationMode =
    authentication.mode === "keep" ? current?.authenticationMode : authentication.mode;
  if (!authenticationMode) throw new Error("Cannot preserve missing source credentials");
  const credentialConfigured =
    authentication.mode === "keep"
      ? (current?.credentialConfigured ?? false)
      : authentication.mode !== "none";
  const facts = {
    id:
      input.kind === "register" ? `source-${source.provider}-${++state.sequence}` : input.sourceId,
    revision: `source-revision-${++state.generation}`,
    name: input.name.trim(),
    endpoint: source.endpoint,
    authenticationMode,
    credentialConfigured,
  };
  if (source.provider === "nacos") {
    const location = source.namespace;
    return { ...facts, provider: source.provider, namespace: location };
  }
  const location = source.datacenter;
  return { ...facts, provider: source.provider, datacenter: location };
}

async function handleMutation(request: Request, state: MockState): Promise<Response> {
  const requestId = requestIdOf(request);
  if (!authorized()) return forbidden(requestId);
  if (!request.headers.get(CONSOLE_HEADER.Csrf)) return problem(requestId, "csrf_failed", 403);
  const input = SourceMutationSchema.safeParse(await request.json().catch(() => null));
  if (
    !input.success ||
    request.headers.get(CONSOLE_HEADER.IdempotencyKey) !== input.data?.requestKey
  )
    return problem(requestId, "invalid_request", 400);

  const mutation = input.data;
  const digest = await fingerprint(mutation);
  const previous = state.operations.get(mutation.requestKey);
  if (previous)
    return previous.fingerprint === digest
      ? json(requestId, previous.result, 202)
      : problem(requestId, "idempotency_conflict", 409);

  let result: Operation;
  if (mutation.kind === "register") {
    const duplicate = [...state.sources.values()].some(
      (source) =>
        source.provider === mutation.source.provider &&
        source.endpoint === mutation.source.endpoint &&
        (mutation.source.provider === "nacos"
          ? source.provider === "nacos" && source.namespace === mutation.source.namespace
          : source.provider === "consul" && source.datacenter === mutation.source.datacenter),
    );
    if (duplicate)
      result = { status: "rejected", requestKey: mutation.requestKey, reason: "conflict" };
    else {
      const record = safeRecord(mutation, undefined, state);
      state.sources.set(record.id, record);
      result = { status: "completed", requestKey: mutation.requestKey, record };
    }
  } else {
    const current = state.sources.get(mutation.sourceId);
    if (!current)
      result = { status: "rejected", requestKey: mutation.requestKey, reason: "not_found" };
    else if (
      current.revision !== mutation.expectedRevision ||
      current.provider !== mutation.source.provider
    )
      result = { status: "rejected", requestKey: mutation.requestKey, reason: "conflict" };
    else {
      const record = safeRecord(mutation, current, state);
      state.sources.set(record.id, record);
      result = { status: "completed", requestKey: mutation.requestKey, record };
    }
  }
  state.operations.set(mutation.requestKey, { fingerprint: digest, result });
  const validated = SourceOperationObservationSchema.safeParse(result);
  return validated.success
    ? json(requestId, validated.data, 202)
    : problem(requestId, "dependency_unavailable", 503);
}

/** Create synthetic HTTP handlers with isolated mutable state and an explicit source seed. */
export function createSourceRegistrationMockHandlers(
  initialSources: readonly SafeSource[],
  checkScenario: SourceCheckMockScenario,
  now: () => number = Date.now,
) {
  let state = createState(initialSources);
  const handlers = Object.freeze([
    http.get("*/api/v1/system/sources", ({ request }) => {
      const requestId = requestIdOf(request);
      if (!authorized()) return forbidden(requestId);
      const result = SourceRegistrySchema.safeParse({
        asOf: instant(now()),
        items: [...state.sources.values()],
      });
      return result.success
        ? json(requestId, result.data)
        : problem(requestId, "dependency_unavailable", 503);
    }),
    http.post("*/api/v1/system/sources/check", async ({ request }) => {
      const requestId = requestIdOf(request);
      if (!authorized()) return forbidden(requestId);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return problem(requestId, "csrf_failed", 403);
      const parsed = SourceCheckInputSchema.safeParse(await request.json().catch(() => null));
      if (!parsed.success) return problem(requestId, "invalid_request", 400);

      // This is synthetic demo data, never a network probe or a provider health claim.
      const checkedAt = now();
      const result =
        new URL(parsed.data.source.endpoint).hostname === checkScenario.unavailableHostname
          ? {
              status: "unreachable" as const,
              checkedAt: instant(checkedAt),
              expiresAt: instant(checkedAt + checkScenario.validForMs),
              reason: "connection" as const,
            }
          : {
              status: "reachable" as const,
              checkedAt: instant(checkedAt),
              expiresAt: instant(checkedAt + checkScenario.validForMs),
              capabilities: checkScenario.capabilities,
            };
      return json(requestId, result);
    }),
    http.post("*/api/v1/system/sources/commands", ({ request }) => handleMutation(request, state)),
    http.get("*/api/v1/system/sources/operations/:requestKey", ({ request, params }) => {
      const requestId = requestIdOf(request);
      if (!authorized()) return forbidden(requestId);
      const requestKey = String(params.requestKey);
      const result = state.operations.get(requestKey)?.result ?? {
        status: "not_found" as const,
        requestKey,
      };
      const parsed = SourceOperationObservationSchema.safeParse(result);
      return parsed.success
        ? json(requestId, parsed.data)
        : problem(requestId, "dependency_unavailable", 503);
    }),
  ]);
  return Object.freeze({
    handlers,
    /** Current non-secret registry facts let sibling demo handlers share this single authority. */
    readRegisteredSources: () => Object.freeze([...state.sources.values()]),
    reset: () => {
      state = createState(initialSources);
    },
  });
}
