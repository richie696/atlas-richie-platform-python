import { createContext, useContext, type ReactNode } from "react";
import type { ConsoleServices } from "./consoleServices";

const ConsoleServicesContext = createContext<ConsoleServices | null>(null);

/** Provides the one transport and feature ports assembled for this application lifetime. */
export function ConsoleServicesProvider({
  services,
  children,
}: {
  readonly services: ConsoleServices;
  readonly children: ReactNode;
}) {
  return (
    <ConsoleServicesContext.Provider value={services}>{children}</ConsoleServicesContext.Provider>
  );
}

/** Access the application-owned HTTP ports, never a feature fixture or transport mode. */
export function useConsoleServices(): ConsoleServices {
  const services = useContext(ConsoleServicesContext);
  if (!services) throw new Error("ConsoleServicesProvider is required");
  return services;
}
