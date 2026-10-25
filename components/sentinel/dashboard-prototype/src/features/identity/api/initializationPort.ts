import type { BootstrapFact } from "../model/controlPlaneAccess";
import type { BootstrapReadOptions } from "./bootstrapReadOptions";
import type {
  SetupSourceInput,
  SetupStorageInput,
  SetupSubmission,
} from "../model/setupSubmission";

/** Redacted connectivity fact, not a persisted configuration or permission to initialize. */
export type ConnectionCheck =
  | { readonly status: "reachable" }
  | {
      readonly status: "unreachable";
      readonly reason: "authentication" | "connection" | "unsupported";
    };

/** Internal operation correlation, NOT an authentication token or a frozen HTTP envelope. */
export type InitializationObservation =
  | { readonly status: "not-found"; readonly requestKey: string }
  | {
      readonly status: "pending" | "completed";
      readonly requestKey: string;
      readonly operationId: string;
    }
  | {
      readonly status: "rejected";
      readonly requestKey: string;
      readonly operationId: string;
      readonly reason: "validation" | "setup-closed" | "dependency";
    };

/**
 * Consumer-owned setup boundary. Connectivity checks have no persistent side effects.
 * Initialization must be server-idempotent by requestKey; lookup must authenticate
 * the bootstrap operator in F6/B0, not rely on knowledge of this key alone.
 * Responses/errors must exclude credentials, raw provider messages and stack traces.
 */
export interface InitializationPort {
  readonly readBootstrap: (
    signal: AbortSignal,
    options?: BootstrapReadOptions,
  ) => Promise<BootstrapFact>;
  readonly checkDatabase: (
    input: SetupStorageInput,
    signal: AbortSignal,
  ) => Promise<ConnectionCheck>;
  readonly checkSource: (input: SetupSourceInput, signal: AbortSignal) => Promise<ConnectionCheck>;
  readonly initialize: (
    request: { readonly requestKey: string; readonly input: SetupSubmission },
    signal: AbortSignal,
  ) => Promise<InitializationObservation>;
  /** Absence may be caused by visibility lag; not-found is never proof of rollback. */
  readonly readInitialization: (
    requestKey: string,
    signal: AbortSignal,
  ) => Promise<InitializationObservation>;
}
