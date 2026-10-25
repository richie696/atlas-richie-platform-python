import type { ConsoleTransport } from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type { IdentityAccessPort } from "./identityAccessPort";
import { IDENTITY_ACCESS_ENDPOINTS } from "./identityAccessEndpoints";
import { LoginInputSchema } from "./identityAccessWire";

/** Bind authentication operations without importing first-run setup commands or schemas. */
export function createIdentityHttp(transport: ConsoleTransport): IdentityAccessPort {
  return Object.freeze({
    async readBootstrap(signal) {
      const value = await transport.send(IDENTITY_ACCESS_ENDPOINTS.Bootstrap, { signal });
      return value.initialized
        ? { initialized: true }
        : {
            initialized: false,
            setupAvailable: value.setupAvailable,
            operatorAuthorized: value.operatorAuthorized,
          };
    },
    readSession: async (signal) => transport.send(IDENTITY_ACCESS_ENDPOINTS.Session, { signal }),
    login: async (credentials, signal) =>
      transport.send(IDENTITY_ACCESS_ENDPOINTS.Login, {
        signal,
        body: parseConsoleInput(LoginInputSchema, credentials),
      }),
    async logout(signal) {
      await transport.send(IDENTITY_ACCESS_ENDPOINTS.Logout, { signal });
    },
  } satisfies IdentityAccessPort);
}
