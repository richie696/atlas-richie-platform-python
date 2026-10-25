import type { ConsoleTransport } from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import { RequestKeySchema } from "../../../core/api/protocol/common";
import type { InitializationPort } from "./initializationPort";
import type { BootstrapAuthorizationPort } from "./bootstrapAuthorizationPort";
import { IDENTITY_ACCESS_ENDPOINTS } from "./identityAccessEndpoints";
import { BOOTSTRAP_SETUP_ENDPOINTS } from "./bootstrapSetupEndpoints";
import {
  BootstrapAuthorizationInputSchema,
  LocalBootstrapAuthorizationInputSchema,
  InitializeCommandSchema,
  SetupStorageSchema,
} from "./bootstrapSetupWire";
import { ConfigurationSourceInputSchema } from "../../../shared/api/configurationSourceWire";
import { createIdentityHttp } from "./identityAccessHttp";

/** Explicit operator boundary. Neither a form boolean nor a request key grants this authority. */
export function createBootstrapAuthorizationHttp(
  transport: ConsoleTransport,
): BootstrapAuthorizationPort {
  return Object.freeze({
    async readGate(signal) {
      const value = await transport.send(IDENTITY_ACCESS_ENDPOINTS.Bootstrap, { signal });
      return value.initialized || !value.setupAvailable
        ? { kind: "closed" }
        : { kind: "open", authorized: value.operatorAuthorized };
    },
    async authorize(code, signal) {
      const body = parseConsoleInput(BootstrapAuthorizationInputSchema, { operatorCode: code });
      await transport.send(BOOTSTRAP_SETUP_ENDPOINTS.AuthorizeBootstrap, { signal, body });
    },
    async authorizeLocal(signal) {
      await transport.send(BOOTSTRAP_SETUP_ENDPOINTS.AuthorizeLocalBootstrap, {
        signal,
        body: parseConsoleInput(LocalBootstrapAuthorizationInputSchema, {}),
      });
    },
  } satisfies BootstrapAuthorizationPort);
}

/** Initialization is an idempotent command; connectivity checks remain independent operations. */
export function createInitializationHttp(transport: ConsoleTransport): InitializationPort {
  const identity = createIdentityHttp(transport);
  return Object.freeze({
    readBootstrap: identity.readBootstrap,
    checkDatabase: async (input, signal) =>
      transport.send(BOOTSTRAP_SETUP_ENDPOINTS.CheckDatabase, {
        signal,
        body: parseConsoleInput(SetupStorageSchema, input),
      }),
    checkSource: async (input, signal) =>
      transport.send(BOOTSTRAP_SETUP_ENDPOINTS.CheckSource, {
        signal,
        body: parseConsoleInput(ConfigurationSourceInputSchema, input),
      }),
    initialize: async (request, signal) =>
      transport.send(
        {
          ...BOOTSTRAP_SETUP_ENDPOINTS.Initialize,
          accept: (value) => value.requestKey === request.requestKey,
        },
        {
          signal,
          body: parseConsoleInput(InitializeCommandSchema, request),
          requestKey: request.requestKey,
        },
      ),
    readInitialization: async (requestKey, signal) =>
      transport.send(
        {
          ...BOOTSTRAP_SETUP_ENDPOINTS.Initialization,
          accept: (value) => value.requestKey === requestKey,
        },
        {
          signal,
          pathParams: [parseConsoleInput(RequestKeySchema, requestKey)],
        },
      ),
  } satisfies InitializationPort);
}
