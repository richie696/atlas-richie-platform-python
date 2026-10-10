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
  const createAccessReader = () => {
    const current = authentication.getSnapshot().access;
    const confirmedFacts = current.phase === "resolved" ? current.facts : undefined;
    return async (signal: AbortSignal, options?: BootstrapReadOptions) => {
      signal.throwIfAborted();
      const access =
        confirmedFacts && !options?.forceRefresh ? confirmedFacts : await authentication.restore();
      signal.throwIfAborted();
      return access;
    };
  };
  const readGateAccess = createAccessReader();
  const readInitializationAccess = createAccessReader();
  return Object.freeze({
    authorization: Object.freeze({
      ...authorization,
      readGate: async (signal: AbortSignal, options?: BootstrapReadOptions) =>
        bootstrapOperatorGateFromAccess(await readGateAccess(signal, options)),
    }),
    initialization: Object.freeze({
      ...initialization,
      readBootstrap: async (signal: AbortSignal, options?: BootstrapReadOptions) =>
        bootstrapFactFromAccess(await readInitializationAccess(signal, options)),
    }),
  });
}
