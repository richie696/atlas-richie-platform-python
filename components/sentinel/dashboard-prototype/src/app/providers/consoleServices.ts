import { createConsoleAuthentication } from "../api/consoleAuthentication";
import type { ConsoleRuntimeConfiguration } from "../../core/api/runtime/consoleRuntimeConfiguration";

/** Stable application-lifetime Console transport and server-confirmed identity owner. */
export function createConsoleServices(configuration: ConsoleRuntimeConfiguration) {
  const authentication = createConsoleAuthentication({ baseUrl: configuration.apiBaseUrl });
  let disposed = false;
  return Object.freeze({
    mode: configuration.mode,
    transport: authentication.transport,
    authentication: authentication.authentication,
    session: authentication.session,
    dispose() {
      if (disposed) return;
      disposed = true;
      authentication.dispose();
    },
  });
}

export type ConsoleServices = ReturnType<typeof createConsoleServices>;
