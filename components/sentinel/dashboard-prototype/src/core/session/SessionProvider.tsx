/**
 * React projection of the authenticated principal. This provider owns no login,
 * persistence, identity selection, or authorization; the App composition maps
 * the current server-confirmed session into this display snapshot.
 */
import { createContext, useContext, type ReactNode } from "react";
import type { SessionCapability } from "./capabilities";

export type SessionRoleId = "admin" | "view";

export interface Session {
  readonly roleId: SessionRoleId | null;
  readonly capabilities: readonly SessionCapability[];
}

const EMPTY_SESSION: Session = Object.freeze({ roleId: null, capabilities: Object.freeze([]) });
const SessionContext = createContext<Session>(EMPTY_SESSION);

/** Supply only capabilities and role facts observed from the Console server. */
export function SessionProvider({
  session,
  children,
}: {
  readonly session: Session;
  readonly children: ReactNode;
}) {
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

/** Read-only UI authorization projection; the server remains authoritative per request. */
export function useSession(): Session {
  return useContext(SessionContext);
}

/**
 * @deprecated Demo role selection is retired from the application runtime.
 * Kept temporarily for the frozen, unreachable legacy LoginPage during F6
 * migration; invoking it cannot create or change an authenticated session.
 */
export function useSessionRoleSetter(): (roleId: SessionRoleId) => void {
  return (roleId) => {
    void roleId;
    throw new Error("Demo role switching is unavailable; authenticate through the Console server");
  };
}

/** UI visibility hint only. Every server command must authorize independently. */
export function useCan(required: SessionCapability): boolean {
  return useSession().capabilities.includes(required);
}
