import { createQueryResource, type QuerySnapshot } from "../../../shared/state/queryResource";
import type { IdentityAccessPort } from "../api/identityAccessPort";
import type { AccessFacts, ControlPlaneAccessState } from "../model/controlPlaneAccess";

/** App-owned session generation, reset on logout/identity change; never a token or stored role choice. */
export interface AccessQuery {
  readonly sessionGeneration: string;
}

/** Sequence server bootstrap before session restoration; unopened setup never requests private identity. */
export function createAccessResource(port: IdentityAccessPort) {
  return createQueryResource<AccessQuery, AccessFacts>({
    keyOf: ({ sessionGeneration }) => JSON.stringify(["control-plane-access", sessionGeneration]),
    read: async (_query, signal) => {
      const bootstrap = await port.readBootstrap(signal);
      if (!bootstrap.initialized)
        return {
          kind: "uninitialized",
          setupAvailable: bootstrap.setupAvailable,
          operatorAuthorized: bootstrap.operatorAuthorized,
        };
      signal.throwIfAborted();
      const identity = await port.readSession(signal);
      return identity ? { kind: "authenticated", identity } : { kind: "anonymous" };
    },
    classify: () => "ready",
  });
}

/** Permission freshness is stricter than chart freshness: stale/refreshing identity never grants commands. */
export function accessStateFromResource(
  snapshot: QuerySnapshot<AccessFacts>,
): ControlPlaneAccessState {
  switch (snapshot.status) {
    case "idle":
      return { phase: "unknown" };
    case "loading":
    case "refreshing":
      return { phase: "checking" };
    case "ready":
      return { phase: "resolved", facts: snapshot.data };
    case "denied":
    case "error":
    case "stale":
    case "partial":
    case "empty":
    case "filtered-empty":
      return { phase: "unavailable" };
  }
}
