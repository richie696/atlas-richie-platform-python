import { IDENTITY_ROLE, type IdentityRoleId } from "./account";
import type { BootstrapOperatorGate } from "./bootstrapOperator";
import { SESSION_CAPABILITY, type SessionCapability } from "../../../core/session/capabilities";

/** Initialization is a server fact. Dependency failure must never reopen a completed setup window. */
export type BootstrapFact =
  | {
      readonly initialized: false;
      readonly setupAvailable: boolean;
      readonly operatorAuthorized: boolean;
    }
  | { readonly initialized: true };

/** Read-only session identity. Cookies/tokens/passwords are intentionally absent. */
export interface SessionIdentity {
  readonly accountId: string;
  readonly username: string;
  readonly roleId: IdentityRoleId;
  readonly capabilities: readonly SessionCapability[];
  /** Opaque local ownership identity supplied by the authentication adapter, not a credential. */
  readonly sessionEpoch: string;
}

/** One resolved bootstrap/session read; never contradictory authenticated/initialized booleans. */
export type AccessFacts =
  | {
      readonly kind: "uninitialized";
      readonly setupAvailable: boolean;
      readonly operatorAuthorized: boolean;
    }
  | { readonly kind: "anonymous" }
  | { readonly kind: "authenticated"; readonly identity: SessionIdentity };

/** Project the app-owned bootstrap/session fact into the setup workflow's server contract. */
export function bootstrapFactFromAccess(facts: AccessFacts): BootstrapFact {
  return facts.kind === "uninitialized"
    ? {
        initialized: false,
        setupAvailable: facts.setupAvailable,
        operatorAuthorized: facts.operatorAuthorized,
      }
    : { initialized: true };
}

/** Project the app-owned bootstrap/session fact into the one-use setup authorization view. */
export function bootstrapOperatorGateFromAccess(facts: AccessFacts): BootstrapOperatorGate {
  return facts.kind === "uninitialized" && facts.setupAvailable
    ? { kind: "open", authorized: facts.operatorAuthorized }
    : { kind: "closed" };
}

export type ControlPlaneAccessState =
  | { readonly phase: "unknown" | "authenticating" | "expired" }
  | { readonly phase: "checking"; readonly previousFacts?: AccessFacts }
  | { readonly phase: "unavailable" }
  | { readonly phase: "resolved"; readonly facts: AccessFacts };

/** Product permission policy, supplied by the route owner rather than imported from app/router. */
export type AccessRequirement = "public" | "setup" | "session" | "metrics" | "admin";
export type AccessDecision =
  | { readonly kind: "wait" | "unavailable" | "setup" | "login" | "allow" }
  | { readonly kind: "denied"; readonly reason: "admin_required" | "metrics_required" };

/** Interpret the closed role id at the identity boundary; callers never duplicate role literals. */
export function isAdministrator(identity: Pick<SessionIdentity, "roleId">): boolean {
  return identity.roleId === IDENTITY_ROLE.Admin;
}

/** Fail closed until initialization/session are confirmed; role changes cannot bypass capability checks. */
export function decideControlPlaneAccess(
  requirement: AccessRequirement,
  state: ControlPlaneAccessState,
): AccessDecision {
  if (state.phase === "expired") return { kind: "login" };
  if (state.phase === "unavailable") return { kind: "unavailable" };
  if (state.phase !== "resolved") return { kind: "wait" };
  const facts = state.facts;
  if (facts.kind === "uninitialized")
    return { kind: facts.setupAvailable ? "setup" : "unavailable" };
  // After completion, even a hand-written setup URL cannot reopen initialization.
  if (requirement === "setup") return { kind: "login" };
  if (requirement === "public") return { kind: "allow" };
  if (facts.kind === "anonymous") return { kind: "login" };
  if (requirement === "admin" && !isAdministrator(facts.identity))
    return { kind: "denied", reason: "admin_required" };
  if (
    requirement === "metrics" &&
    !facts.identity.capabilities.includes(SESSION_CAPABILITY.MetricsView)
  )
    return { kind: "denied", reason: "metrics_required" };
  return { kind: "allow" };
}
