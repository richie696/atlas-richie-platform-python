import type { Url } from "@richie696/react-framework";
import type { z } from "zod";
import type { ConsoleErrorCode } from "../protocol/common";

/** Consumer-owned endpoint. Core executes this contract without importing any feature or deciding permissions. */
export interface ConsoleEndpoint<Output> {
  readonly url: Url;
  /** z.undefined() is used only for a 204 result; schema generation omits that non-JSON response. */
  readonly response: z.ZodType<Output>;
  readonly successStatus: 200 | 201 | 202 | 204;
  readonly errors: readonly ConsoleErrorCode[];
  /** An unverifiable response after dispatch must retain the original operation, not permit resubmission. */
  readonly command: boolean;
  /** Authentication uses session inspection, while managed mutations correlate an original operation by request key. */
  readonly idempotency: "required" | "none";
  readonly csrf: boolean;
  readonly expireOnUnauthorized: boolean;
  /** Pure semantic checks are explicit; generated JSON Schema never pretends to encode cross-field policy. */
  readonly accept?: (value: Output) => boolean;
}
export interface ConsoleCallOptions {
  readonly signal: AbortSignal;
  readonly pathParams?: readonly string[];
  readonly query?: Readonly<Record<string, string | number | boolean | null | undefined>>;
  readonly body?: unknown;
  readonly requestKey?: string;
}
export interface ConsoleTransport {
  readonly send: <Output>(
    endpoint: ConsoleEndpoint<Output>,
    options: ConsoleCallOptions,
  ) => Promise<Output>;
  /** Clear CSRF memory on an actual authentication owner transition, never persist it. */
  readonly clearCredentials: () => void;
  readonly dispose: () => void;
}
