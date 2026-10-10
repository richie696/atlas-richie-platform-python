import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { AuthenticationWorkflow } from "../application/authenticationWorkflow";
import { observeAuthenticationForeground } from "./foregroundRevalidation";

const AuthenticationContext = createContext<AuthenticationWorkflow | null>(null);

/**
 * The composition root supplies one stable owner. Bootstrap, forms and guards
 * subscribe to it; this provider does not copy identity or construct a second
 * session. StrictMode cleanup aborts observation without permanently disposing
 * the owner that React will immediately reuse. Its creator owns final disposal.
 */
export function AuthenticationProvider({
  workflow,
  children,
}: {
  readonly workflow: AuthenticationWorkflow;
  readonly children: ReactNode;
}) {
  useEffect(() => {
    void workflow.restore().catch(() => {
      // Safe failure state belongs to the workflow, never an inferred role.
    });
    return () => workflow.cancel();
  }, [workflow]);
  useEffect(() => {
    return observeAuthenticationForeground(workflow, window, document);
  }, [workflow]);
  return <AuthenticationContext value={workflow}>{children}</AuthenticationContext>;
}

/** Read the same immutable snapshot used by login, menus and route authorization. */
export function useAuthentication() {
  const workflow = useContext(AuthenticationContext);
  if (!workflow) throw new Error("AuthenticationProvider is required");
  const snapshot = useExternalSnapshot(workflow);
  return { workflow, snapshot };
}
