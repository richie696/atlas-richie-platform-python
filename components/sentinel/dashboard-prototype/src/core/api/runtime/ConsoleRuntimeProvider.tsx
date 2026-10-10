import { createContext, useContext, type ReactNode } from "react";
import type { ConsoleRuntimeConfiguration } from "./consoleRuntimeConfiguration";

const ConsoleRuntimeContext = createContext<ConsoleRuntimeConfiguration | null>(null);

/** Expose the immutable runtime destination to the application composition root and gateway assembly. */
export function ConsoleRuntimeProvider({
  configuration,
  children,
}: {
  readonly configuration: ConsoleRuntimeConfiguration;
  readonly children: ReactNode;
}) {
  return <ConsoleRuntimeContext value={configuration}>{children}</ConsoleRuntimeContext>;
}

/** Read the already validated API mode and origin; UI features must not branch on the mode. */
export function useConsoleRuntime(): ConsoleRuntimeConfiguration {
  const configuration = useContext(ConsoleRuntimeContext);
  if (!configuration) throw new Error("ConsoleRuntimeProvider is required");
  return configuration;
}
