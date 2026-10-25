import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { NavigationProtectionRegistry } from "./navigationProtection";
const Context = createContext<NavigationProtectionRegistry | null>(null);
/** One native-close effect per app. No URL, session, command body or framework-specific router enters shared. */
export function NavigationProtectionProvider({
  registry,
  children,
}: {
  readonly registry: NavigationProtectionRegistry;
  readonly children: ReactNode;
}) {
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => {
      const state = registry.getSnapshot();
      if (!state.dirty && !state.locked) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [registry]);
  return <Context value={registry}>{children}</Context>;
}
/** Optional so isolated internal feature consumers retain native-close protection without an app router. */
export const useNavigationProtectionRegistry = () => useContext(Context);
