import type { BootstrapOperatorGate } from "../model/bootstrapOperator";
import type { BootstrapReadOptions } from "./bootstrapReadOptions";

/** Write-only deployment code exchange; an unknown exchange is investigated by reading the grant, never replayed automatically. */
export interface BootstrapAuthorizationPort {
  readonly readGate: (
    signal: AbortSignal,
    options?: BootstrapReadOptions,
  ) => Promise<BootstrapOperatorGate>;
  readonly authorize: (code: string, signal: AbortSignal) => Promise<void>;
  /** Request the loopback-only first-run path; remote peers are rejected. */
  readonly authorizeLocal: (signal: AbortSignal) => Promise<void>;
}
