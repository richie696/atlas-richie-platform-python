import type {
  AuthenticationWorkflow,
  BootstrapAuthorizationPort,
  BootstrapReadOptions,
  InitializationPort,
} from "../../features/identity";
import { bootstrapFactFromAccess, bootstrapOperatorGateFromAccess } from "../../features/identity";

/**
 * Compose setup readers from the app's single authentication/bootstrap owner.
 * Setup workflows receive feature-shaped projections, but never create another
 * reader for the authoritative `/system/bootstrap` fact.
 */
export function createSetupIdentityPorts(
  authentication: Pick<AuthenticationWorkflow, "getSnapshot" | "restore">,
  authorization: BootstrapAuthorizationPort,
  initialization: InitializationPort,
): Readonly<{
  authorization: BootstrapAuthorizationPort;
  initialization: InitializationPort;
}> {
  const readAccess = async (signal: AbortSignal, options?: BootstrapReadOptions) => {
    signal.throwIfAborted();
    const current = authentication.getSnapshot().access;
    const access =
      current.phase === "resolved" && !options?.forceRefresh
        ? current.facts
        : await authentication.restore();
    signal.throwIfAborted();
    return access;
  };
  return Object.freeze({
    authorization: Object.freeze({
      ...authorization,
      readGate: async (signal: AbortSignal, options?: BootstrapReadOptions) =>
        bootstrapOperatorGateFromAccess(await readAccess(signal, options)),
    }),
    initialization: Object.freeze({
      ...initialization,
      readBootstrap: async (signal: AbortSignal, options?: BootstrapReadOptions) =>
        bootstrapFactFromAccess(await readAccess(signal, options)),
    }),
  });
}
