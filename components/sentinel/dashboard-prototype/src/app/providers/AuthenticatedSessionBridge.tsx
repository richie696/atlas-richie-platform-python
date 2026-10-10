import { useMemo, type ReactNode } from "react";
import { SessionProvider, type Session } from "../../core/session";
import { useAuthentication } from "../../features/identity/authentication";

/**
 * Projects one resolved Console identity into the legacy capability-visibility
 * context while remaining fail-closed for unknown, anonymous and expired states.
 * It never reads browser storage or decides server authorization.
 */
export function AuthenticatedSessionBridge({ children }: { readonly children: ReactNode }) {
  const { snapshot } = useAuthentication();
  const session = useMemo<Session>(() => {
    const access = snapshot.access;
    if (access.phase !== "resolved" || access.facts.kind !== "authenticated")
      return Object.freeze({ roleId: null, capabilities: Object.freeze([]) });
    return Object.freeze({
      roleId: access.facts.identity.roleId,
      capabilities: access.facts.identity.capabilities,
    });
  }, [snapshot.access]);
  return <SessionProvider session={session}>{children}</SessionProvider>;
}
