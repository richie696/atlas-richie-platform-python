import {
  createConsoleTransport,
  type ConsoleTransportOptions,
} from "../../core/api/transport/consoleTransport";
import { createIdentityHttp } from "../../features/identity/authenticationHttp";
import {
  createAuthenticationWorkflow,
  type IdentityAccessPort,
  type IdentitySessionOwner,
} from "../../features/identity/authentication";

/**
 * One application authentication/transport owner. Rotation follows accepted authentication intent,
 * not React's temporary checking phase or a server-returned session epoch. Login/logout dispatch
 * once from the already confirmed access state, then the workflow confirms the server facts.
 */
export function createConsoleAuthentication(
  options: Omit<ConsoleTransportOptions, "owner" | "onUnauthorized">,
) {
  let generation = 0;
  const transport = createConsoleTransport({
    ...options,
    owner: () => String(generation),
    onUnauthorized: () => authentication.expire(),
  });
  const identity = createIdentityHttp(transport);
  // Accepted authentication intent clears the in-memory CSRF nonce. This read only
  // obtains a fresh nonce for the following command; its body is not a second
  // bootstrap/session state source.
  const preflight = async (signal: AbortSignal) => {
    await identity.readBootstrap(signal);
  };
  const accessPort: IdentityAccessPort = Object.freeze({
    readBootstrap: identity.readBootstrap,
    readSession: identity.readSession,
    async login(input, signal) {
      await preflight(signal);
      return identity.login(input, signal);
    },
    async logout(signal) {
      await preflight(signal);
      await identity.logout(signal);
    },
  } satisfies IdentityAccessPort);
  const authentication = createAuthenticationWorkflow(accessPort, {
    begin() {
      generation++;
      transport.clearCredentials();
    },
  });
  const session: IdentitySessionOwner = Object.freeze({
    read: () => authentication.getSnapshot().access,
    subscribe: authentication.subscribe,
    revalidateAccess: authentication.revalidateAccess,
  });
  return Object.freeze({
    transport,
    authentication,
    session,
    dispose() {
      authentication.dispose();
      transport.dispose();
    },
  });
}
