import {
  AppError,
  AppErrorKind,
  HttpClient,
  HttpMethod,
  MemoryStorage,
} from "@richie696/react-framework";
import {
  ConsoleErrorSchema,
  CONSOLE_ERROR_STATUS,
  CONSOLE_HEADER,
  CsrfNonceSchema,
  RateLimitedConsoleErrorSchema,
  RequestKeySchema,
} from "../protocol/common";
import type { ConsoleCallOptions, ConsoleEndpoint, ConsoleTransport } from "./consoleEndpoint";
import { boundedResponse, withinJsonDepth } from "./boundedResponse";

const CSRF_HEADER = CONSOLE_HEADER.Csrf;
const CORRELATION_HEADER = CONSOLE_HEADER.RequestId;
const LEGACY_HEADERS = [
  "x-user-id",
  "x-device-id",
  "x-client-id",
  "x-client-timestamp",
  "x-gateway-protocol-version",
  "authorization",
] as const;
const isConsoleApiPath = (path: string) => /^\/api\/v[12]\//.test(path);
const validCsrf = (value: string) => CsrfNonceSchema.safeParse(value).success;
interface RequestObservation {
  readonly owner: string;
  readonly command: boolean;
  readonly expireOnUnauthorized: boolean;
  status?: number;
  csrf?: string;
  dispatched: boolean;
  unauthorizedHandled: boolean;
}
export interface ConsoleTransportOptions {
  readonly baseUrl: string;
  readonly fetch?: typeof fetch;
  readonly owner: () => string;
  readonly onUnauthorized: () => void;
  readonly requestId?: () => string;
  readonly timeoutMs?: number;
}
const failure = (command: boolean) =>
  new AppError(
    command ? AppErrorKind.SERVER : AppErrorKind.PROTOCOL,
    "Console response could not be verified",
    { status: command ? 502 : undefined, code: "console_response_invalid" },
  );

/**
 * One foundation HTTP client for mock/live. This adapter owns protocol validation and ephemeral CSRF,
 * not business state, retries, a second client, global fetch replacement or fixture dispatch.
 */
export function createConsoleTransport(options: ConsoleTransportOptions): ConsoleTransport {
  const base = new URL(options.baseUrl);
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.search ||
    base.hash ||
    base.pathname !== "/"
  )
    throw new Error("Invalid Console API origin");
  const requests = new Map<string, RequestObservation>();
  const lifetime = new AbortController();
  const fetcher = options.fetch ?? globalThis.fetch;
  const makeRequestId = options.requestId ?? (() => crypto.randomUUID());
  const timeoutMs = options.timeoutMs ?? 10_000;
  let csrf: { owner: string; value: string } | null = null,
    disposed = false;
  const handleUnauthorized = (observation: RequestObservation | undefined) => {
    if (!observation || observation.unauthorizedHandled) return;
    observation.unauthorizedHandled = true;
    if (observation.expireOnUnauthorized && observation.owner === options.owner() && !disposed) {
      csrf = null;
      options.onUnauthorized();
    }
  };
  const client = new HttpClient({
    baseUrl: base.origin,
    fetch: async (input, init) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const ticket = request.headers.get(CORRELATION_HEADER),
        observation = ticket ? requests.get(ticket) : undefined;
      if (!observation || observation.owner !== options.owner() || disposed)
        throw new AppError(AppErrorKind.CANCELLED, "Console owner changed before dispatch");
      observation.dispatched = true;
      const response = await fetchUntilAborted(fetcher, request, timeoutMs);
      observation.status = response.status;
      // Authentication validity is an HTTP fact even when its rejection DTO is malformed.
      if (response.status === 401) handleUnauthorized(observation);
      try {
        const returnedId = response.headers.get(CORRELATION_HEADER);
        if (returnedId !== ticket) throw new Error("Console correlation mismatch");
        const nextCsrf = response.headers.get(CSRF_HEADER);
        if (nextCsrf !== null && !validCsrf(nextCsrf))
          throw new Error("Invalid Console CSRF header");
        observation.csrf = nextCsrf ?? undefined;
        return await boundedResponse(response, request.signal);
      } catch {
        void response.body?.cancel().catch(() => {});
        throw failure(observation.command);
      }
    },
    timeoutMs,
    maxRetries: 0,
    enableHeaderAutoManagement: false,
    persistManagedHeaders: false,
    sendHardwareFingerprint: false,
    storage: new MemoryStorage(),
    requestInterceptors: [
      (request) => {
        const resolved = new URL(request.url);
        if (resolved.origin !== base.origin || !isConsoleApiPath(resolved.pathname))
          throw new AppError(AppErrorKind.PROTOCOL, "Console endpoint escaped its API origin");
        const headers = new Headers(request.headers);
        for (const name of LEGACY_HEADERS) headers.delete(name);
        return new Request(request, { headers });
      },
    ],
    onUnauthorized: (ticket) => {
      const observation = ticket ? requests.get(ticket) : undefined;
      handleUnauthorized(observation);
    },
  });
  return Object.freeze({
    async send<Output>(
      endpoint: ConsoleEndpoint<Output>,
      call: ConsoleCallOptions,
    ): Promise<Output> {
      if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Console transport disposed");
      const owner = options.owner(),
        ticket = makeRequestId();
      if (!RequestKeySchema.safeParse(ticket).success || requests.has(ticket))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid Console request correlation");
      if (
        !isConsoleApiPath(endpoint.url.path) ||
        endpoint.url.path.includes("?") ||
        endpoint.url.path.includes("#") ||
        endpoint.url.needEncryption ||
        endpoint.url.needDuplicateCheck ||
        (endpoint.command &&
          ![HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE].includes(
            endpoint.url.method,
          ))
      )
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid Console endpoint");
      if ((call.pathParams ?? []).some((value) => value === "." || value === ".."))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid Console path identity");
      if (
        endpoint.idempotency === "required" &&
        (!call.requestKey || !RequestKeySchema.safeParse(call.requestKey).success)
      )
        throw new AppError(AppErrorKind.PROTOCOL, "Console command requires a valid request key");
      if (endpoint.idempotency === "none" && call.requestKey !== undefined)
        throw new AppError(AppErrorKind.PROTOCOL, "Unexpected Console idempotency key");
      if (endpoint.csrf && (!csrf || csrf.owner !== owner))
        throw new AppError(AppErrorKind.FORBIDDEN, "Console CSRF authorization required", {
          code: "csrf_failed",
          status: 403,
        });
      const observation: RequestObservation = {
        owner,
        command: endpoint.command,
        expireOnUnauthorized: endpoint.expireOnUnauthorized,
        dispatched: false,
        unauthorizedHandled: false,
      };
      requests.set(ticket, observation);
      try {
        const result = await client.requestData<unknown>(endpoint.url, call.body, {
          signal: AbortSignal.any([call.signal, lifetime.signal]),
          pathParams: call.pathParams,
          query: call.query,
          credentials: "include",
          cache: "no-store",
          redirect: "error",
          timeoutMs,
          parseEnvelope: false,
          requestId: ticket,
          idempotencyKey: call.requestKey,
          headers: {
            accept: "application/json",
            ...(endpoint.csrf && csrf ? { [CSRF_HEADER]: csrf.value } : {}),
          },
        });
        if (disposed || observation.owner !== options.owner() || call.signal.aborted)
          throw new AppError(AppErrorKind.CANCELLED, "Console response owner expired");
        if (observation.status !== endpoint.successStatus || !withinJsonDepth(result))
          throw failure(endpoint.command);
        if (endpoint.successStatus === 204 && result !== undefined) throw failure(endpoint.command);
        const parsed = endpoint.response.safeParse(result);
        if (!parsed.success || (endpoint.accept && !endpoint.accept(parsed.data)))
          throw failure(endpoint.command);
        if (endpoint.successStatus === 204) csrf = null;
        else if (observation.csrf) csrf = { owner, value: observation.csrf };
        return parsed.data;
      } catch (cause) {
        if (cause instanceof AppError && cause.code === "console_response_invalid") throw cause;
        if (
          cause instanceof AppError &&
          [AppErrorKind.NETWORK, AppErrorKind.TIMEOUT, AppErrorKind.CANCELLED].includes(cause.kind)
        )
          throw new AppError(cause.kind, "Console transport unavailable");
        if (cause instanceof AppError && cause.status !== undefined) {
          const errorSchema =
            cause.status === CONSOLE_ERROR_STATUS.rate_limited
              ? RateLimitedConsoleErrorSchema
              : ConsoleErrorSchema;
          const parsed = errorSchema.safeParse(cause.responseBody);
          if (
            parsed.success &&
            parsed.data.error.requestId === ticket &&
            CONSOLE_ERROR_STATUS[parsed.data.error.code] === cause.status &&
            endpoint.errors.includes(parsed.data.error.code)
          ) {
            const error = parsed.data.error;
            throw new AppError(cause.kind, "Console request rejected", {
              status: cause.status,
              code: error.code,
              requestId: error.requestId,
              retryAfterMs: error.retryAfterMs,
            });
          }
        }
        throw failure(observation.dispatched && endpoint.command);
      } finally {
        requests.delete(ticket);
      }
    },
    clearCredentials() {
      csrf = null;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      lifetime.abort();
      csrf = null;
      client.cleanup();
    },
  });
}

/**
 * Keep the transport bounded even when an injected Fetch implementation ignores its signal.
 * The late response is discarded and its body cancelled; dispatched commands remain unknown.
 */
function fetchUntilAborted(
  fetcher: typeof fetch,
  request: Request,
  timeoutMs: number,
): Promise<Response> {
  const deadline = new AbortController();
  const timeout = setTimeout(() => deadline.abort(), timeoutMs);
  const signal = AbortSignal.any([request.signal, deadline.signal]);
  const boundedRequest = new Request(request, { signal });
  if (signal.aborted) {
    clearTimeout(timeout);
    return Promise.reject(signal.reason);
  }

  return new Promise<Response>((resolve, reject) => {
    const removeAbortListener = () => signal.removeEventListener("abort", onAbort);
    const onAbort = () => {
      removeAbortListener();
      reject(
        deadline.signal.aborted
          ? new AppError(AppErrorKind.TIMEOUT, "Console request deadline exceeded")
          : signal.reason,
      );
    };
    signal.addEventListener("abort", onAbort, { once: true });

    Promise.resolve()
      .then(() => fetcher(boundedRequest))
      .then(
        (response) => {
          removeAbortListener();
          if (signal.aborted) {
            void response.body?.cancel().catch(() => {});
            reject(signal.reason);
            return;
          }
          resolve(response);
        },
        (error: unknown) => {
          removeAbortListener();
          reject(error);
        },
      );
  }).finally(() => clearTimeout(timeout));
}
