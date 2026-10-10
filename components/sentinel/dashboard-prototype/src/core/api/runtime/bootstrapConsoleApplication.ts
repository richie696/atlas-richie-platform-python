import type { ConsoleRuntimeConfiguration } from "./consoleRuntimeConfiguration";

/** Dependencies required to mount the Console only after its request boundary is ready. */
export interface ConsoleBootstrapOperations<TServices> {
  readonly startInterception: (configuration: ConsoleRuntimeConfiguration) => Promise<void>;
  readonly createServices: (configuration: ConsoleRuntimeConfiguration) => TServices;
  readonly mount: (services: TServices) => void;
}

/** A failed request-boundary startup never creates services or renders request-capable pages. */
export async function bootstrapConsoleApplication<TServices>(
  configuration: ConsoleRuntimeConfiguration,
  operations: ConsoleBootstrapOperations<TServices>,
): Promise<TServices> {
  await operations.startInterception(configuration);
  const services = operations.createServices(configuration);
  operations.mount(services);
  return services;
}
