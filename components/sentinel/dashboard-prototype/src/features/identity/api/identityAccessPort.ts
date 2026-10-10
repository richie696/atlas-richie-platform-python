import type { LoginCredentials } from "../model/account";
import type {
  AccessFacts,
  BootstrapFact,
  SessionIdentity,
  ControlPlaneAccessState,
} from "../model/controlPlaneAccess";

/** Observe the existing app authentication owner; credentials never belong to this read contract. */
export interface IdentitySessionObserver {
  readonly read: () => ControlPlaneAccessState;
  readonly subscribe: (listener: () => void) => () => void;
}

/** App-owned capability used only when an account command can alter the active principal. */
export interface IdentitySessionRevalidator {
  /** Re-read bootstrap/session authority after a confirmed mutation of the current account. */
  readonly revalidateAccess: () => Promise<AccessFacts | undefined>;
}

/** Minimal session observer plus the explicit authority refresh needed by account management. */
export type IdentitySessionOwner = IdentitySessionObserver & IdentitySessionRevalidator;

/**
 * Consumer-owned async authentication boundary. F6 supplies the new HTTP adapter;
 * neither this Port nor its consumers know fixtures, mock mode or vendor URLs.
 */
export interface IdentityAccessPort {
  /** A failed read throws; it is not interpreted as uninitialized. */
  readonly readBootstrap: (signal: AbortSignal) => Promise<BootstrapFact>;
  /** Confirmed anonymous/expired session is null; transport/parse failures throw. */
  readonly readSession: (signal: AbortSignal) => Promise<SessionIdentity | null>;
  /** Credentials are write-only and never returned. A nonempty form is not authentication. */
  readonly login: (credentials: LoginCredentials, signal: AbortSignal) => Promise<SessionIdentity>;
  /** Cookie/session invalidation is server-owned; a failed response does not prove logout committed. */
  readonly logout: (signal: AbortSignal) => Promise<void>;
}
